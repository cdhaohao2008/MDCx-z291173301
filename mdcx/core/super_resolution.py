"""海报低清超分增强（议题 #26，借鉴 sqzw-x/amane sr 模块设计）。

实现选型（与 amane 一致）：调用 ncnn-vulkan 外部二进制而非打包 torch/ONNX——
- Real-ESRGAN（xinntao v0.2.5.0）与 waifu2x（nihui 20250915）官方 GitHub Release
  的三平台 zip；Windows/Linux 打包版内置，macOS/源码首次使用时按需下载到 userdata/sr/tools/；
- 模型目录随 zip 下发，二进制按自身所在目录解析模型（cwd 设为二进制目录）；
- 全程失败静默降级原图：无 Vulkan 环境/下载失败/超时无输出都不影响刮削结果。

触发策略：`poster_sr_enabled` 默认开；仅当海报最长边 < `poster_sr_max_dim`
（老图/下架图常见 147x200 形态）且开关开启时对落盘海报跑一次超分并原子替换。
"""

import asyncio
import contextlib
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from enum import StrEnum
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from ..config.manager import manager
from ..config.resources import resources
from ..signals import signal

_PRESET_REALESRGAN_MODEL = "realesrgan-x4plus"
_PRESET_WAIFU_MODEL = "upconv_7_photo"

_RELEASE_REALESRGAN = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
_RELEASE_WAIFU2X = "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915"

_PLATFORM = {"darwin": "macos", "linux": "linux", "win32": "windows"}


class SrPreset(StrEnum):
    REALESR_PHOTO_4X = "realesr-photo-4x"
    WAIFU_PHOTO_2X = "waifu-photo-2x"


_PRESET_META: dict[SrPreset, dict[str, object]] = {
    SrPreset.REALESR_PHOTO_4X: {
        "tool": "realesrgan",
        "model": _PRESET_REALESRGAN_MODEL,
        "scale": 4,
        "model_flag": "-n",
    },
    SrPreset.WAIFU_PHOTO_2X: {
        "tool": "waifu2x",
        "model": _PRESET_WAIFU_MODEL,
        "scale": 2,
        "model_flag": "-m",
    },
}

# 各工具 release 资产的平台后缀并不统一：Real-ESRGAN 只发 ubuntu 版，
# 按 linux 拼出的 realesrgan-ncnn-vulkan-20220424-linux.zip 实测 404（Linux 上必然降级）；
# waifu2x 发的才是 linux 版。改资产名时按 tool 单独覆盖，别再统一套 `_PLATFORM`。
_TOOL_ASSET_PLATFORMS: dict[str, dict[str, str]] = {
    "realesrgan": {"macos": "macos", "linux": "ubuntu", "windows": "windows"},
    "waifu2x": {"macos": "macos", "linux": "linux", "windows": "windows"},
}

_ASSET_URL_TEMPLATES: dict[str, str] = {
    "realesrgan": f"{_RELEASE_REALESRGAN}/realesrgan-ncnn-vulkan-20220424-{{}}.zip",
    "waifu2x": f"{_RELEASE_WAIFU2X}/waifu2x-ncnn-vulkan-20250915-{{}}.zip",
}

_TOOL_DOWNLOAD_URLS: dict[str, dict[str, str]] = {
    tool: {platform: template.format(_TOOL_ASSET_PLATFORMS[tool][platform]) for platform in _PLATFORM.values()}
    for tool, template in _ASSET_URL_TEMPLATES.items()
}

# 官方 release zip 的基准 sha256（tool × platform）：按需下载路径用它确认拿到的
# 是官方原包，避免传输中断/被替换的可执行文件被当成可用工具。
# 重新生成（工具版本升级时）：逐个下载 `_TOOL_DOWNLOAD_URLS` 里的官方 URL 后
# `sha256sum <file>`，把结果按下表填回。
_TOOL_CHECKSUMS: dict[str, dict[str, str]] = {
    "realesrgan": {
        "macos": "e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a",
        "linux": "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96",
        "windows": "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
    },
    "waifu2x": {
        "macos": "a5b58b239eb3aa030db5464f6759637fe412d8c07891a4346ea57f708b514d42",
        "linux": "848e0fba55657d34da90b775b8139e9806dc754798b029f95e106ba8850a731f",
        "windows": "7425be94b94e4c8f37a1e433ac0e0100c43790e2c37418f4b65d8235adfbdc87",
    },
}


