"""演员管理器主窗口左键手势回归：单击选中 / 双击编辑 / 三击详情。

背景：此前可编辑列（姓名/出生日期/出生地/详情/标签）单击即弹行内编辑器，
误触一次就进入编辑态，用户反馈"太容易误操作"。改成单击只选中后，
"双击编辑"与"双击打开详情窗"又撞在一起，故约定三击开详情窗。

Qt 自己不区分三击：连击的第 2 次按下报的是 MouseButtonDblClick（不是
MouseButtonPress），故连击次数由管理器自己数（press/dblclick 都算一次），
本测试直接驱动管理器内部的连击计数与手势分派函数，验证：

- 单击可编辑列只选中，不弹编辑器；
- 双击可编辑列才进行内编辑，编辑器初值取 UserRole 里的完整值；
- 三击可编辑列提交编辑器后弹演员详情窗（第三次点击落在盖住格子的编辑器上，
  靠行内编辑代理把左键按下转调出去续上连击计数）；
- 不可编辑列双击直接弹详情窗（那里没有编辑器，不存在冲突）；
- 连击计数按「同一格 + 间隔内」累加，换格即重新计数；
- 同一次物理按下被重复上报（press + dblclick）只算一次点击。
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


def _click(dlg, row: int, col: int, times: int = 1, kinds=None):
    """模拟在 (row, col) 上连点 times 次左键（每次按下+松开）。

    kinds 缺省按 Qt 真实行为给：第 1 次报 press，第 2 次起报 dblclick
    （Qt 连击的第 2 次按下不再报 MouseButtonPress）。两次点击之间留
    30ms 间隔，别被「同一次物理按下的重复上报」去重窗口吃掉。
    """
    pos = _cell_pos(dlg, row, col)
    if kinds is None:
        kinds = ["press"] + ["dblclick"] * (times - 1)
    for i in range(times):
        kind = kinds[i] if i < len(kinds) else "press"
        dlg._on_viewport_mouse_click(pos, kind)
        dlg._on_viewport_mouse_release()
        time.sleep(0.03)


def test_single_click_only_selects_no_editor(app):
    """单击可编辑列只选中：不再自动弹行内编辑器（防误触）。"""
    dlg = _manager([_make_actor()])
    try:
        _click(dlg, 0, 1)
        assert dlg._cell_editor is None, "单击不该弹出行内编辑器"
        # 选中由表格自身处理，这里只确认没有编辑器被打开。
        assert dlg._click_count == 1
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_double_click_opens_inline_editor(app):
    """双击可编辑列进行内编辑，编辑器初值取 UserRole 里的完整值。"""
    long_tags = ["标签一", "标签二", "标签三"]
    dlg = _manager([_make_actor(existing_taglines=long_tags)])
    try:
        table = dlg.table
        # 展示只取前 2 个标签，完整值在 UserRole 里。
        assert table.item(0, 7).text() == "标签一, 标签二"
        _click(dlg, 0, 7, times=2)
        editor = dlg._cell_editor
        assert editor is not None, "双击应打开行内编辑器"
        assert editor.text() == "标签一, 标签二, 标签三", "编辑器初值应是完整标签，不是展示文本"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_triple_click_opens_detail_window(app):
    """三击可编辑列：提交编辑器后弹演员详情窗。"""
    actor = _make_actor(name="三击演员", actor_id="e9")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1, times=2)  # 双击进行内编辑器
        editor = dlg._cell_editor
        assert editor is not None
        editor.setText("三击改名")
        # 第三次点击落在盖住格子的编辑器上，表格收不到，由代理转调。
        dlg._on_editor_clicked(0, 1)
        app.processEvents()
        assert actor.name == "三击改名", "弹详情窗前应先提交行内编辑器"
        assert set(dlg._detail_dialogs) == {"e9"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_triple_click_on_viewport_opens_detail_window(app):
    """编辑器没盖住点击点时，三击也走表格视口路径弹详情窗。"""
    actor = _make_actor(name="视口三击", actor_id="e10")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1, times=3)
        app.processEvents()
        assert set(dlg._detail_dialogs) == {"e10"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_double_click_non_editable_column_opens_detail(app):
    """不可编辑列（状态/头像/简介/影片数）双击直接弹详情窗：那里没有编辑器，不冲突。"""
    actor = _make_actor(name="只读列", actor_id="e11")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 0, times=2)
        app.processEvents()
        assert set(dlg._detail_dialogs) == {"e11"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_click_count_resets_when_cell_changes(app):
    """连击按「同一格 + 间隔内」累加：换格即重新计数，不会把两格连成三击。"""
    actor = _make_actor(name="换格", actor_id="e12")
    dlg = _manager([actor])
    try:
        _click(dlg, 0, 1)  # 第一格第 1 次
        _click(dlg, 0, 4)  # 换格 → 重新从 1 起算
        assert dlg._click_count == 1
        assert dlg._cell_editor is None
        _click(dlg, 0, 4)  # 第二格第 2 次 → 双击进行内编辑器
        assert dlg._cell_editor is not None
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_delegate_forwards_editor_click_to_manager(app):
    """行内编辑代理把编辑器上的左键按下/双击转调给管理器（行/列/种类）。

    第三次点击落在盖住格子的编辑器上，表格收不到，得靠代理把事件转调
    出去续上连击计数；种类 press/dblclick 一起带上，主窗口才能给
    「同一次物理按下的重复上报」去重。
    """
    from mdcx.tools.emby_actor_manager_ui import _InlineEditDelegate

    seen: list[tuple[int, int, str]] = []
    delegate = _InlineEditDelegate(None, None, editor_clicked=lambda r, c, k: seen.append((r, c, k)))
    dlg = _manager([_make_actor()])
    try:
        _click(dlg, 0, 4, times=2)
        editor = dlg._cell_editor
        assert editor is not None
        delegate.eventFilter(editor, _left_press_event())
        delegate.eventFilter(editor, _left_dblclick_event())
        assert seen == [(0, 4, "press"), (0, 4, "dblclick")]
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_same_physical_press_reported_twice_counts_once(app):
    """同一次物理按下既报 press 又报 dblclick 时只算一次点击。

    否则双击会被误算成三击：双击就弹详情窗、编辑器都进不去。
    """
    dlg = _manager([_make_actor()])
    try:
        pos = _cell_pos(dlg, 0, 1)
        dlg._on_viewport_mouse_click(pos, "press")
        dlg._on_viewport_mouse_click(pos, "dblclick")  # 同一物理按下的重复上报
        dlg._on_viewport_mouse_release()
        assert dlg._click_count == 1, "重复上报不该累加连击次数"
        assert dlg._cell_editor is None, "只算一次点击就不该弹编辑器"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def _left_press_event():
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5.0, 5.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _left_dblclick_event():
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(5.0, 5.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
