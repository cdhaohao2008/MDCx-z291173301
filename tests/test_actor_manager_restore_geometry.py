"""议题 #176：演员管理器最大化后再还原，窗口尺寸必须回到默认（普通态）尺寸。

根因：`_fit_visible_rows` 为把演员表对齐到 20 整行，会用 `setFixedHeight` 锁死
上下两个分割窗格；窗格按最大化高度锁死后，对话框的 `minimumSizeHint` 被抬到接近
最大化高度（宽亦然）。此时点还原，Windows 把还原矩形按这个被抬大的最小尺寸钳位，
窗口就以最大化的尺寸回来——底部越过屏幕边界（用户截图即此形态）。

修法：普通态矩形持续留存（`_normal_geometry`，最大化期间的 resize 不得写入），
从最大化还原时①先解除 fit 冻结、②再把矩形复位回普通态尺寸，且复位前按屏幕可用区
夹一次，任何情况下都不越界。

离屏环境造不出真 maximize/restore 的事件序列，用例直接驱动 `_on_window_state_change`
并用桩把最大化阶段的 `isMaximized()` 置真——这正是真实运行时让采样跳过的那个判据；
钉的仍是真实的钳位形态（窗口带着最大化尺寸、窗格被 fit 冻结）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


class _FakeStateChange:
    """只带 oldState() 的 WindowStateChange 替身（离屏下造不出真事件）。"""

    def __init__(self, old_state: Qt.WindowState):
        self._old_state = old_state

    def oldState(self) -> Qt.WindowState:
        return self._old_state


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


@pytest.fixture
def dlg(app):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dialog = EmbyActorManagerDialog()
    dialog.show()
    app.processEvents()
    dialog._schedule_capture_normal_geometry()
    app.processEvents()
    try:
        yield dialog
    finally:
        dialog.close()
        app.processEvents()


def _freeze_panes_as_maximized(dialog):
    """复刻最大化态 `_fit_visible_rows` 的冻结：窗格按当前（最大化的）分割区高度锁死。

    这正是把 `minimumSizeHint` 抬到最大化高度、把还原矩形顶出屏幕的那一步。
    """
    dialog._list_widget.setFixedHeight(dialog._list_widget.height())
    dialog._log_widget.setFixedHeight(dialog._log_widget.height())


def _maximize_phase(dialog, app, width: int, height: int):
    """模拟最大化阶段：窗口撑到最大化尺寸 + 窗格被 fit 冻结。

    冻结放在 resize 之后：最大化那几帧的 `_fit_visible_rows` 会自己按最大化高度
    重新锁一次窗格，离屏下塞不下 20 行则改为解除冻结——放在 resize 之后才能稳定
    复刻「带着冻结进还原」的真实形态。

    期间把 `isMaximized()` 置真——最大化中的 resize 绝不能被记成普通态矩形，
    否则还原就没有「回到默认尺寸」的基准了。
    """
    real = dialog.isMaximized
    dialog.isMaximized = lambda: True
    try:
        dialog.resize(width, height)
        app.processEvents()
        _freeze_panes_as_maximized(dialog)
    finally:
        dialog.isMaximized = real
    app.processEvents()
    for w in (dialog._list_widget, dialog._log_widget):
        assert w.minimumHeight() == w.maximumHeight() > 0, "前置条件：窗格应处于 fit 冻结态"


def _restore_phase(dialog, app):
    """模拟「从最大化点还原」。"""
    dialog._on_window_state_change(_FakeStateChange(Qt.WindowState.WindowMaximized))
    for _ in range(6):
        app.processEvents()


def _expected_restored(dialog) -> tuple[int, int]:
    """还原后应达到的尺寸：存下来的普通态尺寸，按屏幕可用区与窗口最小尺寸各夹一次。"""
    avail = dialog.screen().availableGeometry()
    stored = dialog._normal_geometry
    return (
        max(dialog.minimumWidth(), min(stored.width(), avail.width())),
        max(dialog.minimumHeight(), min(stored.height(), avail.height())),
    )


def test_normal_geometry_is_seeded_and_tracks_resize(dlg, app):
    """普通态矩形在构造时就有初值，并随用户拖拽更新。"""
    stored = dlg._normal_geometry
    assert stored is not None and stored.isValid()
    assert (stored.width(), stored.height()) == (dlg.width(), dlg.height())

    dlg.resize(1300, 780)
    app.processEvents()
    dlg._schedule_capture_normal_geometry()
    app.processEvents()
    assert (dlg._normal_geometry.width(), dlg._normal_geometry.height()) == (1300, 780)


def test_restore_returns_to_default_size_despite_inflated_minimum(dlg, app):
    """核心回归：窗格按最大化高度冻结、窗口被系统钳位后，还原仍回到默认尺寸。"""
    default = (dlg._normal_geometry.width(), dlg._normal_geometry.height())
    assert default == (dlg.width(), dlg.height())

    # ① 最大化：窗格按最大化高度锁死，窗口撑大
    _maximize_phase(dlg, app, 1500, 1000)
    assert (dlg.width(), dlg.height()) != default, "前置条件：窗口应已被钳大"

    # ② 还原
    _restore_phase(dlg, app)
    assert (dlg.width(), dlg.height()) == _expected_restored(dlg), (
        f"还原后未回到默认尺寸: {dlg.geometry().getRect()} vs 期望 {_expected_restored(dlg)}"
    )
    assert dlg.height() < 1000, "还原后高度必须小于最大化高度（底部不得越界）"

    # ③ 冻结必须解除，否则最小尺寸一直被胀着、下次还原仍被钳
    for w in (dlg._list_widget, dlg._log_widget):
        assert w.minimumHeight() == 0
        assert w.maximumHeight() > 1000


def test_restore_keeps_user_resized_size(dlg, app):
    """用户自己拖过尺寸后，最大化再还原回到他拖的尺寸，不是启动默认值。"""
    dlg.resize(1300, 780)
    app.processEvents()
    dlg._schedule_capture_normal_geometry()
    app.processEvents()

    _maximize_phase(dlg, app, 1500, 1000)
    _restore_phase(dlg, app)
    assert (dlg.width(), dlg.height()) == _expected_restored(dlg)
    assert dlg._normal_geometry.height() == 780, "用户拖过的高度应被保留为还原基准"


def test_restore_is_idempotent_across_rounds(dlg, app):
    """反复最大化/还原不得逐轮漂移——采样不能把系统钳位后的矩形当成普通态存下。"""
    dlg.resize(1300, 780)
    app.processEvents()
    dlg._schedule_capture_normal_geometry()
    app.processEvents()

    for i in range(3):
        _maximize_phase(dlg, app, 1500, 1000)
        _restore_phase(dlg, app)
        assert (dlg.width(), dlg.height()) == _expected_restored(dlg), f"第 {i} 轮漂移"
        assert dlg._normal_geometry.height() == 780, f"第 {i} 轮基准被污染"


def test_restore_never_exceeds_screen_available_area(dlg, app):
    """存下来的矩形比屏幕还大时（换过分辨率 / 拔过副屏），还原也不越界。"""
    from PyQt6.QtCore import QRect

    screen = dlg.screen()
    if screen is None:
        pytest.skip("离屏环境无屏幕信息")
    avail = screen.availableGeometry()
    dlg._normal_geometry = QRect(0, 0, avail.width() * 3, avail.height() * 3)

    _restore_phase(dlg, app)
    want_w = max(dlg.minimumWidth(), avail.width())
    want_h = max(dlg.minimumHeight(), avail.height())
    assert (dlg.width(), dlg.height()) == (want_w, want_h)
    assert dlg.height() <= max(avail.height(), dlg.minimumHeight())


def test_entering_maximized_does_not_overwrite_normal_geometry(dlg, app):
    """进入最大化不得覆盖普通态矩形（否则还原就没有基准了）。

    窗口管理器「先发尺寸、后发状态」：resizeEvent 到达时 isMaximized() 还是旧值，
    故采样必须延迟一帧——这里钉的正是延迟后 isMaximized() 才为真的那一拍。
    """
    dlg.resize(1300, 780)
    app.processEvents()
    dlg._schedule_capture_normal_geometry()
    app.processEvents()

    real = dlg.isMaximized
    dlg.isMaximized = lambda: True
    try:
        for _ in range(4):
            app.processEvents()
    finally:
        dlg.isMaximized = real
    assert (dlg._normal_geometry.width(), dlg._normal_geometry.height()) == (1300, 780)


def test_state_change_from_minimize_does_not_restore_geometry(dlg, app):
    """非「从最大化还原」的状态变更不得动几何（最小化还原走 Qt 自身逻辑）。"""
    before = (dlg.width(), dlg.height())
    _freeze_panes_as_maximized(dlg)
    dlg._on_window_state_change(_FakeStateChange(Qt.WindowState.WindowMinimized))
    for _ in range(4):
        app.processEvents()
    assert (dlg.width(), dlg.height()) == before
    # 冻结只在最大化还原时解除
    assert dlg._list_widget.minimumHeight() > 0