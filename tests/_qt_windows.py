"""在真实 Windows Qt 平台下重跑单个 GUI 用例。

默认测试进程使用 ``QT_QPA_PLATFORM=offscreen``：没有字体、没有 Windows shell，
像素对齐和任务栏 AppUserModelID 都无法验证。这里把这类用例放到子进程里，用
``QT_QPA_PLATFORM=windows`` 重新执行；子进程用环境变量防止递归。非 Windows
平台没有真实窗口系统，仍然跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_in_windows_qt(test_file: str, test_name: str) -> None:
    if sys.platform != "win32":
        pytest.skip("需要真实 Windows 窗口系统")
    if os.environ.get("MDCX_QT_WINDOWS_CHILD") == "1":
        pytest.fail("无法启动 QT_QPA_PLATFORM=windows，像素/任务栏断言不可信")

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "windows"
    env["MDCX_QT_WINDOWS_CHILD"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    node_id = f"{Path(test_file).resolve()}::{test_name}"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", node_id, "-q"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, (
        f"真实 Windows Qt 子进程未通过: {node_id}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
