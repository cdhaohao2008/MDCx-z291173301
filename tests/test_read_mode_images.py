"""读取模式（整理模式）本地主图路径解析回归测试。

读取模式下界面缩略图取自 NFO 所在目录里的 poster / thumb / fanart，主图不局限于
.jpg：png / webp / bmp / gif / avif 等格式同样要能被识别（修复前后缀写死成 .jpg，
目录里的 thumb.gif 永远找不到，界面缩略图不显示）。
"""

from types import SimpleNamespace

import pytest

from mdcx.config.enums import Language
from mdcx.core import nfo as nfo_module
from mdcx.gen.field_enums import CrawlerResultFields


def _prepare(tmp_path, name: str = "ABC-123"):
    video_path = tmp_path / f"{name}.mp4"
    video_path.write_bytes(b"")
    nfo_path = tmp_path / f"{name}.nfo"
    nfo_path.write_text(
        f"<movie><title>{name} 标题</title><num>{name}</num></movie>",
        encoding="utf-8",
    )
    return video_path


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nfo_module.manager.config, "read_mode", [])
    monkeypatch.setattr(
        nfo_module.manager.config.__class__,
        "get_field_config",
        lambda self, field: SimpleNamespace(
            language=Language.ZH_CN if field == CrawlerResultFields.OUTLINE else Language.JP
        ),
    )


@pytest.mark.asyncio
async def test_read_mode_finds_gif_thumb(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """目录里的 thumb.gif 要能被识别成缩略图。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)
    thumb = tmp_path / "thumb.gif"
    thumb.write_bytes(b"GIF89a")

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.thumb_path == thumb


@pytest.mark.asyncio
async def test_read_mode_finds_webp_poster(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """目录里的 poster.webp 要能被识别成封面。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)
    poster = tmp_path / "poster.webp"
    poster.write_bytes(b"RIFF....WEBP")

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.poster_path == poster


@pytest.mark.asyncio
async def test_read_mode_finds_gif_fanart(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """目录里的 fanart.gif 要能被识别。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)
    fanart = tmp_path / "fanart.gif"
    fanart.write_bytes(b"GIF89a")

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.fanart_path == fanart


@pytest.mark.asyncio
async def test_read_mode_file_level_thumb_gif_wins(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """文件级 xxx-thumb.gif 优先于目录级 thumb.jpg（与原有优先级一致）。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)
    file_thumb = tmp_path / "ABC-123-thumb.gif"
    file_thumb.write_bytes(b"GIF89a")
    (tmp_path / "thumb.jpg").write_bytes(b"jpg")

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.thumb_path == file_thumb


@pytest.mark.asyncio
async def test_read_mode_jpg_still_first(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """jpg 优先级最高，既有行为不变（同时存在 jpg 与 gif 时选 jpg）。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)
    (tmp_path / "thumb.jpg").write_bytes(b"jpg")
    (tmp_path / "thumb.gif").write_bytes(b"GIF89a")

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.thumb_path == tmp_path / "thumb.jpg"


@pytest.mark.asyncio
async def test_read_mode_no_images_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """没有任何主图时返回 None，不报错。"""
    _configure(monkeypatch)
    video_path = _prepare(tmp_path)

    data, info = await nfo_module.get_nfo_data(video_path, "ABC-123")

    assert data is not None
    assert info is not None
    assert info.poster_path is None
    assert info.thumb_path is None
    assert info.fanart_path is None
