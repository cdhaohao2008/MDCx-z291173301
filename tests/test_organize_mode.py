"""整理模式（main_mode == 6）回归测试。

覆盖：
- extend.is_organize_mode / ORGANIZE_MAIN_MODE
- core.utils.get_video_size_for_file（STRM 本地目标解析、mediainfo.json 兜底）
- base.file.move_mediainfo（同名 mediainfo 随视频移动并重命名、不覆盖）
- base.file.get_movie_list 在整理模式下扫描 .strm（其他模式不扫描）
- core.organize 事务整理（全部伴生文件移动、失败回滚）
- 连续刮削数量控制分批调度
- MDCx.ui 中整理模式单选项与说明文案
"""

import asyncio
import sys
from pathlib import Path

import pytest

from mdcx.base.file import get_movie_list, move_mediainfo
from mdcx.config.extend import ORGANIZE_MAIN_MODE, is_organize_mode
from mdcx.config.manager import manager
from mdcx.core import organize as organize_module
from mdcx.core.organize import organize_files
from mdcx.core.scraper import Scraper
from mdcx.core.utils import get_video_size_for_file
from mdcx.models.enums import FileMode

pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="项目配置模型需要 Python 3.13+")


def test_is_organize_mode_only_for_mode_six(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert is_organize_mode() is False
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    assert ORGANIZE_MAIN_MODE == 6
    assert is_organize_mode() is True


@pytest.mark.asyncio
async def test_get_video_size_for_file_prefers_strm_local_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "ABC-123-1080P.mp4"
    target.write_bytes(b"video")
    strm = tmp_path / "ABC-123.strm"
    strm.write_text(str(target), encoding="utf-8")
    monkeypatch.setattr(manager.config, "hd_get", "path")
    monkeypatch.setattr(manager.config, "hd_name", "height")

    definition, _codec = await get_video_size_for_file(strm, "ABC-123")

    assert definition == "1080P"


@pytest.mark.asyncio
async def test_get_video_size_for_file_falls_back_to_mediainfo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    strm = tmp_path / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    (tmp_path / "ABS-040-mediainfo.json").write_text(
        '{"media": {"track": [{"@type": "Video", "Height": 2160, "Format": "AVC"}]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(manager.config, "hd_get", "path")
    monkeypatch.setattr(manager.config, "hd_name", "height")

    definition, codec = await get_video_size_for_file(strm, "ABS-040")

    assert definition == "4K"
    assert codec == "H264"


@pytest.mark.asyncio
async def test_move_mediainfo_moves_and_renames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)

    await move_mediainfo(old_dir, new_dir, "ABS-040.mp4", "ABS-040-4K")

    assert not (old_dir / "ABS-040-mediainfo.json").exists()
    assert (new_dir / "ABS-040-4K-mediainfo.json").exists()


@pytest.mark.asyncio
async def test_move_mediainfo_does_not_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    source = old_dir / "ABS-040-mediainfo.json"
    source.write_text("old", encoding="utf-8")
    target = new_dir / "ABS-040-4K-mediainfo.json"
    target.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)

    await move_mediainfo(old_dir, new_dir, "ABS-040.mp4", "ABS-040-4K")

    assert target.read_text(encoding="utf-8") == "keep"
    assert source.exists()


@pytest.mark.asyncio
async def test_move_mediainfo_requires_move_or_rename(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    source = old_dir / "ABS-040-mediainfo.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", False)
    monkeypatch.setattr(manager.config, "success_file_rename", False)

    await move_mediainfo(old_dir, new_dir, "ABS-040.mp4", "ABS-040-4K")

    assert source.exists()
    assert not (new_dir / "ABS-040-4K-mediainfo.json").exists()


