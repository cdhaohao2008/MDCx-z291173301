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
    """ncnn-vulkan 包带一层顶层目录：解到父目录后整体改名到 dest_dir。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = zf.namelist()
        top = names[0].split("/")[0] if names and "/" in names[0] else ""
        if top:
            with tempfile.TemporaryDirectory(dir=dest_dir.parent) as tmp:
                zf.extractall(tmp)
                extracted = Path(tmp) / top
                if extracted.is_dir():
                    if dest_dir.exists():
                        shutil.rmtree(dest_dir, ignore_errors=True)
                    shutil.copytree(extracted, dest_dir, dirs_exist_ok=True)
        else:
            zf.extractall(dest_dir)
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
    proxy = getattr(manager.config, "proxy", "") or ""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_SR_DOWNLOAD_TIMEOUT_SECONDS, connect=_SR_CONNECT_TIMEOUT_SECONDS),
        follow_redirects=True,
        proxy=proxy or None,
    ) as client:
        resp = await client.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {' '.join(resp.text.split())[:120]}")
        return resp.content


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


def _run_elevated(cmd: list[str], cwd: str, timeout: float) -> tuple[int, bytes, bytes]:
    """Windows 专用：隐藏窗口（CREATE_NO_WINDOW / SW_HIDE）执行命令，
    通过临时文件重定向捕获 stdout/stderr。返回 (exit_code, stdout_bytes, stderr_bytes)。"""
    stdout_path = tempfile.mktemp(suffix="_sr_stdout.log")
    stderr_path = tempfile.mktemp(suffix="_sr_stderr.log")
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
        exit_code = -1
    except Exception as e:
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
            if exit_code != 0 or not dst.is_file() or dst.stat().st_size == 0:
                output = stderr_text or stdout_text
                signal.show_traceback_log(f"🔶 超分失败（保持原图）: {src.name} {output[:120]}")
                _sr_report_skip(tool, [_classify_upscale_failure(output)])
                return False
            return True
    except Exception as e:
        signal.show_traceback_log(f"🔶 超分异常（保持原图）: {src.name}: {e}")
        return False


def _is_all_black(path: Path) -> bool:
    """检查图片是否全黑（像素平均值接近 0），用于判断超分产物是否失败。"""
    try:
        with Image.open(path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            # 使用缩小图快速判断，避免大图耗时
            thumb = img.resize((32, 32))
            pixels = list(thumb.getdata())
            if not pixels:
                return False
            total = sum(sum(p) for p in pixels)
            avg = total / (len(pixels) * 3)
            # 平均值小于 5 视为全黑（允许微小噪声）
            return avg < 5
    except Exception:
        return False


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
    超分完成后检查是否全黑：若全黑则重新超分一次；若仍全黑则删除超分图片直接使用原图片。"""
    if not _sr_trigger_ok(poster_path):
        return False
    preset_raw = str(getattr(manager.config, "poster_sr_preset", SrPreset.REALESR_PHOTO_4X))
    try:
        preset = SrPreset(preset_raw)
    except ValueError:
        preset = SrPreset.REALESR_PHOTO_4X
    tmp = poster_path.with_name(poster_path.stem + ".[SR].jpg")
    retry_tmp = poster_path.with_name(poster_path.stem + ".[SR].retry.jpg")
    try:
        # 第一次超分
        if not await upscale_image(poster_path, tmp, preset):
            return False
        # 检查是否全黑
        if _is_all_black(tmp):
            signal.show_traceback_log(f"🔶 超分产物全黑（可能失败），尝试重新超分一次: {poster_path.name}")
            # 重新超分到不同临时文件
            if await upscale_image(poster_path, retry_tmp, preset):
                if _is_all_black(retry_tmp):
                    # 仍然全黑：删除超分图片，直接使用原图片
                    signal.show_traceback_log(f"🔶 超分重试仍全黑，删除超分产物直接使用原图: {poster_path.name}")
                    try:
                        retry_tmp.unlink(missing_ok=True)
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return False
                else:
                    # 重试成功且非全黑：使用重试结果
                    # 先检查尺寸
                    if _image_max_dim(retry_tmp) <= _image_max_dim(poster_path):
                        signal.show_traceback_log(f"🔶 超分重试产物尺寸未增大，弃用: {poster_path.name}")
                        try:
                            retry_tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                        return False
                    # 替换原图
                    os.replace(retry_tmp, poster_path)
                    signal.show_log_text(f"✨ 海报超分重试完成: {poster_path.name}")
                    return True
            else:
                # 重试失败
                signal.show_traceback_log(f"🔶 超分重试失败（保持原图）: {poster_path.name}")
                return False
        else:
            # 第一次成功且非全黑：继续正常流程
            pass

        # 校验产物确为放大图，防二进制输出异常覆盖原图
        if _image_max_dim(tmp) <= _image_max_dim(poster_path):
            signal.show_traceback_log(f"🔶 超分产物尺寸未增大，弃用: {poster_path.name}")
            return False
        os.replace(tmp, poster_path)
        signal.show_log_text(f"✨ 海报超分完成: {poster_path.name}")
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
