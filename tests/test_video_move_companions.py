"""视频模式「搬视频 + 删除伴生文件」与共用「搬运计划 + 事务」的回归测试。

覆盖四件事：
1. 视频模式不再有「删除本地已下载的图片和信息文件」「移动已下载图片和文件到
   新目录」两个选项——界面、配置枚举、老配置迁移三层都已移除；
2. 视频模式删除伴生文件时按关联索引判定归属：只删属于当前番号的文件，
   同目录里其它番号的文件、归属不明的共用文件一律不动；
3. 共用的事务搬运（补全模式复用）：视频本体最后搬，任一环节失败整体回滚；
4. 空目录收尾只删空目录。
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mdcx.config import extend as extend_module
from mdcx.config.extend import VIDEO_MAIN_MODE
from mdcx.config.manager import manager
from mdcx.config.migrations import migrate_config_data
from mdcx.core import organize as organize_module
from mdcx.core.organize import build_organize_index, delete_companion_files, organize_companion_files

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")

UI_PATH = Path(__file__).resolve().parents[1] / "mdcx" / "views" / "MDCx.ui"


def _configure_video_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """把配置切到视频模式（视频模式已无额外开关，行为固定）。"""
    monkeypatch.setattr(extend_module, "_runtime_main_mode", None)
    monkeypatch.setattr(manager.config, "main_mode", VIDEO_MAIN_MODE)
    monkeypatch.setattr(manager.config, "switch_on", [])
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")
    monkeypatch.setattr(manager.config, "prevent_char", "")


def _make_folders(tmp_path: Path) -> tuple[Path, Path, Path]:
    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    return old_folder, new_folder, video


@pytest.mark.asyncio
async def test_organize_companion_files_moves_all_companions_and_video_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """伴生文件全部落到新目录，视频本体最后搬（补全模式复用同一套事务）。"""
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
    """没有伴生文件时，视频本体照常搬过去。"""
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


# --------------------------------------------------------------------------
# 视频模式：默认删除伴生文件（按关联索引，不碰无关文件）
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_companion_files_removes_owned_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """同目录混放两个番号：只删当前番号的文件，另一个番号的与共用文件都不动。"""
    _configure_video_mode(monkeypatch)

    old_folder = tmp_path / "old"
    old_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    other = old_folder / "ABS-041.mp4"
    other.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie/>", encoding="utf-8")
    (old_folder / "ABS-041.nfo").write_text("<movie/>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-041-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040.zh.srt").write_text("sub", encoding="utf-8")
    (old_folder / "extrafanart").mkdir()
    (old_folder / "extrafanart" / "fanart1.jpg").write_bytes(b"extra")

    index = build_organize_index([old_folder])
    cleaned, error = await delete_companion_files(
        file_path=video,
        folder_old_path=old_folder,
        folder_new_path=tmp_path / "new",
        nfo_new_path=tmp_path / "new" / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[".zh.srt"],
        poster_final_path=tmp_path / "new" / "poster.jpg",
        thumb_final_path=tmp_path / "new" / "thumb.jpg",
        fanart_final_path=tmp_path / "new" / "fanart.jpg",
        index=index,
    )

    assert cleaned, error
    # 当前番号的伴生文件被删除
    assert not (old_folder / "ABS-040.nfo").exists()
    assert not (old_folder / "ABS-040-poster.jpg").exists()
    assert not (old_folder / "ABS-040.zh.srt").exists()
    # 另一个番号的文件、归属不明的共用剧照目录都不动
    assert (old_folder / "ABS-041.nfo").exists()
    assert (old_folder / "ABS-041-poster.jpg").exists()
    assert (old_folder / "extrafanart" / "fanart1.jpg").exists()
    # 视频本体不在删除范围内（由调用方先搬走）
    assert video.exists()
    assert other.exists()


@pytest.mark.asyncio
async def test_delete_companion_files_removes_asset_dirs_in_single_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """单视频目录：剧照、预告片、主题视频等伴生目录一并清空。"""
    _configure_video_mode(monkeypatch)

    old_folder = tmp_path / "old"
    old_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie/>", encoding="utf-8")
    (old_folder / "extrafanart").mkdir()
    (old_folder / "extrafanart" / "fanart1.jpg").write_bytes(b"e")
    (old_folder / "backdrops").mkdir()
    (old_folder / "backdrops" / "theme_video.mp4").write_bytes(b"t")
    (old_folder / "trailers").mkdir()
    (old_folder / "trailers" / "trailer.mp4").write_bytes(b"tr")

    index = build_organize_index([old_folder])
    cleaned, error = await delete_companion_files(
        file_path=video,
        folder_old_path=old_folder,
        folder_new_path=tmp_path / "new",
        nfo_new_path=tmp_path / "new" / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=tmp_path / "new" / "poster.jpg",
        thumb_final_path=tmp_path / "new" / "thumb.jpg",
        fanart_final_path=tmp_path / "new" / "fanart.jpg",
        index=index,
    )

    assert cleaned, error
    assert not (old_folder / "ABS-040.nfo").exists()
    assert not (old_folder / "extrafanart" / "fanart1.jpg").exists()
    assert not (old_folder / "backdrops" / "theme_video.mp4").exists()
    assert not (old_folder / "trailers" / "trailer.mp4").exists()
    assert video.exists()


@pytest.mark.asyncio
async def test_delete_companion_files_without_index_reports_no_index(tmp_path: Path):
    """索引不可用时返回 no-index，由调用方回退到按固定路径清理。"""
    video = tmp_path / "ABS-040.mp4"
    video.write_bytes(b"video")

    cleaned, error = await delete_companion_files(
        file_path=video,
        folder_old_path=tmp_path,
        folder_new_path=tmp_path / "new",
        nfo_new_path=tmp_path / "new" / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[],
        poster_final_path=tmp_path / "new" / "poster.jpg",
        thumb_final_path=tmp_path / "new" / "thumb.jpg",
        fanart_final_path=tmp_path / "new" / "fanart.jpg",
        index=None,
    )

    assert cleaned is False
    assert error == "no-index"
    assert video.exists()


# --------------------------------------------------------------------------
# 配置与界面：两个选项已彻底移除
# --------------------------------------------------------------------------


def test_migration_drops_removed_video_mode_switches():
    """老配置里残留的 sort_del / sort_move 一律清掉（幂等）。"""
    data = {"switch_on": ["sort_del", "sort_move", "auto_exit"]}
    migrate_config_data(data)
    assert "sort_del" not in data["switch_on"]
    assert "sort_move" not in data["switch_on"]
    assert "auto_exit" in data["switch_on"]

    # 逗号分隔的字符串形态同样清理
    data = {"switch_on": "sort_del,sort_move,auto_exit"}
    migrate_config_data(data)
    assert "sort_del" not in str(data["switch_on"])
    assert "sort_move" not in str(data["switch_on"])
    assert "auto_exit" in str(data["switch_on"])

    # 没有这两个键时不会被改动（其它默认档开关由别的迁移补齐）
    data = {"switch_on": ["auto_exit"]}
    migrate_config_data(data)
    assert "auto_exit" in data["switch_on"]
    assert "sort_del" not in data["switch_on"]
    assert "sort_move" not in data["switch_on"]


def test_ui_has_no_video_mode_delete_move_checkboxes():
    """界面：视频模式行不再有「删除…」「移动…」两个复选框。"""
    root = ET.parse(UI_PATH).getroot()
    widgets = {element.get("name"): element for element in root.iter() if element.get("name")}

    assert "checkBox_sortmode_delpic" not in widgets
    assert "checkBox_sortmode_movefile" not in widgets
    ui_text = UI_PATH.read_text(encoding="utf-8")
    assert "删除本地已下载的图片和信息文件" not in ui_text
    assert "移动已下载图片和文件到新目录" not in ui_text


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
