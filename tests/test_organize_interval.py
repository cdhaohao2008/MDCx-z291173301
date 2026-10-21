"""整理模式「间隔时间」相关回归测试。

覆盖用户提出的 4 项需求：
1. 整理模式下文件已经在「成功输出目录」内 → 自动退化为读取模式（不移动/复制/重命名），
   左下角文案由「整理模式」切换为「读取模式」。
2. 「刮削模式」页新增的左右两枚互斥复选框（本地不限制间隔 / 网盘按自动休息间隔）
   写入 JSON 配置，旧配置自动迁移。
3. 网盘存储：两次整理之间的间隔必须大于「高级 → 间歇刮削 → 自动休息」，不足自动等待。
4. 「自动休息」允许的最小值为 40 秒。
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

from mdcx.config.extend import (
    ORGANIZE_MAIN_MODE,
    is_in_success_folder,
    organize_netdisk_rest_enabled,
    organize_rest_seconds,
)
from mdcx.config.manager import manager
from mdcx.config.migrations import _migrate_organize_interval_keys
from mdcx.config.models import MIN_REST_TIME_SECONDS, Config
from mdcx.core import scraper as scraper_module
from mdcx.core.scraper import Scraper
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags

pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="项目配置模型需要 Python 3.13+")


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
    """把配置切到与用户实测一致的整理模式。"""
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
    monkeypatch.setattr(manager.config, "emby_on", [])
    monkeypatch.setattr(manager.config, "actor_photo_kodi_auto", False)


# ---------------------------------------------------------------------------
# 需求 1：已在成功输出目录内的文件 → 自动退化为读取模式
# ---------------------------------------------------------------------------


def test_is_in_success_folder_detects_inplace_files(tmp_path: Path):
    success = tmp_path / "JAV_output"
    inside = success / "あやめ美桜" / "ABS-040" / "ABS-040.strm"
    outside = tmp_path / "あやめ美桜" / "ABS-040.strm"

    assert is_in_success_folder(inside, success) is True
    assert is_in_success_folder(outside, success) is False
    # 没有成功输出目录时不能误判
    assert is_in_success_folder(inside, None) is False


@pytest.mark.asyncio
async def test_organize_inplace_file_is_handled_as_read_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """文件已在成功输出目录内 → 不移动任何文件，左下角文案切换为「读取模式」。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    _configure_organize_mode(monkeypatch, media_dir)

    moved: list = []
    monkeypatch.setattr(scraper_module, "organize_files", lambda *args, **kwargs: moved.append((args, kwargs)))

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    # 没有调用任何整理（移动/复制）动作
    assert moved == []
    # 文件仍在原地
    assert strm.exists()
    # 结果正常统计
    assert Flags.total_count == 1
    assert Flags.fail_count == 0
    # 左下角文案切换为「读取模式」
    assert Flags.mode_text_override == "读取模式"


@pytest.mark.asyncio
async def test_organize_outside_file_still_moves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """尚未整理的文件仍然走正常的「移动 + 重命名」流程（不受新规则影响）。"""
    media_dir = tmp_path / "media"
    movie_dir = media_dir / "あやめ美桜" / "プレステージ" / "2017-11-21 ABS-040"
    _write_sample_nfo(movie_dir)
    (movie_dir / "ABS-040.strm").write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _configure_organize_mode(monkeypatch, media_dir)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert Flags.total_count == 1
    assert Flags.fail_count == 0
    assert len(list(media_dir.glob("JAV_output/**/*.strm"))) == 1
    # 未全部在成功输出目录内 → 不覆盖左下角模式文案
    assert Flags.mode_text_override == ""


# ---------------------------------------------------------------------------
# 需求 2：两枚互斥复选框的配置持久化与旧配置迁移
# ---------------------------------------------------------------------------


def test_migrate_organize_interval_keys_fills_missing_keys():
    """旧配置没有这两个键 → 自动补齐为「本地不限制间隔」。"""
    data: dict = {}
    _migrate_organize_interval_keys(data)

    assert data["organize_local_no_interval"] is True
    assert data["organize_netdisk_rest_interval"] is False


def test_migrate_organize_interval_keys_netdisk_wins_when_both_on():
    """两个键同时为真（手改配置）→ 以网盘为准。"""
    data = {"organize_local_no_interval": True, "organize_netdisk_rest_interval": True}
    _migrate_organize_interval_keys(data)

    assert data["organize_local_no_interval"] is False
    assert data["organize_netdisk_rest_interval"] is True


def test_migrate_organize_interval_keys_local_when_both_off():
    """两个键同时为假（手改配置）→ 以本地不限制为准。"""
    data = {"organize_local_no_interval": False, "organize_netdisk_rest_interval": False}
    _migrate_organize_interval_keys(data)

    assert data["organize_local_no_interval"] is True
    assert data["organize_netdisk_rest_interval"] is False


def test_config_update_migrates_old_config(monkeypatch: pytest.MonkeyPatch):
    """旧版本配置文件载入时自动补齐新字段（配置升级迁移）。"""
    data: dict = {"main_mode": 6}
    Config.update(data)

    assert data["organize_local_no_interval"] is True
    assert data["organize_netdisk_rest_interval"] is False


def test_config_defaults_are_local_no_interval():
    cfg = Config.model_validate({"main_mode": 6})
    assert cfg.organize_local_no_interval is True
    assert cfg.organize_netdisk_rest_interval is False


# ---------------------------------------------------------------------------
# 需求 3：网盘存储按自动休息间隔整理
# ---------------------------------------------------------------------------


