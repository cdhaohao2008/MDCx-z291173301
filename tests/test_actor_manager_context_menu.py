"""演员管理器主窗口右键小菜单回归：复制内容 / 编辑内容 / 查看详情。

背景：可编辑列（姓名/出生日期/出生地/详情/标签）此前右键直接复制展示
文本，既没有反馈也不能做别的操作；用户要求右键弹一个小窗口，三项分别是：
- 复制内容：直接复制当前栏的内容（取 UserRole 里的完整值，展示文本会被
  截断：详情只留 80 字、标签只展示前 2 个，复制半截没意义）；
- 编辑内容：与左键双击一致，直接把本栏变成行内可编辑状态；
- 查看详情：与左键三击一致，弹出演员详情窗口。

QMenu.exec() 在离屏环境下会阻塞事件循环，故测试里替换成截获实现；
不可编辑列（状态/头像/简介/影片数）右键不弹菜单。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

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


def _patch_menu(monkeypatch) -> dict:
    """替换 QMenu.exec（真实 exec 阻塞离屏事件循环），返回可变状态字典。

    state["action"] 指定要自动选中的菜单项文本（模拟用户点选，exec 返回该项），
    state["menus"] 收集弹出的菜单实例。
    """
    from PyQt6.QtWidgets import QMenu

    state: dict = {"action": None, "menus": []}

    def _fake_exec(self, *args, **kwargs):
        state["menus"].append(self)
        target = state["action"]
        if target:
            for act in self.actions():
                if act.text() == target:
                    return act
        return None

    monkeypatch.setattr(QMenu, "exec", _fake_exec)
    return state


def _right_click(dlg, row: int, col: int) -> None:
    dlg._on_table_right_clicked(_cell_pos(dlg, row, col))


def test_right_click_menu_has_three_items(app, monkeypatch):
    """右键可编辑列弹出的菜单正好三项，顺序为 复制内容/编辑内容/查看详情。"""
    from mdcx.tools.emby_actor_manager_ui import (
        _CELL_MENU_COPY,
        _CELL_MENU_DETAIL,
        _CELL_MENU_EDIT,
    )

    dlg = _manager([_make_actor()])
    try:
        state = _patch_menu(monkeypatch)
        _right_click(dlg, 0, 1)
        assert len(state["menus"]) == 1, "右键可编辑列应弹出一个菜单"
        texts = [act.text() for act in state["menus"][0].actions()]
        assert texts == [_CELL_MENU_COPY, _CELL_MENU_EDIT, _CELL_MENU_DETAIL]
        assert texts == ["复制内容", "编辑内容", "查看详情"]
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_menu_copy_copies_full_cell_value(app, monkeypatch):
    """「复制内容」复制该栏的完整内容，而不是被截断的展示文本。"""
    from PyQt6.QtGui import QGuiApplication

    long_tags = ["标签一", "标签二", "标签三"]
    dlg = _manager([_make_actor(existing_taglines=long_tags)])
    try:
        table = dlg.table
        assert table.item(0, 7).text() == "标签一, 标签二"  # 展示只留前 2 个
        state = _patch_menu(monkeypatch)
        state["action"] = "复制内容"
        _right_click(dlg, 0, 7)
        assert QGuiApplication.clipboard().text() == "标签一, 标签二, 标签三"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_menu_edit_opens_inline_editor(app, monkeypatch):
    """「编辑内容」与左键双击一致：把本栏变成行内可编辑状态。"""
    long_tags = ["标签一", "标签二", "标签三"]
    dlg = _manager([_make_actor(existing_taglines=long_tags)])
    try:
        state = _patch_menu(monkeypatch)
        state["action"] = "编辑内容"
        _right_click(dlg, 0, 7)
        editor = dlg._cell_editor
        assert editor is not None, "「编辑内容」应打开行内编辑器"
        assert editor.text() == "标签一, 标签二, 标签三", "编辑器初值应是完整内容"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_menu_detail_opens_actor_detail_window(app, monkeypatch):
    """「查看详情」与左键三击一致：弹出演员详情窗口。"""
    actor = _make_actor(name="右键详情", actor_id="e20")
    dlg = _manager([actor])
    try:
        state = _patch_menu(monkeypatch)
        state["action"] = "查看详情"
        _right_click(dlg, 0, 1)
        app.processEvents()
        assert set(dlg._detail_dialogs) == {"e20"}
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_right_click_non_editable_column_has_no_menu(app, monkeypatch):
    """不可编辑列（状态/头像/简介/影片数）右键不弹菜单。"""
    dlg = _manager([_make_actor()])
    try:
        state = _patch_menu(monkeypatch)
        for col in (0, 2, 3, 8):
            _right_click(dlg, 0, col)
        assert state["menus"] == [], "不可编辑列不该弹菜单"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_right_click_outside_any_cell_has_no_menu(app, monkeypatch):
    """点在空白处（无格子）右键不弹菜单。"""
    dlg = _manager([_make_actor()])
    try:
        state = _patch_menu(monkeypatch)
        dlg._on_table_right_clicked(dlg.table.viewport().rect().bottomLeft())
        assert state["menus"] == [], "空白处不该弹菜单"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_menu_closed_without_selection_does_nothing(app, monkeypatch):
    """菜单被点外面关掉（没有选中任何项）时不做任何事。"""
    from PyQt6.QtGui import QGuiApplication

    dlg = _manager([_make_actor()])
    try:
        QGuiApplication.clipboard().setText("原样")
        state = _patch_menu(monkeypatch)
        state["action"] = None  # 模拟点菜单外关闭
        _right_click(dlg, 0, 1)
        assert QGuiApplication.clipboard().text() == "原样"
        assert dlg._cell_editor is None
        assert dlg._detail_dialogs == {}
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
