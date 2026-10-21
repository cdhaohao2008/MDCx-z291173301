"""演员管理器行内编辑器的外观回归：编辑状态纯白底 + 四周一圈蓝边。

用户 2026-10-21 反馈：姓名/出生日期/出生地/详情/标签进入编辑状态后整格铺着
蓝色底色——那是 Qt 打开编辑器时自动全选文本 + 系统高亮色（Highlight=#308cc6
配 HighlightedText=#ffffff，白字压深蓝底）造成的，看不清。要求改成纯白底，
只在四周留一圈蓝条表示「正处于编辑状态」。

本测试验证：
- 编辑器底色纯白、文字黑色、四周有蓝色边框（编辑状态只由蓝边表示）；
- 打开编辑器后没有选中的文字（光标落在文本末尾），格子不会出现蓝底；
- 打开瞬间的「选中底色」是白色（选中态隐形），用户自己动手后换成浅蓝底
  黑字（看得清、也认得出选中了哪一段）；
- 五个可编辑列（姓名/出生日期/出生地/详情/标签）走的是同一套样式。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import Qt
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


def _open_editor(dlg, row: int, col: int):
    """打开行内编辑器并返回它（走管理器自己的入口）。"""
    dlg._open_cell_editor(row, col)
    editor = dlg._cell_editor
    assert editor is not None, f"({row},{col}) 没能打开行内编辑器"
    return editor


def test_editor_is_white_with_blue_border(app):
    """编辑器：纯白底 + 黑字 + 一圈蓝边（编辑状态只由蓝边表示）。"""
    from mdcx.tools.emby_actor_manager_ui import _INLINE_EDITOR_QSS

    dlg = _manager([_make_actor()])
    try:
        editor = _open_editor(dlg, 0, 1)
        style = editor.styleSheet()
        assert "background-color: #ffffff" in style, "编辑器底色应为纯白"
        assert "color: #000000" in style, "编辑器文字应为黑色"
        assert "border: 2px solid #1565c0" in style, "编辑器四周应有蓝色边框"
        assert style == _INLINE_EDITOR_QSS, "样式表应与常量一致，避免两处各写一份"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_editor_opens_without_selected_text(app):
    """打开编辑器时不再有选中的文字：不会铺出一整块蓝底。"""
    dlg = _manager([_make_actor(existing_taglines=["标签一", "标签二", "标签三"])])
    try:
        editor = _open_editor(dlg, 0, 7)
        assert not editor.hasSelectedText(), "打开编辑器不应全选文本"
        assert editor.selectedText() == ""
        assert editor.cursorPosition() == len(editor.text()), "光标应落在文本末尾"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_selection_color_hidden_on_open_then_light_after_user_input(app):
    """打开瞬间选中底色是白色（隐形）；用户动手后换成浅蓝底黑字。"""
    from PyQt6.QtTest import QTest

    from mdcx.tools.emby_actor_manager_ui import (
        _INLINE_EDITOR_SELECTION_BG,
        _INLINE_EDITOR_SELECTION_BG_HIDDEN,
        _INLINE_EDITOR_SELECTION_FG,
    )

    dlg = _manager([_make_actor()])
    try:
        editor = _open_editor(dlg, 0, 1)
        pal = editor.palette()
        assert pal.color(pal.ColorRole.Highlight).name().lower() == _INLINE_EDITOR_SELECTION_BG_HIDDEN
        assert pal.color(pal.ColorRole.HighlightedText).name().lower() == _INLINE_EDITOR_SELECTION_FG
        # 用户按一次键（Shift 不改内容）后，选中态改回可见的浅蓝底
        QTest.keyClick(editor, Qt.Key.Key_Shift)
        pal = editor.palette()
        assert pal.color(pal.ColorRole.Highlight).name().lower() == _INLINE_EDITOR_SELECTION_BG
        assert pal.color(pal.ColorRole.HighlightedText).name().lower() == _INLINE_EDITOR_SELECTION_FG
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_all_editable_columns_share_the_same_style(app):
    """姓名/出生日期/出生地/详情/标签五个可编辑列都是同一套纯白底 + 蓝边。"""
    from PyQt6.QtWidgets import QAbstractItemDelegate

    from mdcx.tools.emby_actor_manager_ui import _EDITABLE_COLUMNS

    assert _EDITABLE_COLUMNS == frozenset((1, 4, 5, 6, 7))
    dlg = _manager([_make_actor()])
    try:
        for col in sorted(_EDITABLE_COLUMNS):
            dlg._open_cell_editor(0, col)
            editor = dlg._cell_editor
            assert editor is not None, f"第 {col} 列没能打开行内编辑器"
            style = editor.styleSheet()
            assert "background-color: #ffffff" in style, f"第 {col} 列底色应为纯白"
            assert "border: 2px solid #1565c0" in style, f"第 {col} 列应有蓝色边框"
            assert not editor.hasSelectedText(), f"第 {col} 列打开时不应有选中的文字"
            # 关闭编辑器，避免下一列沿用上一个编辑器
            dlg.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.SubmitModelCache)
            app.processEvents()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
