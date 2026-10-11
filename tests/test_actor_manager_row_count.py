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
