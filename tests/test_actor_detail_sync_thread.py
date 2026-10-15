"""议题 #175 同源回归：演员详情窗口的同步任务不得再用裸 threading.Thread。

根因：``ActorDetailDialog._run_sync`` 自行拉起 ``threading.Thread``，不继承
``_CancellableWorkerThread``，因此：
  1. 没有 ``abort()``/``cancel()``，``sync_actor`` 卡在网络请求上时无法打断；
  2. 没有登记进统一收尾，窗口 ``WA_DeleteOnClose`` 销毁时线程仍在跑；
  3. 与其余五根工作线程（fetch/preview/sync/clean/source-test）的保命手段脱节。

修复：同步任务改走 ``DetailSyncThread``（``_CancellableWorkerThread`` 子类，
经 ``_run_blocking`` 把阻塞业务函数登记进共享执行器），并给详情窗口补上
与管理器同源的 ``closeEvent``：abort → wait(5000) → 必要时 ``_detach_running_thread``。

本测试同时用 AST 锁死「不再出现裸 threading.Thread」这一回退。
"""

from __future__ import annotations

import ast
import os
import threading
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None
ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "mdcx/tools/emby_actor_manager_ui.py"


def _ensure_app():
    global _app
    _app = QApplication.instance() or QApplication([])
    return _app


def _class_source(class_name: str) -> str:
    tree = ast.parse(UI_PATH.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name)
    return ast.get_source_segment(UI_PATH.read_text(encoding="utf-8"), node) or ""


def _method_node(class_name: str, method: str) -> ast.FunctionDef:
    tree = ast.parse(UI_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return item
    raise AssertionError(f"{class_name}.{method} 未找到")


def _method_source(class_name: str, method: str) -> str:
    src = UI_PATH.read_text(encoding="utf-8")
    return ast.get_source_segment(src, _method_node(class_name, method)) or ""


# ---------------------------------------------------------------- 静态断言


def test_detail_sync_thread_is_a_cancellable_worker():
    """同步线程必须与其余工作线程同源，否则关窗打不断。"""
    tree = ast.parse(UI_PATH.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DetailSyncThread")
    bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
    assert "_CancellableWorkerThread" in bases, "DetailSyncThread 必须继承 _CancellableWorkerThread"


def test_run_sync_no_longer_spawns_bare_thread():
    """回退守卫：同步任务一旦改回裸 threading.Thread，本测试必须红。"""
    node = _method_node("ActorDetailDialog", "_run_sync")
    bare = [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Thread"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "threading"
    ]
    assert not bare, "同步任务不得再绕开可取消的 QThread 框架"
    src = ast.unparse(node)
    assert "DetailSyncThread" in src
    assert "sync_done" in src and "_emit_done" in src, "回写仍须走信号出口 _emit_done"


def test_detail_dialog_has_close_event_shutdown():
    """详情窗口必须像管理器一样在关窗时 abort + wait + 必要时 detach。"""
    src = _method_source("ActorDetailDialog", "closeEvent")
    assert "abort" in src
    assert "wait(" in src
    assert "_detach_running_thread" in src
    assert "super().closeEvent" in src, "closeEvent 不得吞掉基类收尾"


# ---------------------------------------------------------------- 运行期行为


def test_abort_unblocks_hanging_sync_thread(monkeypatch):
    """abort 后 run() 必须在轮询步长内返回，且不发射 sync_done（静默取消）。"""
    _ensure_app()
    from mdcx.tools import emby_actor_manager
    from mdcx.tools.emby_actor_manager_ui import DetailSyncThread

    gate = threading.Event()
    emitted: list[object] = []
    started = threading.Event()

    def _hang(_actor, _sync_type):
        started.set()
        gate.wait()
        return (True, "不应到达")

    # run() 内部是函数级 `from .emby_actor_manager import sync_actor`，
    # 因此打模块属性即可替换，无需改被测源码。
    monkeypatch.setattr(emby_actor_manager, "sync_actor", _hang)

    thread = DetailSyncThread(SimpleNamespace(), "both", None)
    thread.sync_done.connect(emitted.append)
    thread.start()
    assert started.wait(5), "后台任务未启动"
    thread.abort()
    assert thread.wait(5000), "abort 后线程未在 5s 内退出（说明仍在裸等阻塞）"
    assert not emitted, "已取消的任务不得再回写 UI"
    gate.set()


def test_detail_close_event_detaches_unresponsive_thread():
    """关窗遇到卡死的同步线程：必须打断、卸父级并保住引用，避免 WA_DeleteOnClose 拆线程。

    用真实 ActorDetailDialog 实例驱动 closeEvent（而非复述其逻辑），确保护逻辑
    与管理器的收尾同源、且在真实窗口上成立。
    """
    _ensure_app()
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import _ORPHAN_WORKER_THREADS, ActorDetailDialog

    dlg = ActorDetailDialog(ActorInfo(name="测试演员", actor_id="id1", server_id="srv1"))
    hang = _HangThread(dlg)
    hang.start()
    assert hang.wait(20) is False
    dlg._sync_thread = hang
    try:
        dlg.close()
        assert hang.abort_called, "关窗必须先打断同步任务"
        assert hang.parent() is None, "超时后必须卸父级，避免 WA_DeleteOnClose 拆线程"
        assert hang in _ORPHAN_WORKER_THREADS
        assert dlg._sync_thread is None
    finally:
        hang.release()
        hang.wait(2000)
        _ORPHAN_WORKER_THREADS.discard(hang)
        dlg.deleteLater()


def test_detail_close_event_clears_thread_when_it_exits_promptly():
    """同步线程及时退出时不应被 detach（不制造多余孤儿引用）。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import _ORPHAN_WORKER_THREADS, ActorDetailDialog

    dlg = ActorDetailDialog(ActorInfo(name="测试演员", actor_id="id1", server_id="srv1"))
    done = _HangThread(dlg)
    done.release()
    done.start()
    done.wait(2000)
    dlg._sync_thread = done
    try:
        dlg.close()
        assert done.abort_called
        assert done.parent() is dlg, "已结束的线程不必卸父级"
        assert done not in _ORPHAN_WORKER_THREADS
        assert dlg._sync_thread is None
    finally:
        dlg.deleteLater()


class _HangThread(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._gate = threading.Event()
        self.abort_called = False

    def abort(self):
        self.abort_called = True

    def run(self):
        self._gate.wait()

    def release(self):
        self._gate.set()
