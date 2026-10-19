"""议题 #26 回归：海报超分（触发条件/参数/原子替换/失败降级），全程离线。"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.core import super_resolution as sr


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "u", lambda rel: tmp_path / rel)
    monkeypatch.setattr(manager.config, "poster_sr_enabled", True)
    monkeypatch.setattr(manager.config, "poster_sr_preset", "realesr-photo-4x")
    monkeypatch.setattr(manager.config, "poster_sr_max_dim", 1200)
    # 「只报一次」类模块全局逐例复位，避免上一例的结论吞掉本例要断言的日志
    monkeypatch.setattr(sr, "_SR_SKIP_REPORTED", False, raising=False)
    monkeypatch.setattr(sr, "_BUILTIN_MISS_REPORTED", False, raising=False)
    yield


def _make_jpg(path, w: int, h: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (120, 60, 200)).save(path, "JPEG")


def test_trigger_requires_switch_small_dim_and_size_guard(tmp_path, monkeypatch):
    small = tmp_path / "poster_small.jpg"
    _make_jpg(small, 300, 450)
    big = tmp_path / "poster_big.jpg"
    _make_jpg(big, 2000, 3000)

    assert sr._sr_trigger_ok(small) is True
    assert sr._sr_trigger_ok(big) is False, "最长边超阈值不超分"
    assert sr._sr_trigger_ok(tmp_path / "missing.jpg") is False

    monkeypatch.setattr(manager.config, "poster_sr_enabled", False)
    assert sr._sr_trigger_ok(small) is False, "开关默认关时绝不触发"


def test_build_args_per_preset():
    a = sr.build_args(sr.Path("/tmp/i.jpg"), sr.Path("/tmp/o.jpg"), sr.SrPreset.REALESR_PHOTO_4X)
    assert ["-n", "realesrgan-x4plus"] == a[a.index("-n") : a.index("-n") + 2]
    assert "-s" in a and a[a.index("-s") + 1] == "4"

    b = sr.build_args(sr.Path("/tmp/i.jpg"), sr.Path("/tmp/o.jpg"), sr.SrPreset.WAIFU_PHOTO_2X)
    assert ["-m", "upconv_7_photo"] == b[b.index("-m") : b.index("-m") + 2]
    assert b[b.index("-s") + 1] == "2"


def test_download_urls_cover_three_platforms():
    for tool in ("realesrgan", "waifu2x"):
        urls = sr._TOOL_DOWNLOAD_URLS[tool]
        assert set(urls) == {"macos", "linux", "windows"}
        assert all(u.startswith("https://github.com/") for u in urls.values())


def test_realesrgan_linux_asset_uses_ubuntu_suffix():
    """#26: Real-ESRGAN 官方 Linux 资产名为 ubuntu，拼成 linux.zip 实测 404；waifu2x 才是 linux。"""
    assert sr._TOOL_DOWNLOAD_URLS["realesrgan"]["linux"].endswith("-ubuntu.zip")
    assert sr._TOOL_DOWNLOAD_URLS["waifu2x"]["linux"].endswith("-linux.zip")


def test_checksum_matches_when_baseline_configured(monkeypatch):
    data = b"zip-bytes"
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {"realesrgan": {"linux": hashlib.sha256(data).hexdigest()}})
    assert sr._checksum_matches(data, "realesrgan", "linux") is True


def test_checksum_detects_mismatch(monkeypatch):
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {"realesrgan": {"linux": "0" * 64}})
    assert sr._checksum_matches(b"zip-bytes", "realesrgan", "linux") is False


def test_checksum_passes_without_baseline(monkeypatch):
    """无基准时不拦截，仅靠解压后可执行性兜底。"""
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {})
    assert sr._checksum_matches(b"anything", "realesrgan", "linux") is True


@pytest.mark.asyncio
async def test_ensure_binary_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sr.sys, "platform", "plan9")
    assert await sr.ensure_binary("realesrgan") is None


@pytest.mark.asyncio
async def test_maybe_upscale_replaces_atomically(tmp_path, monkeypatch):
    poster = tmp_path / "poster.jpg"
    _make_jpg(poster, 300, 450)
    original = poster.read_bytes()

    async def fake_upscale(src, dst, preset):
        # 非纯黑图片（避免被 _is_all_black 误判为失败）
        Image.new("RGB", (1200, 1800), (120, 60, 200)).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is True
    assert max(Image.open(poster).size) == 1800
    leftovers = [p for p in tmp_path.rglob("*") if "[SR]" in p.name]
    assert leftovers == [], "临时产物须清理"
    assert original != poster.read_bytes()


