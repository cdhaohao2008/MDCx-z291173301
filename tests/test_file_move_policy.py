"""「设置 → 高级 → 移动文件」策略（覆盖旧文件 / 保留旧文件）的回归测试。

覆盖：
1. 策略读取（get_file_move_policy）与老配置自动升级（互斥归一）；
2. 整理模式/视频模式移动文件时复用该策略：
   - 覆盖旧文件 → 目标目录同名文件被被移动文件覆盖（事务 + 回滚 + 校验仍然生效）；
   - 保留旧文件 → 源文件留在原目录、目标目录同名文件不覆盖、不更改；
3. 其它刮削模式不受影响（目标同名仍然报错中止）；
4. 界面互斥（勾选其一自动去勾另一）与界面结构。
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config import extend as extend_module
from mdcx.config.enums import Switch
from mdcx.config.extend import (
    FILE_MOVE_KEEP,
    FILE_MOVE_OVERWRITE,
    ORGANIZE_MAIN_MODE,
    VIDEO_MAIN_MODE,
    get_file_move_policy,
)
from mdcx.config.manager import manager
from mdcx.config.migrations import migrate_config_data
from mdcx.core.file import creat_folder, move_movie
from mdcx.core.organize import OrganizeTransaction, organize_files
from mdcx.models.model_types import FileInfo, OtherInfo

pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="项目配置模型需要 Python 3.13+")

UI_PATH = Path(__file__).resolve().parents[1] / "mdcx" / "views" / "MDCx.ui"


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: int) -> None:
    monkeypatch.setattr(extend_module, "_runtime_main_mode", None)
    monkeypatch.setattr(manager.config, "main_mode", mode)


def _set_policy(monkeypatch: pytest.MonkeyPatch, *switches: Switch) -> None:
    monkeypatch.setattr(manager.config, "switch_on", list(switches))


def _make_file_info(file_path: Path) -> FileInfo:
    return FileInfo(
        number="ABS-040",
        mosaic="",
        appoint_number="",
        appoint_url="",
        c_word="",
        cd_part="",
        destroyed="",
        file_ex=".mp4",
        file_name=file_path.name,
        file_path=file_path,
        file_show_name=file_path.name,
        file_show_path=file_path,
        folder_path=file_path.parent,
        has_sub=False,
        leak="",
        letters="",
        short_number="ABS-040",
        sub_list=[],
        website_name="",
        wuma="",
        youma="",
        definition="",
        codec="",
    )


# --------------------------------------------------------------------------
# 1. 策略读取与配置归一
# --------------------------------------------------------------------------


def test_get_file_move_policy_reads_switches(monkeypatch: pytest.MonkeyPatch):
    """未勾选返回空串；勾选时分别返回覆盖/保留。"""
    _set_policy(monkeypatch)
    assert get_file_move_policy() == ""

    _set_policy(monkeypatch, Switch.MOVE_OVERWRITE)
    assert get_file_move_policy() == FILE_MOVE_OVERWRITE

    _set_policy(monkeypatch, Switch.MOVE_KEEP)
    assert get_file_move_policy() == FILE_MOVE_KEEP


def test_migration_keeps_move_keep_when_both_present():
    """老配置/手改配置若两个开关都勾上，保留更安全的 move_keep、去掉 move_overwrite。"""
    data = {"switch_on": ["move_overwrite", "move_keep"]}
    migrate_config_data(data)
    assert "move_keep" in data["switch_on"]
    assert "move_overwrite" not in data["switch_on"]

    # 单独勾选时保持不变
    data = {"switch_on": ["move_overwrite"]}
    migrate_config_data(data)
    assert "move_overwrite" in data["switch_on"]

    # 逗号分隔的字符串形态同样归一
    data = {"switch_on": "move_overwrite,move_keep"}
    migrate_config_data(data)
    assert "move_overwrite" not in str(data["switch_on"])
    assert "move_keep" in str(data["switch_on"])


# --------------------------------------------------------------------------
# 2. 移动事务的行为
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transaction_keeps_existing_target_under_keep_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「保留旧文件」：目标已有同名文件 → 源文件留在原目录，目标文件不被覆盖、不被删除。"""
    _set_policy(monkeypatch, Switch.MOVE_KEEP)

    src = tmp_path / "old" / "ABS-040.mp4"
    dst = tmp_path / "new" / "ABS-040.mp4"
    src.parent.mkdir()
    dst.parent.mkdir()
    src.write_bytes(b"new")
    dst.write_bytes(b"old")

    transaction = OrganizeTransaction()
    ok, error = await transaction.move_file(src, dst)

    assert ok, error
    assert src.read_bytes() == b"new", "源文件应留在原目录"
    assert dst.read_bytes() == b"old", "目标目录同名文件必须保持原样"


