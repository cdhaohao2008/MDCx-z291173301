"""三个站点列表里 chip 内的文字（站点名、分组标题）必须左右居中。

用户需求原文：
    「可用网站（按类型分组）、启用网站（从左到右优先级递减）、可用网站（拖到下方
      字段中；字段内从左到右优先级递减）小方框内的站点名称、站点组全部居中显示」

QSS 里写 `QListWidget::item { text-align: center }` 与给条目设 `Qt::TextAlignmentRole`
**都不管用**（Qt 6 `QStyleSheetStyle::drawPrimitive(PE_PanelItemViewItem)` 取不到
alignment 规则时硬编码 AlignLeft，既不看 `opt.displayAlignment` 也不看条目角色），
而 chip 宽度是贴着文字收紧的，于是那点右余量直接变成肉眼可见的偏左：
改之前每个 chip 里文字离左边约 8.8px、离右边约 15.2px，偏左 6.4 个逻辑像素。

修法是把这 6px 补进左内边距（`padding: 5px 9px 5px 15px`）。这 6px 在 1.25x 与 2.5x
缩放下量出来都是同样的逻辑像素（不是设备像素），故补内边距即可，不必自己接管绘制
——接管绘制会连 hover/选中的底色边框一起重写，而这个项目此前已经因为
「QSS 的 `QListWidget::item { background }` 盖掉 delegate 设的 `backgroundBrush`」
把自绘方案回退过一次。

用例分两层：
  * QSS 层钉住那 6px 补偿（有人「顺手改回对称」会立刻红）；
  * 渲染层真把 chip 抓成图，量文字墨迹到左右边框的留白（覆盖分组标题的加粗、
    三个列表各自的条目、以及站点名长短不一的排布）。
"""

import re

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    PrioritySiteList,
    SiteListEditorDialog,
    SitePaletteList,
    _setup_site_list,
    _style_site_list,
)

# Qt 在 QSS 列表项文字矩形右缘多留的余量（逻辑像素）。左右内边距差必须等于它，
# 否则文字又会偏出去；改动 QSS 时这个数会跟着一起量。
QT_TEXT_RIGHT_SLACK_PX = 6

# 渲染测量容差：字形光栅化会带 ±1px 的舍入，字号/缩放再变一点也会有零点几的差。
TOLERANCE_PX = 2.0

ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------- QSS 层


def _item_padding(list_widget) -> tuple[int, int, int, int]:
    """从列表的样式表里取出 `QListWidget::item` 的 padding（上 右 下 左）。"""
    style_sheet = re.sub(r"/\*.*?\*/", "", list_widget.styleSheet(), flags=re.S)
    match = re.search(r"QListWidget::item\s*\{[^}]*\bpadding:\s*([^;]+);", style_sheet)
    assert match, f"样式表里没有 `QListWidget::item` 的 padding：\n{list_widget.styleSheet()}"
    values = [int(part.replace("px", "").strip()) for part in match.group(1).split()]
    assert len(values) == 4, f"padding 应写成四边，拿到 {values}"
    return tuple(values)  # type: ignore[return-value]


def test_item_padding_absorbs_qt_right_slack(qt_app):
    """左内边距要比右多出 Qt 文字矩形那份额外余量，chip 里的文字才正中。"""
    palette = SitePaletteList([Website.DMM], grouped=False)
    top, right, bottom, left = _item_padding(palette)
    assert (top, bottom) == (5, 5), "上下内边距不该被这次居中改动"
    assert left - right == QT_TEXT_RIGHT_SLACK_PX, (
        f"左内边距应比右多 {QT_TEXT_RIGHT_SLACK_PX}px（Qt 文字矩形的右余量），"
        f"实际左 {left} 右 {right}，文字会偏左 {QT_TEXT_RIGHT_SLACK_PX - (left - right)}px"
    )


def test_all_three_site_lists_share_the_compensated_chip_style(qt_app):
    """用户点名的三个列表都得吃到补偿，不能只改一个类。"""
    editor = SiteListEditorDialog("编辑网站", [Website.DMM, Website.JAVDB], ALL_SITES)
    # 「可用网站（按类型分组）」候选区 与「启用网站（从左到右优先级递减）」
    assert _item_padding(editor.available_list)[:1] == (5,)
    assert _item_padding(editor.selected_list)[:1] == (5,)
    for list_widget in (editor.available_list, editor.selected_list):
        top, right, bottom, left = _item_padding(list_widget)
        assert left - right == QT_TEXT_RIGHT_SLACK_PX
    editor.close()
    editor.deleteLater()


