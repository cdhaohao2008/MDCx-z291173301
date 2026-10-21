"""路径归属判断(is_descendant)的回归测试。

背景: 网络盘/云盘挂载盘(CloudDrive2 等)调用 os.path.realpath 会抛出
OSError(WinError 1005 "此卷不包含可识别的文件系统")。旧实现一旦解析失败就直接
返回 False, 导致挂在网盘上的媒体库永远无法识别"文件已在成功输出目录内",
整理模式也就无法自动切换到读取模式(左下角文案一直停留在"整理模式")。
"""

import os
from pathlib import Path

import pytest

from mdcx.config.extend import is_in_success_folder
from mdcx.utils.path import is_any_descendant, is_descendant


def _simulate_netdisk_realpath(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """让指定前缀(模拟网盘盘符)下的 realpath 抛出 WinError 1005。"""

    original = os.path.realpath

    def fake_realpath(path, *args, **kwargs):
        text = os.fspath(path)
        if str(text).lower().startswith(prefix.lower()):
            raise OSError(1005, "此卷不包含可识别的文件系统")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)


def _simulate_netdisk_realpath_lenient(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """模拟网盘上 realpath 的真实行为: 不抛异常, 直接返回绝对路径。"""

    original = os.path.realpath

    def fake_realpath(path, *args, **kwargs):
        text = os.fspath(path)
        if str(text).lower().startswith(prefix.lower()):
            return os.path.abspath(text)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)


def test_is_descendant_accepts_child_path(tmp_path: Path):
    child = tmp_path / "JAV_output" / "ABS-039.strm"
    child.parent.mkdir(parents=True)
    child.write_text("x")

    assert is_descendant(child, tmp_path / "JAV_output") is True
    assert is_descendant(child, tmp_path) is True


def test_is_descendant_accepts_same_path(tmp_path: Path):
    assert is_descendant(tmp_path, tmp_path) is True


def test_is_descendant_rejects_sibling_with_common_prefix(tmp_path: Path):
    """docs 与 docsx 前缀相同但不是父子关系, 不能误判为后代。"""
    parent = tmp_path / "docs"
    sibling = tmp_path / "docsx" / "Changelog.md"
    parent.mkdir()
    sibling.parent.mkdir()
    sibling.write_text("x")

    assert is_descendant(sibling, parent) is False
    assert is_descendant(sibling, tmp_path) is True


def test_is_descendant_rejects_unrelated_path(tmp_path: Path):
    assert is_descendant(tmp_path / "a" / "b.strm", tmp_path / "c") is False


def test_is_descendant_falls_back_to_lexical_when_realpath_fails(monkeypatch: pytest.MonkeyPatch):
    """realpath 抛 OSError 时应退回词法比较, 而不是直接判定"不是后代"。"""
    _simulate_netdisk_realpath(monkeypatch, "K:\\")
    root = "K:\\CloudMedia\\测试\\新建文件夹"
    success_folder = os.path.join(root, "JAV_output")
    file_path = os.path.join(success_folder, "立花美凉", "ABS-039.strm")

    assert is_descendant(file_path, success_folder) is True
    assert is_descendant(file_path, root) is True
    assert is_descendant(os.path.join(root, "ABS-039.strm"), success_folder) is False


def test_is_descendant_returns_false_for_different_drives(monkeypatch: pytest.MonkeyPatch):
    """网盘与本地盘属于不同盘符, 不能互为后代。"""
    _simulate_netdisk_realpath(monkeypatch, "K:\\")

    assert is_descendant("K:\\CloudMedia\\a.strm", "D:\\Media") is False


def test_is_descendant_works_when_realpath_is_lenient(monkeypatch: pytest.MonkeyPatch):
    """网盘上 realpath(strict=False) 不抛异常, 直接返回绝对路径 → 比较必须成立。"""
    _simulate_netdisk_realpath_lenient(monkeypatch, "K:\\")
    root = "K:\\CloudMedia\\测试\\新建文件夹"
    success_folder = os.path.join(root, "JAV_output")

    assert is_descendant(os.path.join(success_folder, "ABS-039.strm"), success_folder) is True
    assert is_descendant(os.path.join(root, "ABS-039.strm"), success_folder) is False


def test_is_any_descendant_matches_any_parent(tmp_path: Path):
    target = tmp_path / "JAV_output" / "ABS-039.strm"

    assert is_any_descendant(target, tmp_path / "other", tmp_path / "JAV_output") is True
    assert is_any_descendant(target, tmp_path / "other") is False


def test_is_in_success_folder_works_on_netdisk(monkeypatch: pytest.MonkeyPatch):
    """成功输出目录判断在网盘上必须成立, 否则整理模式无法自动转读取模式。"""
    _simulate_netdisk_realpath(monkeypatch, "K:\\")
    success_folder = "K:\\CloudMedia\\测试\\新建文件夹\\JAV_output"

    assert is_in_success_folder(os.path.join(success_folder, "ABS-039.strm"), success_folder) is True
    assert is_in_success_folder("K:\\CloudMedia\\测试\\新建文件夹\\ABS-039.strm", success_folder) is False
    assert is_in_success_folder(os.path.join(success_folder, "ABS-039.strm"), None) is False


def test_is_in_success_folder_works_on_local_disk(tmp_path: Path):
    success_folder = tmp_path / "JAV_output"
    success_folder.mkdir()

    assert is_in_success_folder(success_folder / "ABS-039.strm", success_folder) is True
    assert is_in_success_folder(tmp_path / "ABS-039.strm", success_folder) is False
