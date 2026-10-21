"""演员管理器主窗口左键手势回归：单击选中 / 再次单击编辑 / 双击（连续点击）看详情。

用户 2026-10-21 分三轮反馈，逐步收紧交互：
1) 编辑状态整格铺蓝底看不清 → 改成纯白底 + 四周一圈蓝边
   （见 tests/test_actor_manager_inline_editor_style.py）；
2) 选中态不要铺浅蓝底 → 保持格子原有底色（白/隔行浅灰），只在四周画一圈蓝条；
3) 单击选中后，双击/连续点击要弹演员详情窗；编辑状态里双击同样要弹详情窗。

手势约定：
- 单击某格 → 只选中（不弹编辑器，防误触）；
- 已选中该格、再点一次（间隔超出双击间隔）→ 进行内编辑（延后一个双击间隔
  才开：这期间若来了双击，改弹详情窗，双击不会顺带闪出编辑器）；
- 快速双击 / 连续快速点击（间隔在双击间隔内）→ 弹演员详情窗；
- 行内编辑器里双击/连续点击 → 提交已改的值后弹演员详情窗。

"再次单击"与"快速双击"的区分不靠自己的连击计数，而靠两件事：
① 点的是不是上一次点过的那一格；② 两次点击的间隔是否在系统双击间隔内。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _make_actor(**kw):
    from mdcx.tools.emby_actor_manager import ActorInfo

    base = {"name": "高桥惠子", "actor_id": "id1", "server_id": "srv1"}
    base.update(kw)
    return ActorInfo(**base)


def _manager(actors):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg._actors = list(actors)
    dlg._populate_table(list(actors))
    return dlg


def _cell_pos(dlg, row: int, col: int):
    table = dlg.table
    item = table.item(row, col)
    assert item is not None, f"格子 ({row},{col}) 不存在"
    return table.visualItemRect(item).center()


def _click(dlg, row: int, col: int, kind: str = "press", wait: float = 0.0):
    """在 (row, col) 上按一次左键（按下+松开）。

    kind 缺省 "press"（普通单击）；快速双击的第二下传 "dblclick"（Qt 在双击
    间隔内就是这么报的）。wait 是本次点击**之前**先等待的秒数，用来控制与
    上一次点击的间隔（决定算「再次单击」还是「快速双击」）。
    """
    if wait:
        time.sleep(wait)
    pos = _cell_pos(dlg, row, col)
    dlg._on_viewport_mouse_click(pos, kind)
    dlg._on_viewport_mouse_release(pos)


def _slow_gap(dlg) -> float:
    """「再次单击」的间隔：超过系统双击间隔（这种第二次点击走行内编辑）。"""
    return dlg._click_interval() + 0.05


def _fast_gap() -> float:
    """「快速双击」的间隔：在双击间隔内、但大于重复上报去重窗口（10ms）。"""
    return 0.05


def _wait_editor(dlg, timeout: float = 2.0):
    """等延后定时器把行内编辑器开出来（编辑器是延后一个双击间隔才开的）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if dlg._cell_editor is not None:
            return dlg._cell_editor
        time.sleep(0.01)
    QApplication.processEvents()
    return dlg._cell_editor


