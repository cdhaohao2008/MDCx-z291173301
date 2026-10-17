"""议题 #162: 演员管理器「数据清洗规则」独立窗的两个默认按钮。

- 「恢复默认」按钮右侧新增「保存默认」, 点它把当前编辑的规则存成默认规则
- 再点「恢复默认」读到的就是用户保存的那份(存 Config.actor_clean_rules_default)
- 两条 minnano 占位规则即使用户删了, 保存时也补回并置顶到最前两条;
  内置英文身份译名缺失也补齐
- 「保存默认」只改下次恢复默认的底座, 不动当前生效的规则(用不用由「确定」决定)

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
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

_app: QApplication | None = None

_PINNED = [
    ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
    ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
]


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

    必须是 fixture 而不是只在构造窗口时 patch: 规则窗的按钮回调(_on_save_default /
    _on_restore_default)会再去读模块级的 `manager`, patch 提前退出就会写到真实用户
    配置上去。
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


class TestSaveDefaultButton:
    def test_button_sits_right_of_restore_default(self, dlg):
        """需求原文: 「保存默认」加在「恢复默认」右侧。"""
        texts = [b.text() for b in dlg.findChildren(QPushButton)]
        assert "恢复默认" in texts, texts
        assert "保存默认" in texts, texts
        assert texts.index("保存默认") == texts.index("恢复默认") + 1, texts
        # 只多这一个按钮, 没顺手加别的
        assert set(texts) == {"添加规则", "删除选中", "恢复默认", "保存默认", "确定", "取消"}, texts

    def test_tooltips_state_the_two_guarantees(self, dlg):
        tips = {b.text(): b.toolTip() for b in dlg.findChildren(QPushButton)}
        assert "置顶" in tips["保存默认"], tips["保存默认"]
        assert "补齐" in tips["保存默认"], tips["保存默认"]
        assert "保存默认" in tips["恢复默认"], tips["恢复默认"]

    def test_save_then_restore_round_trip(self, mgr, dlg):
        """保存后恢复默认读到的是用户那份; 且只改默认不动当前生效规则。"""
        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        saved = dlg.rules()
        # 保存后表格回填归一化结果: 两条占位置顶 + 内置英文四条补齐
        assert saved[:2] == _PINNED
        assert ("noise", "噪声") in saved
        assert "已保存为默认规则" in dlg.status_label.text()

        # 清空表格再点「恢复默认」, 读到的就是刚保存的那一份
        dlg.set_rules([])
        dlg._on_restore_default()
        assert dlg.rules() == saved

        # 只改默认: 当前生效的规则没被动过
        assert [list(r) for r in mgr.config.actor_clean_rules] != [list(r) for r in saved]
        assert mgr.save_calls == 1

    def test_deleted_pinned_rules_come_back_pinned_on_first_rows(self, dlg):
        """用户把两条占位规则删光再保存, 仍补回并排最前(需求硬约束)。"""
        dlg.set_rules([("noise", "噪声")])
        dlg._on_save_default()
        assert dlg.table.item(0, 0).text() == _PINNED[0][0]
        assert dlg.table.item(1, 0).text() == _PINNED[1][0]

    def test_restore_default_before_saving_shows_builtin(self, dlg):
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        dlg.set_rules([("noise", "噪声")])
        dlg._on_restore_default()
        assert dlg.rules() == DEFAULT_CLEAN_RULES

    def test_status_line_still_reports_pending_count_after_save(self, dlg):
        """状态行除了保存提示, 仍要报「按当前规则将清洗几个演员」。"""
        dlg.set_rules([*_PINNED, ("noise", "噪声")])
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
