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
from mdcx.config.enums import Switch
from mdcx.config.extend import (
    ORGANIZE_MAIN_MODE,
    drop_ignore_dir,
    get_movie_path_setting,
    is_organize_mode,
)
from mdcx.config.manager import manager
from mdcx.core import organize as organize_module
from mdcx.core.organize import build_organize_index, organize_files
from mdcx.core.scraper import Scraper, get_scan_ignore_dirs
from mdcx.core.utils import get_video_size_for_file
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags

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
async def test_organize_files_moves_gif_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理模式必须搬运 gif 等动图，且保持原文件名（不能改名成 .jpg）。"""
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
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
    (old_folder / "fanart.gif").write_bytes(b"fanart gif")
    (old_folder / "thumb.gif").write_bytes(b"thumb gif")
    (old_folder / "sample.gif").write_bytes(b"sample gif")
    (old_folder / "ABS-040-1.gif").write_bytes(b"numbered gif")

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
    assert (new_folder / "fanart.gif").exists()
    assert (new_folder / "thumb.gif").exists()
    assert (new_folder / "sample.gif").exists()
    assert (new_folder / "ABS-040-1.gif").exists()
    # 动图不能被改名成主图名
    assert not (new_folder / "fanart.jpg").exists()
    assert not (new_folder / "thumb.jpg").exists()
    assert not any(path.suffix == ".gif" for path in old_folder.iterdir())


@pytest.mark.asyncio
async def test_organize_files_moves_misspelled_extrafanart_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """剧照目录写成 extarfanart（拼写错误）时也必须整体搬迁，且目录名归一为 extrafanart。"""
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
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
    extra = old_folder / "extarfanart"
    extra.mkdir()
    (extra / "fanart1.jpg").write_bytes(b"extra1")
    (extra / "fanart2.gif").write_bytes(b"extra2")

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
    assert (new_folder / "extrafanart" / "fanart1.jpg").exists()
    assert (new_folder / "extrafanart" / "fanart2.gif").exists()
    # 错别字目录名不保留，搬走时归一成标准名
    assert not (new_folder / "extarfanart").exists()
    assert not any(path.is_file() for path in old_folder.rglob("*"))


def test_canonical_asset_folder_name_normalizes_typos(monkeypatch: pytest.MonkeyPatch):
    """错别字剧照目录名归一到标准名；标准名与自定义名保持原样。"""
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")

    # 错别字按关键词归一
    assert organize_module._canonical_asset_folder_name("extarfanart") == "extrafanart"
    assert organize_module._canonical_asset_folder_name("extarfanart_copy") == "extrafanart_copy"
    assert organize_module._canonical_asset_folder_name("backdropss") == "backdrops"
    assert organize_module._canonical_asset_folder_name("trailer") == "trailers"
    # 标准名 / 配置里的自定义名 / 与剧照无关的目录名原样保留
    assert organize_module._canonical_asset_folder_name("extrafanart") == "extrafanart"
    assert organize_module._canonical_asset_folder_name("extrafanart_copy") == "extrafanart_copy"
    assert organize_module._canonical_asset_folder_name("my_shots") == "my_shots"


@pytest.mark.asyncio
async def test_organize_files_moves_unknown_companion_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """媒体目录下的伴生目录（不认识的目录名）也必须整体搬迁。"""
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
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
    shots = old_folder / "my_shots"
    shots.mkdir()
    (shots / "shot1.jpg").write_bytes(b"shot")
    (shots / "nested").mkdir()
    (shots / "nested" / "shot2.gif").write_bytes(b"shot2")

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
    assert (new_folder / "my_shots" / "shot1.jpg").exists()
    assert (new_folder / "my_shots" / "nested" / "shot2.gif").exists()
    assert not any(path.is_file() for path in old_folder.rglob("*"))


def test_build_organize_index_detects_companion_dirs(tmp_path: Path):
    """索引要把非标准命名的剧照目录识别为伴生目录，并把里面的文件归属到媒体。"""
    title = tmp_path / "title"
    title.mkdir()
    video = title / "ABS-040.mp4"
    video.write_bytes(b"video")
    extra = title / "extarfanart"
    extra.mkdir()
    extra_file = extra / "fanart1.jpg"
    extra_file.write_bytes(b"extra")

    index = build_organize_index([title])

    assert index.media_count == 1
    assert index.owner_of(extra_file) == video
    assert extra in index.asset_dirs_in(title)


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
    """「覆盖旧文件」策略：目标同名文件被覆盖，commit 后备份文件被删除。

    默认档是「保留旧文件」（目标同名就不搬），所以这里显式切到覆盖策略，
    专门验证「备份 → 覆盖 → commit 删备份」这条链路。
    """
    monkeypatch.setattr(manager.config, "switch_on", [Switch.MOVE_OVERWRITE])
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


def test_build_organize_index_links_numbers_and_companions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])

    folder = tmp_path / "library"
    folder.mkdir()
    video = folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    other_video = folder / "ABS-040-1.mp4"
    other_video.write_bytes(b"other video")
    nfo = folder / "ABS-040.nfo"
    nfo.write_text("<movie />", encoding="utf-8")
    other_nfo = folder / "ABS-040-1.nfo"
    other_nfo.write_text("<movie />", encoding="utf-8")
    poster = folder / "ABS-040-poster.jpg"
    poster.write_bytes(b"poster")
    other_poster = folder / "ABS-040-1-poster.jpg"
    other_poster.write_bytes(b"other poster")
    shared_poster = folder / "poster.jpg"
    shared_poster.write_bytes(b"shared")
    extra = folder / "extrafanart" / "ABS-040-extra.jpg"
    extra.parent.mkdir()
    extra.write_bytes(b"extra")
    other_extra = folder / "extrafanart" / "ABS-040-1-extra.jpg"
    other_extra.write_bytes(b"other extra")

    index = build_organize_index([folder])

    assert index.file_count == 9
    assert index.media_count == 2
    assert index.number_count == 1
    assert {(info.path, info.number) for info in (index.media_info(video), index.media_info(other_video)) if info} == {
        (video, "ABS-040"),
        (other_video, "ABS-040"),
    }
    assert index.owner_of(nfo) == video
    assert index.owner_of(poster) == video
    assert index.owner_of(extra) == video
    assert index.owner_of(other_nfo) == other_video
    assert index.owner_of(other_poster) == other_video
    assert index.owner_of(other_extra) == other_video
    # 同目录多个番号时，无前缀的 poster.jpg 归属不明，必须保持原位。
    assert index.owner_of(shared_poster) is None
    assert set(index.media_for_number("ABS-040")) == {video, other_video}


def test_build_organize_index_links_nested_asset_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    show_folder = tmp_path / "ABS-100"
    show_folder.mkdir()
    video = show_folder / "ABS-100.mp4"
    video.write_bytes(b"video")
    extra = show_folder / "extrafanart" / "random.jpg"
    extra.parent.mkdir()
    extra.write_bytes(b"extra")

    index = build_organize_index([tmp_path])

    assert index.owner_of(extra) == video
    assert index.files_under(show_folder / "extrafanart") == [extra]


def test_build_organize_index_does_not_promote_asset_video_to_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    show_folder = tmp_path / "ABS-101"
    show_folder.mkdir()
    video = show_folder / "ABS-101.mp4"
    video.write_bytes(b"video")
    trailer = show_folder / "trailers" / "trailer.mp4"
    trailer.parent.mkdir()
    trailer.write_bytes(b"trailer")

    index = build_organize_index([tmp_path])

    assert index.media_count == 1
    assert index.owner_of(trailer) == video


@pytest.mark.asyncio
async def test_organize_files_reuses_prebuilt_index_after_previous_number_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", False)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")

    old_folder = tmp_path / "old"
    old_folder.mkdir()
    for stem in ("ABS-040", "ABS-040-1"):
        (old_folder / f"{stem}.mp4").write_bytes(b"video")
        (old_folder / f"{stem}.nfo").write_text("<movie />", encoding="utf-8")
        (old_folder / f"{stem}-poster.jpg").write_bytes(b"poster")
        (old_folder / f"{stem}-mediainfo.json").write_text("{}", encoding="utf-8")
        (old_folder / f"{stem}.zh.srt").write_text("subtitle", encoding="utf-8")
        (old_folder / f"{stem}.torrent").write_bytes(b"torrent")
    (old_folder / "poster.jpg").write_bytes(b"shared poster")
    extra_folder = old_folder / "extrafanart"
    extra_folder.mkdir()
    (extra_folder / "ABS-040-extra.jpg").write_bytes(b"extra")
    (extra_folder / "ABS-040-1-extra.jpg").write_bytes(b"other extra")

    index = build_organize_index([old_folder])
    assert index.owner_of(old_folder / "ABS-040-poster.jpg") == old_folder / "ABS-040.mp4"
    assert index.owner_of(old_folder / "ABS-040-1-poster.jpg") == old_folder / "ABS-040-1.mp4"

    async def organize_one(stem: str) -> tuple[bool, str]:
        new_folder = tmp_path / f"new-{stem}"
        new_folder.mkdir()
        return await organize_files(
            file_path=old_folder / f"{stem}.mp4",
            file_new_path=new_folder / f"{stem}.mp4",
            folder_old_path=old_folder,
            folder_new_path=new_folder,
            nfo_new_path=new_folder / f"{stem}.nfo",
            naming_rule=stem,
            number=stem,
            sub_list=[".zh.srt"],
            poster_final_path=new_folder / "poster.jpg",
            thumb_final_path=new_folder / "thumb.jpg",
            fanart_final_path=new_folder / "fanart.jpg",
            index=index,
        )

    moved, error = await organize_one("ABS-040")
    assert moved, error
    moved, error = await organize_one("ABS-040-1")
    assert moved, error

    first_folder = tmp_path / "new-ABS-040"
    second_folder = tmp_path / "new-ABS-040-1"
    for new_folder, stem in ((first_folder, "ABS-040"), (second_folder, "ABS-040-1")):
        assert (new_folder / f"{stem}.mp4").exists()
        assert (new_folder / f"{stem}.nfo").exists()
        assert (new_folder / "poster.jpg").exists()
        assert (new_folder / f"{stem}-mediainfo.json").exists()
        assert (new_folder / f"{stem}.zh.srt").exists()
        assert (new_folder / f"{stem}.torrent").exists()
        assert (new_folder / "extrafanart" / f"{stem}-extra.jpg").exists()
    assert (old_folder / "poster.jpg").read_bytes() == b"shared poster"


@pytest.mark.asyncio
async def test_organize_transaction_accepts_move_reported_as_failed_after_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    async def move_then_report_failure(src, dst, *, overwrite: bool = False):
        Path(src).rename(dst)
        return False, "网络盘回报失败，但文件已经移动"

    monkeypatch.setattr(organize_module, "move_file_async", move_then_report_failure)
    source = tmp_path / "source.jpg"
    target = tmp_path / "target.jpg"
    source.write_bytes(b"image")

    transaction = organize_module.OrganizeTransaction()
    ok, error = await transaction.move_file(source, target)

    assert ok, error
    assert target.read_bytes() == b"image"
    assert not source.exists()


# ---------------------------------------------------------------------------
# 整理模式「共 0 个文件」回归（用户实测）
#
# 现象：整理模式把文件成功整理到 JAV_output（成功输出目录）后，再点「开始」
# 重新整理，界面直接提示「恭喜！全部刮削完成！共 0 个文件！用时 0.05 秒」，
# 只有重启软件后整理模式才恢复正常。
#
# 根因：整理结果写在「成功输出目录」里，而该目录默认也在「排除目录」列表中，
# 扫描时整棵被跳过 → 整理模式看不见自己上一次的产物，第二次必然扫到 0 个文件。
# ---------------------------------------------------------------------------


class _DummyCrawlerProvider:
    """整理模式不联网刮削，爬虫提供者只需要能被 close()。"""

    client = None

    async def close(self) -> None:
        return None


def _write_sample_nfo(folder: Path, number: str = "ABS-040") -> Path:
    """写一个整理模式可解析的最小 nfo。"""
    folder.mkdir(parents=True, exist_ok=True)
    nfo = folder / f"{number}.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<movie>\n"
        f"  <title>{number} cheeky pretty</title>\n"
        "  <originaltitle>cheeky pretty</originaltitle>\n"
        f"  <num>{number}</num>\n"
        "  <release>2017-11-21</release>\n"
        "  <studio>プレステージ</studio>\n"
        "  <actor><name>あやめ美桜</name></actor>\n"
        "</movie>\n",
        encoding="utf-8",
    )
    return nfo


def _configure_organize_mode(monkeypatch: pytest.MonkeyPatch, media_dir: Path) -> None:
    """把配置切到与用户实测一致的整理模式（成功输出目录同时也在排除目录里）。"""
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "media_path", str(media_dir))
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output")
    monkeypatch.setattr(manager.config, "failed_output_folder", "failed")
    monkeypatch.setattr(manager.config, "folders", ["JAV_output"])
    monkeypatch.setattr(manager.config, "folder_name", "{{ actor }}/{{ number }}")
    monkeypatch.setattr(manager.config, "naming_file", "{{ number }}")
    monkeypatch.setattr(manager.config, "media_type", [".mp4", ".strm"])
    monkeypatch.setattr(manager.config, "clean_enable", [])
    monkeypatch.setattr(manager.config, "no_escape", [])
    monkeypatch.setattr(manager.config, "switch_on", [])
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "del_empty_folder", False)
    monkeypatch.setattr(manager.config, "scrape_softlink_path", False)
    # 关闭刮削结束后的 emby 演员照片同步（会联网，测试环境不可用）
    monkeypatch.setattr(manager.config, "emby_on", [])
    monkeypatch.setattr(manager.config, "actor_photo_kodi_auto", False)


def test_drop_ignore_dir_removes_only_the_target(tmp_path: Path):
    success = tmp_path / "JAV_output"
    other = tmp_path / "examples"
    ignore_dirs = [success, other]

    dropped = drop_ignore_dir(ignore_dirs, success)

    assert dropped == [other]
    # 不修改传入的列表
    assert ignore_dirs == [success, other]
    # 目标不存在时保持原样
    assert drop_ignore_dir(ignore_dirs, tmp_path / "not-exists") == ignore_dirs


def test_scan_ignore_dirs_keep_success_folder_only_in_organize_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(manager.config, "media_path", str(media_dir))
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output")
    monkeypatch.setattr(manager.config, "folders", ["JAV_output"])

    setting = get_movie_path_setting(movie_path_override=media_dir)
    assert setting.success_folder in setting.ignore_dirs

    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    organize_ignore = get_scan_ignore_dirs(setting)
    assert setting.success_folder not in organize_ignore

    monkeypatch.setattr(manager.config, "main_mode", 1)
    normal_ignore = get_scan_ignore_dirs(setting)
    assert setting.success_folder in normal_ignore


@pytest.mark.asyncio
async def test_organize_scan_finds_files_inside_success_output_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    (success_dir / "ABS-040.strm").write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _configure_organize_mode(monkeypatch, media_dir)

    setting = get_movie_path_setting(movie_path_override=media_dir)
    organize_movies = await get_movie_list(FileMode.Default, media_dir, get_scan_ignore_dirs(setting))
    assert [path.name for path in organize_movies] == ["ABS-040.strm"]

    # 正常模式仍然排除成功输出目录（避免把已整理好的文件重复刮削）
    monkeypatch.setattr(manager.config, "main_mode", 1)
    normal_movies = await get_movie_list(FileMode.Default, media_dir, get_scan_ignore_dirs(setting))
    assert normal_movies == []


@pytest.mark.asyncio
async def test_organize_rerun_after_first_run_still_finds_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理成功后再次点「开始」，必须仍能扫到文件（原来恒为「共 0 个文件」）。"""
    media_dir = tmp_path / "media"
    movie_dir = media_dir / "あやめ美桜" / "プレステージ" / "2017-11-21 ABS-040"
    _write_sample_nfo(movie_dir)
    (movie_dir / "ABS-040.strm").write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _configure_organize_mode(monkeypatch, media_dir)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert Flags.total_count == 1
    assert Flags.fail_count == 0
    organized = sorted(media_dir.glob("JAV_output/**/*.strm"))
    assert len(organized) == 1

    # 第二次整理：文件已经在成功输出目录里，必须能被重新扫到并（幂等地）重新整理
    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert Flags.total_count == 1
    assert Flags.fail_count == 0
    assert sorted(media_dir.glob("JAV_output/**/*.strm")) == organized


@pytest.mark.asyncio
async def test_zero_file_run_reports_not_found_instead_of_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """一个文件都没扫到时不能再报「恭喜！全部刮削完成」，否则用户无法定位问题。"""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    _configure_organize_mode(monkeypatch, media_dir)

    from mdcx.core import scraper as scraper_module

    class _Recorder:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def emit(self, text: str) -> None:
            self.messages.append(text)

        def connect(self, *args, **kwargs) -> None:
            return None

        def disconnect(self, *args, **kwargs) -> None:
            return None

    recorder = _Recorder()
    monkeypatch.setattr(scraper_module.signal, "set_label_file_path", recorder)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert Flags.total_count == 0
    assert recorder.messages, "没有收到结果提示"
    assert "恭喜" not in recorder.messages[-1]
    assert "未找到" in recorder.messages[-1]