@pytest.mark.asyncio
async def test_maybe_upscale_rejects_non_enlarged_output(tmp_path, monkeypatch):
    poster = tmp_path / "poster.jpg"
    _make_jpg(poster, 300, 450)
    before = poster.read_bytes()

    async def fake_upscale(src, dst, preset):
        Image.new("RGB", (300, 450), (0, 0, 0)).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is False
    assert poster.read_bytes() == before, "产物未增大必须弃用并保持原图"


@pytest.mark.asyncio
async def test_maybe_upscale_failure_keeps_original(tmp_path, monkeypatch):
    poster = tmp_path / "poster.jpg"
    _make_jpg(poster, 300, 450)
    before = poster.read_bytes()

    async def fake_upscale(src, dst, preset):
        return False

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is False
    assert poster.read_bytes() == before


def _make_textured_jpg(path, w: int, h: int) -> None:
    from PIL import ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (w, h), (120, 60, 200))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, w - 20, h - 20], fill=(200, 180, 60))
    d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(30, 120, 90))
    img.save(path, "JPEG")


def test_similarity_high_for_good_upscale(tmp_path):
    src = tmp_path / "src.jpg"
    _make_textured_jpg(src, 300, 450)
    dst = tmp_path / "dst.jpg"
    with Image.open(src) as im:
        im.resize((1200, 1800), Image.BICUBIC).save(dst, "JPEG")
    sim = sr._similarity(src, dst)
    assert sim is not None and sim >= 0.9, f"正常超分相似度应很高，实际 {sim}"
    assert sr._upscale_failure_reason(src, dst) is None


def test_similarity_low_for_black_output(tmp_path):
    src = tmp_path / "src.jpg"
    _make_textured_jpg(src, 300, 450)
    dst = tmp_path / "black.jpg"
    Image.new("RGB", (1200, 1800), (0, 0, 0)).save(dst, "JPEG")
    sim = sr._similarity(src, dst)
    assert sim is not None and sim < 0.5, f"黑图相似度应低于阈值，实际 {sim}"
    assert sr._upscale_failure_reason(src, dst) is not None


@pytest.mark.asyncio
async def test_maybe_upscale_deletes_low_similarity_first_and_retries(tmp_path, monkeypatch):
    """首超相似度<50%（黑图）须删除并换工具重试，重试可用则保留。"""
    poster = tmp_path / "poster.jpg"
    _make_textured_jpg(poster, 300, 450)
    calls: list[str] = []

    async def fake_upscale(src, dst, preset):
        calls.append(str(preset))
        if len(calls) == 1:
            Image.new("RGB", (1200, 1800), (0, 0, 0)).save(dst, "JPEG")
        else:
            with Image.open(src) as im:
                im.resize((1200, 1800), Image.BICUBIC).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is True
    assert calls == ["realesr-photo-4x", "waifu-photo-2x"], "重试须换另一款工具"
    assert [p for p in tmp_path.rglob("*") if "[SR]" in p.name] == [], "临时产物须清理"


@pytest.mark.asyncio
async def test_maybe_upscale_keeps_usable_retry_despite_low_similarity(tmp_path, monkeypatch):
    """二次相似度仍<50% 但非黑/非纯色时按策略保留（噪声图模拟内容偏离但可用）。"""
    import random

    poster = tmp_path / "poster.jpg"
    _make_textured_jpg(poster, 300, 450)

    async def fake_upscale(src, dst, preset):
        rnd = random.Random(7)
        px = bytes(rnd.randint(0, 255) for _ in range(300 * 450))
        Image.frombytes("L", (300, 450), px).convert("RGB").resize((1200, 1800)).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    # 首超即噪声：相似度低触发重试；二次同样噪声但硬判定通过，按策略保留
    assert await sr.maybe_upscale_poster(poster) is True


@pytest.mark.asyncio
async def test_maybe_upscale_discards_solid_retry(tmp_path, monkeypatch):
    """二次仍是纯色（白图）则弃用并保持原图。"""
    poster = tmp_path / "poster.jpg"
    _make_textured_jpg(poster, 300, 450)
    before = poster.read_bytes()

    async def fake_upscale(src, dst, preset):
        Image.new("RGB", (1200, 1800), (255, 255, 255)).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is False
    assert poster.read_bytes() == before


