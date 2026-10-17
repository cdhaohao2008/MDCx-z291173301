"""主窗口轮询定时器在隐藏/关闭时停表、重新显示时复原的回归测试。

回归背景：全量 pytest 会间歇性以 `Windows fatal exception: access violation`
崩在某个用例的 `app.processEvents()` 里。根因链里最上游的一环是
`main_window.py` 上一个 **100ms 热表**（`self.timer`，回调 `show_detail_log` /
`_flush_main_log_queue`，会去 emit 信号刷日志控件），而四个轮询定时器此前
**既没有 `hideEvent` 也没有 `closeEvent` 去停它们**：

- 测试里 40+ 个文件各造一个 `MyMAinWindow`，`deleteLater()` 因
  `processEvents()` 不投递 DeferredDelete 事件而从未生效 ⇒ 窗口全程泄漏；
- 泄漏窗口身上的定时器继续跑 ⇒ 任意后续用例的 `processEvents()` 都会派发
  几百个陈旧回调，摸控件 / 写日志 / 发网络 ⇒ 某次状态不一致就 access violation；
- 而且崩溃位置随缘漂移，看起来像「收尾期」问题，极难定位。

修复要点（两条 Qt 语义坑都在测试里锁住）：

1. **从未 `show()` 过的窗口调 `close()` 不会触发 `hideEvent`**（本来就是
   `WA_WState_Hidden` 态，`setVisible(false)` 直接早退）。所以停表必须同时
   挂在 `hideEvent` 和 `closeEvent` 上——测试文件里绝大多数窗口都只
   `close()` 而没 `show()` 过。
2. **`MyMAinWindow` 是多继承，`closeEvent` 的真正实现在 `WindowOpsMixin` 里**
   （托盘隐藏 / `ready_to_exit`）。在 `MyMAinWindow` 类体里新写 `closeEvent`
   会把它遮蔽成死代码，所以修复是往 `WindowOpsMixin.closeEvent` 开头插调用，
   不是新加 override——第 4 个用例专门锁住这一点。

复原策略是「记住停表前哪些是 active 及其 interval，显示时按记录恢复」，
而不是写死一张间隔表，这样 `timer_scrape`（无固定间隔、由业务流程自己
start/stop）也能正确复原。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

from mdcx.controllers.main_window.window_ops import WindowOpsMixin

_app: QApplication | None = None

# 四个轮询定时器的名字，与 main_window.py 里的创建顺序保持一致。
POLLING_TIMERS = ("timer", "timer_scrape", "timer_update", "timer_remain_task")


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    """造一个**保持定时器运行**的主窗口——本文件要测的就是停表行为本身。

    注意不能复用 `tests/test_window_state_matrix.py` 的同名 fixture：那个
    fixture 构造后立刻把四个表全停了（几何测试不需要定时器回调），在这里
    用会让「停表前是否 active」的前置条件全部落空。
    """
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    yield window
    window._stop_polling_timers()


def _active_timers(win) -> set[str]:
    return {name for name in POLLING_TIMERS if getattr(win, name).isActive()}


def _intervals(win) -> dict[str, int]:
    return {name: getattr(win, name).interval() for name in POLLING_TIMERS}


def test_polling_timers_start_active_so_fixture_precondition_holds(win):
    """前置条件自检：构造完成后四个轮询定时器确实在跑。

    没有这条，后面的「close 之后不再 active」就可能因为「本来就没 active」
    而假绿。注意 `timer_scrape` 不是裸 QTimer 默认不跑——`load_config.py:1110`
    在构造期就会按配置 `start()` 它（`main_window.py:320-321` 只建不启动）。
    """
    assert _active_timers(win) == set(POLLING_TIMERS)


def test_close_without_ever_showing_stops_polling_timers(win):
    """核心修复：从未 show() 过的窗口 close() 也必须停表。

    这正是测试泄漏的那条路径——40+ 个测试文件构造窗口后只 close/deleteLater，
    从不 show()。只挂 hideEvent 的话这里完全不会触发，表会一直跑到进程结束。
    """
    assert _active_timers(win), "前置条件：构造后应有定时器在跑"

    win.close()

    assert _active_timers(win) == set()


def test_hide_stops_and_show_restarts_with_same_intervals(win):
    """隐藏到托盘是正常生产流程，停表后必须能按原间隔起回来。"""
    before = _intervals(win)
    assert _active_timers(win)

    win.hide()
    assert _active_timers(win) == set()

    win.show()
    after_active = _active_timers(win)
    assert "timer" in after_active
    assert "timer_update" in after_active
    assert "timer_remain_task" in after_active
    # 复原后间隔必须与隐藏前逐个一致，不能被写死的默认值覆盖。
    assert {name: _intervals(win)[name] for name in after_active} == {name: before[name] for name in after_active}


def test_timer_scrape_started_by_business_flow_round_trips(win):
    """`timer_scrape` 的间隔由业务配置决定（`load_config.py:1110`），不是写死的。

    停表要按「停之前确实 active」来记，恢复时按记录的 interval 起回来——
    若实现里改成查一张写死的间隔字典，这里就会起错间隔。
    """
    win.timer_scrape.start(777)
    assert "timer_scrape" in _active_timers(win)

    win.hide()
    assert "timer_scrape" not in _active_timers(win)

    win.show()
    assert win.timer_scrape.isActive()
    assert win.timer_scrape.interval() == 777


def test_hide_twice_does_not_lose_the_restore_record(win):
    """连续隐藏两次，第二次已经把表停了，记录不能被清空。

    否则「隐藏 → 隐藏 → 显示」会变成表再也不回来。
    """
    win.hide()
    recorded = list(win._polling_timers_was_active)
    assert recorded, "第一次隐藏应记录下 active 的表"

    win.hide()
    assert list(win._polling_timers_was_active) == recorded


def test_close_event_stays_the_mixin_one(win):
    """不能为了停表在 `MyMAinWindow` 类体里新写 `closeEvent`。

    那会把 `WindowOpsMixin.closeEvent`（托盘隐藏 / `ready_to_exit` 的真正处理器）
    遮蔽成死代码，属于严重回归。这里直接锁住「还是同一个函数对象」，
    并顺带确认 `hideEvent` 确实定义在 `MyMAinWindow` 自己身上（新加的方法）。
    """
    from mdcx.controllers.main_window.main_window import MyMAinWindow

    assert MyMAinWindow.closeEvent is WindowOpsMixin.closeEvent
    assert "hideEvent" in MyMAinWindow.__dict__
    assert "closeEvent" not in MyMAinWindow.__dict__
    assert win.hideEvent is not None


def test_restart_does_not_touch_a_timer_started_while_hidden(win):
    """隐藏期间业务自己 start 的表，显示时不覆盖——以业务为准。"""
    win.hide()
    assert not win.timer_scrape.isActive()

    # 模拟隐藏期间业务流程启动了刮削定时器
    win.timer_scrape.start(1234)

    win.show()

    assert win.timer_scrape.interval() == 1234
