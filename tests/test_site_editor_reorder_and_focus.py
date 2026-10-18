"""「编辑网站」对话框的两条实机反馈：

    一、「启用网站（从左到右优先级递减）」里的站点不能调整顺序了，左键选中调整顺序时
        站点直接就被移除了。
    二、「可用网站（按类型分组）」里的网站选中时内部会有方框，删掉内部方框。

第一条的成因在 Qt 自己的收尾逻辑里，不在本项目的代码顺序上：
`QAbstractItemView::startDrag`（qtbase/src/widgets/itemviews/qabstractitemview.cpp）在
`drag->exec()` 返回 MoveAction 之后会调 `clearOrRemove()`，而它删的是**当前选中着的整行**：

    d->dropEventMoved = false;
    if (drag->exec(supportedActions, defaultDropAction) == Qt::MoveAction && !d->dropEventMoved) {
        if (dragDropMode() != InternalMove || drag->target() == viewport())
            d->clearOrRemove();
    }

`dropEventMoved` 这个标志全 Qt 只有上面那行置 false，没有任何一处置 true——基类
`QAbstractItemView::dropEvent` 也没置，所以「走基类 dropEvent」并不等于安全，它安全是因为
Qt 自己 `moveRows` 搬动时已经用 `rowsRemoved` 把选中态带走了。我们这里是**自实现的 dropEvent**
（联动组要整组同行，基类只搬被拖的那一个），顺序改完之后又把被移动的站点重新选中，于是
clearOrRemove() 把它们从 model 里删了——用户看到的就是「拖一下，站点消失」。

离屏环境跑不了真拖拽（`QDropEvent.source()` 恒为 None，见 test_site_group_linkage 的说明），
所以这里直接构造 QDropEvent 喂给 dropEvent，并在之后照抄一遍 clearOrRemove 的实现当回归锁；
`test_qt_cleanup_port_is_not_a_noop` 先证明这份抄写确实会删东西，免得锁了个空断言。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import SiteListEditorDialog  # noqa: E402

ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]

CUSTOM_ORDER = [Website.XCITY, Website.MGSTAGE, Website.GETCHU, Website.JAVBUS]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _editor(qt_app, selected=None):
    dlg = SiteListEditorDialog("t", list(CUSTOM_ORDER if selected is None else selected), ALL_SITES, None)
    dlg.resize(860, 640)
    dlg.show()
    qt_app.processEvents()
    return dlg


def _values(list_widget) -> list[str]:
    from mdcx.controllers.main_window.site_priority_dialog import _list_sites

    return [site.value for site in _list_sites(list_widget)]


def _row_of(list_widget, site_value: str) -> int:
    return next(
        row for row in range(list_widget.count()) if list_widget.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


def _select(list_widget, site_value: str) -> None:
    for r in range(list_widget.count()):
        list_widget.item(r).setSelected(list_widget.item(r).data(Qt.ItemDataRole.UserRole) == site_value)


def _drop_at(list_widget, site_value: str, before: str) -> None:
    """真走一次 dropEvent：选中 → mimeData 记 drag_sites → 落到 before 那一行之前。

    `QDropEvent.source()` 离屏恒为 None，正好绕开「从候选区拖进来」那条插入分支，
    剩下的就是自实现的内部重排分支（PrioritySiteList.dropEvent 的 `_auto_group` 段）。
    """
    _select(list_widget, site_value)
    mime = list_widget.mimeData([list_widget.item(_row_of(list_widget, site_value))])
    target = list_widget.item(_row_of(list_widget, before))
    list_widget.dropEvent(
        QDropEvent(
            QPointF(list_widget.visualItemRect(target).center()),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def _qt_post_drag_cleanup(list_widget) -> list[str]:
    """照抄 `QAbstractItemViewPrivate::clearOrRemove`：删掉当前选中着的整行。

    真机上这一步由 startDrag 在 `drag->exec()` 返回 MoveAction 之后调用；离屏跑不了真拖拽，
    只能照抄。列表模型的 columnCount 恒为 1，选中区间必然是 (row, 0, row, 0)，clearOrRemove
    里那两道 left/right 判断在这恒成立，直接省掉（PyQt 把 columnCount 暴露成私有方法了）。
    """
    model = list_widget.model()
    for rng in list_widget.selectionModel().selection():
        model.removeRows(rng.top(), rng.bottom() - rng.top() + 1, rng.parent())
    return _values(list_widget)


# ------------------------------------------------------------------ 一、自定义顺序


def test_dropping_inside_the_enabled_list_reorders_it(qt_app):
    """启用列表内部拖拽 = 重排：拖到谁前面就排到谁前面，站��一个不少。"""
    dlg = _editor(qt_app)
    try:
        before = _values(dlg.selected_list)
        _drop_at(dlg.selected_list, "Getchu", "Xcity")
        after = _values(dlg.selected_list)
        assert after[0] == "Getchu", f"没挪到 Xcity 前面：{after}"
        assert sorted(after) == sorted(before), f"重排改动了名单：{before} → {after}"
        assert dlg.selected_sites()[0] == Website.GETCHU
    finally:
        dlg.deleteLater()


def test_reorder_survives_qts_post_drag_cleanup(qt_app):
    """回归锁：拖完再跑一遍 Qt 那段收尾，站点不许少。

    这条正是用户看到的现象：站点在拖动结束的瞬间被 Qt 连根拔掉。
    """
    dlg = _editor(qt_app)
    try:
        _drop_at(dlg.selected_list, "Getchu", "Xcity")
        assert _qt_post_drag_cleanup(dlg.selected_list) == [
            "Getchu",
            "Xcity",
            "MGStage",
            "JavBus",
        ], "Qt 的收尾把刚排好的站点删掉了"
    finally:
        dlg.deleteLater()


def test_qt_cleanup_port_is_not_a_noop(qt_app):
    """上一条的锁要有牙齿：照抄的 clearOrRemove 确实会删掉选中着的行。

    没有这一条，上一条可能只是因为「压根没删」而绿，等哪天抄漏了也照样绿。
    """
    dlg = _editor(qt_app)
    try:
        lst = dlg.selected_list
        _select(lst, "Getchu")
        assert _qt_post_drag_cleanup(lst) == ["Xcity", "MGStage", "JavBus"], "照抄的收尾没删掉选中行"
    finally:
        dlg.deleteLater()


def test_reordering_one_site_does_not_disturb_the_others(qt_app):
    """挪一个动一个：其余站点的相对次序必须原样保留。"""
    dlg = _editor(qt_app)
    try:
        before = _values(dlg.selected_list)
        _drop_at(dlg.selected_list, "JavBus", "Xcity")
        after = _values(dlg.selected_list)
        assert after == ["JavBus", "Xcity", "MGStage", "Getchu"]
        assert [site for site in before if site != "JavBus"] == [site for site in after if site != "JavBus"]
    finally:
        dlg.deleteLater()


# ------------------------------------------------------- 二、候选区不要内部方框


def test_clicking_a_site_leaves_no_current_item(qt_app):
    """点站点只该选中，不该把它变成「当前项」。

    当前项会被 Qt 再套一层内嵌的聚焦框（`QListView::paintEvent` 给 `current == index`
    且视图有焦点的行加 `State_HasFocus`），于是 chip 里面多出一个方框——用户截图里的那圈。
    """
    dlg = _editor(qt_app)
    try:
        palette = dlg.available_list
        row = _row_of(palette, "7mmtv")
        QTest.mouseClick(
            palette.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            palette.visualItemRect(palette.item(row)).center(),
        )
        qt_app.processEvents()
        assert palette.currentRow() == -1, f"点完站点它成了当前项：{palette.currentItem().text()}"
    finally:
        dlg.deleteLater()


def test_clicking_a_site_still_selects_it(qt_app):
    """清当前项不能顺手把选中态也清了——「添加选中」全靠它。"""
    dlg = _editor(qt_app)
    try:
        palette = dlg.available_list
        row = _row_of(palette, "7mmtv")
        QTest.mouseClick(
            palette.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            palette.visualItemRect(palette.item(row)).center(),
        )
        qt_app.processEvents()
        assert [palette.row(item) for item in palette.selectedItems()] == [row]
        dlg._add_selected()
        assert dlg.selected_sites()[-1] == Website.MMTV
    finally:
        dlg.deleteLater()


def test_multi_click_still_collects_every_picked_site(qt_app):
    """Ctrl 连点攒出来的多选也要原样保住（清当前项走的是同一套路）。"""
    dlg = _editor(qt_app, selected=[])
    try:
        palette = dlg.available_list
        rows = [_row_of(palette, name) for name in ("7mmtv", "Dahlia")]
        QTest.mouseClick(
            palette.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            palette.visualItemRect(palette.item(rows[0])).center(),
        )
        QTest.mouseClick(
            palette.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            palette.visualItemRect(palette.item(rows[1])).center(),
        )
        qt_app.processEvents()
        assert sorted(palette.row(item) for item in palette.selectedItems()) == sorted(rows)
        assert palette.currentRow() == -1
        dlg._add_selected()
        assert set(dlg.selected_sites()) == {Website.MMTV, Website.DAHLIA}
    finally:
        dlg.deleteLater()


def _diff(a, b) -> int:
    """两张图不同的像素数。用「差异数」而不是 `!=`：PyQt 的 `!=` 说不出差在哪。"""
    return sum(1 for y in range(a.height()) for x in range(a.width()) if a.pixel(x, y) != b.pixel(x, y))


def test_selected_chip_has_no_inner_box_left(qt_app):
    """像素级：点完那一格的画，和「不设当前项」的画一模一样。

    先量出「设了当前项」到底多画了多少像素（这是用户截图里那个内部方框），再量点完之后
    那个数字归零——只断言归零会空过（万一这个版本 Qt 压根不画聚焦框）。
    """
    dlg = _editor(qt_app)
    try:
        palette = dlg.available_list
        item = palette.item(_row_of(palette, "7mmtv"))
        # 聚焦框只在「视图有焦点」时才画（QListView::paintEvent 里的 focus 变量）
        palette.setFocus()
        qt_app.processEvents()
        assert palette.hasFocus() or palette.viewport().hasFocus(), "列表没拿到焦点，聚焦框压根不会画"

        def paint():
            qt_app.processEvents()
            return palette.grab().toImage().copy(palette.visualItemRect(item))

        palette.setCurrentRow(-1)
        item.setSelected(True)  # 单独设选中不会回填当前项（实测），这一步是「选中但没有当前项」
        without_current = paint()
        palette.setCurrentRow(_row_of(palette, "7mmtv"))
        with_current = paint()
        assert _diff(without_current, with_current) > 0, "当前项没有画出任何差异，这组对照说明不了问题"

        palette.setCurrentRow(-1)  # 清当前项会连带清掉选中态，正好从零开始模拟那一次点击
        QTest.mouseClick(
            palette.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            palette.visualItemRect(item).center(),
        )
        assert _diff(without_current, paint()) == 0, "点完那一格里面还留着聚焦框"
    finally:
        dlg.deleteLater()
