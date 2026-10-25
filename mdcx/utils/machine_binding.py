"""机器绑定：把「导入账单」入口锁在作者这台电脑上（用户 2026-10-26 需求）。

判据是 CPU 编号（Windows ``Win32_Processor.ProcessorId``，形如 ``178BFBFF00A70F41``）。
仓库里只存编号的 SHA-256，不存明文——公开仓库里摆一串机器指纹没必要，哈希足够做等值比较。

取编号要起子进程（``wmic`` 在新系统上已移除，退回 PowerShell 的 ``Get-CimInstance``），
实测 PowerShell 冷启动约 1 秒，**不能在 UI 线程同步调**。故对外分三步：

* :func:`ensure_probe_started` —— 起一次后台探测线程（全进程只起一次）；
* :func:`probe_state` —— 非阻塞读结果，``None`` 表示还在算；
* :func:`is_bound_machine` —— 阻塞版，给「点击时再校验一次」这种不着急的场合用。

调用方（``BillImportMixin``）用 QTimer 轮询 :func:`probe_state`，算完再把按钮显出来。
"""

import hashlib
import os
import re
import subprocess
import threading

# 作者本机的 CPU 编号哈希（SHA-256 of "178BFBFF00A70F41"）。
# 换机器时把新编号的哈希加进来即可；空集合 = 谁都用不了（安全默认）。
_BOUND_CPU_HASHES = frozenset({"bb397a8566e799f0cfbf7564bc71a1322728c9428dea3a6171c9ece751cce376"})

# 子进程超时：CIM 查询在慢机器上偶尔要 3~5 秒，给足余量但仍要能收手
_TIMEOUT_SECONDS = 20
# Windows 下不弹黑框
_NO_WINDOW = 0x08000000

_PROCESSOR_ID_RE = re.compile(r"^[0-9A-Fa-f]{8,}$")

# 用命名元组而不是 `except (A, B):`：ruff 0.17.2 的 formatter 会把括号形式改写成
# Python 2 的 `except A, B:`（本仓 3.15 下语法虽合法，但格式会被反复改写）。
_RUN_ERRORS = (OSError, subprocess.SubprocessError)

_lock = threading.Lock()
# 子进程串行化：多个窗口同时构造时不能各起一个 PowerShell
_probe_lock = threading.Lock()
_cached_id: str | None = None
_cached_bound: bool | None = None
_started = False


def _run_quiet(command: list[str]) -> str:
    """跑一条命令并返回 stdout；任何失败都返回空串（绑定判定不该抛异常）。"""
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
    return completed.stdout or ""


def _from_wmic() -> str:
    """老系统（Win7~Win10 早期）直接有 wmic，最快。"""
    output = _run_quiet(["wmic", "cpu", "get", "ProcessorId"])
    for line in output.splitlines():
        text = line.strip()
        if _PROCESSOR_ID_RE.match(text):
            return text.upper()
    return ""


def _from_powershell() -> str:
    """新系统（Win11 已移除 wmic）走 CIM。"""
    output = _run_quiet(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-CimInstance Win32_Processor).ProcessorId",
        ]
    )
    for line in output.splitlines():
        text = line.strip()
        if _PROCESSOR_ID_RE.match(text):
            return text.upper()
    return ""


def processor_id() -> str:
    """本机 CPU 编号（大写十六进制串）；取不到返回空串。结果进程内缓存。"""
    global _cached_id
    with _lock:
        if _cached_id is not None:
            return _cached_id
    with _probe_lock:
        with _lock:
            if _cached_id is not None:
                return _cached_id
        value = ""
        if os.name == "nt":
            value = _from_wmic() or _from_powershell()
        with _lock:
            _cached_id = value
        return value


def is_bound_machine() -> bool:
    """本机是否在绑定名单里（阻塞）。取不到 CPU 编号时一律 False——宁可不给入口。"""
    global _cached_bound
    with _lock:
        if _cached_bound is not None:
            return _cached_bound
    value = processor_id()
    bound = bool(value) and hashlib.sha256(value.encode()).hexdigest() in _BOUND_CPU_HASHES
    with _lock:
        _cached_bound = bound
        return bound


def probe_state() -> bool | None:
    """后台探测的结果：``True``/``False``，还在算时是 ``None``（非阻塞）。"""
    with _lock:
        return _cached_bound


def ensure_probe_started() -> None:
    """起一次后台探测（全进程只起一次，非阻塞）。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_probe, name="MDCxMachineBindProbe", daemon=True).start()


def _probe() -> None:
    global _cached_bound
    try:
        is_bound_machine()
    except Exception:
        # 探测失败按「未绑定」处理，绝不让异常冒到线程顶层
        with _lock:
            _cached_bound = False
