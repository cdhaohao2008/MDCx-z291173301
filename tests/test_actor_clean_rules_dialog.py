"""演员管理器「数据清洗规则」独立窗的交互与默认规则行为。

- 空白区左键单击/双击自动追加一行并进入编辑;
- 单元格编辑完成(单击别处/回车)即自动保存生效规则;
- 右键规则行弹出「删除规则」并立即保存;
- 「恢复默认」/「保存默认」仍可用, 但两条 minnano 占位规则自 v2.7.2 起
  不再是默认规则, 用户删掉后不会被补回或置顶;
- 「取消」只关闭窗口, 不回滚已经自动保存的编辑。

Qt 用例单独成文件: 构造 QDialog 必须先有 QApplication, 与纯函数用例
(test_emby_actor_data_clean.py) 分开以免把 Qt 依赖带进那个文件。做法照
tests/test_window_centering.py 的 `_ensure_app()`。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


class _FakeManager:
    """只实现清洗规则持久化用到的三个成员, 免得测 UI 也去起真实 ConfigManager 写盘。"""

    def __init__(self):
        from mdcx.config.models import Config

        self.config = Config()
        self.save_calls = 0

    def _replace_config(self, cfg):
        self.config = cfg

    def save(self):
        self.save_calls += 1


@pytest.fixture
def mgr():
    """整段用例把模块级 manager 换成 fake。

    必须是 fixture 而不是只在构造窗口时 patch: 规则窗的按钮回调与自动保存都会
    再读模块级的 `manager`, patch 提前退出就会写到真实用户配置上去。
    """
    fake = _FakeManager()
    with patch("mdcx.tools.emby_actor_manager_ui.manager", fake):
        yield fake


@pytest.fixture
def dlg(mgr):
    """规则窗实例; 关窗交给用例的 finally, 删除延后由 conftest 的 Qt 收尾处理。"""
    from mdcx.tools.emby_actor_manager_ui import ActorCleanRulesDialog

    _ensure_app()
    window = ActorCleanRulesDialog([])
    try:
        yield window
    finally:
        window.close()


def _blank_pos(window) -> QPoint:
    """最后一行下方的空白点, 并确认它确实不落在任何单元格上。"""
    table = window.table
    viewport = table.viewport()
    assert viewport is not None
    last_row = table.rowCount() - 1
    if last_row >= 0:
        rect = table.visualItemRect(table.item(last_row, 0))
        y = min(max(rect.bottom() + 12, 8), viewport.height() - 8)
    else:
        y = 8
    pos = QPoint(12, y)
    assert not table.indexAt(pos).isValid(), "测试取点应位于表格空白区"
    return pos


def _click_blank(window) -> QPoint:
    from PyQt6.QtWidgets import QAbstractItemView

    window.show()
    QApplication.processEvents()
    pos = _blank_pos(window)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QApplication.processEvents()
    assert window.table.state() == QAbstractItemView.State.EditingState
    return pos


class TestSaveDefaultButton:
    def test_button_sits_right_of_restore_default(self, dlg):
        """需求原文: 「保存默认」加在「恢复默认」右侧。"""
        texts = [b.text() for b in dlg.findChildren(QPushButton)]
        assert "恢复默认" in texts, texts
        assert "保存默认" in texts, texts
        assert texts.index("保存默认") == texts.index("恢复默认") + 1, texts
        # 只多这一个按钮, 没顺手加别的
        assert set(texts) == {"添加规则", "删除选中", "恢复默认", "保存默认", "确定", "取消"}, texts

    def test_tooltips_state_the_guarantees(self, dlg):
        tips = {b.text(): b.toolTip() for b in dlg.findChildren(QPushButton)}
        assert "补齐" in tips["保存默认"], tips["保存默认"]
        assert "minnano" in tips["保存默认"], tips["保存默认"]
        assert "不再" in tips["保存默认"], tips["保存默认"]
        assert "置顶" not in tips["保存默认"], tips["保存默认"]
        assert "保存默认" in tips["恢复默认"], tips["恢复默认"]

    def test_save_then_restore_round_trip(self, mgr, dlg):
        """保存后恢复默认读到的是用户那份; 且只改默认不动当前生效规则。"""
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        saved = dlg.rules()
        # 保存后表格回填归一化结果: 用户自定义在前, 内置英文四条补齐
        assert saved == [("noise", "噪声"), *DEFAULT_CLEAN_RULES]
        assert not any("minnano" in original for original, _ in saved)
        assert "已保存为默认规则" in dlg.status_label.text()

        # 清空表格再点「恢复默认」, 读到的就是刚保存的那一份
        dlg.set_rules([])
        dlg._on_restore_default()
        assert dlg.rules() == saved

        # 只改默认: 当前生效的规则没被动过
        assert [list(r) for r in mgr.config.actor_clean_rules] != [list(r) for r in saved]
        assert mgr.save_calls == 1

    def test_deleted_minnano_rules_never_come_back(self, dlg):
        """两条 minnano 占位规则删掉后再保存默认, 不会被补回或置顶。"""
        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        saved = dlg.rules()
        assert saved[0] == ("noise", "噪声")
        assert not any("minnano" in original for original, _ in saved), saved

    def test_restore_default_before_saving_shows_builtin(self, dlg):
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        dlg.set_rules([("noise", "噪声")])
        dlg._on_restore_default()
        assert dlg.rules() == DEFAULT_CLEAN_RULES
        assert not any("minnano" in original for original, _ in dlg.rules())

    def test_status_line_still_reports_pending_count_after_save(self, dlg):
        """状态行除了保存提示, 仍要报「按当前规则将清洗几个演员」。"""
        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        text = dlg.status_label.text()
        assert text.startswith("已保存为默认规则")
        assert "按当前规则将清洗" in text
        assert "共 0 个" in text

    def test_saved_default_reaches_active_rules_through_confirm(self, mgr, dlg):
        """保存默认 → 点「确定」→ 重开窗口, 生效规则里已含用户保存的自定义规则。"""
        from mdcx.tools.emby_actor_manager_ui import ActorCleanRulesDialog, save_clean_rules

        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        save_clean_rules(dlg.rules())
        assert ["noise", "噪声"] in mgr.config.actor_clean_rules

        dlg.close()
        reopened = ActorCleanRulesDialog([])
        try:
            assert ("noise", "噪声") in reopened.rules()
        finally:
            reopened.close()


class TestQuickEdit:
    def test_single_click_below_last_row_appends_and_edits(self, dlg):
        """空白区左键单击: 自动加一行并进入「原始数值」编辑。"""
        dlg.show()
        QApplication.processEvents()
        before = dlg.table.rowCount()
        pos = _blank_pos(dlg)

        QTest.mouseClick(dlg.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        QApplication.processEvents()

        assert dlg.table.rowCount() == before + 1
        assert dlg.table.currentRow() == before
        assert dlg.table.currentColumn() == 0
        assert dlg.table.item(before, 0).text() == ""

    def test_double_click_below_last_row_adds_only_one_row(self, dlg):
        """双击的第一次单击已加行, 紧随的 DblClick 不再重复加。"""
        dlg.show()
        QApplication.processEvents()
        before = dlg.table.rowCount()
        pos = _blank_pos(dlg)

        QTest.mouseDClick(dlg.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        QApplication.processEvents()

        assert dlg.table.rowCount() == before + 1

    def test_edit_autosaves_without_confirm(self, mgr, dlg):
        """单元格编辑完成即写回生效规则, 无需再点「确定」。"""
        dlg.set_rules([("noise", "")])
        assert mgr.save_calls == 0, "程序化装载规则不应触发自动保存"

        dlg.table.item(0, 1).setText("噪声")
        QApplication.processEvents()

        assert ["noise", "噪声"] in mgr.config.actor_clean_rules
        assert mgr.save_calls == 1
        assert "已自动保存" in dlg.status_label.text()

    def test_enter_commits_and_autosaves(self, mgr, dlg):
        """编辑单元格后按回车即提交并自动保存。"""
        from PyQt6.QtWidgets import QLineEdit

        dlg.set_rules([("noise", "")])
        dlg.show()
        dlg.activateWindow()
        QApplication.processEvents()
        dlg.table.editItem(dlg.table.item(0, 1))
        QApplication.processEvents()
        editor = QApplication.focusWidget()
        assert isinstance(editor, QLineEdit)

        QTest.keyClicks(editor, "X")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QApplication.processEvents()

        assert dlg.table.item(0, 1).text() == "X"
        assert ["noise", "X"] in mgr.config.actor_clean_rules
        assert mgr.save_calls == 1

    def test_clicking_blank_area_commits_edit_before_adding_row(self, mgr, dlg):
        """编辑单元格后单击下方空白区: 先提交并保存, 再新增一行。"""
        from PyQt6.QtWidgets import QLineEdit

        dlg.set_rules([("noise", "")])
        dlg.show()
        dlg.activateWindow()
        QApplication.processEvents()
        dlg.table.editItem(dlg.table.item(0, 1))
        QApplication.processEvents()
        editor = QApplication.focusWidget()
        assert isinstance(editor, QLineEdit)
        QTest.keyClicks(editor, "X")
        pos = _blank_pos(dlg)

        QTest.mouseClick(dlg.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        QApplication.processEvents()

        assert dlg.table.item(0, 1).text() == "X"
        assert ["noise", "X"] in mgr.config.actor_clean_rules
        assert dlg.table.rowCount() == 2
        assert mgr.save_calls == 1

    def test_cancel_does_not_roll_back_autosaved_edit(self, mgr, dlg):
        """「取消」只关窗; 已经自动保存的编辑不回滚。"""
        dlg.set_rules([("noise", "")])
        dlg.table.item(0, 1).setText("噪声")
        QApplication.processEvents()

        dlg.reject()
        QApplication.processEvents()

        assert ["noise", "噪声"] in mgr.config.actor_clean_rules


class TestRightClickDelete:
    def test_right_click_row_deletes_and_autosaves(self, mgr, dlg, monkeypatch):
        """右键规则行 → 菜单「删除规则」→ 删行并立即保存。"""

        class _Action:
            def setToolTip(self, _text):
                pass

        class _Menu:
            def __init__(self, _parent=None):
                self.action = _Action()

            def addAction(self, _text):
                return self.action

            def exec(self, _pos):
                return self.action

        monkeypatch.setattr("mdcx.tools.emby_actor_manager_ui.QMenu", _Menu)
        dlg.set_rules([("a", "1"), ("b", "2")])
        dlg.show()
        QApplication.processEvents()
        rect = dlg.table.visualItemRect(dlg.table.item(0, 0))
        pos = rect.center()

        dlg._on_table_context_menu(pos)
        QApplication.processEvents()

        assert dlg.table.rowCount() == 1
        assert dlg.rules()[0] == ("b", "2")
        assert ["a", "1"] not in mgr.config.actor_clean_rules
        assert ["b", "2"] in mgr.config.actor_clean_rules
        assert mgr.save_calls == 1
        assert "已自动保存" in dlg.status_label.text()

    def test_blank_context_menu_does_nothing(self, mgr, dlg, monkeypatch):
        """空白区右键不弹删除菜单, 也不触发保存。"""

        class _Menu:
            def __init__(self, _parent=None):
                raise AssertionError("空白区不应创建右键菜单")

        monkeypatch.setattr("mdcx.tools.emby_actor_manager_ui.QMenu", _Menu)
        dlg.set_rules([("a", "1")])
        dlg.show()
        QApplication.processEvents()
        before = dlg.table.rowCount()

        dlg._on_table_context_menu(_blank_pos(dlg))
        QApplication.processEvents()

        assert dlg.table.rowCount() == before
        assert mgr.save_calls == 0