def test_field_priority_palette_list_uses_the_same_chip_style(qt_app):
    """「字段优先级」里那个「可用网站（拖到下方字段中…）」也是同一个列表类。"""
    palette = SitePaletteList(ALL_SITES, grouped=False)
    _style_site_list(palette, 150, False)
    top, right, bottom, left = _item_padding(palette)
    assert (top, bottom) == (5, 5)
    assert left - right == QT_TEXT_RIGHT_SLACK_PX


# ---------------------------------------------------------------- 渲染层


def _chip_gaps(list_widget) -> list[tuple[str, float, float]]:
    """把列表抓成图，量首行每个 chip 里文字墨迹到 chip 左右边缘的留白（逻辑像素）。

    chip 的横向范围直接问 `visualItemRect()` 要，不靠数像素找边界——边框颜色与
    chip 底色都浅，靠扫描找圆角矩形会在圆角处量歪。纵向只取 chip 中间的四分之一，
    既躲开上下相邻行，也躲开文字 ascender/descender 以外的边框像素。
    """
    list_widget.setCurrentRow(-1)
    list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    list_widget.show()
    QApplication.processEvents()
    list_widget.setCurrentRow(-1)
    QApplication.processEvents()

    image = list_widget.grab().toImage()
    scale = list_widget.devicePixelRatioF()
    offset = list_widget.viewport().mapTo(list_widget, QPoint(0, 0))

    def dark(x: int, y: int) -> bool:
        argb = image.pixel(x, y)
        return ((argb >> 16) & 0xFF) + ((argb >> 8) & 0xFF) + (argb & 0xFF) < 400

    rects = [
        (list_widget.item(row).text(), list_widget.visualItemRect(list_widget.item(row)))
        for row in range(list_widget.count())
        if list_widget.item(row) is not None
    ]
    first_row = min(rect.top() for _, rect in rects)
    gaps: list[tuple[str, float, float]] = []
    for text, rect in rects:
        if rect.top() != first_row:
            continue  # 换行流里只量首行，后面的 chip 坐标对不齐
        left = (rect.left() + offset.x()) * scale
        right = (rect.right() + offset.x()) * scale
        top = (rect.top() + offset.y() + rect.height() * 0.25) * scale
        bottom = (rect.top() + offset.y() + rect.height() * 0.75) * scale
        ink = [x for x in range(int(left), int(right) + 1) for y in range(int(top), int(bottom) + 1) if dark(x, y)]
        if not ink:
            continue
        gaps.append((text, (min(ink) - left) / scale, (right - max(ink)) / scale))
    return gaps


def _assert_centered(list_widget, expected_min: int) -> None:
    gaps = _chip_gaps(list_widget)
    assert len(gaps) >= expected_min, f"只量到 {len(gaps)} 个 chip，列表没铺开：{[name for name, _, _ in gaps]}"
    for text, left, right in gaps:
        assert abs(right - left) <= TOLERANCE_PX, f"「{text}」没居中：左 {left:.2f} 右 {right:.2f}"
    list_widget.close()
    list_widget.deleteLater()


def test_palette_site_chips_are_centered(qt_app):
    """候选区里长短不一的站点名都要居中（宽度贴文字，偏一点就看得出来）。"""
    sites = [Website.DMM, Website.OFFICIAL, Website.MISSAV_API, Website.GETCHU, Website.MADOUQU]
    palette = SitePaletteList(sites, grouped=False)
    palette.resize(760, 150)
    _assert_centered(palette, expected_min=len(sites))


def test_palette_group_title_chips_are_centered(qt_app):
    """分组标题是加粗的，字号不同、宽度也不同，同样必须居中。"""
    palette = SitePaletteList(ALL_SITES, grouped=True)
    palette.resize(760, 150)
    _assert_centered(palette, expected_min=7)


def test_priority_site_chips_are_centered(qt_app):
    """「字段优先级」里每字段的可用网站列表走的是 PrioritySiteList。"""
    sites = [Website.DMM, Website.OFFICIAL, Website.MISSAV_API, Website.GETCHU, Website.MADOUQU]
    priority = PrioritySiteList(sites, 74)
    priority.resize(760, 74)
    _setup_site_list(priority, sites)  # PrioritySiteList 自己不铺站点，由调用方铺
    _assert_centered(priority, expected_min=len(sites))
