"""行数对齐（仅内部）：普通窗 15 行演员 + 8 行日志，最大化 20 行 + 10 行。

约束（主界面同款，原生动画零干扰）：只调表行高与 splitter 分配——窗格不锁
`setFixedHeight`、不碰窗口自身几何、不留存快照，`minimumSizeHint` 全程稳定。
离屏可测：视口/行高/日志行高皆为实测值（`isMaximized` 桩驱动最大化档）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTableWidgetItem  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


def _pump(app, n: int = 8):
    for _ in range(n):
        app.processEvents()


def _populated(app, dlg, count: int = 30):
    dlg.table.setRowCount(count)
    for r in range(count):
        dlg.table.setItem(r, 1, QTableWidgetItem(f"actor{r:02d}"))
    app.processEvents()


def _fit_window_height(dlg, app, rows: int, lines: int) -> None:
    """把窗口给到刚好装下 rows 行 + lines 行日志的高度（纯测量，不锁任何东西）。"""
    dlg.resize(1600, 1100)
    app.processEvents()
    t = dlg.table
    log = dlg.log_text
    header_h = t.horizontalHeader().height()
    table_fixed = (dlg._list_widget.height() - t.height()) + header_h + (
        t.height() - header_h - t.viewport().height()
    )
    log_fixed = (dlg._log_widget.height() - log.height()) + (log.height() - log.viewport().height())
    line_h = log.fontMetrics().lineSpacing()
    doc_top = int(log.document().documentMargin())
    base_r = t.verticalHeader().defaultSectionSize()
    need = table_fixed + rows * base_r + log_fixed + doc_top + lines * line_h + dlg._splitter.handleWidth()
    dlg.resize(1600, 1100 + (need - dlg._splitter.height()))
    app.processEvents()


def _full_table_rows(t) -> tuple[int, int]:
    """(完整行数, 视口总高)：从第 0 行累加实际行高，半行/空白都藏不住。"""
    vp = t.viewport().height()
    used, count = 0, 0
    for i in range(t.rowCount()):
        used += t.rowHeight(i)
        if used <= vp:
            count += 1
        else:
            break
    return count, vp


def test_tier_constants():
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog as D

    assert (D.TABLE_VISIBLE_ROWS, D.LOG_VISIBLE_LINES) == (20, 10)
    assert (D.NORMAL_TABLE_ROWS, D.NORMAL_LOG_LINES) == (15, 8)


def test_normal_window_exact_counts(app):
    """普通窗：15 整行演员 + 8 整行日志（用户报障 16.1 行 / 6.1 行）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    try:
        _populated(app, dlg)
        _fit_window_height(dlg, app, 15, 8)
        assert not dlg.isMaximized()
        dlg._fit_visible_rows()
        _pump(app)
        t = dlg.table
        count, vp = _full_table_rows(t)
        assert count == 15, f"表格应恰好 15 整行: 实得 {count} 整行（视口 {vp}）"
        log = dlg.log_text
        want_log = 8 * log.fontMetrics().lineSpacing() + int(log.document().documentMargin())
        assert log.viewport().height() == want_log, (
            f"日志应恰好 8 整行无 peek 无空白: 视口 {log.viewport().height()} vs {want_log}"
        )
    finally:
        dlg.close()
        app.processEvents()


def test_maximized_exact_counts(app):
    """最大化（桩）：20 整行演员 + 10 整行日志（用户报障 21.5 行 / 8.1 行）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    dlg.isMaximized = lambda: True
    try:
        _populated(app, dlg)
        _fit_window_height(dlg, app, 20, 10)
        dlg._fit_visible_rows()
        _pump(app)
        t = dlg.table
        count, vp = _full_table_rows(t)
        assert count == 20, f"表格应恰好 20 整行: 实得 {count} 整行（视口 {vp}）"
        log = dlg.log_text
        want_log = 10 * log.fontMetrics().lineSpacing() + int(log.document().documentMargin())
        assert log.viewport().height() == want_log, (
            f"日志应恰好 10 整行无 peek 无空白: 视口 {log.viewport().height()} vs {want_log}"
        )
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_fit_never_freezes_nor_inflates_minhint(app):
    """对齐后：窗格无冻结、minimumSizeHint 不被抬到窗口高度（动画零干扰的根基）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    try:
        _populated(app, dlg)
        dlg.resize(1600, 1100)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        for w in (dlg._list_widget, dlg._log_widget):
            assert w.minimumHeight() == 0, "窗格不应被锁高"
            assert w.maximumHeight() > 1000, "窗格 maximum 不应被压小"
        assert dlg.minimumSizeHint().height() < dlg.height(), "minimumSizeHint 不应胀到窗口高"
    finally:
        dlg.close()
        app.processEvents()