@pytest.mark.asyncio
async def test_get_movie_list_scans_strm_in_organize_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    movie_dir = tmp_path / "movie"
    movie_dir.mkdir()
    (movie_dir / "a.mp4").write_bytes(b"video")
    (movie_dir / "b.strm").write_text("https://example.com/b.mp4", encoding="utf-8")
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "clean_enable", [])
    monkeypatch.setattr(manager.config, "no_escape", [])

    movies = await get_movie_list(FileMode.Default, movie_dir, [])

    assert {path.name for path in movies} == {"a.mp4", "b.strm"}


@pytest.mark.asyncio
async def test_get_movie_list_ignores_strm_in_normal_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    movie_dir = tmp_path / "movie"
    movie_dir.mkdir()
    (movie_dir / "a.mp4").write_bytes(b"video")
    (movie_dir / "b.strm").write_text("https://example.com/b.mp4", encoding="utf-8")
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "clean_enable", [])
    monkeypatch.setattr(manager.config, "no_escape", [])

    movies = await get_movie_list(FileMode.Default, movie_dir, [])

    assert {path.name for path in movies} == {"a.mp4"}


def test_organize_mode_ui_texts():
    from lxml import etree

    ui_path = Path(__file__).resolve().parents[1] / "mdcx" / "views" / "MDCx.ui"
    root = etree.parse(str(ui_path)).getroot()

    radio = root.find(".//widget[@name='radioButton_mode_organize']")
    assert radio is not None
    assert radio.findtext("property[@name='text']/string") == "整理模式"
    # 与正常模式同为第 0 列、无额外缩进/染色，保证左边缘严格对齐。
    assert radio.find("property[@name='styleSheet']") is None
    organize_item = radio.getparent()
    common_radio = root.find(".//widget[@name='radioButton_mode_common']")
    assert common_radio is not None
    common_item = common_radio.getparent()
    assert organize_item is not None and common_item is not None
    assert organize_item.get("column") == "0"
    assert common_item.get("column") == "0"

    label = root.find(".//widget[@name='label_organize_mode']")
    assert label is not None
    assert (
        label.findtext("property[@name='text']/string")
        == "执行：刮削->移动文件->重命名->加字幕等全部操作，适合需要海报墙的情况"
    )


@pytest.mark.asyncio
async def test_organize_files_moves_all_companions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")
    (old_folder / "ABS-040.zh.srt").write_text("subtitle", encoding="utf-8")
    (old_folder / "extrafanart").mkdir()
    (old_folder / "extrafanart" / "a.jpg").write_bytes(b"extra")
    (old_folder / "ABS-040.torrent").write_bytes(b"torrent")

    moved, error = await organize_files(
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
    )

    assert moved, error
    assert not any(path.exists() for path in old_folder.iterdir() if path.is_file())
    assert (new_folder / "ABS-040.mp4").exists()
    assert (new_folder / "ABS-040.nfo").exists()
    assert (new_folder / "poster.jpg").exists()
    assert (new_folder / "ABS-040-mediainfo.json").exists()
    assert (new_folder / "ABS-040.zh.srt").exists()
    assert (new_folder / "ABS-040.torrent").exists()
    assert (new_folder / "extrafanart" / "a.jpg").exists()


@pytest.mark.asyncio
async def test_organize_files_rolls_back_when_video_move_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from mdcx.utils.file import move_file_async as real_move_file_async

    async def flaky_move(src, dst, *, overwrite: bool = False):
        if Path(dst).name == "ABS-040.mp4":
            return False, "mock move failure"
        return await real_move_file_async(src, dst, overwrite=overwrite)

    monkeypatch.setattr(organize_module, "move_file_async", flaky_move)

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")

    moved, error = await organize_files(
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
    )

    assert moved is False
    assert "回滚" in error
    # 已移动的 nfo/图片/json 必须全部退回原目录。
    assert video.exists()
    assert (old_folder / "ABS-040.nfo").exists()
    assert (old_folder / "ABS-040-poster.jpg").exists()
    assert (old_folder / "ABS-040-mediainfo.json").exists()
    assert not (new_folder / "ABS-040.nfo").exists()
    assert not (new_folder / "poster.jpg").exists()


