"""演员管理工具窗口几何：最大化/最小化/还原全走系统原生行为（主界面同款）。

行数对齐只许纯内部手段（`_fit_visible_rows` 调行高 + 分隔条分配）：窗格不锁、
不留存几何存档、`minimumSizeHint` 全程稳定。本文件钉住这些不变量。

唯一允许的窗口几何干预是**宽度自适应**：`_narrow_min_width` 实测两行态最宽并作为
对话框最小宽（`_apply_narrow_min_width`），最大化/全屏还原回窄态时 `_shrink_narrow_width`
按内容宽再贴合一次。感知「最大化→还原」必须过 `changeEvent`，故它不再属于被禁项——
本文件禁的是**存档矩形与复位**（旧设计会把用户拖动的几何钉回存档值），见
`test_no_custom_geometry_machinery`。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog  # noqa: E402


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
    """定制几何机制已删除：无冻结/复位/矩形留存。

    窗口宽度自适应（`_narrow_min_width` / `_shrink_narrow_width`）必须感知
    「最大化 → 还原」这一拍，所以 `changeEvent` 允许存在，且只触发一次按内容宽贴合。
    但它**不得**留存任何存档矩形把用户拖动的几何钉回去——旧设计正是这么干的。
    """
    from PyQt6.QtCore import QRect

    from mdcx.tools import emby_actor_manager_ui as ui_mod

    for name in (
        "_on_window_state_change",
        "_after_state_change",
        "_collapsed_sizes",
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
    # 用户拖动允许且必须存在（拖后本次打开不再自动重排，数据源测试窗同款）。
    assert callable(getattr(dlg, "_on_splitter_moved", None))
    # 存档矩形不得以任何形式留在实例状态里（changeEvent 存在也不许破例）。
    archived = sorted(k for k, v in vars(dlg).items() if isinstance(v, QRect))
    assert not archived, f"窗口几何存档残留: {archived}"
    assert ui_mod.EmbyActorManagerDialog._BASE_MIN_W > 0


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
    """resize 按原样落定：无人改窗口几何（旧复位逻辑会钉回存档矩形）。

    对话框按内容实测强制一个最小宽（`_narrow_min_width`，≈1392），窄于它的 resize
    会被 Qt 顶回下限——那是刻意设计，不是「被改几何」。所以这里从下限之上取值，
    断言请求值逐像素落定，专门盯旧复位逻辑。
    """
    floor = dlg.minimumWidth()
    assert floor >= EmbyActorManagerDialog._NARROW_MIN_W_FLOOR
    w = floor + 120
    dlg.resize(w, 780)
    _pump(app)
    assert (dlg.width(), dlg.height()) == (w, 780)
    # 窄于下限时被顶回下限，且高度仍按请求落定。
    dlg.resize(1300, 780)
    _pump(app)
    assert (dlg.width(), dlg.height()) == (floor, 780)


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
