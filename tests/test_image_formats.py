"""poster / thumb / fanart 支持其它图片格式的回归测试。

覆盖：
- 整理模式：主图保留源文件真实扩展名（poster.png / thumb.webp / fanart.gif）
- 整理模式：.jpg 主图仍然优先（既有行为不变）
- 普通/更新模式：_migrate_picture_resource 保留扩展名搬迁并回传实际落位路径
- 工具函数：resolve_main_image / remove_other_image_variants / image_path_with_suffix
"""

import sys
from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file import _migrate_picture_resource
from mdcx.core.organize import organize_files
from mdcx.utils.picture import (
    IMAGE_SUFFIXES,
    image_path_candidates,
    image_path_with_suffix,
    remove_other_image_variants,
    resolve_main_image,
)

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")


def _prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")


@pytest.mark.asyncio
async def test_organize_mode_keeps_main_image_extensions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理模式：png / webp / gif 主图保留真实扩展名，不得被改名成 .jpg。"""
    _prepare(monkeypatch)

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.png").write_bytes(b"poster png")
    (old_folder / "ABS-040-thumb.webp").write_bytes(b"thumb webp")
    (old_folder / "ABS-040-fanart.gif").write_bytes(b"fanart gif")

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
    assert (new_folder / "poster.png").read_bytes() == b"poster png"
    assert (new_folder / "thumb.webp").read_bytes() == b"thumb webp"
    assert (new_folder / "fanart.gif").read_bytes() == b"fanart gif"
    # 不做格式伪装：不能把 png/webp/gif 改名成 .jpg
    assert not (new_folder / "poster.jpg").exists()
    assert not (new_folder / "thumb.jpg").exists()
    assert not (new_folder / "fanart.jpg").exists()
    # 源目录不再残留这些图片
    assert not (old_folder / "ABS-040-poster.png").exists()
    assert not (old_folder / "ABS-040-thumb.webp").exists()
    assert not (old_folder / "ABS-040-fanart.gif").exists()


@pytest.mark.asyncio
async def test_organize_mode_prefers_jpg_main_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理模式：jpg 主图仍然优先，其它格式按普通图片原名搬走。"""
    _prepare(monkeypatch)

    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    video = old_folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old_folder / "ABS-040.nfo").write_text("<movie><title>ABS-040</title></movie>", encoding="utf-8")
    (old_folder / "ABS-040-poster.jpg").write_bytes(b"poster jpg")
    (old_folder / "ABS-040-poster.png").write_bytes(b"poster png")

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
    assert (new_folder / "poster.jpg").read_bytes() == b"poster jpg"
    assert (new_folder / "ABS-040-poster.png").read_bytes() == b"poster png"


@pytest.mark.asyncio
async def test_migrate_picture_resource_keeps_extension(tmp_path: Path):
    """普通/更新模式：旧目录的 png 封面搬到新目录时保留扩展名，并回传实际路径。"""
    old_folder = tmp_path / "old"
    new_folder = tmp_path / "new"
    old_folder.mkdir()
    new_folder.mkdir()
    (old_folder / "poster.png").write_bytes(b"poster png")

    exists, done_path_copy, actual = await _migrate_picture_resource(
        number="ABS-040",
        done_path=None,
        final_path=new_folder / "poster.jpg",
        new_path_with_filename=new_folder / "ABS-040-poster.jpg",
        old_path_with_filename=old_folder / "ABS-040-poster.jpg",
        old_path_no_filename=old_folder / "poster.jpg",
        local_key="poster",
    )

    assert exists is True
    assert done_path_copy is True
    assert actual == new_folder / "poster.png"
    assert (new_folder / "poster.png").read_bytes() == b"poster png"
    # 不得产生一个内容相同、扩展名被改写的 poster.jpg
    assert not (new_folder / "poster.jpg").exists()
    # 旧位置已清空
    assert not (old_folder / "poster.png").exists()


@pytest.mark.asyncio
async def test_migrate_picture_resource_prefers_existing_final(tmp_path: Path):
    """普通/更新模式：目标位置已有 jpg 时直接认领，不再搬 png 覆盖。"""
    new_folder = tmp_path / "new"
    new_folder.mkdir()
    (new_folder / "poster.jpg").write_bytes(b"poster jpg")

    exists, done_path_copy, actual = await _migrate_picture_resource(
        number="ABS-040",
        done_path=None,
        final_path=new_folder / "poster.jpg",
        new_path_with_filename=new_folder / "ABS-040-poster.jpg",
        old_path_with_filename=tmp_path / "ABS-040-poster.jpg",
        old_path_no_filename=tmp_path / "poster.jpg",
        local_key="poster",
    )

    assert exists is True
    assert actual == new_folder / "poster.jpg"


@pytest.mark.asyncio
async def test_resolve_main_image_finds_variants_and_cleans(tmp_path: Path):
    """resolve_main_image 能认出其它后缀；drop_other_variants 能清掉残留副本。"""
    base = tmp_path / "poster.jpg"
    (tmp_path / "poster.png").write_bytes(b"png")

    assert await resolve_main_image(base) == tmp_path / "poster.png"

    base.write_bytes(b"jpg")
    assert await resolve_main_image(base) == base

    # 规范名优先，并清理同名的其它副本
    assert await resolve_main_image(base, drop_other_variants=True) == base
    assert not (tmp_path / "poster.png").exists()
    assert base.read_bytes() == b"jpg"


@pytest.mark.asyncio
async def test_remove_other_image_variants_keeps_given(tmp_path: Path):
    """remove_other_image_variants 保留指定的那一张，其余同名前缀副本删除。"""
    base = tmp_path / "fanart.jpg"
    (tmp_path / "fanart.jpg").write_bytes(b"jpg")
    (tmp_path / "fanart.png").write_bytes(b"png")
    (tmp_path / "fanart.gif").write_bytes(b"gif")

    await remove_other_image_variants(base, keep=tmp_path / "fanart.gif")

    assert not (tmp_path / "fanart.jpg").exists()
    assert not (tmp_path / "fanart.png").exists()
    assert (tmp_path / "fanart.gif").read_bytes() == b"gif"


def test_picture_helpers_basics(tmp_path: Path):
    """后缀集合与路径工具的基础行为。"""
    assert ".gif" in IMAGE_SUFFIXES
    assert ".avif" in IMAGE_SUFFIXES
    assert image_path_with_suffix(tmp_path / "poster.jpg", ".png") == tmp_path / "poster.png"
    # 不受支持的后缀退回原路径
    assert image_path_with_suffix(tmp_path / "poster.jpg", ".txt") == tmp_path / "poster.jpg"
    candidates = image_path_candidates(tmp_path / "poster.jpg")
    assert candidates[0] == tmp_path / "poster.jpg"
    assert tmp_path / "poster.gif" in candidates
