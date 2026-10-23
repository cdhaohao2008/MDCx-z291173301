"""分离模式 STRM「生成 / 覆盖」联动回归测试。

用户诉求：勾选「替换链接文本」时同步勾选
「生成链接文本」——没有生成 STRM 文件就无从覆盖。

覆盖三层：

1. 归一口径：``normalize_strm_policy``（勾了覆盖 ⇒ 必须也勾了生成；
   取消生成 ⇒ 覆盖一并取消）
2. 界面层：两个处理器互相联动
3. 配置层：配置迁移把「只勾了覆盖」的旧配置补上生成（否则覆盖永远不生效）
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mdcx.config.extend import normalize_strm_policy
from mdcx.config.migrations import migrate_config_data

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = REPO_ROOT / "mdcx" / "views" / "MDCx.ui"


# --------------------------------------------------------------------------
# 1. 归一口径（加载 / 保存共用的唯一实现）
# --------------------------------------------------------------------------


def test_normalize_strm_policy_links_overwrite_to_generate():
    """勾了覆盖 ⇒ 必须同时勾了生成；没勾覆盖时生成原样保留。"""
    assert normalize_strm_policy(False, True) == (True, True)
    assert normalize_strm_policy(True, True) == (True, True)
    assert normalize_strm_policy(True, False) == (True, False)
    assert normalize_strm_policy(False, False) == (False, False)


def test_normalize_strm_policy_never_keeps_overwrite_without_generate():
    """归一后的组合里不允许出现「只勾覆盖」这种没有生成可覆盖的非法状态。"""
    for generate in (False, True):
        for overwrite in (False, True):
            new_generate, new_overwrite = normalize_strm_policy(generate, overwrite)
            assert not (new_overwrite and not new_generate)


# --------------------------------------------------------------------------
# 2. 界面层
# --------------------------------------------------------------------------


class _FakeCheckBox:
    """只实现 setChecked / isChecked 的假复选框，用于单测联动处理器。"""

    def __init__(self, checked: bool = False) -> None:
        self.checked = checked

    def setChecked(self, value: bool) -> None:
        self.checked = bool(value)

    def isChecked(self) -> bool:
        return self.checked


class _FakeUi:
    def __init__(self) -> None:
        self.checkBox_separate_generate_strm = _FakeCheckBox()
        self.checkBox_separate_overwrite_strm = _FakeCheckBox()


class _FakeHost:
    def __init__(self) -> None:
        self.Ui = _FakeUi()


def test_ui_handlers_link_overwrite_and_generate():
    """界面层：勾覆盖 → 同步勾生成；取消生成 → 覆盖一并取消。"""
    from mdcx.controllers.main_window.settings_actions import SettingsActionsMixin

    host = _FakeHost()
    generate = host.Ui.checkBox_separate_generate_strm
    overwrite = host.Ui.checkBox_separate_overwrite_strm

    # 勾「替换链接文本」→ 同步勾「生成链接文本」
    overwrite.checked = True
    SettingsActionsMixin.checkBox_separate_overwrite_strm_changed(host, True)
    assert overwrite.checked is True
    assert generate.checked is True, "勾选覆盖时必须同步勾选生成"

    # 取消「生成」→ 覆盖一并取消（没有生成就没有可覆盖的）
    generate.checked = False
    SettingsActionsMixin.checkBox_separate_generate_strm_changed(host, False)
    assert generate.checked is False
    assert overwrite.checked is False, "取消生成后覆盖项应同步取消"

    # 取消「覆盖」不牵连「生成」
    generate.checked = True
    overwrite.checked = False
    SettingsActionsMixin.checkBox_separate_overwrite_strm_changed(host, False)
    assert generate.checked is True
    assert overwrite.checked is False


# --------------------------------------------------------------------------
# 3. 配置层（迁移升级）
# --------------------------------------------------------------------------


def test_migration_adds_generate_when_only_overwrite_enabled():
    """旧配置只勾了覆盖 → 迁移补上生成，否则覆盖永远不生效。"""
    data = {"separate_overwrite_strm": True}
    migrate_config_data(data)
    assert data["separate_generate_strm"] is True
    assert data["separate_overwrite_strm"] is True


def test_migration_keeps_both_enabled_untouched():
    """两个都勾了 → 保持原样。"""
    data = {"separate_overwrite_strm": True, "separate_generate_strm": True}
    migrate_config_data(data)
    assert data["separate_generate_strm"] is True
    assert data["separate_overwrite_strm"] is True


def test_migration_keeps_both_disabled_untouched():
    """两个都没勾 → 保持原样（默认档＝既不生成也不覆盖）。"""
    data = {"separate_overwrite_strm": False, "separate_generate_strm": False}
    migrate_config_data(data)
    assert data["separate_generate_strm"] is False
    assert data["separate_overwrite_strm"] is False


def test_migration_only_generate_stays_unchanged():
    """只勾生成 → 保持原样（允许只生成不覆盖）。"""
    data = {"separate_overwrite_strm": False, "separate_generate_strm": True}
    migrate_config_data(data)
    assert data["separate_generate_strm"] is True
    assert data["separate_overwrite_strm"] is False


# --------------------------------------------------------------------------
# 4. 界面结构
# --------------------------------------------------------------------------


def _widget(root: ET.Element, name: str) -> ET.Element | None:
    for element in root.iter():
        if element.get("name") == name:
            return element
    return None


def _string_prop(widget: ET.Element, prop_name: str) -> str:
    for prop in widget.findall("property"):
        if prop.get("name") == prop_name:
            node = prop.find("string")
            if node is not None and node.text:
                return node.text
    return ""


def test_ui_tooltip_explains_overwrite_auto_links_generate():
    """覆盖框的提示词写明「勾选本项会自动勾选生成」。"""
    root = ET.parse(UI_PATH).getroot()
    overwrite = _widget(root, "checkBox_separate_overwrite_strm")
    assert overwrite is not None, "缺少 checkBox_separate_overwrite_strm"
    tip = _string_prop(overwrite, "toolTip")
    assert "自动勾选" in tip, f"提示词未说明自动勾选生成：{tip}"
    assert "生成链接文本" in tip, f"提示词未点明联动项：{tip}"


def test_ui_strm_checkbox_texts_unchanged():
    """两枚复选框的文案保持不变（只改联动，不改文案）。"""
    root = ET.parse(UI_PATH).getroot()
    generate = _widget(root, "checkBox_separate_generate_strm")
    overwrite = _widget(root, "checkBox_separate_overwrite_strm")
    assert generate is not None and overwrite is not None
    assert _string_prop(generate, "text") == "生成链接文本"
    assert _string_prop(overwrite, "text") == "替换链接文本"
