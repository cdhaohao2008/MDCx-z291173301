"""整理模式「自动转为读取模式」+「成功输出目录内文件零移动」回归测试。

覆盖用户提出的 2 项需求：
1. 整理模式且所有文件都已在「成功输出目录」内 → 运行时自动切成读取模式
   （只改运行态，不写配置文件），左下角显示「读取模式·字段优先」。
2. 整理模式下已经在「成功输出目录」内的文件，任何情况下都不移动，
   也不做「复制后再删除源文件」（跨盘 shutil.move 的退化行为）。
"""

import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config.enums import ReadMode
from mdcx.config.extend import (
    ORGANIZE_MAIN_MODE,
    READ_MAIN_MODE,
    get_runtime_main_mode,
    is_organize_selected,
    is_success_output_tree,
    reset_runtime_main_mode,
    set_runtime_main_mode,
)
from mdcx.config.manager import manager
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
    monkeypatch.setattr(manager.config, "read_mode", [])


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    """每个用例前后都复位运行态模式覆盖与 Flags，避免用例之间互相污染。"""
    reset_runtime_main_mode()
    Flags.reset()
    yield
    reset_runtime_main_mode()
    Flags.reset()


class _FsSpy:
    """记录所有移动/复制/删除调用，用于断言「成功输出目录内的文件零操作」。"""

    def __init__(self) -> None:
        self.moves: list[tuple[str, str, str]] = []
        self.copies: list[tuple[str, str, str]] = []
        self.removes: list[str] = []

    def _norm(self, value) -> str:
        try:
            return os.path.normcase(os.path.abspath(str(value)))
        except TypeError, ValueError:  # pragma: no cover - 极端输入
            return str(value)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_move = shutil.move
        real_copy = shutil.copy
        real_copy2 = shutil.copy2
        real_copyfile = shutil.copyfile
        real_remove = os.remove
        real_unlink = os.unlink

        def spy_move(src, dst, *args, **kwargs):
            self.moves.append((self._norm(src), self._norm(dst), "move"))
            return real_move(src, dst, *args, **kwargs)

        def spy_copy(src, dst, *args, **kwargs):
            self.copies.append((self._norm(src), self._norm(dst), "copy"))
            return real_copy(src, dst, *args, **kwargs)

        def spy_copy2(src, dst, *args, **kwargs):
            self.copies.append((self._norm(src), self._norm(dst), "copy2"))
            return real_copy2(src, dst, *args, **kwargs)

        def spy_copyfile(src, dst, *args, **kwargs):
            self.copies.append((self._norm(src), self._norm(dst), "copyfile"))
            return real_copyfile(src, dst, *args, **kwargs)

        def spy_remove(path, *args, **kwargs):
            self.removes.append(self._norm(path))
            return real_remove(path, *args, **kwargs)

        def spy_unlink(path, *args, **kwargs):
            self.removes.append(self._norm(path))
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "move", spy_move)
        monkeypatch.setattr(shutil, "copy", spy_copy)
        monkeypatch.setattr(shutil, "copy2", spy_copy2)
        monkeypatch.setattr(shutil, "copyfile", spy_copyfile)
        monkeypatch.setattr(os, "remove", spy_remove)
        monkeypatch.setattr(os, "unlink", spy_unlink)

    def touched(self, path: Path) -> bool:
        """该路径是否被移动/复制/删除过。"""
        target = self._norm(path)
        for src, dst, _ in self.moves:
            if src == target or dst == target:
                return True
        for src, dst, _ in self.copies:
            if src == target or dst == target:
                return True
        return target in self.removes


# ---------------------------------------------------------------------------
# 需求 1：整理模式 → 自动转为读取模式（只改运行态）
# ---------------------------------------------------------------------------


def test_runtime_mode_override_never_touches_config():
    """运行态覆盖只影响内存，不改 manager.config（也就不会写回配置文件）。"""
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(manager.config, "main_mode", ORGANIZE_MAIN_MODE)
        set_runtime_main_mode(READ_MAIN_MODE)
        assert get_runtime_main_mode() == READ_MAIN_MODE
        # 用户在配置里选择的仍然是整理模式
        assert manager.config.main_mode == ORGANIZE_MAIN_MODE
        assert is_organize_selected() is True
        reset_runtime_main_mode()
        assert get_runtime_main_mode() == ORGANIZE_MAIN_MODE
    finally:
        monkey.undo()
        reset_runtime_main_mode()