@pytest.mark.asyncio
async def test_transaction_overwrites_existing_target_and_rolls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「覆盖旧文件」：目标被覆盖；事务回滚后目标恢复原内容、源文件回到原目录。"""
    _set_policy(monkeypatch, Switch.MOVE_OVERWRITE)

    src = tmp_path / "old" / "ABS-040.mp4"
    dst = tmp_path / "new" / "ABS-040.mp4"
    src.parent.mkdir()
    dst.parent.mkdir()
    src.write_bytes(b"new")
    dst.write_bytes(b"old")

    transaction = OrganizeTransaction()
    ok, error = await transaction.move_file(src, dst)
    assert ok, error
    assert dst.read_bytes() == b"new", "目标文件应被被移动文件覆盖"
    assert not src.exists(), "源文件应已搬走"

    # 回滚：目标恢复旧内容，源文件回到原目录
    await transaction.rollback()
    assert dst.read_bytes() == b"old", "回滚后目标文件应恢复原内容"
    assert src.read_bytes() == b"new", "回滚后源文件应回到原目录"


@pytest.mark.asyncio
async def test_organize_files_overwrite_policy_overwrites_success_folder_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """整理模式 + 覆盖旧文件：成功输出目录里的同名文件会被覆盖。"""
    _set_mode(monkeypatch, ORGANIZE_MAIN_MODE)
    _set_policy(monkeypatch, Switch.MOVE_OVERWRITE)
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")

    success = tmp_path / "success"
    success.mkdir()
    old = tmp_path / "old"
    old.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    existing = success / "ABS-040.mp4"
    existing.write_bytes(b"old")

    moved, error = await organize_files(
        file_path=video,
        file_new_path=existing,
        folder_old_path=old,
        folder_new_path=success,
        nfo_new_path=success / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=success / "poster.jpg",
        thumb_final_path=success / "thumb.jpg",
        fanart_final_path=success / "fanart.jpg",
        success_folder=success,
    )

    assert moved, error
    assert existing.read_bytes() == b"new", "覆盖旧文件策略应覆盖成功输出目录内的同名文件"
    assert not video.exists()


@pytest.mark.asyncio
async def test_organize_files_without_policy_keeps_existing_success_folder_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """未选择策略时维持原行为：成功输出目录里的同名文件不覆盖、不移动，源文件留在原地。"""
    _set_mode(monkeypatch, ORGANIZE_MAIN_MODE)
    _set_policy(monkeypatch)
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")

    success = tmp_path / "success"
    success.mkdir()
    old = tmp_path / "old"
    old.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    existing = success / "ABS-040.mp4"
    existing.write_bytes(b"old")

    moved, error = await organize_files(
        file_path=video,
        file_new_path=existing,
        folder_old_path=old,
        folder_new_path=success,
        nfo_new_path=success / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=success / "poster.jpg",
        thumb_final_path=success / "thumb.jpg",
        fanart_final_path=success / "fanart.jpg",
        success_folder=success,
    )

    assert moved, error
    assert existing.read_bytes() == b"old", "未选择策略时不应覆盖既有文件"
    assert video.exists(), "未选择策略时源文件应留在原目录"


# --------------------------------------------------------------------------
# 3. creat_folder / move_movie 的策略分支
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creat_folder_keep_policy_marks_keep_and_does_not_abort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「保留旧文件」：目标同名时不再中止任务，并标记本次整单不搬动。"""
    _set_mode(monkeypatch, VIDEO_MAIN_MODE)
    _set_policy(monkeypatch, Switch.MOVE_KEEP)
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)

    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    target = new / "ABS-040.mp4"
    target.write_bytes(b"old")

    other = OtherInfo.empty()
    json_data = SimpleNamespace(title="")
    ok = await creat_folder(
        other,
        json_data,
        new,
        video,
        target,
        new / "thumb.jpg",
        new / "poster.jpg",
    )

    assert ok is True, "保留旧文件策略下不应中止任务"
    assert other.keep_existing_target is True
    assert other.dont_move_movie is True
    assert target.read_bytes() == b"old"