def test_organize_netdisk_rest_enabled_requires_netdisk_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "organize_local_no_interval", True)
    monkeypatch.setattr(manager.config, "organize_netdisk_rest_interval", False)
    assert organize_netdisk_rest_enabled() is False

    monkeypatch.setattr(manager.config, "organize_local_no_interval", False)
    monkeypatch.setattr(manager.config, "organize_netdisk_rest_interval", True)
    assert organize_netdisk_rest_enabled() is True

    # 非整理模式下不生效
    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert organize_netdisk_rest_enabled() is False


def test_organize_rest_seconds_uses_rest_time_with_minimum(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "rest_time", timedelta(minutes=10))
    assert organize_rest_seconds() == 600

    # 低于 40s 时按 40s 计算
    monkeypatch.setattr(manager.config, "rest_time", timedelta(seconds=5))
    assert organize_rest_seconds() == MIN_REST_TIME_SECONDS


@pytest.mark.asyncio
async def test_wait_organize_interval_waits_until_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """间隔不足时自动等待到满足「自动休息」时间后才开始整理。"""
    now = {"value": 1_000.0}

    class _FakeTime:
        @staticmethod
        def time() -> float:
            return now["value"]

        @staticmethod
        def localtime(t: float | None = None):
            import time as _time

            return _time.localtime(t if t is not None else now["value"])

        @staticmethod
        def strftime(fmt: str, t=None) -> str:
            import time as _time

            return _time.strftime(fmt, t if t is not None else now["value"])

    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now["value"] += seconds

    monkeypatch.setattr(scraper_module, "time", _FakeTime)
    monkeypatch.setattr(scraper_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(scraper_module, "load_organize_state", lambda: {"last_run_end": 990.0})
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "organize_local_no_interval", False)
    monkeypatch.setattr(manager.config, "organize_netdisk_rest_interval", True)
    monkeypatch.setattr(manager.config, "rest_time", timedelta(seconds=40))

    await Scraper(_DummyCrawlerProvider())._wait_organize_interval()

    # 上次结束于 990，本次休息 40s → 必须等到 1030 之后才开始
    assert slept, "应该执行等待"
    assert now["value"] >= 1030.0


@pytest.mark.asyncio
async def test_wait_organize_interval_skips_when_enough_time_passed(monkeypatch: pytest.MonkeyPatch):
    """间隔已满足（或首次运行）→ 不等待。"""
    now = {"value": 1_000.0}

    class _FakeTime:
        @staticmethod
        def time() -> float:
            return now["value"]

        @staticmethod
        def localtime(t: float | None = None):
            import time as _time

            return _time.localtime(t if t is not None else now["value"])

        @staticmethod
        def strftime(fmt: str, t=None) -> str:
            import time as _time

            return _time.strftime(fmt, t if t is not None else now["value"])

    async def _fake_sleep(seconds: float) -> None:  # pragma: no cover - 不应被调用
        raise AssertionError("间隔已满足时不应该等待")

    monkeypatch.setattr(scraper_module, "time", _FakeTime)
    monkeypatch.setattr(scraper_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(scraper_module, "load_organize_state", lambda: {"last_run_end": 900.0})
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "organize_local_no_interval", False)
    monkeypatch.setattr(manager.config, "organize_netdisk_rest_interval", True)
    monkeypatch.setattr(manager.config, "rest_time", timedelta(seconds=40))

    await Scraper(_DummyCrawlerProvider())._wait_organize_interval()


@pytest.mark.asyncio
async def test_wait_organize_interval_skips_for_local_storage(monkeypatch: pytest.MonkeyPatch):
    """勾选「本地存储不限制间隔时间」→ 不等待。"""
    now = {"value": 1_000.0}

    class _FakeTime:
        @staticmethod
        def time() -> float:
            return now["value"]

    async def _fake_sleep(seconds: float) -> None:  # pragma: no cover - 不应被调用
        raise AssertionError("本地存储不应该等待")

    monkeypatch.setattr(scraper_module, "time", _FakeTime)
    monkeypatch.setattr(scraper_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(scraper_module, "load_organize_state", lambda: {"last_run_end": 999.0})
    monkeypatch.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
    monkeypatch.setattr(manager.config, "organize_local_no_interval", True)
    monkeypatch.setattr(manager.config, "organize_netdisk_rest_interval", False)

    await Scraper(_DummyCrawlerProvider())._wait_organize_interval()


@pytest.mark.asyncio
async def test_organize_run_records_last_run_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理结束后记录结束时间，供下一次整理计算间隔。"""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    _configure_organize_mode(monkeypatch, media_dir)

    state_file = tmp_path / "organize_state.json"
    monkeypatch.setattr(
        scraper_module.resources, "u", lambda name: state_file if name == "organize_state.json" else tmp_path / name
    )

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert state_file.exists()
    import json

    data = json.loads(state_file.read_text("UTF-8"))
    assert data["last_run_end"] > 0


# ---------------------------------------------------------------------------
# 需求 4：自动休息最小 40 秒
# ---------------------------------------------------------------------------


def test_rest_time_is_clamped_to_minimum():
    """低于 40 秒的自动休息时间会被抬到 40 秒。"""
    cfg = Config.model_validate({"main_mode": 1, "rest_time": "00:00:05"})
    assert cfg.rest_time == timedelta(seconds=MIN_REST_TIME_SECONDS)

    cfg2 = Config.model_validate({"main_mode": 1, "rest_time": "00:00:40"})
    assert cfg2.rest_time == timedelta(seconds=MIN_REST_TIME_SECONDS)

    cfg3 = Config.model_validate({"main_mode": 1, "rest_time": "00:10:00"})
    assert cfg3.rest_time == timedelta(minutes=10)


def test_rest_time_default_is_minimum():
    cfg = Config.model_validate({"main_mode": 1})
    assert cfg.rest_time == timedelta(seconds=MIN_REST_TIME_SECONDS)
