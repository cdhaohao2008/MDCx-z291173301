"""整理模式（main_mode == 6）回归测试。

覆盖：
- extend.is_organize_mode / ORGANIZE_MAIN_MODE
- core.utils.get_video_size_for_file（STRM 本地目标解析、mediainfo.json 兜底）
- base.file.move_mediainfo（同名 mediainfo 随视频移动并重命名、不覆盖）
- base.file.get_movie_list 在整理模式下扫描 .strm（其他模式不扫描）
- MDCx.ui 中整理模式单选项与说明文案
"""

import sys
from pathlib import Path

import pytest

from mdcx.base.file import get_movie_list, move_mediainfo
from mdcx.config.extend import ORGANIZE_MAIN_MODE, is_organize_mode
from mdcx.config.manager import manager
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

    label = root.find(".//widget[@name='label_organize_mode']")
    assert label is not None
    assert (
        label.findtext("property[@name='text']/string")
        == "执行：刮削->整理文件->重命名->打水印等全部操作，适合需要海报墙的情况"
    )
