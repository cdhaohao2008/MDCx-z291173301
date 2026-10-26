"""设备编号：读本机唯一的设备标识，供设置页「设备编号」按钮导出成 txt（用户 2026-10-26 需求）。

各系统的取值口径与系统自带「关于」页一致：

* Windows 11 —— 设置 → 系统 → 关于 → **设备 ID**，即注册表
  ``HKLM\\SOFTWARE\\Microsoft\\SQMClient`` 的 ``MachineId``（形如
  ``{8B03AEC9-7C26-4CA6-973D-1A4FFC028576}``，带花括号，与系统页逐字相同）；
  读不到时退回 ``Cryptography\\MachineGuid``，再退回 DMI 的
  ``Win32_ComputerSystemProduct.UUID``。
* macOS —— 系统信息 → 硬件概览的「硬件 UUID」，即 ``ioreg`` 的 ``IOPlatformUUID``；
  取不到再退回 ``system_profiler`` 的 Hardware UUID。
* Linux / Ubuntu —— ``/etc/machine-id``（安装级唯一），退回 ``/var/lib/dbus/machine-id``
  与 ``/sys/class/dmi/id/product_uuid``。

全部是本地读取（注册表 / 读文件 / 一次轻量子进程），**不联网**；结果进程内缓存，
按钮点多少次都只算一次。
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from datetime import datetime
from functools import cache
from pathlib import Path

# 子进程超时：ioreg / system_profiler 在慢机器上偶尔要几秒，给足余量但仍能收手
_TIMEOUT_SECONDS = 20
# Windows 下不弹黑框
_NO_WINDOW = 0x08000000

# 用命名元组而不是 `except (A, B):`：ruff 0.17.2 的 formatter 会把括号形式改写成
# Python 2 的 `except A, B:`（本仓 3.15 下语法虽合法，但格式会被反复改写）。
_RUN_ERRORS = (OSError, subprocess.SubprocessError)

# Windows 设备 ID 的读取顺序：第一项就是「设置 → 系统 → 关于 → 设备 ID」那个值
_WINDOWS_ID_KEYS = (
    (r"SOFTWARE\Microsoft\SQMClient", "MachineId"),
    (r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"),
)
_WINDOWS_VERSION_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

# Win11 从 22000 起；注册表里的 ProductName 在 Win11 上仍写着 "Windows 10"
_WINDOWS_11_MIN_BUILD = 22000

_IO_PLATFORM_UUID_RE = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')

# Linux 上的候选文件，按可信度排序
_LINUX_ID_FILES = (
    "/etc/machine-id",
    "/var/lib/dbus/machine-id",
    "/sys/class/dmi/id/product_uuid",
)


def _run(command: list[str]) -> str:
    """跑一条命令并返回 stdout；任何失败都返回空串（取编号不该抛异常）。"""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            creationflags=_NO_WINDOW if os.name == "nt" else 0,
        )
    except _RUN_ERRORS:
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _read_registry(path: str, name: str) -> str:
    """读 HKLM 下的字符串值；不存在 / 无权限 / 非 Windows 一律返回空串。"""
    try:
        import winreg
    except ImportError:
        return ""
    # 32 位 Python 默认被重定向到 Wow6432Node，故先按 64 位视图读、再退回默认视图
    for extra in (winreg.KEY_WOW64_64KEY, 0):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | extra) as key:
                value, _kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        text = str(value).strip() if value else ""
        if text:
            return text
    return ""


def _windows_device_id() -> str:
    for path, name in _WINDOWS_ID_KEYS:
        value = _read_registry(path, name)
        if value:
            return value
    # 两条注册表都读不到（极罕见）才起子进程问 DMI 的整机 UUID
    output = _run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
        ]
    )
    return output.splitlines()[0].strip() if output else ""


def _macos_device_id() -> str:
    output = _run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
    match = _IO_PLATFORM_UUID_RE.search(output)
    if match:
        return match.group(1).strip()
    # 老系统 / ioreg 被裁掉时退回 system_profiler 的「硬件 UUID」
    for line in _run(["system_profiler", "SPHardwareDataType"]).splitlines():
        text = line.strip()
        if text.lower().startswith("hardware uuid:"):
            return text.split(":", 1)[1].strip()
    return ""


def _linux_device_id() -> str:
    for name in _LINUX_ID_FILES:
        try:
            text = Path(name).read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if text:
            return text
    return ""


@cache
def device_id() -> str:
    """本机设备编号；取不到返回空串（调用方负责提示用户）。结果进程内缓存。"""
    system = platform.system()
    if system == "Windows":
        return _windows_device_id()
    if system == "Darwin":
        return _macos_device_id()
    return _linux_device_id()


def _windows_system_name() -> str:
    product = _read_registry(_WINDOWS_VERSION_KEY, "ProductName") or "Windows"
    display = _read_registry(_WINDOWS_VERSION_KEY, "DisplayVersion")
    build = _read_registry(_WINDOWS_VERSION_KEY, "CurrentBuildNumber") or _read_registry(
        _WINDOWS_VERSION_KEY, "CurrentBuild"
    )
    # Win11 的 ProductName 仍是「Windows 10 专业版」，按 build 号纠正成 11
    if build.isdigit() and int(build) >= _WINDOWS_11_MIN_BUILD and product.startswith("Windows 10"):
        product = "Windows 11" + product[len("Windows 10") :]
    parts = [product]
    if display:
        parts.append(display)
    if build:
        parts.append(f"Build {build}")
    return " ".join(parts)


def _linux_pretty_name() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


@cache
def system_name() -> str:
    """系统名称（给人看的版本串，例如 ``Windows 11 专业版 24H2 Build 26100``）。"""
    system = platform.system()
    if system == "Windows":
        return _windows_system_name()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    return _linux_pretty_name() or f"{system} {platform.release()}".strip()


def build_report() -> str:
    """导出到 txt 的正文：第一行就是设备编号，后面几行供排查时对照。"""
    lines = [
        f"设备编号：{device_id()}",
        f"系统：{system_name()}",
        f"计算机名：{platform.node()}",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
    ]
    return "\n".join(lines) + "\n"
