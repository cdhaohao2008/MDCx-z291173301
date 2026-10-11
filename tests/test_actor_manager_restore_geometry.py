"""演员管理器窗口几何：最大化/最小化/还原全走系统原生行为（主界面同款）。

行数对齐只许纯内部手段（`_fit_visible_rows` 调行高 + 分隔条分配）：窗格不锁、
窗口几何不动、`minimumSizeHint` 全程稳定。本文件钉住这些不变量。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


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
    try:
        yield dialog
    finally:
        dialog.close()
        app.processEvents()


def _pump(app, n: int = 6):
    for _ in range(n):
        app.processEvents()


def test_no_custom_geometry_machinery(dlg):
    """定制几何机制已删除：无冻结/复位/矩形留存，不过载 changeEvent。"""
    from mdcx.tools import emby_actor_manager_ui as ui_mod

    for name in (
        "_on_window_state_change",
        "_after_state_change",
        "_collapsed_sizes",
        "_on_splitter_moved",
        "_capture_normal_geometry",
        "_schedule_capture_normal_geometry",
        "_visible_rows_target",
        "_apply_conn_extra",
        "_settle_layout",
        "_normal_geometry",
        "_in_state_change",
        "_restoring",
        "_capture_pending",
        "_fitting_rows",
    ):
        assert not hasattr(dlg, name), f"定制几何机制残留: {name}"
    assert "changeEvent" not in ui_mod.EmbyActorManagerDialog.__dict__, "changeEvent 不应再被过载"


def test_panes_never_frozen_and_minhint_stable(dlg, app):
    """缩放 + 事件落定后：窗格不锁高，minimumSizeHint 不被抬到窗口高度。"""
    dlg.resize(1300, 780)
    _pump(app)
    for w in (dlg._list_widget, dlg._log_widget):
        assert w.minimumHeight() == 0, "窗格不应被 setFixedHeight 锁死"
        assert w.maximumHeight() > 1000, "窗格 maximum 不应被压小"
    hint = dlg.minimumSizeHint()
    assert hint.height() < dlg.height(), (
        f"minimumSizeHint 高 {hint.height()} 不应胀到窗口高 {dlg.height()}（旧冻结形态）"
    )


def test_resize_keeps_requested_geometry(dlg, app):
    """resize 按原样落定：无人改窗口几何（旧复位逻辑会钉回存档矩形）。"""
    dlg.resize(1300, 780)
    _pump(app)
    assert (dlg.width(), dlg.height()) == (1300, 780)


def test_splitter_honors_user_drag(dlg, app):
    """分隔条自由拖拽不被顶回：落定后保持，且不可折叠到 0。"""
    assert dlg._splitter.childrenCollapsible() is False
    dlg.resize(1300, 780)
    _pump(app)
    dlg._splitter.setSizes([500, 200])
    _pump(app)
    settled = dlg._splitter.sizes()
    assert sum(settled) > 0
    _pump(app)
    assert dlg._splitter.sizes() == settled, "用户拖的分隔条位置不应被抢回"


def test_minimize_restore_keeps_geometry_and_no_freeze(dlg, app):
    """最小化→还原：几何不变、无冻结（原生行为，旧代码会在此跳变/复位）。"""
    dlg.resize(1300, 780)
    _pump(app)
    before = (dlg.width(), dlg.height())
    dlg.showMinimized()
    _pump(app)
    dlg.showNormal()
    _pump(app)
    assert (dlg.width(), dlg.height()) == before, "最小化还原不应改变窗口尺寸"
    for w in (dlg._list_widget, dlg._log_widget):
        assert w.minimumHeight() == 0, "最小化还原不应引入窗格冻结"