@pytest.mark.asyncio
async def test_upscale_image_timeout_degrades(monkeypatch, tmp_path):
    src = tmp_path / "a.jpg"
    dst = tmp_path / "b.jpg"
    _make_jpg(src, 10, 10)

    class _HangProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(30)
            return b"", b""

        def kill(self):
            pass

        async def wait(self):
            return None

    async def fake_exec(*args, **kwargs):
        return _HangProc()

    monkeypatch.setattr(sr.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(sr, "ensure_binary", lambda tool: _pass())
    monkeypatch.setattr(sr, "_SR_TIMEOUT_SECONDS", 0.05)

    assert await sr.upscale_image(src, dst, sr.SrPreset.REALESR_PHOTO_4X) is False


def _make_tool_zip(tool: str) -> bytes:
    """构造官方形态的 zip：顶层目录 `<tool>/`，二进制名为 `<tool>-ncnn-vulkan`。"""
    name = f"{tool}-ncnn-vulkan.exe" if sys.platform == "win32" else f"{tool}-ncnn-vulkan"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{tool}/{name}", b"fake binary")
    return buffer.getvalue()


async def _pass():
    from pathlib import Path

    return Path("/bin/true")


def test_scraper_hooks_upscale_after_poster_success():
    """AST 哨兵：poster 下载成功后必须挂 maybe_upscale_poster（防未来重构丢钩子）。"""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mdcx/core/scraper.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and any("maybe_upscale_poster" in ast.unparse(s) for s in ast.walk(n))
    )
    text = ast.unparse(fn)
    idx_hook = text.index("maybe_upscale_poster")
    idx_check = text.index("poster_task.result()")
    assert idx_hook > idx_check, "超分必须在 poster 成功判定之后"
    assert "contextlib.suppress" in text, "超分异常不得影响刮削结果"


@pytest.mark.asyncio
async def test_ensure_binary_prefers_builtin_without_download(tmp_path, monkeypatch):
    """一体包（_MEIPASS）内置工具时直接释放使用，不触发下载。"""
    builtin = tmp_path / "mei" / "sr_tools" / "realesrgan"
    builtin.mkdir(parents=True)
    # 按平台实际的可执行文件名造（Windows 带 .exe），内置目录缺二进制会被判释放失败
    (builtin / sr._binary_name("realesrgan")).write_text("#!/bin/sh\nexit 0")
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)

    async def fail_download(url):
        raise AssertionError("内置工具可用时不应发起下载")

    monkeypatch.setattr(sr, "_download_bytes", fail_download)
    assert await sr.ensure_binary("realesrgan") is not None


@pytest.mark.asyncio
async def test_ensure_binary_retries_after_transient_failure(tmp_path, monkeypatch):
    tool = "realesrgan"
    platform = sr._PLATFORM.get(sr.sys.platform) or ""
    data = _make_tool_zip(tool)
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {tool: {platform: hashlib.sha256(data).hexdigest()}})

    calls: list[int] = []

    async def fake_download(url):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("timeout")
        return data

    monkeypatch.setattr(sr, "_download_bytes", fake_download)
    assert await sr.ensure_binary(tool) is not None
    assert len(calls) == 2, "瞬时失败应重试一次"


@pytest.mark.asyncio
async def test_ensure_binary_degrades_when_checksum_mismatch(tmp_path, monkeypatch):
    tool = "waifu2x"
    platform = sr._PLATFORM.get(sr.sys.platform) or ""
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {tool: {platform: "0" * 64}})

    async def fake_download(url):
        return _make_tool_zip(tool)

    monkeypatch.setattr(sr, "_download_bytes", fake_download)
    assert await sr.ensure_binary(tool) is None, "校验不匹配必须降级，不能拿可疑二进制当工具"