def _wait_detail(dlg, timeout: float = 2.0):
    """等详情窗真的弹出来（双击后是 QTimer.singleShot(0) 延后开的）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if dlg._detail_dialogs:
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(dlg._detail_dialogs)


def _editor_event(kind: str, x: float = 3.0):
    """造一个发给行内编辑器的鼠标事件。"""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    etype = QEvent.Type.MouseButtonDblClick if kind == "dblclick" else QEvent.Type.MouseButtonPress
    return QMouseEvent(
        etype,
        QPointF(x, 3.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_single_click_only_selects_no_editor(app):
    """单击可编辑列只选中：不再自动弹行内编辑器（防误触）。"""
    dlg = _manager([_make_actor()])
    try:
        _click(dlg, 0, 1)
        assert dlg._cell_editor is None, "单击不该弹出行内编辑器"
        assert dlg._click_gesture == "select", "首次点击应是「选中」手势"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_second_click_opens_inline_editor(app):
    """已选中的格子再次单击：进行内编辑，初值取 UserRole 里的完整值。"""
    long_tags = ["标签一", "标签二", "标签三"]
    dlg = _manager([_make_actor(existing_taglines=long_tags)])
    try:
        table = dlg.table
        # 展示只取前 2 个标签，完整值在 UserRole 里。
        assert table.item(0, 7).text() == "标签一, 标签二"
        _click(dlg, 0, 7)  # 第一次：只选中
        assert dlg._cell_editor is None
        _click(dlg, 0, 7, wait=_slow_gap(dlg))  # 第二次（慢）：进行内编辑
        editor = _wait_editor(dlg)
        assert editor is not None, "再次单击应打开行内编辑器"
        assert editor.text() == "标签一, 标签二, 标签三", "编辑器初值应是完整标签，不是展示文本"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_fast_double_click_opens_detail_window(app):
    """快速双击可编辑列：弹演员详情窗，且不会同时开行内编辑器。"""
    actor = _make_actor(name="双击演员", actor_id="e9")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)  # 第一下：只选中
        _click(dlg, 0, 1, kind="dblclick", wait=_fast_gap())  # 第二下：快速双击
        assert _wait_detail(dlg), "快速双击应弹演员详情窗"
        assert set(dlg._detail_dialogs) == {"e9"}
        # 延后开编辑器的定时器也会在这期间到期，双击不该顺带闪出编辑器
        _wait_editor(dlg, timeout=dlg._click_interval() + 0.3)
        assert dlg._cell_editor is None, "快速双击不该同时开行内编辑器"
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_rapid_consecutive_clicks_open_detail_window(app):
    """连续快速点击（两次按下间隔在双击间隔内）：同样弹演员详情窗。"""
    actor = _make_actor(name="连击演员", actor_id="e20")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)  # 第一下：只选中
        _click(dlg, 0, 1, wait=_fast_gap())  # 第二下：连击（报成 press）
        assert _wait_detail(dlg), "连续点击应弹演员详情窗"
        assert set(dlg._detail_dialogs) == {"e20"}
        assert dlg._cell_editor is None
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_fast_double_click_on_readonly_column_opens_detail(app):
    """不可编辑列（状态/头像/简介/影片数）快速双击也弹详情窗。"""
    actor = _make_actor(name="只读列", actor_id="e11")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 0)
        _click(dlg, 0, 0, kind="dblclick", wait=_fast_gap())
        assert _wait_detail(dlg)
        assert set(dlg._detail_dialogs) == {"e11"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_second_click_on_readonly_column_does_nothing(app):
    """只读列没有编辑器可进：再次单击（慢）什么都不做，详情窗留给快速双击。"""
    actor = _make_actor(name="只读列2", actor_id="e13")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 0)
        _click(dlg, 0, 0, wait=_slow_gap(dlg))
        app.processEvents()
        assert dlg._cell_editor is None, "只读列不该有行内编辑器"
        assert dlg._detail_dialogs == {}, "只读列的再次单击不该弹详情窗"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_click_on_another_cell_starts_over(app):
    """换格即重新开始：不会把两格连成一次「再次单击」。"""
    dlg = _manager([_make_actor()])
    try:
        _click(dlg, 0, 1)  # 第一格第 1 次：只选中
        _click(dlg, 0, 4)  # 换格 → 又是一次「选中」
        assert dlg._cell_editor is None
        assert dlg._click_gesture == "select"
        _click(dlg, 0, 4, wait=_slow_gap(dlg))  # 第二格第 2 次 → 行内编辑器
        assert _wait_editor(dlg) is not None
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_double_click_inside_inline_editor_opens_detail(app):
    """编辑状态里双击：弹演员详情窗（用户 2026-10-21 要求）。"""
    from PyQt6.QtWidgets import QApplication as _App

    actor = _make_actor(name="编辑中", actor_id="e14")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)
        _click(dlg, 0, 1, wait=_slow_gap(dlg))
        editor = _wait_editor(dlg)
        assert editor is not None, "应先进，行内编辑器"
        _App.sendEvent(editor, _editor_event("dblclick"))
        assert _wait_detail(dlg), "编辑状态里双击应弹演员详情窗"
        assert set(dlg._detail_dialogs) == {"e14"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_rapid_clicks_inside_inline_editor_open_detail(app):
    """编辑状态里连续快速点击：同样弹演员详情窗。"""
    from PyQt6.QtWidgets import QApplication as _App

    actor = _make_actor(name="编辑中2", actor_id="e15")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)
        _click(dlg, 0, 1, wait=_slow_gap(dlg))
        editor = _wait_editor(dlg)
        assert editor is not None
        _App.sendEvent(editor, _editor_event("press", x=3.0))
        time.sleep(0.02)
        _App.sendEvent(editor, _editor_event("press", x=9.0))
        assert _wait_detail(dlg), "编辑状态里连续点击应弹演员详情窗"
        assert set(dlg._detail_dialogs) == {"e15"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_selected_cell_keeps_original_background_with_blue_border(app):
    """选中格保持原有底色（白/隔行浅灰），只在四周画一圈蓝条表示选中。"""
    from mdcx.tools.emby_actor_manager_ui import _SELECTION_BORDER_COLOR

    dlg = _manager([_make_actor(), _make_actor(name="第二行", actor_id="id2")])
    try:
        dlg.show()
        app.processEvents()
        table = dlg.table
        style = dlg.styleSheet()
        assert "item:selected" not in style, "选中态不该再用样式表铺底色"
        assert "#bbdefb" not in style, "选中态不该再铺浅蓝底"
        table.setCurrentCell(0, 1)
        app.processEvents()
        item = table.item(0, 1)
        rect = table.visualItemRect(item)
        img = table.viewport().grab().toImage()
        assert not img.isNull()

        def px(x, y):
            c = img.pixelColor(x, y)
            return (c.red(), c.green(), c.blue())

        border = tuple(int(_SELECTION_BORDER_COLOR[i : i + 2], 16) for i in (1, 3, 5))
        # 四周一圈蓝条
        assert px(rect.x() + 1, rect.y() + 1) == border, "左上角应是蓝色边框"
        assert px(rect.x() + rect.width() - 2, rect.y() + rect.height() // 2) == border, "右侧应是蓝色边框"
        # 格子内部保持原底色（不是浅蓝、也不是系统高亮深蓝）
        center = px(rect.x() + rect.width() // 2, rect.y() + rect.height() // 2)
        assert center != (187, 222, 251), "选中格不该铺浅蓝底"
        assert center != (48, 140, 198), "选中格不该铺系统高亮深蓝"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
