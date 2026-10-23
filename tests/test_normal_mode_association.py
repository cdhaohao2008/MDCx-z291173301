"""正常模式伴生文件搬移：番号关联 + 事务回滚 的回归测试。

覆盖：
1. 传入关联索引后，只搬归属当前视频的文件——同目录其它番号的图片、归属不明的
   共用剧照目录都不会被「整目录端走」；
2. 单视频目录下，剧照/剧照副本/主题视频/附加视频目录按归属逐个搬移并清理空目录；
3. 任一文件搬移失败 → 整体回滚，文件全部回到原目录；
4. 不传索引时保持旧的整路径搬移行为（分离模式/补全模式/索引失败时的回退）。
"""

import sys
from pathlib import Path

import pytest

from mdcx.config import extend as extend_module
from mdcx.config.extend import NORMAL_MAIN_MODE
from mdcx.config.manager import manager
from mdcx.core import file as file_module
from mdcx.core.file import deal_old_files
from mdcx.core.organize import build_organize_index
from mdcx.models.flags import Flags
from mdcx.models.model_types import OtherInfo

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extend_module, "_runtime_main_mode", None)
    monkeypatch.setattr(manager.config, "main_mode", NORMAL_MAIN_MODE)
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart_copy")
    monkeypatch.setattr(manager.config, "trailer_simple_name", True)
    monkeypatch.setattr(manager.config, "subtitle_add_chs", False)
    monkeypatch.setattr(manager.config, "sub_type", [".srt", ".ass"])
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])
    Flags.file_done_dic.clear()
    Flags.pic_catch_set.clear()


async def _deal(video: Path, old: Path, new: Path, number: str, index=None) -> tuple[bool, bool, bool]:
    name = number
    return await deal_old_files(
        number,
        OtherInfo.empty(),
        old,
        new,
        video,
        new / f"{name}-thumb.jpg",
        new / f"{name}-poster.jpg",
        new / f"{name}-fanart.jpg",
        new / f"{name}.nfo",
        new / "poster.jpg",
        new / "thumb.jpg",
        new / "fanart.jpg",
        name,
        index=index,
    )


@pytest.mark.asyncio
async def test_deal_old_files_only_moves_owned_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """同目录混放两个番号：只搬当前番号的图片与 nfo，另一个番号的原封不动。"""
    _configure(monkeypatch)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "ABS-041.mp4").write_bytes(b"video")
    (old / "ABS-040.nfo").write_text("<movie/>", encoding="utf-8")
    (old / "ABS-041.nfo").write_text("<movie/>", encoding="utf-8")
    (old / "ABS-040-poster.jpg").write_bytes(b"p40")
    (old / "ABS-041-poster.jpg").write_bytes(b"p41")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "fanart1.jpg").write_bytes(b"e1")

    index = build_organize_index([old])
    ok, _pic, _single = await _deal(video, old, new, "ABS-040", index)

    assert ok
    # 当前番号的资源搬走
    assert (new / "poster.jpg").exists()
    assert (new / "ABS-040.nfo").exists()
    assert not (old / "ABS-040-poster.jpg").exists()
    assert not (old / "ABS-040.nfo").exists()
    # 另一个番号的资源原地不动
    assert (old / "ABS-041-poster.jpg").exists()
    assert (old / "ABS-041.nfo").exists()
    # 共用剧照目录归属不明：不搬
    assert (old / "extrafanart" / "fanart1.jpg").exists()
    assert not (new / "extrafanart").exists()


@pytest.mark.asyncio
async def test_deal_old_files_moves_asset_dirs_in_single_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """单视频目录：剧照、剧照副本、主题视频、附加视频按归属搬走，空目录清理掉。"""
    _configure(monkeypatch)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "ABS-040.nfo").write_text("<movie/>", encoding="utf-8")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "fanart1.jpg").write_bytes(b"e1")
    (old / "extrafanart_copy").mkdir()
    (old / "extrafanart_copy" / "1.jpg").write_bytes(b"c1")
    (old / "backdrops").mkdir()
    (old / "backdrops" / "theme_video.mp4").write_bytes(b"tv")
    (old / "behind the scenes").mkdir()
    (old / "behind the scenes" / "fanart1.mp4").write_bytes(b"bs")

    index = build_organize_index([old])
    ok, _pic, _single = await _deal(video, old, new, "ABS-040", index)

    assert ok
    assert (new / "extrafanart" / "fanart1.jpg").exists()
    assert (new / "extrafanart_copy" / "1.jpg").exists()
    assert (new / "backdrops" / "theme_video.mp4").exists()
    assert (new / "behind the scenes" / "fanart1.mp4").exists()
    # 搬空的旧目录被清理
    assert not (old / "extrafanart").exists()
    assert not (old / "backdrops").exists()