@pytest.mark.asyncio
async def test_upscale_failure_reports_vulkan_unavailable(tmp_path, monkeypatch):
    """开关开着却没效果时，日志要给可读结论：无 Vulkan 设备是最常见原因。"""
    logs: list[str] = []
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)
    monkeypatch.setattr(sr, "ensure_binary", lambda tool: _pass())
    monkeypatch.setattr(sr, "_SR_SKIP_REPORTED", False, raising=False)

    class _FailProc:
        returncode = 1

        async def communicate(self):
            return b"", b"vkCreateInstance failed -9"

        def kill(self):
            pass

        async def wait(self):
            return 1

    # Windows 平台使用 _run_elevated，同步函数无法直接 monkeypatch async 执行器；
    # 直接 monkeypatch _run_elevated 模拟失败返回（带 Vulkan 错误输出）。
    def fake_elevated(cmd, cwd, timeout):
        return 1, b"", b"vkCreateInstance failed -9"

    monkeypatch.setattr(sr, "_run_elevated", fake_elevated)

    src = tmp_path / "a.jpg"
    dst = tmp_path / "b.jpg"
    _make_jpg(src, 300, 450)

    assert await sr.upscale_image(src, dst, sr.SrPreset.REALESR_PHOTO_4X) is False
    hits = [text for text in logs if "海报超分未生效" in text]
    assert len(hits) == 1, f"结论行应只报一次，实际: {hits}"
    assert "Vulkan" in hits[0]


@pytest.mark.asyncio
async def test_maybe_upscale_mixed_black_white_keeps_original(tmp_path, monkeypatch):
    """两次超分分别是黑图/纯白图：必须删产物、保原图、无残留。"""
    poster = tmp_path / "poster.jpg"
    _make_textured_jpg(poster, 300, 450)
    before = poster.read_bytes()
    calls: list[int] = []

    async def fake_upscale(src, dst, preset):
        calls.append(1)
        color = (0, 0, 0) if len(calls) == 1 else (255, 255, 255)
        Image.new("RGB", (1200, 1800), color).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    assert await sr.maybe_upscale_poster(poster) is False
    assert poster.read_bytes() == before, "两次全坏必须保持原始下载图"
    assert [p for p in tmp_path.rglob("*") if "[SR]" in p.name] == [], "超分产物须删除"


@pytest.mark.asyncio
async def test_maybe_upscale_replace_failure_keeps_original(tmp_path, monkeypatch):
    """落盘替换被锁抛错时返回 False 而不是抛异常，原图不动。"""
    import os

    poster = tmp_path / "poster.jpg"
    _make_textured_jpg(poster, 300, 450)
    before = poster.read_bytes()

    async def fake_upscale(src, dst, preset):
        with Image.open(src) as im:
            im.resize((1200, 1800), Image.BICUBIC).save(dst, "JPEG")
        return True

    monkeypatch.setattr(sr, "upscale_image", fake_upscale)
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    assert await sr.maybe_upscale_poster(poster) is False
    assert poster.read_bytes() == before


@pytest.mark.asyncio
async def test_ensure_binary_concurrent_install_single_download(tmp_path, monkeypatch):
    """批刮并发只下载安装一次（_SR_INSTALL_LOCK 防 rmtree/copytree 竞态）。"""
    monkeypatch.setattr(sr, "_TOOL_CHECKSUMS", {})
    calls: list[int] = []

    async def fake_download(url):
        calls.append(1)
        await asyncio.sleep(0.1)
        return _make_tool_zip("realesrgan")

    monkeypatch.setattr(sr, "_download_bytes", fake_download)
    results = await asyncio.gather(*[sr.ensure_binary("realesrgan") for _ in range(5)])
    assert all(r is not None for r in results)
    assert len(calls) == 1, f"5 并发应只下载 1 次，实际 {len(calls)} 次"


def test_run_elevated_timeout_returns_distinct_code(tmp_path, monkeypatch):
    """_run_elevated 超时返回 _TIMEOUT_EXIT_CODE（与二进制失败区分，便于正确上报）。"""
    import subprocess

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(sr.subprocess, "run", boom)
    code, _, _ = sr._run_elevated(["realesrgan-ncnn-vulkan.exe"], str(tmp_path), 1)
    assert code == sr._TIMEOUT_EXIT_CODE