def test_wide_state_buttons_taller_widths_unchanged(app):
    """最大化（桩）：按钮行统一加高（hint+12），三处定宽按宽态不变，行数仍精确。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    names = [
        "btn_connect",
        "btn_fetch",
        "cmb_fetch_mode",
        "btn_preview",
        "btn_clean",
        "btn_sync",
        "btn_test_source",
        "btn_clear_cache",
        "btn_settings",
    ]
    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    dlg.isMaximized = lambda: True
    try:
        _populated(app, dlg)
        dlg.resize(1920, 1040)
        dlg._deferred_after_resize()
        _pump(app, 20)
        for n in names:
            w = getattr(dlg, n)
            assert w.height() == w.sizeHint().height() + 12, f"{n} 宽态应加高 12px"
        cmb = dlg.cmb_fetch_mode
        assert (cmb.minimumWidth(), cmb.maximumWidth()) == (220, 220), "宽态下拉定宽 220 不变"
        for b in (dlg.btn_clean, dlg.btn_settings):
            assert b.minimumWidth() == 0 and b.maximumWidth() == dlg._HELP_MAX_W, "宽态恢复自适应"
        t = dlg.table
        count, _vp = _full_table_rows(t)
        assert count == 20, f"加高按钮后表格仍应 20 整行: 实得 {count}"
        log = dlg.log_text
        want_log = 10 * log.fontMetrics().lineSpacing() + int(log.document().documentMargin())
        assert log.viewport().height() == want_log, "加高按钮后日志仍应 10 整行"
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_tall_window_log_stays_exact(app):
    """超高窗（桩）：行高按需长高、无封顶撑坏分配，日志仍 10 整行、窗格外无空白。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    dlg.isMaximized = lambda: True
    try:
        _populated(app, dlg)
        for i in range(25):
            dlg.log(f"tall probe {i} " + "X" * 40)
        dlg.resize(1600, 2200)
        _pump(app, 25)
        t = dlg.table
        count, _vp = _full_table_rows(t)
        assert count == 20, f"超高窗表格应 20 整行: 实得 {count}"
        log = dlg.log_text
        want_log = 10 * log.fontMetrics().lineSpacing() + int(log.document().documentMargin())
        assert log.viewport().height() == want_log, (
            f"超高窗日志应 10 整行无下方空白: 视口 {log.viewport().height()} vs {want_log}"
        )
        sp = dlg._splitter
        assert sum(sp.sizes()) == sp.height() - sp.handleWidth(), "窗格分配之和须等于可用高度"
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_user_drag_survives_repopulate(app):
    """用户拖过分隔条：取数重填/直接重对都不抢回；我们自己的 setSizes 不算拖动。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    try:
        _populated(app, dlg)
        dlg.resize(1600, 1100)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        assert dlg._user_moved_splitter is False, "我们自己的 setSizes 不得置位"
        sizes0 = dlg._splitter.sizes()
        # 模拟用户亲手拖动：发信号 + 落尺寸
        dlg._splitter.splitterMoved.emit(100, 1)
        assert dlg._user_moved_splitter is True
        custom = [sizes0[0] + 60, sizes0[1] - 60]
        dlg._splitter.setSizes(custom)
        _pump(app)
        # QSplitter 会按最小值/手柄归一化几 px：以落定值为准，后续断言"不被抢回"。
        custom = dlg._splitter.sizes()
        assert custom != sizes0, "拖动应改变分隔条位置"
        # 取数重填（_populate_table 末尾排队重对）不得抢回
        _populated(app, dlg)
        dlg._populate_table([])
        _pump(app)
        assert dlg._splitter.sizes() == custom, "取数后分隔条应保持拖后位置"
        # 直接重对也不得抢回
        dlg._fit_visible_rows()
        _pump(app)
        assert dlg._splitter.sizes() == custom, "重对不得抢回用户拖动"
    finally:
        dlg.close()
        app.processEvents()
