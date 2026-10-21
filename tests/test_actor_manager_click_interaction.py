"""演员管理器主窗口左键手势回归：单击选中 / 再次单击编辑 / 快速双击详情。

背景：可编辑列（姓名/出生日期/出生地/详情/标签）此前单击即弹行内编辑器，
误触一次就进入编辑态，用户反馈"太容易误操作"。改成单击只选中后，
"双击编辑"与"双击打开详情窗"又撞在一起，故约定三段式手势。

用户 2026-10-21 再次调整手势：
- 单击某格 → 只选中（浅蓝底）；
- 已选中该格、再点一次（两次点击间隔超出双击间隔）→ 进行内编辑；
- 快速双击（两次点击间隔在双击间隔内，Qt 把第二次按下报成
  MouseButtonDblClick）→ 弹演员详情窗。

"再次单击"与"快速双击"的区分不靠自己的连击计数，而靠两件事：
① 点的是不是上一次点过的那一格；② 两次点击的间隔是否在系统双击间隔内。

本测试直接驱动管理器内部的手势判定与分派函数，验证：

- 单击可编辑列只选中，不弹编辑器；
- 再次单击可编辑列进行内编辑，编辑器初值取 UserRole 里的完整值；
- 快速双击可编辑列弹演员详情窗（且不会同时开编辑器）；
- 不可编辑列快速双击也弹详情窗，再次单击则什么都不做；
- 换格即重新开始（不会把两格连成一次手势）；
- 同一次物理按下被重复上报（press + dblclick）只算一次点击；
- 编辑器里点击不再弹详情窗（详情窗由快速双击在进编辑器之前就分派完了）。
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
    dlg._on_viewport_mouse_release()


def _slow_gap(dlg) -> float:
    """「再次单击」的间隔：超过系统双击间隔（这种第二次点击走行内编辑）。"""
    return dlg._click_interval() + 0.05


def _fast_gap() -> float:
    """「快速双击」的间隔：在双击间隔内、但大于重复上报去重窗口（10ms）。"""
    return 0.05


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
        editor = dlg._cell_editor
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
        app.processEvents()
        assert set(dlg._detail_dialogs) == {"e9"}, "快速双击应弹演员详情窗"
        assert dlg._cell_editor is None, "快速双击不该同时开行内编辑器"
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
        app.processEvents()
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
        assert dlg._cell_editor is not None
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_same_physical_press_reported_twice_counts_once(app):
    """同一次物理按下既报 press 又报 dblclick 时只算一次点击。

    否则一次按下会被当成「单击 + 快速双击」两个手势：既弹详情窗又进编辑器。
    """
    dlg = _manager([_make_actor()])
    try:
        pos = _cell_pos(dlg, 0, 1)
        dlg._on_viewport_mouse_click(pos, "press")
        dlg._on_viewport_mouse_click(pos, "dblclick")  # 同一物理按下的重复上报
        dlg._on_viewport_mouse_release()
        app.processEvents()
        assert dlg._click_gesture == "select", "重复上报不该被当成快速双击"
        assert dlg._cell_editor is None, "只算一次点击就不该弹编辑器"
        assert dlg._detail_dialogs == {}, "只算一次点击就不该弹详情窗"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_selected_cell_uses_light_blue_background(app):
    """选中的格子用浅蓝底 + 黑字（不再是深蓝底 #42a5f5 配白字，看不清）。"""
    dlg = _manager([_make_actor()])
    try:
        style = dlg.styleSheet()
        assert "QTableWidget::item:selected { background-color: #bbdefb; color: #000000; }" in style, (
            "选中态应为浅蓝底 + 黑字"
        )
        assert "#42a5f5" not in style, "选中态不应再用深蓝底"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_click_inside_editor_does_not_open_detail(app):
    """编辑器里点击只挪光标，不弹详情窗（详情窗由快速双击在进编辑器前分派）。"""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    actor = _make_actor(name="编辑中", actor_id="e14")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)
        _click(dlg, 0, 1, wait=_slow_gap(dlg))  # 再次单击 → 进编辑器
        editor = dlg._cell_editor
        assert editor is not None
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(3.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(editor, press)  # 编辑器里点一下（挪光标）
        app.processEvents()
        assert dlg._detail_dialogs == {}, "编辑器里点击不该弹详情窗"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