@pytest.mark.asyncio
async def test_organize_files_only_moves_current_number_in_shared_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", False)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040-1.mp4").write_bytes(b"other video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-1.nfo").write_text("<movie><title>ABS-040-1</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "ABS-040-1-poster.jpg").write_bytes(b"other poster")
    (old_folder / "poster.jpg").write_bytes(b"shared poster")
    (old_folder / "ABS-040-1-mediainfo.json").write_text("{}", encoding="utf-8")
    (old_folder / "ABS-040-1.zh.srt").write_text("other subtitle", encoding="utf-8")
    (old_folder / "extrafanart").mkdir()
    (old_folder / "extrafanart" / "ABS-040-extra.jpg").write_bytes(b"extra")
    (old_folder / "extrafanart" / "ABS-040-1-extra.jpg").write_bytes(b"other extra")

    moved, error = await organize_files(
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
    )

    assert moved, error
    assert (new_folder / "ABS-040.mp4").exists()
    assert (new_folder / "ABS-040.nfo").exists()
    assert (new_folder / "poster.jpg").read_bytes() == b"poster"
    assert (new_folder / "extrafanart" / "ABS-040-extra.jpg").exists()
    # 同目录其它番号的视频、nfo、图片、json、字幕、剧照必须保持原位。
    assert (old_folder / "ABS-040-1.mp4").exists()
    assert (old_folder / "ABS-040-1.nfo").exists()
    assert (old_folder / "ABS-040-1-poster.jpg").exists()
    assert (old_folder / "poster.jpg").exists()
    assert (old_folder / "ABS-040-1-mediainfo.json").exists()
    assert (old_folder / "ABS-040-1.zh.srt").exists()
    assert (old_folder / "extrafanart" / "ABS-040-1-extra.jpg").exists()


@pytest.mark.asyncio
async def test_organize_files_uses_actual_video_stem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", False)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "hhd800.com@ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "hhd800.com@ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "hhd800.com@ABS-040-poster.jpg").write_bytes(b"poster")
    (old_folder / "hhd800.com@ABS-040-mediainfo.json").write_text("{}", encoding="utf-8")

    moved, error = await organize_files(
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
    )

    assert moved, error
    assert (new_folder / "ABS-040.mp4").exists()
    assert (new_folder / "ABS-040.nfo").exists()
    assert (new_folder / "poster.jpg").exists()
    assert (new_folder / "ABS-040-mediainfo.json").exists()


@pytest.mark.asyncio
async def test_get_movie_list_respects_ignore_dirs_in_organize_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    movie_dir = tmp_path / "movie"
    ignored_dir = movie_dir / "skip"
    ignored_dir.mkdir(parents=True)
    (movie_dir / "keep.mp4").write_bytes(b"video")
    (ignored_dir / "skip.mp4").write_bytes(b"video")
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "clean_enable", [])
    monkeypatch.setattr(manager.config, "no_escape", [])

    movies = await get_movie_list(FileMode.Default, movie_dir, [ignored_dir])

    assert {path.name for path in movies} == {"keep.mp4"}


@pytest.mark.asyncio
async def test_organize_commit_removes_overwritten_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", False)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>new</title></movie>", encoding="utf-8")
    (new_folder / "ABS-040.nfo").write_text("<movie><title>old</title></movie>", encoding="utf-8")

    moved, error = await organize_files(
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
    )

    assert moved, error
    assert "new" in (new_folder / "ABS-040.nfo").read_text(encoding="utf-8")
    assert not any("mdcx_organize_backup" in path.name for path in new_folder.iterdir())