@pytest.mark.asyncio
async def test_organize_auto_switches_runtime_to_read_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """整理模式 + 全部文件已在成功输出目录内 → 运行时自动切成读取模式。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    _configure_organize_mode(monkeypatch, media_dir)

    observed: list[int] = []
    original_get_nfo = scraper_module.get_nfo_data

    async def _spy_get_nfo(file_path, movie_number):
        observed.append(get_runtime_main_mode())
        return await original_get_nfo(file_path, movie_number)

    monkeypatch.setattr(scraper_module, "get_nfo_data", _spy_get_nfo)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    # 处理每个文件时，运行态模式已经是读取模式
    assert observed, "应该处理过文件"
    assert all(mode == READ_MAIN_MODE for mode in observed), observed
    # 配置文件里的选择没有被改动
    assert manager.config.main_mode == ORGANIZE_MAIN_MODE
    # 运行结束后运行态覆盖被清理，不影响下一次运行
    assert get_runtime_main_mode() == ORGANIZE_MAIN_MODE
    # 左下角显示「读取模式」
    assert Flags.mode_text_override == "读取模式"
    # 文件没有被移动
    assert strm.exists()
    assert Flags.total_count == 1
    assert Flags.fail_count == 0


@pytest.mark.asyncio
async def test_organize_auto_switch_does_not_write_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """自动切换只改运行态：配置文件内容保持原样。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    (success_dir / "ABS-040.strm").write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    _configure_organize_mode(monkeypatch, media_dir)

    config_file = tmp_path / "config.json"
    config_file.write_text('{"main_mode": 6}', encoding="utf-8")

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert config_file.read_text(encoding="utf-8") == '{"main_mode": 6}'
    assert manager.config.main_mode == ORGANIZE_MAIN_MODE


@pytest.mark.asyncio
async def test_organize_auto_switch_keeps_file_in_success_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """自动切换后，成功输出目录内的文件零移动、零复制、零删除。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    nfo = _write_sample_nfo(success_dir)
    _configure_organize_mode(monkeypatch, media_dir)

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert not spy.touched(strm), "成功输出目录内的媒体文件被移动/复制/删除了"
    assert not spy.touched(nfo), "成功输出目录内的 nfo 被移动/复制/删除了"
    assert strm.exists()
    assert strm.read_text(encoding="utf-8") == "https://example.com/ABS-040.mp4"
    assert nfo.exists()


@pytest.mark.asyncio
async def test_organize_inplace_file_never_moved_when_read_mode_updates_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """即使读取模式勾选了「更新 nfo / 重新下载」，成功输出目录内的文件也不移动。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    _configure_organize_mode(monkeypatch, media_dir)
    monkeypatch.setattr(
        manager.config,
        "read_mode",
        [ReadMode.HAS_NFO_UPDATE, ReadMode.READ_UPDATE_NFO, ReadMode.READ_DOWNLOAD_AGAIN],
    )

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert not spy.touched(strm)
    assert strm.exists()
    assert Flags.mode_text_override == "读取模式"


# ---------------------------------------------------------------------------
# 需求 2：成功输出目录内的文件任何情况下都不移动
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_scenario_only_moves_file_outside_success_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """一半在成功输出目录内、一半在目录外 → 只整理目录外的文件，目录内的原地不动。"""
    media_dir = tmp_path / "media"
    inside_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-041"
    inside_dir.mkdir(parents=True)
    inside_strm = inside_dir / "ABS-041.strm"
    inside_strm.write_text("https://example.com/ABS-041.mp4", encoding="utf-8")
    _write_sample_nfo(inside_dir, "ABS-041")

    outside_dir = media_dir / "あやめ美桜" / "プレステージ" / "2017-11-21 ABS-040"
    _write_sample_nfo(outside_dir, "ABS-040")
    outside_strm = outside_dir / "ABS-040.strm"
    outside_strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")

    _configure_organize_mode(monkeypatch, media_dir)

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    # 目录内的文件原地不动
    assert inside_strm.exists()
    assert not spy.touched(inside_strm)
    # 目录外的文件被整理进成功输出目录
    assert not outside_strm.exists()
    moved = list(media_dir.glob("JAV_output/**/ABS-040.strm"))
    assert len(moved) == 1
    # 没有全部落在成功输出目录内 → 不覆盖左下角模式文案
    assert Flags.mode_text_override == ""
    assert Flags.total_count == 2
    assert Flags.fail_count == 0