@pytest.mark.asyncio
async def test_deal_old_files_rolls_back_when_move_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """任一文件搬移失败 → 整体回滚，原目录内容保持不变。"""
    _configure(monkeypatch)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "ABS-040.nfo").write_text("<movie/>", encoding="utf-8")
    (old / "ABS-040-poster.jpg").write_bytes(b"p40")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "fanart1.jpg").write_bytes(b"e1")

    real_move = file_module.move_file_async

    async def flaky_move(src, dst, *, overwrite: bool = False):
        if Path(dst).parent.name == "extrafanart":
            return False, "mock move failure"
        return await real_move(src, dst, overwrite=overwrite)

    monkeypatch.setattr(file_module, "move_file_async", flaky_move)
    # 事务内部走 organize.move_file_async，这里同样打桩
    from mdcx.core import organize as organize_module

    monkeypatch.setattr(organize_module, "move_file_async", flaky_move)

    index = build_organize_index([old])
    ok, _pic, _single = await _deal(video, old, new, "ABS-040", index)

    assert ok is False
    # 已经搬走的 nfo / poster 被回滚回原目录
    assert (old / "ABS-040.nfo").exists()
    assert (old / "ABS-040-poster.jpg").exists()
    assert (old / "extrafanart" / "fanart1.jpg").exists()
    assert not (new / "ABS-040.nfo").exists()
    assert not (new / "poster.jpg").exists()


@pytest.mark.asyncio
async def test_deal_old_files_without_index_keeps_legacy_behaviour(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """不传索引（分离模式/补全模式/索引失败）：保持旧的整目录搬移行为。"""
    _configure(monkeypatch)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "ABS-041.mp4").write_bytes(b"video")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "fanart1.jpg").write_bytes(b"e1")

    ok, _pic, _single = await _deal(video, old, new, "ABS-040", None)

    assert ok
    # 旧行为：整个剧照目录被搬走
    assert (new / "extrafanart" / "fanart1.jpg").exists()
    assert not (old / "extrafanart").exists()


@pytest.mark.asyncio
async def test_companion_plan_routes_assets_to_asset_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """分离模式：剧照目录与主图落数据目录（asset_root），字幕等仍落视频目录。"""
    from mdcx.core import organize as organize_module
    from mdcx.core.organize import organize_companion_files

    _configure(monkeypatch)
    old = tmp_path / "old"
    video_dir = tmp_path / "video"
    meta_dir = tmp_path / "meta"
    for folder in (old, video_dir, meta_dir):
        folder.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "ABS-040-poster.jpg").write_bytes(b"poster")
    (old / "ABS-040.zh.srt").write_text("sub", encoding="utf-8")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "a.jpg").write_bytes(b"e1")

    real_move = organize_module.move_file_async

    async def move_media() -> bool:
        return await real_move(video, video_dir / "ABS-040.mp4")

    moved, error = await organize_companion_files(
        file_path=video,
        file_new_path=video_dir / "ABS-040.mp4",
        folder_old_path=old,
        folder_new_path=video_dir,
        nfo_new_path=meta_dir / "ABS-040.nfo",
        naming_rule="ABS-040",
        number="ABS-040",
        sub_list=[".zh.srt"],
        poster_final_path=meta_dir / "poster.jpg",
        thumb_final_path=meta_dir / "thumb.jpg",
        fanart_final_path=meta_dir / "fanart.jpg",
        move_media=move_media,
        asset_root=meta_dir,
    )

    assert moved, error
    assert (meta_dir / "poster.jpg").exists(), "主图应落数据目录"
    assert (meta_dir / "extrafanart" / "a.jpg").exists(), "剧照目录应落数据目录"
    assert (video_dir / "ABS-040.zh.srt").exists(), "字幕应跟随视频目录"
    assert (video_dir / "ABS-040.mp4").exists()
    assert not (video_dir / "poster.jpg").exists()
    assert not (video_dir / "extrafanart").exists()


def test_index_skips_system_dirs(tmp_path: Path):
    """系统/回收站目录（@eaDir、#recycle 等）不进索引，也不被当成剧照目录。"""
    old = tmp_path / "old"
    old.mkdir()
    (old / "ABS-040.mp4").write_bytes(b"v")
    (old / "@eaDir").mkdir()
    (old / "@eaDir" / "thumb.jpg").write_bytes(b"x")
    (old / "#recycle").mkdir()
    (old / "#recycle" / "old.jpg").write_bytes(b"x")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "a.jpg").write_bytes(b"x")

    index = build_organize_index([old])

    assert index.entry(old / "@eaDir") is None
    assert index.entry(old / "@eaDir" / "thumb.jpg") is None
    assert index.entry(old / "#recycle") is None
    assert index.asset_dirs_in(old) == [old / "extrafanart"]


@pytest.mark.asyncio
async def test_deal_old_files_ignores_system_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """搬移时系统目录原地不动，不会被当成剧照目录端走。"""
    _configure(monkeypatch)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    video = old / "ABS-040.mp4"
    video.write_bytes(b"video")
    (old / "@eaDir").mkdir()
    (old / "@eaDir" / "thumb.jpg").write_bytes(b"x")
    (old / "extrafanart").mkdir()
    (old / "extrafanart" / "a.jpg").write_bytes(b"x")

    index = build_organize_index([old])
    ok, _pic, _single = await _deal(video, old, new, "ABS-040", index)

    assert ok
    assert (old / "@eaDir" / "thumb.jpg").exists(), "系统缩略图目录不能被搬走或删除"
    assert not (new / "@eaDir").exists()
    assert (new / "extrafanart" / "a.jpg").exists()