@pytest.mark.asyncio
async def test_organize_transaction_uses_elevated_only_in_retry_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from mdcx.utils.file import move_file_async as real_move_file_async

    async def failed_move(_src, _dst, *, overwrite: bool = False):
        return False, "mock move failure"

    async def elevated_move(src, dst):
        return await real_move_file_async(src, dst, overwrite=True)

    monkeypatch.setattr(organize_module, "move_file_async", failed_move)
    monkeypatch.setattr(organize_module, "elevated_move_file", elevated_move)

    source = tmp_path / "source.jpg"
    target = tmp_path / "target.jpg"
    source.write_bytes(b"image")

    ok, _error = await organize_module.OrganizeTransaction()._move_once(source, target)
    assert ok is False
    assert source.exists()

    ok, error = await organize_module.OrganizeTransaction(elevated=True)._move_once(source, target)
    assert ok, error
    assert target.read_bytes() == b"image"
    assert not source.exists()


@pytest.mark.asyncio
async def test_get_video_size_for_file_uses_url_filename(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    strm = tmp_path / "ABS-040.strm"
    strm.write_text("https://cdn.example.com/library/ABS-040-4K.mp4?token=abc", encoding="utf-8")
    monkeypatch.setattr(manager.config, "hd_get", "path")
    monkeypatch.setattr(manager.config, "hd_name", "height")

    definition, _codec = await get_video_size_for_file(strm, "ABS-040")

    assert definition == "4K"


@pytest.mark.asyncio
async def test_organize_files_moves_number_prefixed_poster_when_video_has_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", False)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "hhd800.com@ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "hhd800.com@ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"number poster")

    moved, error = await organize_files(
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
    )

    assert moved, error
    assert (new_folder / "poster.jpg").read_bytes() == b"number poster"


@pytest.mark.asyncio
async def test_organize_transaction_rejects_destination_directory(tmp_path: Path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"image")
    target = tmp_path / "target.jpg"
    target.mkdir()
    transaction = organize_module.OrganizeTransaction()

    ok, error = await transaction.move_file(source, target)

    assert ok is False
    assert "同名目录" in error
    assert source.exists()


@pytest.mark.asyncio
async def test_organize_batch_stops_when_file_list_is_shorter_than_task_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    scraper = Scraper(object())  # type: ignore[arg-type]
    scraper._organize_batch_size = 2
    processed: list[int] = []

    async def fake_process(file_info):
        processed.append(file_info[1])

    monkeypatch.setattr(scraper, "process_one_file", fake_process)
    files = [tmp_path / "1.mp4", tmp_path / "2.mp4"]

    await asyncio.wait_for(scraper._run_tasks_with_limit(files, 5, 2), timeout=1)

    assert sorted(processed) == [1, 2]


@pytest.mark.asyncio
async def test_run_tasks_triggers_deferred_organize_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scraper = Scraper(object())  # type: ignore[arg-type]
    retried: list[bool] = []

    async def fake_process(_file_info):
        scraper._pending_organize_retries.append(object())  # type: ignore[arg-type]

    async def fake_retry() -> None:
        retried.append(True)

    monkeypatch.setattr(scraper, "process_one_file", fake_process)
    monkeypatch.setattr(scraper, "_retry_pending_organize_files", fake_retry)

    await scraper._run_tasks_with_limit([tmp_path / "1.mp4"], 1, 1)

    assert retried == [True]


@pytest.mark.asyncio
async def test_organize_batch_waits_for_previous_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scraper = Scraper(object())  # type: ignore[arg-type]
    scraper._organize_batch_size = 2
    events: list[str] = []
    active = 0

    async def fake_process(file_info):
        nonlocal active
        index = file_info[1]
        active += 1
        events.append(f"start-{index}")
        await asyncio.sleep(0.01)
        active -= 1
        events.append(f"end-{index}")

    monkeypatch.setattr(scraper, "process_one_file", fake_process)
    files = [tmp_path / f"{index}.mp4" for index in range(1, 6)]

    await scraper._run_tasks_with_limit(files, len(files), 2)

    third_start = events.index("start-3")
    assert events.index("end-1") < third_start
    assert events.index("end-2") < third_start
    assert active <= 2
