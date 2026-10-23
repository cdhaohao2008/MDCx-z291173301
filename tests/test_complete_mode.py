"""补全模式（main_mode == 7）回归测试。

覆盖用户 2026-10-23 的需求：

1. 新增补全模式常量与判定函数（7）；
2. 「番号 ↔ 伴生文件」关联逻辑抽到 `core/file_association.py`，整理/视频/补全三种
   模式共用（`organize` 继续导出同名 API，旧引用不破）；
3. 补全模式优先使用本地 nfo 字段：本地有值的一律保留，只把空着的字段用刮削结果补上；
4. 没有 nfo 的文件自动按正常模式全量刮削；
5. 已在「成功输出目录」内的文件只补内容、不移动；不在目录内的文件按正常模式移动；
6. 读取模式只读取并展示（选项已迁到补全模式）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config.enums import DownloadableFile, NfoInclude, NfoMergeStrategy, ReadMode
from mdcx.config.extend import (
    COMPLETE_MAIN_MODE,
    READ_MAIN_MODE,
    complete_merge_strategy,
    is_complete_mode,
    is_complete_selected,
    is_read_only_mode,
    reset_runtime_main_mode,
    set_runtime_main_mode,
)
from mdcx.config.manager import manager
from mdcx.core import scraper as scraper_module
from mdcx.core.file_association import (
    OrganizeIndex,
    build_organize_index,
    collect_media_assets,
)
from mdcx.core.nfo_merger import filled_missing_fields, merge_nfo_fields
from mdcx.core.scraper import Scraper, get_scan_ignore_dirs
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.models.model_types import CrawlersResult

pytestmark = pytest.mark.skipif(sys.version_info < (3, 15), reason="项目配置模型需要 Python 3.15+")


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    """每个用例前后复位运行态模式覆盖与 Flags，避免用例互相污染。"""
    reset_runtime_main_mode()
    Flags.reset()
    yield
    reset_runtime_main_mode()
    Flags.reset()


class _DummyCrawlerProvider:
    client = None

    async def close(self) -> None:
        return None


def _write_nfo(folder: Path, number: str = "ABS-040", *, with_outline: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    outline = "  <plot>本地简介</plot>\n" if with_outline else ""
    nfo = folder / f"{number}.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<movie>\n"
        f"  <title>{number} 本地标题</title>\n"
        "  <originaltitle>local original</originaltitle>\n"
        f"  <num>{number}</num>\n"
        "  <release>2017-11-21</release>\n"
        "  <studio>プレステージ</studio>\n"
        "  <actor><name>本地演员</name></actor>\n"
        f"{outline}"
        "</movie>\n",
        encoding="utf-8",
    )
    return nfo


def _configure_complete_mode(monkeypatch: pytest.MonkeyPatch, media_dir: Path) -> None:
    monkeypatch.setattr(manager.config, "main_mode", COMPLETE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "media_path", str(media_dir))
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output")
    monkeypatch.setattr(manager.config, "failed_output_folder", "failed")
    monkeypatch.setattr(manager.config, "folders", ["JAV_output"])
    monkeypatch.setattr(manager.config, "folder_name", "{{ number }}")
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
    monkeypatch.setattr(manager.config, "emby_on", [])
    monkeypatch.setattr(manager.config, "actor_photo_kodi_auto", False)
    monkeypatch.setattr(manager.config, "actor_realname", False)
    monkeypatch.setattr(manager.config, "read_mode", [ReadMode.READ_UPDATE_NFO])
    monkeypatch.setattr(manager.config, "nfo_include_new", [NfoInclude.PLOT_, NfoInclude.OUTLINE])
    monkeypatch.setattr(manager.config, "subtitle_add", False)
    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.NFO])
    monkeypatch.setattr(manager.config, "keep_files", [])
    # nfo 标题按 {{ title }} 渲染，方便断言「本地标题没被刮削值覆盖」
    monkeypatch.setattr(manager.config, "naming_media", "{{ title }}")
    monkeypatch.setattr(manager.config, "update_titletemplate", "{{ title }}")
    # 测试里的假视频只有几个字节，必须关掉「最小文件大小」门槛，
    # 否则 check_file 判定不通过、文件会被当成失败文件搬去失败目录。
    monkeypatch.setattr(manager.config, "file_size", 0)


class _FakeFileScraper:
    """替身爬虫：返回一份「与本地 nfo 有重叠、也有新值」的刮削结果。"""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def run(self, _task, _file_mode):
        data = CrawlersResult.empty()
        data.number = "ABS-040"
        data.title = "刮削标题"
        data.originaltitle = "scraped original"
        data.outline = "刮削简介"
        data.release = "2018-01-02"
        data.studio = "刮削片商"
        data.actors = ["刮削演员"]
        data.tags = ["刮削标签"]
        return data


def _stub_heavy_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """把联网/耗时步骤换成空实现，只验证补全模式的编排逻辑。"""
    monkeypatch.setattr(scraper_module, "FileScraper", _FakeFileScraper)

    async def _noop(*_args, **_kwargs):
        return True

    for name in ("thumb_download", "poster_download", "fanart_download", "trailer_download"):
        monkeypatch.setattr(scraper_module, name, _noop)

    async def _no_definition(*_args, **_kwargs):
        return "", ""

    monkeypatch.setattr(scraper_module, "get_video_size_for_file", _no_definition)

    async def _no_translate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scraper_module, "translate_title_outline", _no_translate)


# ---------------------------------------------------------------------------
# 1. 常量与判定
# ---------------------------------------------------------------------------


def test_complete_main_mode_is_seven(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert COMPLETE_MAIN_MODE == 7
    assert is_complete_mode() is False
    assert is_complete_selected() is False

    monkeypatch.setattr(manager.config, "main_mode", COMPLETE_MAIN_MODE)
    assert is_complete_mode() is True
    assert is_complete_selected() is True
    assert is_read_only_mode() is False


def test_runtime_override_switches_complete_mode_off(monkeypatch: pytest.MonkeyPatch):
    """运行时切到读取模式后，补全模式判定要跟着变（整理模式自动降级用同一套）。"""
    monkeypatch.setattr(manager.config, "main_mode", COMPLETE_MAIN_MODE)
    set_runtime_main_mode(READ_MAIN_MODE)
    assert is_complete_mode() is False
    assert is_complete_selected() is True  # 用户配置仍是补全模式
    assert is_read_only_mode() is True


def test_scan_ignore_dirs_drops_success_folder_in_complete_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """补全模式要能扫到「成功输出目录」，否则已归档的文件永远补不到。"""
    success = tmp_path / "JAV_output"
    success.mkdir()
    settings = SimpleNamespace(ignore_dirs=[success, tmp_path / "other"], success_folder=success)

    monkeypatch.setattr(manager.config, "main_mode", COMPLETE_MAIN_MODE)
    assert success not in get_scan_ignore_dirs(settings)

    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert success in get_scan_ignore_dirs(settings)


# ---------------------------------------------------------------------------
# 2. 合并策略与空字段统计
# ---------------------------------------------------------------------------


def test_complete_merge_strategy_defaults_to_prefer_nfo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "nfo_merge_enabled", False)
    monkeypatch.setattr(manager.config, "nfo_merge_strategy", NfoMergeStrategy.MERGE_ARRAYS)
    assert complete_merge_strategy() == NfoMergeStrategy.PREFER_NFO

    monkeypatch.setattr(manager.config, "nfo_merge_enabled", True)
    assert complete_merge_strategy() == NfoMergeStrategy.MERGE_ARRAYS


def test_filled_missing_fields_only_counts_empty_local():
    local = CrawlersResult.empty()
    local.title = "本地标题"
    local.outline = ""
    local.tags = []

    scraped = CrawlersResult.empty()
    scraped.title = "刮削标题"
    scraped.outline = "刮削简介"
    scraped.tags = ["标签"]

    merged = merge_nfo_fields(scraped, local, NfoMergeStrategy.PREFER_NFO)

    assert merged.title == "本地标题", "本地已有值必须保留"
    assert merged.outline == "刮削简介", "本地空字段必须用刮削值补上"
    assert merged.tags == ["标签"]
    assert set(filled_missing_fields(local, merged)) == {"outline", "tags"}


# ---------------------------------------------------------------------------
# 3. 文件关联模块（各模式共用）
# ---------------------------------------------------------------------------


def test_association_module_is_shared_with_organize():
    """organize 继续导出同一套 API（旧引用不破），实现只在 file_association。"""
    from mdcx.core import organize as organize_module

    assert organize_module.build_organize_index is build_organize_index
    assert organize_module.OrganizeIndex is OrganizeIndex


def test_collect_media_assets_maps_all_companions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "media_type", [".mp4", ".strm"])
    folder = tmp_path / "ABS-040"
    folder.mkdir()
    video = folder / "ABS-040.mp4"
    video.write_bytes(b"video")
    nfo = _write_nfo(folder)
    poster = folder / "poster.jpg"
    poster.write_bytes(b"poster")
    thumb = folder / "thumb.png"
    thumb.write_bytes(b"thumb")
    fanart = folder / "ABS-040-fanart.webp"
    fanart.write_bytes(b"fanart")
    sub = folder / "ABS-040.chs.ass"
    sub.write_text("[Script Info]", encoding="utf-8")
    torrent = folder / "ABS-040.torrent"
    torrent.write_bytes(b"torrent")
    mediainfo = folder / "ABS-040-mediainfo.json"
    mediainfo.write_text("{}", encoding="utf-8")

    assets = collect_media_assets(video, number="ABS-040", sub_types=[".ass"])

    assert assets.nfo == nfo
    assert assets.poster == poster
    assert assets.thumb == thumb
    assert assets.fanart == fanart
    assert assets.subtitles == [sub]
    assert assets.torrents == [torrent]
    assert assets.mediainfo == mediainfo
    assert assets.has_nfo and assets.has_subtitle
    assert assets.missing_main_images == []


def test_collect_media_assets_reports_missing_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "media_type", [".mp4", ".strm"])
    folder = tmp_path / "ABS-041"
    folder.mkdir()
    video = folder / "ABS-041.mp4"
    video.write_bytes(b"video")
    (folder / "poster.jpg").write_bytes(b"poster")

    assets = collect_media_assets(video, number="ABS-041")

    assert assets.has_nfo is False
    assert assets.missing_main_images == ["thumb", "fanart"]


def test_collect_media_assets_does_not_steal_other_number(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """共用目录里另一个番号的图片不能算到当前媒体头上。"""
    monkeypatch.setattr(manager.config, "media_type", [".mp4", ".strm"])
    folder = tmp_path / "shared"
    folder.mkdir()
    video_a = folder / "ABS-041.mp4"
    video_a.write_bytes(b"a")
    video_b = folder / "ABS-042.mp4"
    video_b.write_bytes(b"b")
    other_poster = folder / "ABS-042-poster.jpg"
    other_poster.write_bytes(b"poster")

    index = build_organize_index([folder])
    assets = collect_media_assets(video_a, index=index, number="ABS-041")

    assert assets.poster is None
    assert other_poster not in assets.images


# ---------------------------------------------------------------------------
# 4. 补全模式编排：本地优先 / 不移动 / 无 nfo 回退
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_mode_inplace_keeps_local_values_and_does_not_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """已在成功输出目录内：不移动文件，本地字段优先，只补空字段。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "ABS-040"
    success_dir.mkdir(parents=True)
    video = success_dir / "ABS-040.mp4"
    video.write_bytes(b"video")
    nfo = _write_nfo(success_dir)

    _configure_complete_mode(monkeypatch, media_dir)
    _stub_heavy_steps(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert video.exists(), "已在成功输出目录内的视频不能被移动"
    content = nfo.read_text(encoding="utf-8")
    assert "刮削标题" not in content, "本地已有标题不能被刮削值覆盖"
    assert "刮削简介" in content, "本地缺失的简介应该被补上"
    assert "刮削片商" not in content, "本地已有的片商不能被覆盖"
    assert Flags.fail_count == 0


@pytest.mark.asyncio
async def test_complete_mode_without_nfo_falls_back_to_normal_scrape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """没有 nfo 的文件自动按正常模式全量刮削（会生成 nfo 并移动到成功输出目录）。"""
    media_dir = tmp_path / "media"
    source = media_dir / "incoming"
    source.mkdir(parents=True)
    video = source / "ABS-040.mp4"
    video.write_bytes(b"video")

    _configure_complete_mode(monkeypatch, media_dir)
    _stub_heavy_steps(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    moved = media_dir / "JAV_output" / "ABS-040" / "ABS-040.mp4"
    assert moved.exists(), "无 nfo 的文件应按正常模式移动到成功输出目录"
    assert not video.exists()
    assert moved.with_suffix(".nfo").exists(), "正常模式刮削要写出 nfo"
    assert Flags.fail_count == 0


@pytest.mark.asyncio
async def test_complete_mode_moves_file_with_local_first_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """不在成功输出目录内：按设置移动，并保留本地字段、补上空字段。"""
    media_dir = tmp_path / "media"
    source = media_dir / "incoming"
    source.mkdir(parents=True)
    video = source / "ABS-040.mp4"
    video.write_bytes(b"video")
    _write_nfo(source)
    poster = source / "ABS-040-poster.jpg"
    poster.write_bytes(b"poster")

    _configure_complete_mode(monkeypatch, media_dir)
    _stub_heavy_steps(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    target = media_dir / "JAV_output" / "ABS-040"
    assert (target / "ABS-040.mp4").exists(), "视频应被移动到成功输出目录"
    assert (target / "ABS-040.nfo").exists(), "nfo 应随视频一起搬走"
    assert any(target.glob("*poster*")), "封面图应随视频一起搬走"
    content = (target / "ABS-040.nfo").read_text(encoding="utf-8")
    assert "刮削标题" not in content, "本地已有标题不能被刮削值覆盖"
    assert "刮削简介" in content, "本地缺失的简介应该被补上"
    assert not video.exists()
    assert Flags.fail_count == 0


# ---------------------------------------------------------------------------
# 5. 读取模式只读取展示（选项已迁到补全模式）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_mode_only_displays_without_scrape_or_move(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """读取模式只读 nfo 与本地图片并展示：不联网、不写 nfo、不移动文件。"""
    media_dir = tmp_path / "media"
    source = media_dir / "incoming"
    source.mkdir(parents=True)
    video = source / "ABS-040.mp4"
    video.write_bytes(b"video")
    nfo = _write_nfo(source)
    original_nfo = nfo.read_text(encoding="utf-8")

    _configure_complete_mode(monkeypatch, media_dir)
    _stub_heavy_steps(monkeypatch)
    monkeypatch.setattr(manager.config, "main_mode", READ_MAIN_MODE)
    # 即便把这几个旧选项全勾上，读取模式也不再联网/重下/整理
    monkeypatch.setattr(
        manager.config,
        "read_mode",
        [
            ReadMode.HAS_NFO_UPDATE,
            ReadMode.READ_UPDATE_NFO,
            ReadMode.READ_DOWNLOAD_AGAIN,
            ReadMode.NO_NFO_SCRAPE,
        ],
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("读取模式不应联网刮削")

    monkeypatch.setattr(scraper_module, "FileScraper", _boom)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert video.exists(), "读取模式不能移动文件"
    assert nfo.read_text(encoding="utf-8") == original_nfo, "读取模式不能改写 nfo"
    assert Flags.fail_count == 0


def test_update_rules_only_active_when_option_checked(monkeypatch: pytest.MonkeyPatch):
    """补全模式只有勾选「按更新模式重新整理分类」才走 A/B/C/D 更新规则。"""
    from mdcx.config.extend import is_update_rules_active

    monkeypatch.setattr(manager.config, "main_mode", COMPLETE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "read_mode", [])
    assert is_update_rules_active() is False

    monkeypatch.setattr(manager.config, "read_mode", [ReadMode.HAS_NFO_UPDATE])
    assert is_update_rules_active() is True

    # 更新模式本身恒走更新规则
    monkeypatch.setattr(manager.config, "main_mode", 4)
    monkeypatch.setattr(manager.config, "read_mode", [])
    assert is_update_rules_active() is True