def test_extract_zip_rejects_path_traversal(tmp_path):
    """含 ../绝对路径的包必须拒解、不写出目标外。"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../../evil.txt", b"x")
    dest = tmp_path / "tools" / "realesrgan"
    try:
        sr._extract_zip(buffer.getvalue(), dest)
    except ValueError:
        pass
    else:
        raise AssertionError("非法路径包应抛 ValueError")
    assert not (tmp_path / "evil.txt").exists()


# ── 内置工具「为什么没走内置」必须可诊断（Windows 上看到「📥 首次使用下载」的排查依据）──


def _make_builtin(tool: str = "realesrgan", *, with_binary: bool = True) -> Path:
    """在 `sys._MEIPASS` 下造一份内置工具目录（模拟一体包内容）。"""
    root = sr._builtin_root()
    assert root is not None
    builtin = root / sr._SR_TOOLS_BUNDLE_DIR / tool
    builtin.mkdir(parents=True, exist_ok=True)
    if with_binary:
        (builtin / sr._binary_name(tool)).write_text("#!/bin/sh\nexit 0")
    return builtin


def test_install_from_builtin_reports_reason_codes(tmp_path, monkeypatch):
    """返回 None=成功；否则给出原因码，让调用方能区分「包里没有」与「复制失败」。"""
    dest = tmp_path / "tools" / "realesrgan"

    monkeypatch.delattr(sr.sys, "_MEIPASS", raising=False)
    assert sr._install_from_builtin("realesrgan", dest) == (
        "not_frozen",
        "未打包运行（sys._MEIPASS 为空），本就没有内置工具",
    )

    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    assert sr._install_from_builtin("realesrgan", dest)[0] == "not_bundled"

    _make_builtin(with_binary=False)
    monkeypatch.setattr(sr.log_console, "show_traceback_log", lambda *_a, **_k: None)
    assert sr._install_from_builtin("realesrgan", dest)[0] == "extract_failed"


def test_install_from_builtin_rejects_bundle_without_binary(tmp_path, monkeypatch):
    """空/残缺的内置目录不算释放成功——否则会谎报「✅ 内置就绪」直到执行时才炸。"""
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    monkeypatch.setattr(sr.log_console, "show_traceback_log", lambda *_a, **_k: None)
    _make_builtin(with_binary=False)

    dest = tmp_path / "tools" / "realesrgan"
    reason = sr._install_from_builtin("realesrgan", dest)
    assert reason is not None and reason[0] == "extract_failed"
    assert "缺少可执行文件" in reason[1]


def test_install_from_builtin_succeeds_with_complete_bundle(tmp_path, monkeypatch):
    """正常内置目录：释放成功并落出可执行文件（正向兜住上一条别改过头）。"""
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    _make_builtin(with_binary=True)

    dest = tmp_path / "tools" / "realesrgan"
    assert sr._install_from_builtin("realesrgan", dest) is None
    assert (dest / sr._binary_name("realesrgan")).is_file()


def test_rmtree_force_raises_and_names_blocked_files(tmp_path, monkeypatch):
    """文件被占用时必须抛错并点名，旧的 `ignore_errors=True` 会静默吞掉。

    旧行为下 rmtree 假装删干净 → 紧接着 copytree 抛 FileExistsError →
    内置工具明明在包里却去下载 30-60MB。
    """
    import os

    locked = tmp_path / "tools" / "realesrgan"
    locked.mkdir(parents=True)
    victim = locked / "realesrgan-ncnn-vulkan"
    victim.write_text("busy")

    def boom(*_a, **_k):
        raise PermissionError(13, "另一个程序正在使用此文件")

    monkeypatch.setattr(os, "unlink", boom)
    with pytest.raises(OSError) as err:
        sr._rmtree_force(locked)
    assert "被占用" in str(err.value)
    assert victim.name in str(err.value)


def test_rmtree_force_removes_locked_readonly_file(tmp_path, monkeypatch):
    """只读属性（PyInstaller 从 zip 解出的常见形态）先 chmod 再删，仍应删得掉。"""
    import os
    import stat as stat_mod

    target = tmp_path / "tools" / "realesrgan"
    target.mkdir(parents=True)
    readonly = target / "readme.txt"
    readonly.write_text("x")
    readonly.chmod(0o444)

    real_unlink = os.unlink
    seen: list[int] = []

    def picky_unlink(p, *a, **k):
        if stat_mod.S_ISDIR(os.stat(p).st_mode):
            return real_unlink(p, *a, **k)
        seen.append(1)
        if os.stat(p).st_mode & stat_mod.S_IWUSR:
            return real_unlink(p, *a, **k)
        raise PermissionError(13, "只读文件")

    monkeypatch.setattr(os, "unlink", picky_unlink)
    sr._rmtree_force(target)
    assert seen and not target.exists()


def test_explain_builtin_unavailable_says_why_not_silent(tmp_path, monkeypatch):
    """一体包内缺工具必须打结论日志；源码运行要说明来源；两者都不该是零日志。"""
    logs: list[str] = []
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)

    # 源码运行：不是异常，但要说清「不是包没集成」
    monkeypatch.delattr(sr.sys, "_MEIPASS", raising=False)
    sr._explain_builtin_unavailable("realesrgan", "not_frozen", "")
    assert any("源码运行" in t for t in logs), logs

    # 冻结运行但包内没有工具：打包问题，必须点名并给出包内路径
    mei = tmp_path / "mei"
    mei.mkdir()
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(mei), raising=False)
    monkeypatch.setattr(sr, "_BUILTIN_MISS_REPORTED", False, raising=False)
    logs.clear()
    sr._explain_builtin_unavailable("realesrgan", "not_bundled", "包内缺少 sr_tools/realesrgan")
    assert len(logs) == 1
    assert "sr_tools 目录都不在包内" in logs[0]
    assert str(mei / "sr_tools") in logs[0]


def test_explain_builtin_unavailable_silent_on_macos(tmp_path, monkeypatch):
    """macOS 一体包本就不内嵌，找不到内置不是异常，不能报成打包问题。"""
    logs: list[str] = []
    monkeypatch.setattr(sr, "_PLATFORM", {"darwin": "macos"})
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)

    sr._explain_builtin_unavailable("realesrgan", "not_bundled", "包内缺少 sr_tools/realesrgan")
    assert logs == []
    assert sr._BUILTIN_MISS_REPORTED is False, "未解释就不该置位，否则会吞掉后续真结论"


def test_explain_builtin_unavailable_reported_only_once(tmp_path, monkeypatch):
    """批刮会反复问到，只解释一次。"""
    logs: list[str] = []
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)
    monkeypatch.delattr(sr.sys, "_MEIPASS", raising=False)
    for _ in range(3):
        sr._explain_builtin_unavailable("realesrgan", "not_frozen", "")
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_ensure_binary_logs_real_cause_before_downloading(tmp_path, monkeypatch):
    """下载前必须先说清「为什么没走内置」，否则用户只看到「📥 首次使用下载」。"""
    logs: list[str] = []
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    bundled = (sr._PLATFORM.get(sys.platform) or "") in sr._SR_BUNDLED_PLATFORMS

    async def offline(url):
        raise RuntimeError("offline")

    monkeypatch.setattr(sr, "_download_bytes", offline)
    monkeypatch.setattr(sr, "_SR_DOWNLOAD_ATTEMPTS", 1)
    assert await sr.ensure_binary("realesrgan") is None

    warned = [t for t in logs if "一体包内未找到内置工具" in t]
    assert bool(warned) is bundled, f"内置缺失诊断与平台预期不符: {logs}"
    assert any("首次使用，下载超分工具" in t for t in logs)


@pytest.mark.asyncio
async def test_ensure_binary_reports_copy_failure_reason(tmp_path, monkeypatch):
    """内置在包里却释放失败：真因（文件占用）要同时进 traceback 和最终结论。"""
    logs: list[str] = []
    traces: list[str] = []
    monkeypatch.setattr(sr.log_console, "log_text", logs.append)
    monkeypatch.setattr(sr.log_console, "show_traceback_log", traces.append)
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    _make_builtin(with_binary=True)

    def blocked_copytree(src, dst, **kwargs):
        raise FileExistsError(17, "File exists", str(dst))

    async def offline(url):
        raise RuntimeError("offline")

    monkeypatch.setattr(sr.shutil, "copytree", blocked_copytree)
    monkeypatch.setattr(sr, "_download_bytes", offline)
    monkeypatch.setattr(sr, "_SR_DOWNLOAD_ATTEMPTS", 1)

    assert await sr.ensure_binary("realesrgan") is None
    assert any("内置工具释放失败" in t for t in traces), traces
    assert not any("超分工具就绪（内置）" in t for t in logs), logs
    skip = [t for t in logs if "海报超分未生效" in t]
    assert skip and "内置工具释放失败" in skip[0], f"最终结论应带真因: {logs}"