@pytest.mark.asyncio
async def test_existing_file_in_success_folder_is_not_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """目标位置已有成功输出目录内的文件时，既不覆盖它，也不搬动新文件。"""
    media_dir = tmp_path / "media"
    occupied_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    occupied_dir.mkdir(parents=True)
    occupied = occupied_dir / "ABS-040.strm"
    occupied.write_text("https://example.com/old.mp4", encoding="utf-8")
    _write_sample_nfo(occupied_dir, "ABS-040")

    outside_dir = media_dir / "あやめ美桜" / "プレステージ" / "2017-11-21 ABS-040"
    _write_sample_nfo(outside_dir, "ABS-040")
    outside_strm = outside_dir / "ABS-040.strm"
    outside_strm.write_text("https://example.com/new.mp4", encoding="utf-8")

    _configure_organize_mode(monkeypatch, media_dir)

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    # 成功输出目录里的既有文件内容不变，也没有被移动/删除
    assert occupied.exists()
    assert occupied.read_text(encoding="utf-8") == "https://example.com/old.mp4"
    assert not spy.touched(occupied)


# ---------------------------------------------------------------------------
# 需求 3：选中的目录本身位于「成功输出目录」内 → 自动切成读取模式
# ---------------------------------------------------------------------------


def test_is_success_output_tree_detection(tmp_path: Path):
    """判定目录是否落在「成功输出目录」树内（本身是成功输出目录，或是它的子目录）。"""
    media_dir = tmp_path / "media"
    # 成功输出目录本身
    assert is_success_output_tree(media_dir / "JAV_output") is True
    # 成功输出目录的子目录
    assert is_success_output_tree(media_dir / "JAV_output" / "あやめ美桜") is True
    # 普通待刮削目录不在成功输出目录树内
    assert is_success_output_tree(media_dir) is False
    assert is_success_output_tree(media_dir / "あやめ美桜") is False
    # 名字相近但不相等的目录不算
    assert is_success_output_tree(media_dir / "JAV_output_old") is False
    # 多段相对路径取最后一段目录名
    assert is_success_output_tree(media_dir / "output" / "JAV_output", "output/JAV_output") is True
    assert is_success_output_tree(media_dir / "output", "output/JAV_output") is False