def _checksum_matches(data: bytes, tool: str, platform: str) -> bool:
    """校验下载内容 sha256 与基准一致；无基准时不拦截，仅靠解压后可执行性兜底。"""
    expected = _TOOL_CHECKSUMS.get(tool, {}).get(platform, "")
    if not expected:
        return True
    return hashlib.sha256(data).hexdigest() == expected


# 本次进程内「超分不可用」结论只报一次（批刮时不逐文件刷屏）
_SR_SKIP_REPORTED = False

# 按需下载超时/重试预算：连不上早点换重试，整体不拖慢批量刮削
_SR_CONNECT_TIMEOUT_SECONDS = 30.0
_SR_DOWNLOAD_TIMEOUT_SECONDS = 120.0
_SR_DOWNLOAD_ATTEMPTS = 2

# 输出尺寸/耗时护栏：低清海报超分正常 <60s；给足余量防卡死批刮任务
_SR_TIMEOUT_SECONDS = 300.0
_SR_MAX_INPUT_BYTES = 8 * 1024 * 1024

# 同一时间只对一张图片进行超分，完成后再进行下一张
_SR_LOCK = asyncio.Lock()

# 工具安装（释放内置/下载解压）串行化：防批刮并发同时下载解压到同一目录
# （此前无锁，5 并发实测触发 10 次下载 + rmtree/copytree 竞态）。
_SR_INSTALL_LOCK = asyncio.Lock()


def _tools_dir() -> Path:
    return resources.u("sr/tools")


# 包内二进制并不叫工具名：两个工具的可执行文件都是 `<tool>-ncnn-vulkan`
# （waifu2x 只是包名带日期后缀）。按工具名去找会永远找不到，
# 表现为「每次都重新下载，然后判定不可用而降级」。
_TOOL_BINARY_STEMS: dict[str, str] = {
    "realesrgan": "realesrgan-ncnn-vulkan",
    "waifu2x": "waifu2x-ncnn-vulkan",
}


def _binary_name(tool: str) -> str:
    stem = _TOOL_BINARY_STEMS[tool]
    return f"{stem}.exe" if sys.platform == "win32" else stem


def binary_path(tool: str) -> Path:
    return _tools_dir() / tool / _binary_name(tool)


