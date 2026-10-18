"""「字段优先级」窗口：滚轮只滚鼠标所在的那一行字段，不带动上下行与最右侧滚动条。

用户需求原文：
    「字段优先级窗口左侧区域滚动时会影响到上下行和最右侧滚动条，改成鼠标在标题内滚动只影响
      标题，在鼠标原简介内滚动只影响原简介，鼠标在全部演员内滚动只影响全部演员」

为什么这条得靠「事件被接受」来断言，而不是断言滚动条数值：`QApplication.sendEvent`
造出来的是**合成**事件，Qt 明确不让它往父控件传（见 `QApplication::notify` 里
`case QEvent::Wheel` 的注释），所以离屏测试里外层滚动条无论有没有 bug 都不会动。
真正的滚轮是自发事件，派发方式是「从鼠标底下的控件起沿父控件一路往上递，直到某一层
既处理了（`event()` 返回 true）又接受了事件才停」。也就是说：

    外层滚动区会不会跟着动  ==  本行列表最后有没有把事件 accept 掉。

所以这里直接钉住契约本身——滚轮落在任一字段行的 chip 区域里时，返回给 Qt 的那个事件
必须是「已接受」，并且列表带 `WA_NoMousePropagation`（兜住鼠标正好停在行内那条滚动条上、
由滚动条接手的那条路）。事件被吃掉之后，实机上就只剩本行在动。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QWheelEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import FieldPriorityConfig  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    DIALOG_HEIGHT,
    FIELD_PRIORITY_FIELDS,
    FieldPriorityDialog,
    SiteListEditorDialog,
    SitePaletteList,
)
from mdcx.gen.field_enums import CrawlerResultFields  # noqa: E402

ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]

# 用户点名的三行（标题 / 原简介 / 全部演员）+ 一行兜底
TARGET_FIELDS = (
    CrawlerResultFields.TITLE,
    CrawlerResultFields.ORIGINALPLOT,
    CrawlerResultFields.ALL_ACTORS,
    CrawlerResultFields.WANTED,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    # 每一行都按「该类型名单全选中」摆——与用户实机一致：那一行装不下，chip 换行、
    # 行内于是有一条细滚动条（用户截图里每行右侧那条就是它）。
    configs = {field: FieldPriorityConfig(site_prority=list(ALL_SITES)) for field in FIELD_PRIORITY_FIELDS}
    dlg = FieldPriorityDialog("字段优先级", FixedScrapingType.YOUMA, ALL_SITES, configs, None)
    dlg.resize(860, DIALOG_HEIGHT)
    dlg.show()
    qt_app.processEvents()
    try:
        yield dlg
    finally:
        dlg.deleteLater()


def _wheel(widget, delta: int = -120) -> QWheelEvent:
    """造一个滚轮事件并投递给 widget，返回事件本身供断言其是否被接受。

    合成事件不会像真机那样往父控件传递，所以「外层滚动条没动」这种断言在离屏下毫无意义
    （没 bug 时也一样不动），必须断言事件有没有被吃掉，见模块 docstring。
    """
    pos = QPointF(widget.rect().center())
    event = QWheelEvent(
        pos,
        QPointF(widget.mapToGlobal(widget.rect().center())),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    QApplication.processEvents()
    return event


@pytest.mark.parametrize("field", TARGET_FIELDS)
def test_wheel_inside_a_field_row_is_swallowed(dialog, field):
    """鼠标在某一行的 chip 区域里滚，该行必须把事件吃掉（否则外层滚动区会跟着动）。"""
    list_widget = dialog._field_lists[field]
    event = _wheel(list_widget.viewport())
    assert event.isAccepted(), f"「{field}」那一行没吃掉滚轮，滚轮会继续传给外层滚动区"


def test_wheel_stays_inside_the_row_when_the_row_cannot_scroll_anymore(dialog):
    """本行滚到底后再滚也照样吃掉——这正是「滚着滚着整个字段区跟着挪」的那一步。"""
    list_widget = dialog._field_lists[CrawlerResultFields.TITLE]
    bar = list_widget.verticalScrollBar()
    bar.setValue(bar.maximum())
    event = _wheel(list_widget.viewport())
    assert bar.value() == bar.maximum(), "滚动条被推出了最大值"
    assert event.isAccepted(), "已经滚到尽头了还把事件往外递"


def test_wheel_on_an_empty_row_is_swallowed(dialog):
    """站点少到装得下 / 一个都没有的行，Qt 默认会 ignore 事件，同样必须吃掉。"""
    empty = dialog._field_lists[CrawlerResultFields.WANTED]
    empty.clear()
    event = _wheel(empty.viewport())
    assert event.isAccepted(), "空行把滚轮往外递了"


def test_wheel_over_one_row_scrolls_only_that_row(dialog):
    """滚「标题」那一行：只有它的滚动条动，其余十八行一动不动。"""
    target = dialog._field_lists[CrawlerResultFields.TITLE]
    bar = target.verticalScrollBar()
    assert bar.maximum() > 0, "没造出可滚动的溢出，测不到「只影响本行」"
    bar.setValue(0)
    others = {
        field: dialog._field_lists[field].verticalScrollBar()
        for field in FIELD_PRIORITY_FIELDS
        if field is not CrawlerResultFields.TITLE
    }
    _wheel(target.viewport())
    assert bar.value() > 0, "本行没有跟着滚"
    for field, other_bar in others.items():
        assert other_bar.value() == 0, f"滚「标题」时「{field}」那一行也被带着滚了"


def test_every_field_row_blocks_mouse_propagation(dialog):
    """每一行都挂着 `WA_NoMousePropagation`。

    这是滚动条那条路的兜底：鼠标正好停在行内那条细滚动条上时，滚轮由 QScrollBar 接手，
    它滚不动时也会 ignore 事件，递上来的第一站就是本控件——挂上这个属性就不会越过它。
    """
    for field, list_widget in dialog._field_lists.items():
        assert list_widget.testAttribute(Qt.WidgetAttribute.WA_NoMousePropagation), f"「{field}」那一行没挡住传递"


def test_field_rows_keep_the_outer_scroll_area_reachable(dialog):
    """收口只发生在 chip 区域里：标签列与按钮列照旧能把十九行字段上下滚。"""
    scroll = next(w for w in dialog.findChildren(QScrollArea))
    content = scroll.widget()
    row_labels = [label for label in dialog.findChildren(QLabel) if label.parentWidget() is content]
    assert len(row_labels) == len(FIELD_PRIORITY_FIELDS), f"字段行的标签列数量对不上：{len(row_labels)}"
    for label in row_labels:
        assert not label.testAttribute(Qt.WidgetAttribute.WA_NoMousePropagation), (
            "标签列被一起收口了，十九行就再也滚不动"
        )


def test_palette_row_and_site_editor_lists_swallow_the_wheel_too(dialog, qt_app):
    """候选区与「编辑网站」的两个列表共用同一个基类，也得是「只滚自己」。"""
    palette = next(iter(dialog.findChildren(SitePaletteList)))
    palette.verticalScrollBar().setValue(palette.verticalScrollBar().maximum())
    assert _wheel(palette.viewport()).isAccepted(), "候选区把滚轮往外递了"

    editor = SiteListEditorDialog("t", [Website.DMM], ALL_SITES, None)
    try:
        editor.resize(860, DIALOG_HEIGHT)
        editor.show()
        qt_app.processEvents()
        for list_widget in (editor.available_list, editor.selected_list):
            assert list_widget.testAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
            list_widget.verticalScrollBar().setValue(0)
            assert _wheel(list_widget.viewport()).isAccepted(), "「编辑网站」的列表把滚轮往外递了"
    finally:
        editor.deleteLater()