@pytest.mark.asyncio
async def test_selected_success_output_dir_switches_to_read_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """选中的目录本身就是「成功输出目录」→ 自动切成读取模式（不移动任何文件）。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    # 用户直接把「成功输出目录」当成待刮削目录
    _configure_organize_mode(monkeypatch, success_dir)

    observed: list[int] = []
    original_get_nfo = scraper_module.get_nfo_data

    async def _spy_get_nfo(file_path, movie_number):
        observed.append(get_runtime_main_mode())
        return await original_get_nfo(file_path, movie_number)

    monkeypatch.setattr(scraper_module, "get_nfo_data", _spy_get_nfo)

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert observed, "应该处理过文件"
    assert all(mode == READ_MAIN_MODE for mode in observed), observed
    # 配置文件里的选择没有被改动
    assert manager.config.main_mode == ORGANIZE_MAIN_MODE
    assert get_runtime_main_mode() == ORGANIZE_MAIN_MODE
    # 左下角显示「读取模式」
    assert Flags.mode_text_override == "读取模式"
    # 文件没有被移动
    assert strm.exists()
    assert not spy.touched(strm)
    assert Flags.total_count == 1
    assert Flags.fail_count == 0


@pytest.mark.asyncio
async def test_selected_subdir_of_success_output_switches_to_read_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """选中的目录是「成功输出目录」的子目录 → 同样自动切成读取模式。"""
    media_dir = tmp_path / "media"
    success_dir = media_dir / "JAV_output" / "あやめ美桜" / "ABS-040"
    success_dir.mkdir(parents=True)
    strm = success_dir / "ABS-040.strm"
    strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _write_sample_nfo(success_dir)
    # 用户选中了成功输出目录下的子目录
    _configure_organize_mode(monkeypatch, success_dir.parent)

    observed: list[int] = []
    original_get_nfo = scraper_module.get_nfo_data

    async def _spy_get_nfo(file_path, movie_number):
        observed.append(get_runtime_main_mode())
        return await original_get_nfo(file_path, movie_number)

    monkeypatch.setattr(scraper_module, "get_nfo_data", _spy_get_nfo)

    spy = _FsSpy()
    spy.install(monkeypatch)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert observed, "应该处理过文件"
    assert all(mode == READ_MAIN_MODE for mode in observed), observed
    assert manager.config.main_mode == ORGANIZE_MAIN_MODE
    assert Flags.mode_text_override == "读取模式"
    assert strm.exists()
    assert not spy.touched(strm)


@pytest.mark.asyncio
async def test_normal_media_dir_keeps_organize_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """待刮削目录不在成功输出目录树内 → 保持整理模式（不误切换）。"""
    media_dir = tmp_path / "media"
    outside_dir = media_dir / "あやめ美桜" / "プレステージ" / "2017-11-21 ABS-040"
    _write_sample_nfo(outside_dir, "ABS-040")
    outside_strm = outside_dir / "ABS-040.strm"
    outside_strm.write_text("https://example.com/ABS-040.mp4", encoding="utf-8")
    _configure_organize_mode(monkeypatch, media_dir)

    observed: list[int] = []
    original_get_nfo = scraper_module.get_nfo_data

    async def _spy_get_nfo(file_path, movie_number):
        observed.append(get_runtime_main_mode())
        return await original_get_nfo(file_path, movie_number)

    monkeypatch.setattr(scraper_module, "get_nfo_data", _spy_get_nfo)

    await Scraper(_DummyCrawlerProvider()).run(FileMode.Default, None)

    assert observed
    assert all(mode == ORGANIZE_MAIN_MODE for mode in observed), observed
    assert Flags.mode_text_override == ""
    # 文件被整理进成功输出目录
    assert not outside_strm.exists()
    assert len(list(media_dir.glob("JAV_output/**/ABS-040.strm"))) == 1


# ---------------------------------------------------------------------------
# 左下角文案
# ---------------------------------------------------------------------------


def _make_window():
    """构造一个只够展示左下角文案的窗口桩。"""
    from mdcx.controllers.main_window.success_list import SuccessListMixin

    class _Label:
        def __init__(self) -> None:
            self.text = ""

        def emit(self, value) -> None:
            self.text = value

    class _Window(SuccessListMixin):
        def __init__(self) -> None:
            self.Ui = SimpleNamespace(comboBox_website_all=None)
            self.label_show_version = _Label()
            self.localversion = "2.7.6"
            self.new_version = ""

    return _Window()


def test_left_bottom_label_shows_read_mode():
    """左下角显示「读取模式·字段优先」。"""
    Flags.main_mode_text = "整理模式"
    Flags.scrape_like_text = "字段优先"
    Flags.mode_text_override = "读取模式"

    window = _make_window()
    window.show_scrape_info()

    assert "读取模式·字段优先" in window.label_show_version.text
    assert "整理模式" not in window.label_show_version.text


def test_left_bottom_label_shows_organize_mode_in_mixed_case():
    """部分文件在成功输出目录内时，左下角仍显示「整理模式·字段优先」。"""
    Flags.main_mode_text = "整理模式"
    Flags.scrape_like_text = "字段优先"
    Flags.mode_text_override = ""

    window = _make_window()
    window.show_scrape_info()

    assert "整理模式·字段优先" in window.label_show_version.text
