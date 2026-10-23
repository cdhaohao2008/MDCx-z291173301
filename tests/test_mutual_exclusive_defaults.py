"""「必须勾选其中一个」的互斥开关组回归测试。

覆盖两组互斥开关：

1. 高级页 → 移动文件：「覆盖目标文件」/「保留目标文件」
   - 默认档＝保留目标文件（出厂配置、pydantic 默认、迁移升级、界面初始态都勾它）；
   - 两者必须勾选其中一个：都没勾时按默认档校正，保存配置时校验后写盘。
2. 高级功能 → 任务模式：「本地存储文件」/「网盘存储文件」
   - 默认档＝本地存储不设置时间间隔整理文件；
   - 两者必须勾选其中一个：都没勾时按默认档校正，保存配置时校验后写盘。
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mdcx.config.enums import Switch
from mdcx.config.extend import (
    normalize_move_file_policy,
    normalize_move_file_switches,
    normalize_task_mode_switches,
)
from mdcx.config.migrations import migrate_config_data
from mdcx.config.models import Config

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = REPO_ROOT / "mdcx" / "views" / "MDCx.ui"
TEMPLATE_PATH = REPO_ROOT / "resources" / "config" / "default_config.json"


# --------------------------------------------------------------------------
# 1. 归一口径（配置层唯一实现）
# --------------------------------------------------------------------------


def test_normalize_move_file_policy_falls_back_to_keep():
    """都没勾 → 默认档「保留目标文件」；都勾 → 只留「保留目标文件」；只勾一个 → 原样。"""
    assert normalize_move_file_policy(False, False) == (False, True)
    assert normalize_move_file_policy(True, True) == (False, True)
    assert normalize_move_file_policy(True, False) == (True, False)
    assert normalize_move_file_policy(False, True) == (False, True)


def test_normalize_move_file_switches_keeps_explicit_choice():
    """开关列表校正：没勾补默认档、都勾去掉覆盖、只勾一个原样保留。"""
    assert normalize_move_file_switches([], False, False) == [Switch.MOVE_KEEP]
    assert normalize_move_file_switches([Switch.MOVE_OVERWRITE, Switch.MOVE_KEEP], True, True) == [Switch.MOVE_KEEP]
    assert normalize_move_file_switches([Switch.MOVE_OVERWRITE], True, False) == [Switch.MOVE_OVERWRITE]
    assert normalize_move_file_switches([Switch.MOVE_KEEP], False, True) == [Switch.MOVE_KEEP]
    # 其它开关不受影响
    assert normalize_move_file_switches([Switch.SORT_DEL], False, False) == [Switch.SORT_DEL, Switch.MOVE_KEEP]


def test_normalize_task_mode_switches_falls_back_to_local():
    """都没勾 → 默认档「本地存储文件」；都勾 → 只留「网盘存储文件」。"""
    assert normalize_task_mode_switches([]) == [Switch.TASK_STORE_LOCAL]
    assert normalize_task_mode_switches([Switch.TASK_STORE_LOCAL, Switch.TASK_STORE_NETDISK]) == [
        Switch.TASK_STORE_NETDISK
    ]
    assert normalize_task_mode_switches([Switch.TASK_STORE_LOCAL]) == [Switch.TASK_STORE_LOCAL]
    assert normalize_task_mode_switches([Switch.TASK_STORE_NETDISK]) == [Switch.TASK_STORE_NETDISK]


# --------------------------------------------------------------------------
# 2. 配置迁移（老配置自动升级）
# --------------------------------------------------------------------------


def test_migration_adds_move_keep_when_neither_present():
    """老配置没有移动文件开关 → 自动升级为默认档「保留目标文件」。"""
    data = {"switch_on": ["sort_del"]}
    migrate_config_data(data)
    assert "move_keep" in data["switch_on"]
    assert "move_overwrite" not in data["switch_on"]
    assert "sort_del" in data["switch_on"]

    # 逗号分隔的字符串形态同样补齐
    data = {"switch_on": "sort_del"}
    migrate_config_data(data)
    assert "move_keep" in str(data["switch_on"])

    # 两个都勾上 → 只留更安全的 move_keep
    data = {"switch_on": ["move_overwrite", "move_keep"]}
    migrate_config_data(data)
    assert "move_keep" in data["switch_on"]
    assert "move_overwrite" not in data["switch_on"]

    # 只勾了「覆盖目标文件」→ 尊重用户的显式选择
    data = {"switch_on": ["move_overwrite"]}
    migrate_config_data(data)
    assert "move_overwrite" in data["switch_on"]
    assert "move_keep" not in data["switch_on"]


def test_migration_keeps_task_mode_default():
    """老配置没有任务模式开关 → 自动升级为默认档「本地存储文件」。"""
    data: dict = {}
    migrate_config_data(data)
    assert Switch.TASK_STORE_LOCAL in data.get("switch_on", [])
    assert Switch.TASK_STORE_NETDISK not in data.get("switch_on", [])


# --------------------------------------------------------------------------
# 3. 出厂默认
# --------------------------------------------------------------------------


def test_default_config_template_defaults_to_move_keep():
    """出厂配置：移动文件默认勾「保留目标文件」，整理模式默认勾「本地存储不设置时间间隔」。"""
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert "move_keep" in template["switch_on"]
    assert "move_overwrite" not in template["switch_on"]
    assert "task_store_local" in template.get("switch_on", [])
    assert "task_store_netdisk" not in template.get("switch_on", [])


def test_config_model_defaults_to_move_keep():
    """pydantic 默认值：缺 switch_on 的配置也默认勾「保留目标文件」。"""
    config = Config()
    assert Switch.MOVE_KEEP in config.switch_on
    assert Switch.MOVE_OVERWRITE not in config.switch_on
    assert Switch.TASK_STORE_LOCAL in config.switch_on
    assert Switch.TASK_STORE_NETDISK not in config.switch_on


# --------------------------------------------------------------------------
# 4. 界面
# --------------------------------------------------------------------------


def _checked_property(element: ET.Element) -> bool:
    prop = element.find("property[@name='checked']/bool")
    return prop is not None and prop.text == "true"


def test_ui_checkboxes_are_checked_by_default():
    """界面初始态：保留目标文件 / 本地存储不设置时间间隔 默认勾上，覆盖目标文件默认不勾。"""
    root = ET.parse(UI_PATH).getroot()
    widgets = {element.get("name"): element for element in root.iter() if element.get("name")}

    keep = widgets.get("checkBox_move_keep")
    assert keep is not None, "缺少「保留目标文件」复选框"
    assert _checked_property(keep) is True, "「保留目标文件」应当默认勾选"

    overwrite = widgets.get("checkBox_move_overwrite")
    assert overwrite is not None, "缺少「覆盖目标文件」复选框"
    assert _checked_property(overwrite) is False, "「覆盖目标文件」不应默认勾选"

    local = widgets.get("checkBox_task_store_local")
    assert local is not None, "缺少「本地存储文件」复选框"
    assert _checked_property(local) is True, "「本地存储文件」应当默认勾选"

    netdisk = widgets.get("checkBox_task_store_netdisk")
    assert netdisk is not None, "缺少「网盘存储文件」复选框"
    assert _checked_property(netdisk) is False, "「网盘存储文件」不应默认勾选"


class _FakeCheckBox:
    """只实现 setChecked / isChecked 的假复选框。"""

    def __init__(self) -> None:
        self.checked = False

    def setChecked(self, value: bool) -> None:
        self.checked = bool(value)

    def isChecked(self) -> bool:
        return self.checked


class _FakeTaskModeUi:
    def __init__(self) -> None:
        self.checkBox_task_store_local = _FakeCheckBox()
        self.checkBox_task_store_netdisk = _FakeCheckBox()


class _FakeTaskModeHost:
    def __init__(self) -> None:
        self.Ui = _FakeTaskModeUi()


def test_ui_handlers_fall_back_to_local_task():
    """任务模式：取消唯一勾选的那枚时回落到默认档「本地存储文件」。"""
    from mdcx.controllers.main_window.settings_actions import SettingsActionsMixin

    host = _FakeTaskModeHost()
    local = host.Ui.checkBox_task_store_local
    netdisk = host.Ui.checkBox_task_store_netdisk

    # 勾「网盘存储文件」→「本地存储文件」自动取消
    netdisk.checked = True
    SettingsActionsMixin.checkBox_task_store_netdisk_changed(host, True)
    assert local.checked is False

    # 勾「本地存储文件」→「网盘存储文件」自动取消
    local.checked = True
    SettingsActionsMixin.checkBox_task_store_local_changed(host, True)
    assert local.checked is True
    assert netdisk.checked is False

    # 取消「本地存储文件」且网盘也没勾 → 回落到默认档「本地存储文件」
    local.checked = False
    netdisk.checked = False
    SettingsActionsMixin.checkBox_task_store_local_changed(host, False)
    assert local.checked is True
    assert netdisk.checked is False