@pytest.mark.asyncio
async def test_creat_folder_overwrite_policy_does_not_abort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「覆盖旧文件」：目标同名时不再中止任务，交给后面的移动阶段覆盖。"""
    _set_mode(monkeypatch, ORGANIZE_MAIN_MODE)
    _set_policy(monkeypatch, Switch.MOVE_OVERWRITE)
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)

    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    target = new / "ABS-040.mp4"
    target.write_bytes(b"old")

    other = OtherInfo.empty()
    json_data = SimpleNamespace(title="")
    ok = await creat_folder(
        other,
        json_data,
        new,
        video,
        target,
        new / "thumb.jpg",
        new / "poster.jpg",
    )

    assert ok is True, "覆盖旧文件策略下不应中止任务"
    assert other.keep_existing_target is False


@pytest.mark.asyncio
async def test_creat_folder_other_mode_still_aborts_on_same_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """其它刮削模式（正常模式）不受该策略影响：目标同名仍然报错中止。"""
    _set_mode(monkeypatch, 1)
    _set_policy(monkeypatch, Switch.MOVE_KEEP)
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)

    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    target = new / "ABS-040.mp4"
    target.write_bytes(b"old")

    other = OtherInfo.empty()
    json_data = SimpleNamespace(title="")
    ok = await creat_folder(
        other,
        json_data,
        new,
        video,
        target,
        new / "thumb.jpg",
        new / "poster.jpg",
    )

    assert ok is False, "正常模式仍应按原逻辑中止"
    assert other.keep_existing_target is False
    assert "同名文件" in json_data.title


@pytest.mark.asyncio
async def test_move_movie_keep_policy_leaves_source_in_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「保留旧文件」：视频本体也不搬，源文件留在原目录、目标文件保持原样。"""
    _set_mode(monkeypatch, VIDEO_MAIN_MODE)
    _set_policy(monkeypatch, Switch.MOVE_KEEP)
    monkeypatch.setattr(manager.config, "soft_link", 0)

    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    target = new / "ABS-040.mp4"
    target.write_bytes(b"old")

    other = OtherInfo.empty()
    file_info = _make_file_info(video)
    moved = await move_movie(other, file_info, video, target)

    assert moved is True
    assert video.exists(), "保留旧文件时源文件应留在原目录"
    assert target.read_bytes() == b"old", "目标文件必须保持原样"


@pytest.mark.asyncio
async def test_move_movie_overwrite_policy_replaces_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """「覆盖旧文件」：目标文件被直接覆盖，且不留下 _conflict_ 副本。"""
    _set_mode(monkeypatch, VIDEO_MAIN_MODE)
    _set_policy(monkeypatch, Switch.MOVE_OVERWRITE)
    monkeypatch.setattr(manager.config, "soft_link", 0)

    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"new")
    target = new / "ABS-040.mp4"
    target.write_bytes(b"old")

    other = OtherInfo.empty()
    file_info = _make_file_info(video)
    moved = await move_movie(other, file_info, video, target)

    assert moved is True
    assert target.read_bytes() == b"new", "目标文件应被覆盖"
    assert not video.exists()
    assert not list(new.glob("*_conflict_*")), "覆盖策略不应留下冲突副本"