def is_binary_ready(tool: str) -> bool:
    path = binary_path(tool)
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def _make_executable(path: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _extract_zip(data: bytes, dest_dir: Path) -> None:
    """ncnn-vulkan 包带一层顶层目录：校验成员路径防 zip-slip 后解压再整体改名到 dest_dir。

    非法路径（绝对路径/`..`）直接抛错拒绝解压；空包抛错。
    （此前 `top = names[0]..` 对 `..` 开头包会把父目录整树复制进目标目录。）
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members:
            raise ValueError("超分工具包为空")
        for m in members:
            if Path(m.filename).is_absolute() or ".." in Path(m.filename).parts:
                raise ValueError(f"工具包内含非法路径，已拒绝解压: {m.filename}")
        firsts = [Path(m.filename).parts[0] for m in members]
        top = firsts[0] if all(p == firsts[0] for p in firsts) else ""
        with tempfile.TemporaryDirectory(dir=dest_dir.parent) as tmp:
            zf.extractall(tmp)
            extracted = Path(tmp) / top if top and (Path(tmp) / top).is_dir() else Path(tmp)
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            shutil.copytree(extracted, dest_dir, dirs_exist_ok=True)
    _make_executable(binary_path_from_dir(dest_dir.name, dest_dir))


def binary_path_from_dir(tool: str, tool_dir: Path) -> Path:
    return tool_dir / _binary_name(tool)


def _builtin_dir(tool: str) -> Path | None:
    """打包体内置的工具目录（仅一体包存在）；源码运行时返回 None。"""
    meipass = getattr(sys, "_MEIPASS", "")
    if not meipass:
        return None
    path = Path(meipass) / "sr_tools" / tool
    return path if path.is_dir() else None


def _install_from_builtin(tool: str, dest_dir: Path) -> bool:
    """把内置工具目录整目录释放到 userdata 缓存目录再使用。

    二进制按自身所在目录解析模型与依赖库，且打包解压目录不保证可写，
    所以必须整目录复制后执行，不能直接在打包体内运行。
    """
    src = _builtin_dir(tool)
    if src is None:
        return False
    try:
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest_dir)
        _make_executable(binary_path_from_dir(tool, dest_dir))
        return True
    except Exception as e:
        signal.show_traceback_log(f"🔶 超分：内置工具释放失败 {tool}: {e}")
        return False


async def _download_bytes(url: str) -> bytes:
    """下载单个源；HTTP 4xx/5xx 错误串带截断响应体，便于排障。"""
    # 工具包约 30-60MB：流式拼接 + 200MB 封顶，恶意/异常 Content-Length 不再整包驻内存后 OOM
    _MAX_BYTES = 200 * 1024 * 1024
    proxy = getattr(manager.config, "proxy", "") or ""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_SR_DOWNLOAD_TIMEOUT_SECONDS, connect=_SR_CONNECT_TIMEOUT_SECONDS),
        follow_redirects=True,
        proxy=proxy or None,
    ) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise RuntimeError(f"HTTP {resp.status_code}: {' '.join(resp.text.split())[:120]}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(1024 * 256):
                total += len(chunk)
                if total > _MAX_BYTES:
                    raise RuntimeError(f"工具包超过大小上限 ({_MAX_BYTES // (1024**2)} MB)，已拒绝: {url}")
                chunks.append(chunk)
            return b"".join(chunks)


def _classify_upscale_failure(output: str) -> str:
    """把二进制失败输出归成人看得懂的原因（缺 Vulkan 设备最常见）。"""
    text = (output or "").lower()
    if "vulkan" in text or "vkcreate" in text or "vkenumerate" in text or "vk_" in text:
        return "未检测到可用的 Vulkan 设备（较老的 Intel 集成显卡或驱动过旧时常见）"
    if "out of memory" in text or "oom" in text:
        return "显存不足"
    return "超分工具执行失败"


def _sr_report_skip(tool: str, reasons: list[str]) -> None:
    """结论行只打一次：开关开着却没效果时，避免每个文件都刷屏。"""
    global _SR_SKIP_REPORTED
    if _SR_SKIP_REPORTED:
        return
    _SR_SKIP_REPORTED = True
    detail = " | ".join(reasons) or "未知原因"
    signal.show_log_text(f"🔴 海报超分未生效：{detail}；后续刮削保持原图，不影响结果")
    signal.show_log_text(f"ℹ️ 可手动下载后解压到: {binary_path(tool)}")


async def ensure_binary(tool: str) -> Path | None:
    """返回可执行文件路径；平台不支持/内置缺失且下载失败返回 None（调用方降级）。"""
    path = binary_path(tool)
    if is_binary_ready(tool):
        return path
    async with _SR_INSTALL_LOCK:
        # 双重检查：等待锁期间可能已有协程完成安装
        if is_binary_ready(tool):
            return path
        platform = _PLATFORM.get(sys.platform) or ""
        url = _TOOL_DOWNLOAD_URLS.get(tool, {}).get(platform)
        if not url:
            _sr_report_skip(tool, [f"当前系统不支持自动下载（{sys.platform}）"])
            return None
        if _install_from_builtin(tool, path.parent):
            signal.show_log_text(f"✅ 超分工具就绪（内置）: {path}")
            return path
        signal.show_log_text(f"📥 首次使用，下载超分工具 {tool}（约 30-60MB，仅一次）...")
        failures: list[str] = []
        for attempt in range(1, _SR_DOWNLOAD_ATTEMPTS + 1):
            try:
                data = await _download_bytes(url)
            except Exception as e:
                failures.append(f"第 {attempt} 次下载失败: {e}")
                continue
            if not _checksum_matches(data, tool, platform):
                failures.append(f"第 {attempt} 次校验不匹配（内容非官方原包）")
                break
            try:
                _extract_zip(data, path.parent)
            except Exception as e:
                failures.append(f"第 {attempt} 次解压失败: {e}")
                break
            if is_binary_ready(tool):
                signal.show_log_text(f"✅ 超分工具就绪: {path}")
                return path
            failures.append(f"第 {attempt} 次解压产物不可执行")
        _sr_report_skip(tool, failures or [f"工具获取失败: {tool}/{platform}"])
        return None


def build_args(src: Path, dst: Path, preset: SrPreset) -> list[str]:
    meta = _PRESET_META[preset]
    cli = ["-i", str(src.absolute()), "-o", str(dst.absolute())]
    cli += [str(meta["model_flag"]), str(meta["model"])]
    cli += ["-s", str(meta["scale"]), "-f", "jpg"]
    return cli


# _run_elevated 超时专用的退出码：与二进制真实失败(-1/非零)区分，
# 调用方据此走"超时"日志分支（与 POSIX 分支文案对齐），而非误报"工具执行失败"。
_TIMEOUT_EXIT_CODE = -2


def _run_elevated(cmd: list[str], cwd: str, timeout: float) -> tuple[int, bytes, bytes]:
    """Windows 专用：隐藏窗口（CREATE_NO_WINDOW / SW_HIDE）执行命令，
    通过临时文件重定向捕获 stdout/stderr。返回 (exit_code, stdout_bytes, stderr_bytes)。
    超时返回 _TIMEOUT_EXIT_CODE，并在 Windows 上尽力 taskkill 残留子进程
    （shell=True 时 subprocess 只能杀掉 cmd 外壳，ncnn 子进程会变孤儿继续占 GPU/写文件）。"""
    stdout_fd, stdout_path = tempfile.mkstemp(suffix="_sr_stdout.log")
    os.close(stdout_fd)
    stderr_fd, stderr_path = tempfile.mkstemp(suffix="_sr_stderr.log")
    os.close(stderr_fd)
    redirect_cmd = f'{subprocess.list2cmdline(cmd)} > "{stdout_path}" 2> "{stderr_path}"'

    # 使用 subprocess 的 CREATE_NO_WINDOW 隐藏窗口，避免弹出 CMD
    # runas 提权由系统处理，不强制要求（避免 UAC 失败导致全部失败）
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        proc = subprocess.run(
            redirect_cmd,
            cwd=cwd,
            timeout=timeout,
            startupinfo=startupinfo,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # 实际 stdout/stderr 通过重定向文件捕获
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = _TIMEOUT_EXIT_CODE
        if sys.platform == "win32" and cmd:
            with contextlib.suppress(Exception):
                subprocess.run(
                    ["taskkill", "/F", "/IM", Path(cmd[0]).name],
                    capture_output=True,
                    timeout=30,
                )
    except Exception:
        exit_code = -1

    stdout_bytes = b""
    stderr_bytes = b""
    try:
        stdout_bytes = Path(stdout_path).read_bytes()
    except Exception:
        pass
    try:
        stderr_bytes = Path(stderr_path).read_bytes()
    except Exception:
        pass
    try:
        os.unlink(stdout_path)
    except Exception:
        pass
    try:
        os.unlink(stderr_path)
    except Exception:
        pass
    return exit_code, stdout_bytes, stderr_bytes


async def upscale_image(src: Path, dst: Path, preset: SrPreset) -> bool:
    """超分单图。任何失败返回 False，不抛出。
    Windows 平台默认隐藏 CMD 窗口（CREATE_NO_WINDOW / SW_HIDE）并以管理员权限（runas）执行；
    其余平台保持原行为。"""
    tool = str(_PRESET_META[preset]["tool"])
    exe = await ensure_binary(tool)
    if exe is None:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with _SR_LOCK:
            if sys.platform == "win32":
                # Windows：隐藏窗口 + 管理员权限执行，通过同步函数封装在异步中
                loop = asyncio.get_running_loop()
                exit_code, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                    None,
                    lambda: _run_elevated(
                        [str(exe), *build_args(src, dst, preset)],
                        str(exe.parent),
                        _SR_TIMEOUT_SECONDS,
                    ),
                )
                stderr_text = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
                stdout_text = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
            else:
                proc = await asyncio.create_subprocess_exec(
                    str(exe),
                    *build_args(src, dst, preset),
                    cwd=str(exe.parent),  # realesrgan 按 CWD 解析模型路径
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=_SR_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    signal.show_traceback_log(f"🔶 超分超时（保持原图）: {src.name}")
                    _sr_report_skip(tool, [f"超分执行超过 {int(_SR_TIMEOUT_SECONDS)} 秒"])
                    return False
                exit_code = proc.returncode
                stderr_text = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
                stdout_text = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
            if exit_code == _TIMEOUT_EXIT_CODE:
                # Windows 分支超时：与 POSIX 分支同文案上报，避免误报"工具执行失败"
                signal.show_traceback_log(f"🔶 超分超时（保持原图）: {src.name}")
                _sr_report_skip(tool, [f"超分执行超过 {int(_SR_TIMEOUT_SECONDS)} 秒"])
                return False
            if exit_code != 0 or not dst.is_file() or dst.stat().st_size == 0:
                output = stderr_text or stdout_text
                signal.show_traceback_log(f"🔶 超分失败（保持原图）: {src.name} {output[:120]}")
                _sr_report_skip(tool, [_classify_upscale_failure(output)])
                return False
            return True
    except Exception as e:
        signal.show_traceback_log(f"🔶 超分异常（保持原图）: {src.name}: {e}")
        return False


def _image_gray_stats(path: Path) -> tuple[float, float, int] | None:
    """64x64 缩略图灰度统计 (mean, std, max)，读失败返回 None。"""
    try:
        with Image.open(path) as img:
            gray = img.convert("L")
            try:
                thumb = gray.resize((64, 64), Image.Resampling.BILINEAR)
            except AttributeError:  # Pillow < 9.1 兼容
                thumb = gray.resize((64, 64), Image.BILINEAR)
            pixels = list(thumb.getdata())
            if not pixels:
                return None
            n = len(pixels)
            mean = sum(pixels) / n
            var = sum((p - mean) ** 2 for p in pixels) / n
            return mean, var**0.5, max(pixels)
    except Exception:
        return None


# 超分产物与原图相似度下限：首超低于此值视为失败，删除并换工具重试一次。
# 以全局 SSIM（0~1）衡量，正常超分缩回原尺寸后一般 0.85+，出口仅拦截 <0.5 的严重偏离。
_SR_SIMILARITY_THRESHOLD = 0.5

# 近纯色判定：灰度标准差小于此值视为纯色/接近纯色（黑/白/纯红等失败产物 std≈0）。
_SR_SOLID_STD = 8.0


def _bilinear() -> int:
    try:
        return Image.Resampling.BILINEAR  # type: ignore[attr-defined]
    except AttributeError:  # Pillow < 9.1 兼容
        return Image.BILINEAR


def _similarity(src: Path, dst: Path) -> float | None:
    """原图与超分产物的内容相似度（全局 SSIM，0~1），失败返回 None。

    把大尺寸产物缩回原图尺寸再比，避免分辨率不同无法直接比较；
    统一缩到 128x128 灰度图上算全局 SSIM，无 numpy/scipy 依赖。
    黑图 vs 正常海报≈0，正常超分一般 0.85+。
    """
    try:
        with Image.open(src) as a, Image.open(dst) as b:
            w, h = a.size
            if w <= 0 or h <= 0:
                return None
            resample = _bilinear()
            ga = a.convert("L").resize((128, 128), resample)
            gb = b.convert("L").resize((w, h), resample).resize((128, 128), resample)
            pa = list(ga.getdata())
            pb = list(gb.getdata())
            if not pa or len(pa) != len(pb):
                return None
            n = len(pa)
            mu_a = sum(pa) / n
            mu_b = sum(pb) / n
            var_a = sum((p - mu_a) ** 2 for p in pa) / n
            var_b = sum((p - mu_b) ** 2 for p in pb) / n
            cov = sum((pa[i] - mu_a) * (pb[i] - mu_b) for i in range(n)) / n
            c1 = (0.01 * 255) ** 2
            c2 = (0.03 * 255) ** 2
            denom = (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
            if denom == 0:
                return 1.0 if cov == 0 else 0.0
            ssim = (2 * mu_a * mu_b + c1) * (2 * cov + c2) / denom
            return max(0.0, min(1.0, ssim))
    except Exception:
        return None


def _is_near_solid(path: Path) -> bool:
    """单文件是否纯色/接近纯色（灰度标准差极小）。"""
    stats = _image_gray_stats(path)
    if stats is None:
        return False
    return stats[1] < _SR_SOLID_STD


def _is_all_black(path: Path) -> bool:
    """检查图片是否全黑/近黑（单文件绝对亮度判定，无原图对照时用）。

    旧阈值 avg<5 只能抓住纯黑，漏掉“接近纯黑（肉眼看不出差别，均值 5~15）”的
    失败产物——这正是线上仍有黑图落盘的原因。现放宽到均值 <16。
    有原图对照的完整判定见 `_upscale_failure_reason`。
    """
    stats = _image_gray_stats(path)
    if stats is None:
        return False
    mean, _, _ = stats
    return mean < 16


def _upscale_failure_reason(src: Path, dst: Path) -> str | None:
    """对照原图判定超分产物是否失败。返回 None 表示通过，否则为失败原因。

    ncnn-vulkan 工具偶发 exit 0 但输出纯黑/近黑（驱动/Vulkan 异常所致，
    重试同工具大概率复现），单靠绝对阈值会漏检“均值略高于旧阈值但相对原图
    亮度崩塌”的情况，故同时做相对亮度/纹理/高光/相似度对照；原图本身就很暗时
    不误判（相对规则要求原图先达到亮度下限）。
    相似度为全局 SSIM（产物缩回原尺寸后比较），正常超分一般 0.85+，
    仅当 <0.5（内容严重偏离）才判失败。
    """
    dst_dim = _image_max_dim(dst)
    src_dim = _image_max_dim(src)
    if dst_dim == 0 or src_dim == 0:
        return "产物无法读取"
    if dst_dim <= src_dim:
        return "产物尺寸未增大"
    src_stats = _image_gray_stats(src)
    dst_stats = _image_gray_stats(dst)
    if dst_stats is None:
        return "产物无法读取"
    if src_stats is None:
        # 原图都读不出（极端情况）：只做绝对黑判定，避免误替换
        return "产物绝对黑" if dst_stats[0] < 16 else None
    mean_src, std_src, max_src = src_stats
    mean_dst, std_dst, max_dst = dst_stats
    if mean_dst < 8:
        return "产物绝对黑"
    if mean_dst < 18 and mean_src > 35:
        return "产物近黑"
    if mean_src > 30 and mean_dst < 0.35 * mean_src:
        return "产物亮度崩塌"
    if std_dst < 6 and std_src > 18:
        return "产物纹理丢失"
    if max_dst < 24 and max_src > 80:
        return "产物高光丢失"
    sim = _similarity(src, dst)
    if sim is not None and sim < _SR_SIMILARITY_THRESHOLD:
        return f"产物相似度过低({sim:.2f})"
    return None


def _hard_failure_reason(src: Path, dst: Path) -> str | None:
    """第二次超分的硬失败判定：仅拦截不可用的产物（尺寸/无法读取/纯黑/近黑/纯色）。

    按策略：二次相似度仍 <50% 也不再丢弃，只要不是纯黑/近黑/纯色就保留。
    原图本身就是纯色时，纯色产物视为正常（不误判）。
    """
    dst_dim = _image_max_dim(dst)
    src_dim = _image_max_dim(src)
    if dst_dim == 0 or src_dim == 0:
        return "产物无法读取"
    if dst_dim <= src_dim:
        return "产物尺寸未增大"
    src_stats = _image_gray_stats(src)
    dst_stats = _image_gray_stats(dst)
    if dst_stats is None:
        return "产物无法读取"
    if src_stats is None:
        return "产物绝对黑" if dst_stats[0] < 16 else None
    mean_src, std_src, _ = src_stats
    mean_dst, std_dst, _ = dst_stats
    if mean_dst < 8:
        return "产物绝对黑"
    if mean_dst < 18 and mean_src > 35:
        return "产物近黑"
    if std_dst < _SR_SOLID_STD and std_src > 15:
        return "产物纯色"
    return None


_FALLBACK_PRESET: dict[SrPreset, SrPreset] = {
    SrPreset.REALESR_PHOTO_4X: SrPreset.WAIFU_PHOTO_2X,
    SrPreset.WAIFU_PHOTO_2X: SrPreset.REALESR_PHOTO_4X,
}


def _image_max_dim(path: Path) -> int:
    try:
        with Image.open(path) as img:
            return max(img.size)
    except Exception:
        return 0


def _sr_trigger_ok(path: Path) -> bool:
    """开关 + 尺寸 + 体积护栏。最长边小于阈值（默认 800）才值得超分。

    阈值定 1200 会把站点默认分辨率（常见高度 450-1200）几乎全部纳入，
    原本够用的封面也要跑一遍 4 倍放大，批刮耗时与落盘体积都明显上升，
    故默认只兜底真正的低清来源（147x200 / 300x450 这类）。
    """
    cfg = manager.config
    if not getattr(cfg, "poster_sr_enabled", False):
        return False
    if not path.is_file():
        return False
    try:
        if path.stat().st_size > _SR_MAX_INPUT_BYTES:
            return False
    except OSError:
        return False
    max_dim = _image_max_dim(path)
    return 0 < max_dim < int(getattr(cfg, "poster_sr_max_dim", 800))


async def maybe_upscale_poster(poster_path: Path) -> bool:
    """刮削收尾钩子：符合条件时对海报超分并原子替换；否则原样返回 False。

    首超产物无效（含相似度<50%）时删除并换另一款工具重试一次
    （同工具黑图多为确定性驱动问题，重试无意义）；
    二次相似度仍<50% 也不再丢弃，只要不是纯黑/近黑/纯色就保留，
    否则弃用并保持原图。
    """
    if not _sr_trigger_ok(poster_path):
        return False
    preset_raw = str(getattr(manager.config, "poster_sr_preset", SrPreset.REALESR_PHOTO_4X))
    try:
        preset = SrPreset(preset_raw)
    except ValueError:
        preset = SrPreset.REALESR_PHOTO_4X
    fallback = _FALLBACK_PRESET[preset]
    tmp = poster_path.with_name(poster_path.stem + ".[SR].jpg")
    retry_tmp = poster_path.with_name(poster_path.stem + ".[SR].retry.jpg")
    try:
        # 第一次超分（二进制失败直接保原图，不换工具重试，避免超时翻倍）
        if not await upscale_image(poster_path, tmp, preset):
            return False
        reason = _upscale_failure_reason(poster_path, tmp)
        if reason is None:
            try:
                os.replace(tmp, poster_path)
            except OSError as e:
                signal.show_traceback_log(f"🔶 超分落盘失败（保持原图）: {poster_path.name}: {e}")
                return False
            signal.show_log_text(f"✨ 海报超分完成: {poster_path.name}")
            return True
        signal.show_traceback_log(f"🔶 超分产物异常（{reason}），删除并换工具重试一次: {poster_path.name}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        # 换另一款工具重试（同工具黑图多为确定性驱动问题，重试无意义）
        if not await upscale_image(poster_path, retry_tmp, fallback):
            signal.show_traceback_log(f"🔶 超分重试失败（保持原图）: {poster_path.name}")
            return False
        hard_reason = _hard_failure_reason(poster_path, retry_tmp)
        if hard_reason is not None:
            signal.show_traceback_log(f"🔶 超分重试仍异常（{hard_reason}），弃用并保持原图: {poster_path.name}")
            return False
        sim = _similarity(poster_path, retry_tmp)
        if sim is not None and sim < _SR_SIMILARITY_THRESHOLD:
            signal.show_log_text(
                f"✨ 海报超分重试完成（相似度{sim:.2f}仍偏低，但非黑/纯色，按策略保留）: {poster_path.name}"
            )
        else:
            signal.show_log_text(f"✨ 海报超分重试完成: {poster_path.name}")
        try:
            os.replace(retry_tmp, poster_path)
        except OSError as e:
            signal.show_traceback_log(f"🔶 超分落盘失败（保持原图）: {poster_path.name}: {e}")
            return False
        return True
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            retry_tmp.unlink(missing_ok=True)
        except OSError:
            pass
