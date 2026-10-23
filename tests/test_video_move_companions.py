"""视频模式「移动已下载图片和文件到新目录」的回归测试。

覆盖四件事：
1. 新开关只在视频模式（main_mode == 3）且勾选时才生效；
2. 伴生文件（图片/信息文件/json/字幕/剧照目录）按番号关联事务式搬到新目录，
   视频本体最后搬；
3. 任一环节失败都整体回滚（伴生文件退回原目录，新目录无残留）；
4. 与「删除本地已下载的图片和信息文件」互斥的配置归一（老配置自动升级）。
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mdcx.config import extend as extend_module
from mdcx.config.enums import Switch
from mdcx.config.extend import VIDEO_MAIN_MODE
from mdcx.config.manager import manager
from mdcx.config.migrations import migrate_config_data
from mdcx.core import organize as organize_module
from mdcx.core.organize import organize_companion_files

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")

UI_PATH = Path(__file__).resolve().parents[1] / "mdcx" / "views" / "MDCx.ui"


def _configure_video_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """把配置切到视频模式，并打开「移动已下载图片和文件到新目录」。"""
    monkeypatch.setattr(extend_module, "_runtime_main_mode", None)
    monkeypatch.setattr(manager.config, "main_mode", VIDEO_MAIN_MODE)
    monkeypatch.setattr(manager.config, "switch_on", [Switch.SORT_MOVE])
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")


def _make_folders(tmp_path: Path) -> tuple[Path, Path, Path]:
    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    return old_folder, new_folder, video


def test_is_video_move_companions_enabled_only_in_video_mode(monkeypatch: pytest.MonkeyPatch):
    """只有「视频模式 + 勾选新开关」才启用伴生文件搬运。"""
    monkeypatch.setattr(extend_module, "_runtime_main_mode", None)
    monkeypatch.setattr(manager.config, "switch_on", [Switch.SORT_MOVE])

    monkeypatch.setattr(manager.config, "main_mode", VIDEO_MAIN_MODE)
    assert extend_module.is_video_move_companions_enabled() is True

    # 正常模式：即使配置里留着该开关也不生效
    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert extend_module.is_video_move_companions_enabled() is False

    # 视频模式但没勾选
    monkeypatch.setattr(manager.config, "main_mode", VIDEO_MAIN_MODE)
    monkeypatch.setattr(manager.config, "switch_on", [])
    assert extend_module.is_video_move_companions_enabled() is False

    # 勾了「删除…」而不是「移动…」也不启用
    monkeypatch.setattr(manager.config, "switch_on", [Switch.SORT_DEL])
    assert extend_module.is_video_move_companions_enabled() is False


@pytest.mark.asyncio
async def test_organize_companion_files_moves_all_companions_and_video_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """伴生文件全部落到新目录，视频本体最后搬。"""
    _configure_video_mode(monkeypatch)

    old_folder, new_folder, video = _make_folders(tmp_path)
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")
    (old_folder / "ABS-040.zh.srt").write_text("subtitle", encoding="utf-8")
    (old_folder / "extrafanart").mkdir()
    (old_folder / "extrafanart" / "a.jpg").write_bytes(b"extra")

    order: list[str] = []
    real_move = organize_module.move_file_async

    async def tracked_move(src, dst, *, overwrite: bool = False):
        order.append(Path(dst).name)
        return await real_move(src, dst, overwrite=overwrite)

    monkeypatch.setattr(organize_module, "move_file_async", tracked_move)

    async def move_media() -> bool:
        order.append("VIDEO")
        return await real_move(video, new_folder / "ABS-040.mp4")

    moved, error = await organize_companion_files(
        file_path=video,
        file_new_path=new_folder / "ABS-040.mp4",
        folder_old_path=old_folder,
        folder_new_path=new_folder,
        nfo_new_path=new_folder / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[".zh.srt"],
        poster_final_path=new_folder / "poster.jpg",
        thumb_final_path=new_folder / "thumb.jpg",
        fanart_final_path=new_folder / "fanart.jpg",
        move_media=move_media,
    )

    assert moved, error
    # 视频本体必须最后搬
    assert order[-1] == "VIDEO"
    # 伴生文件确实都搬到了新目录
    assert (new_folder / "ABS-040.nfo").exists()
    assert (new_folder / "poster.jpg").exists()
    assert (new_folder / "ABS-040-mediainfo.json").exists()
    assert (new_folder / "ABS-040.zh.srt").exists()
    assert (new_folder / "extrafanart" / "a.jpg").exists()
    assert (new_folder / "ABS-040.mp4").exists()
    # 原目录不再残留这些文件
    assert not (old_folder / "ABS-040.nfo").exists()
    assert not (old_folder / "ABS-040-poster.jpg").exists()
    assert not (old_folder / "ABS-040-mediainfo.json").exists()


@pytest.mark.asyncio
async def test_organize_companion_files_rolls_back_when_video_move_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """视频本体搬运失败 → 伴生文件全部回滚到原目录。"""
    _configure_video_mode(monkeypatch)

    old_folder, new_folder, video = _make_folders(tmp_path)
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")

    async def move_media() -> bool:
        return False

    moved, error = await organize_companion_files(
        file_path=video,
        file_new_path=new_folder / "ABS-040.mp4",
        folder_old_path=old_folder,
        folder_new_path=new_folder,
        nfo_new_path=new_folder / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=new_folder / "poster.jpg",
        thumb_final_path=new_folder / "thumb.jpg",
        fanart_final_path=new_folder / "fanart.jpg",
        move_media=move_media,
    )

    assert moved is False
    assert "回滚" in error
    # 伴生文件全部退回原目录，新目录无残留
    assert (old_folder / "ABS-040.nfo").exists()
    assert (old_folder / "ABS-040-poster.jpg").exists()
    assert (old_folder / "ABS-040-mediainfo.json").exists()
    assert not (new_folder / "ABS-040.nfo").exists()
    assert not (new_folder / "poster.jpg").exists()
    assert not (new_folder / "ABS-040-mediainfo.json").exists()
    # 视频本体没搬走
    assert video.exists()


@pytest.mark.asyncio
async def test_organize_companion_files_rolls_back_when_companion_move_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """伴生文件搬运失败 → 整体回滚并报错。"""
    from mdcx.utils.file import move_file_async as real_move_file_async

    _configure_video_mode(monkeypatch)

    old_folder, new_folder, video = _make_folders(tmp_path)
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")

    async def flaky_move(src, dst, *, overwrite: bool = False):
        if Path(dst).name == "poster.jpg":
            return False, "mock move failure"
        return await real_move_file_async(src, dst, overwrite=overwrite)

    monkeypatch.setattr(organize_module, "move_file_async", flaky_move)

    async def move_media() -> bool:  # pragma: no cover - 不应被调用
        raise AssertionError("伴生文件搬运失败时不应搬视频本体")

    moved, error = await organize_companion_files(
        file_path=video,
        file_new_path=new_folder / "ABS-040.mp4",
        folder_old_path=old_folder,
        folder_new_path=new_folder,
        nfo_new_path=new_folder / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=new_folder / "poster.jpg",
        thumb_final_path=new_folder / "thumb.jpg",
        fanart_final_path=new_folder / "fanart.jpg",
        move_media=move_media,
    )

    assert moved is False
    assert "回滚" in error
    assert (old_folder / "ABS-040.nfo").exists()
    assert (old_folder / "ABS-040-poster.jpg").exists()
    assert not (new_folder / "ABS-040.nfo").exists()
    assert not (new_folder / "poster.jpg").exists()
    assert video.exists()


@pytest.mark.asyncio
async def test_organize_companion_files_without_companions_still_moves_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """没有伴生文件时，视频本体照常按视频模式规则搬过去。"""
    _configure_video_mode(monkeypatch)

    old_folder, new_folder, video = _make_folders(tmp_path)
    real_move = organize_module.move_file_async

    async def move_media() -> bool:
        return await real_move(video, new_folder / "ABS-040.mp4")

    moved, error = await organize_companion_files(
        file_path=video,
        file_new_path=new_folder / "ABS-040.mp4",
        folder_old_path=old_folder,
        folder_new_path=new_folder,
        nfo_new_path=new_folder / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=new_folder / "poster.jpg",
        thumb_final_path=new_folder / "thumb.jpg",
        fanart_final_path=new_folder / "fanart.jpg",
        move_media=move_media,
    )

    assert moved, error
    assert (new_folder / "ABS-040.mp4").exists()
    assert not video.exists()


def test_migration_drops_sort_move_when_sort_del_present():
    """老配置/手改配置若两个开关都勾上，保留 sort_del、去掉 sort_move。"""
    data = {"switch_on": ["sort_del", "sort_move"]}
    migrate_config_data(data)
    assert "sort_del" in data["switch_on"]
    assert "sort_move" not in data["switch_on"]

    # 只勾新开关时保持不变
    data = {"switch_on": ["sort_move"]}
    migrate_config_data(data)
    assert "sort_move" in data["switch_on"]

    # 逗号分隔的字符串形态同样归一
    data = {"switch_on": "sort_del,sort_move"}
    migrate_config_data(data)
    assert "sort_move" not in str(data["switch_on"])
    assert "sort_del" in str(data["switch_on"])


def test_ui_has_move_companions_checkbox_and_removed_delete_hint():
    """界面：新增「移动已下载图片和文件到新目录」复选框，删掉旧的绿色提示词。"""
    root = ET.parse(UI_PATH).getroot()
    widgets = {element.get("name"): element for element in root.iter() if element.get("name")}

    checkbox = widgets.get("checkBox_sortmode_movefile")
    assert checkbox is not None, "缺少「移动已下载图片和文件到新目录」复选框"
    assert checkbox.get("class") == "QCheckBox"
    text = checkbox.find("property[@name='text']/string")
    assert text is not None and text.text == "移动已下载图片和文件到新目录"

    delete_checkbox = widgets.get("checkBox_sortmode_delpic")
    assert delete_checkbox is not None
    delete_text = delete_checkbox.find("property[@name='text']/string")
    assert delete_text is not None and delete_text.text == "删除本地已下载的图片和信息文件"

    # 旧的绿色提示词「不勾选，不删除已下载图片和信息文件」已删除
    assert "label_27" not in widgets
    assert "不勾选，不删除已下载图片和信息文件" not in UI_PATH.read_text(encoding="utf-8")


class _FakeCheckBox:
    """只实现 setChecked 的假复选框，用于单测互斥处理器。"""

    def __init__(self) -> None:
        self.checked = False

    def setChecked(self, value: bool) -> None:
        self.checked = bool(value)


class _FakeUi:
    def __init__(self) -> None:
        self.checkBox_sortmode_delpic = _FakeCheckBox()
        self.checkBox_sortmode_movefile = _FakeCheckBox()


class _FakeHost:
    def __init__(self) -> None:
        self.Ui = _FakeUi()


def test_ui_handlers_keep_delete_and_move_mutually_exclusive():
    """界面层互斥：勾选其一自动去勾另一；去勾不动作（两枚都不勾是合法中间态）。"""
    from mdcx.controllers.main_window.settings_actions import SettingsActionsMixin

    host = _FakeHost()
    delete = host.Ui.checkBox_sortmode_delpic
    move = host.Ui.checkBox_sortmode_movefile

    # 勾「移动」→ 「删除」自动取消
    move.checked = True
    SettingsActionsMixin.checkBox_sortmode_movefile_changed(host, True)
    assert move.checked is True
    assert delete.checked is False

    # 勾「删除」→ 「移动」自动取消
    delete.checked = True
    SettingsActionsMixin.checkBox_sortmode_delpic_changed(host, True)
    assert delete.checked is True
    assert move.checked is False

    # 去勾不动作：两枚都不勾是合法中间态（图片/nfo/字幕留在原目录）
    delete.checked = False
    move.checked = False
    SettingsActionsMixin.checkBox_sortmode_movefile_changed(host, False)
    SettingsActionsMixin.checkBox_sortmode_delpic_changed(host, False)
    assert delete.checked is False
    assert move.checked is False


@pytest.mark.asyncio
async def test_remove_empty_folders_only_deletes_emptied_dirs(tmp_path: Path):
    """空目录收尾：只删空目录，空父目录连带删，扫描根目录与非空目录保留。"""
    from mdcx.core.file import remove_empty_folders

    root = tmp_path / "media"
    emptied = root / "ABS-040"
    emptied.mkdir(parents=True)
    nested = root / "ABS-041" / "CD1"
    nested.mkdir(parents=True)
    busy = root / "ABS-042"
    busy.mkdir()
    (busy / "ABS-042.mp4").write_bytes(b"video")

    removed = await remove_empty_folders([emptied, nested, busy, root], [root])

    assert not emptied.exists(), "搬空后的源目录应被删除"
    assert not nested.exists(), "空目录应被删除"
    assert not (root / "ABS-041").exists(), "空父目录应连带删除"
    assert busy.exists(), "仍非空的目录不能删"
    assert (busy / "ABS-042.mp4").exists(), "非空目录里的文件不能动"
    assert root.exists(), "扫描根目录不能删"
    assert root not in removed, "扫描根目录不能出现在删除列表里"


@pytest.mark.asyncio
async def test_video_mode_cleanup_removes_emptied_source_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """视频模式所有任务完成后：搬空后的源目录被删除，非空目录与扫描根目录保留。"""
    from mdcx.core import scraper as scraper_module

    root = tmp_path / "media"
    source = root / "ABS-040"
    source.mkdir(parents=True)
    busy = root / "ABS-041"
    busy.mkdir()
    (busy / "ABS-041.mp4").write_bytes(b"video")

    monkeypatch.setattr(manager.config, "media_path", str(root))
    monkeypatch.setattr(manager.config, "no_escape", [])
    monkeypatch.setattr(scraper_module.signal, "show_log_text", lambda text: None)

    scraper = scraper_module.Scraper(crawler_provider=None)  # type: ignore[arg-type]
    scraper._video_source_folders.update({source, busy, root})
    await scraper._cleanup_video_empty_folders()

    assert not source.exists(), "视频模式收尾应删除搬空后的源目录"
    assert busy.exists(), "仍非空的目录不能删"
    assert root.exists(), "扫描根目录不能删"
    assert not scraper._video_source_folders, "收尾后登记表应清空"


@pytest.mark.asyncio
async def test_video_mode_cleanup_respects_no_escape_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """勾了「目录」豁免（NoEscape.FOLDER）时，视频模式收尾不删任何目录。"""
    from mdcx.config.enums import NoEscape
    from mdcx.core import scraper as scraper_module

    root = tmp_path / "media"
    source = root / "ABS-040"
    source.mkdir(parents=True)

    monkeypatch.setattr(manager.config, "media_path", str(root))
    monkeypatch.setattr(manager.config, "no_escape", [NoEscape.FOLDER])
    monkeypatch.setattr(scraper_module.signal, "show_log_text", lambda text: None)

    scraper = scraper_module.Scraper(crawler_provider=None)  # type: ignore[arg-type]
    scraper._video_source_folders.add(source)
    await scraper._cleanup_video_empty_folders()

    assert source.exists(), "勾了目录豁免就不该删目录"