# --------------------------------------------------------------------------
# 4. 界面
# --------------------------------------------------------------------------


class _FakeCheckBox:
    """只实现 setChecked / isChecked 的假复选框，用于单测互斥处理器。"""

    def __init__(self) -> None:
        self.checked = False

    def setChecked(self, value: bool) -> None:
        self.checked = bool(value)

    def isChecked(self) -> bool:
        return self.checked


class _FakeUi:
    def __init__(self) -> None:
        self.checkBox_move_overwrite = _FakeCheckBox()
        self.checkBox_move_keep = _FakeCheckBox()


class _FakeHost:
    def __init__(self) -> None:
        self.Ui = _FakeUi()


def test_ui_handlers_keep_move_switches_mutually_exclusive():
    """界面层互斥：勾选其一自动去勾另一；取消勾选时回落到默认档「保留旧文件」。"""
    from mdcx.controllers.main_window.settings_actions import SettingsActionsMixin

    host = _FakeHost()
    overwrite = host.Ui.checkBox_move_overwrite
    keep = host.Ui.checkBox_move_keep

    # 勾「覆盖旧文件」→「保留旧文件」自动取消
    overwrite.checked = True
    SettingsActionsMixin.checkBox_move_overwrite_changed(host, True)
    assert overwrite.checked is True
    assert keep.checked is False

    # 勾「保留旧文件」→「覆盖旧文件」自动取消
    keep.checked = True
    SettingsActionsMixin.checkBox_move_keep_changed(host, True)
    assert keep.checked is True
    assert overwrite.checked is False

    # 取消「覆盖旧文件」→ 另一枚「保留旧文件」保持勾选（不会两枚都不勾）
    overwrite.checked = False
    SettingsActionsMixin.checkBox_move_overwrite_changed(host, False)
    assert keep.checked is True
    assert overwrite.checked is False

    # 取消「保留旧文件」且「覆盖旧文件」也没勾 → 回落到默认档「保留旧文件」
    keep.checked = False
    overwrite.checked = False
    SettingsActionsMixin.checkBox_move_keep_changed(host, False)
    assert keep.checked is True
    assert overwrite.checked is False


def test_ui_has_move_policy_checkboxes_in_advanced_page():
    """界面：高级页「移动文件」一行有「覆盖旧文件」「保留旧文件」两枚互斥复选框。"""
    root = ET.parse(UI_PATH).getroot()
    widgets = {element.get("name"): element for element in root.iter() if element.get("name")}

    overwrite = widgets.get("checkBox_move_overwrite")
    assert overwrite is not None, "缺少「覆盖旧文件」复选框"
    assert overwrite.get("class") == "QCheckBox"
    text = overwrite.find("property[@name='text']/string")
    assert text is not None and text.text == "覆盖旧文件"

    keep = widgets.get("checkBox_move_keep")
    assert keep is not None, "缺少「保留旧文件」复选框"
    assert keep.get("class") == "QCheckBox"
    text = keep.find("property[@name='text']/string")
    assert text is not None and text.text == "保留旧文件"

    label = widgets.get("label_move_file")
    assert label is not None, "缺少「移动文件：」标签"
    text = label.find("property[@name='text']/string")
    assert text is not None and text.text == "移动文件："

    # 两枚复选框都在高级页网格 gridLayout_20 的第 6 行（保留任务行下方）
    grid = widgets.get("gridLayout_20")
    assert grid is not None
    items = {(item.get("row"), item.get("column")): item for item in grid.iter("item") if item.get("row") == "6"}
    assert ("6", "0") in items and ("6", "1") in items
    col0 = items[("6", "0")].find("widget")
    assert col0 is not None and col0.get("name") == "label_move_file"
    col1 = items[("6", "1")].find("widget")
    assert col1 is not None and col1.get("name") == "frame_move_file"
    layout = col1.find(".//layout[@name='horizontalLayout_move_file']")
    assert layout is not None
    names = {child.get("name") for child in layout.iter("widget")}
    assert {"checkBox_move_overwrite", "checkBox_move_keep"} <= names
