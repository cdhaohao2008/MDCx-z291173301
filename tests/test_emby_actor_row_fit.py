"""整行对齐回归双档：最大化 20 整行演员 + 10 整行日志，普通窗 15 整行 + 8 整行。

背景：收紧边距 + splitter 4:1 后，最大化时表格显示 21.5 行（末行半截），
日志只剩约 7 行。现 `_fit_visible_rows` 按窗口状态取行数目标（最大化 20/10、
普通窗 15/8）把高度差均摊到行高上（±1~2px），余数垫在日志底部视口边距里，
两处都不出现半行。离屏造不出真 maximize/resize 事件序列，最大化一律用
`isMaximized` 桩驱动（与 `test_actor_manager_restore_geometry.py` 同手法）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


class _StateChange(QEvent):
    """带 oldState() 的 WindowStateChange 替身（离屏下造不出真事件）。"""

    def __init__(self, old_state: Qt.WindowState):
        super().__init__(QEvent.Type.WindowStateChange)
        self._old_state = old_state

    def oldState(self) -> Qt.WindowState:
        return self._old_state


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


def _populated(app):
    """带 30 个演员的对话框：冻结自动对齐，测量点由用例手动控制。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    actors = [ActorInfo(name=f"演员{i:02d}", actor_id=str(i), server_id="s") for i in range(30)]
    for a in actors:
        a.existing_overview = "简介"
        a.has_overview = True
        a.has_image = True
    dlg._actors = actors
    dlg._fitting_rows = True  # 冻结自动对齐，手动控制测量点
    dlg.show()
    app.processEvents()
    dlg._populate_table(actors)
    app.processEvents()
    return dlg


def _fit_window_height(dlg, app, rows: int, lines: int) -> None:
    """把窗口给到「刚好装下 rows 行演员 + lines 行日志」的高度（冻结自动对齐，测量点手动）。"""
    dlg._fitting_rows = True
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
    dlg._fitting_rows = False


def _as_maximized(dlg):
    """把 isMaximized() 置真（离屏造不出真最大化，桩驱动最大化分支）。"""
    real = dlg.isMaximized
    dlg.isMaximized = lambda: True
    return lambda: setattr(dlg, "isMaximized", real)


def _assert_tier(dlg, rows: int, lines: int) -> None:
    """表格不多不少 rows 整行、日志 lines 整行且底部无空白垫。"""
    t = dlg.table
    log = dlg.log_text
    line_h = log.fontMetrics().lineSpacing()
    doc_top = int(log.document().documentMargin())
    assert t.viewport().height() == rows * t.rowHeight(0), (
        f"表格应恰好 {rows} 整行: 视口 {t.viewport().height()} vs {rows}×{t.rowHeight(0)}"
    )
    assert log.viewport().height() == lines * line_h + doc_top, (
        f"日志应恰好 {lines} 整行: 视口 {log.viewport().height()} vs {lines * line_h + doc_top}"
    )
    assert log.viewportMargins().bottom() == 0, "无空白垫"


def test_fit_constants_are_20_and_10():
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    assert EmbyActorManagerDialog.TABLE_VISIBLE_ROWS == 20
    assert EmbyActorManagerDialog.LOG_VISIBLE_LINES == 10
    # 普通窗双档：15 演员 + 8 日志
    assert EmbyActorManagerDialog.NORMAL_TABLE_ROWS == 15
    assert EmbyActorManagerDialog.NORMAL_LOG_LINES == 8


def test_fit_caps_absorb_surplus_not_pad():
    """富余必须被行高/连接组吸收，而不是留成空白——日志侧高不低于 10 行 + 顶边距。

    行高封顶与连接组封顶之和要足够大：1080p/9pt 富余约 140px、
    1440p/12pt 富余约 500px，两者都应能全吸收（不出现日志底部空白）。
    """
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    cap = EmbyActorManagerDialog.ROW_GROW_CAP * EmbyActorManagerDialog.TABLE_VISIBLE_ROWS
    cap += EmbyActorManagerDialog.CONN_EXTRA_CAP
    assert cap >= 500, f"富余吸收能力不足（{cap}px），超大屏日志底部会留空白"
    assert EmbyActorManagerDialog.LOG_VISIBLE_LINES * 15 < cap  # 10 行日志高远小于吸收能力


@pytest.mark.parametrize(
    ("maximized", "rows", "lines"),
    [(False, 15, 8), (True, 20, 10)],
    ids=["normal-15-8", "maximized-20-10"],
)
def test_visible_rows_target_by_state(app, maximized, rows, lines):
    """行数目标严格按窗口状态切换：最大化 20/10，其余一律 15/8。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    app.processEvents()
    try:
        assert dlg._visible_rows_target() == (15, 8)  # 默认非最大化
        restore = None
        if maximized:
            restore = _as_maximized(dlg)
        try:
            assert dlg._visible_rows_target() == (rows, lines)
        finally:
            if restore is not None:
                restore()
        assert dlg._visible_rows_target() == (15, 8)
    finally:
        dlg.close()
        app.processEvents()


def test_maximized_fit_gives_full_rows_only(app):
    """集成：表格不多不少 20 整行，日志 10 整行且底部无空白垫。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = _populated(app)
    try:
        # 先算出刚好装下 20 行 + 10 行的对话框高度，验证主路径精确性
        _fit_window_height(dlg, app, 20, 10)
        dlg._fitting_rows = False
        restore = _as_maximized(dlg)
        try:
            dlg._fit_visible_rows()
        finally:
            restore()
        app.processEvents()
        _assert_tier(dlg, 20, 10)
        assert dlg._conn_grid.contentsMargins().top() == 4  # 无富余，连接组保持基准
        log = dlg.log_text
        line_h = log.fontMetrics().lineSpacing()
        # 最小高度按普通窗档（8 行）给：最大化目标 10 行高于该下限，小窗也不被压扁
        assert log.minimumHeight() >= EmbyActorManagerDialog.NORMAL_LOG_LINES * line_h
        # 长日志行随后冒出横向滚动条：Show 事件重对后 10 行不被盖、表格仍是 20 整行
        for i in range(12):
            log.appendPlainText(f"[{i:02d}] " + "长日志行_" * 120)
        for _ in range(4):
            app.processEvents()
        restore = _as_maximized(dlg)
        try:
            dlg._fit_visible_rows()  # 事件级联后直接再对一次，结果确定
        finally:
            restore()
        app.processEvents()
        _assert_tier(dlg, 20, 10)
    finally:
        dlg.close()
        app.processEvents()


def test_normal_fit_gives_15_rows_and_8_log_lines(app):
    """集成：普通窗（非最大化）表格恰好 15 整行、日志恰好 8 整行，无空白垫。"""
    dlg = _populated(app)
    try:
        _fit_window_height(dlg, app, 15, 8)
        assert not dlg.isMaximized()
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)
        # 窗口再长高（普通态）：行数目标不变，仍 15/8（行高按富余上浮，封顶 ROW_GROW_CAP）
        dlg._fitting_rows = True
        dlg.resize(1600, 1400)
        app.processEvents()
        dlg._fitting_rows = False
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)
        # 长日志行冒出横向滚动条后重对，仍是 15/8
        log = dlg.log_text
        for i in range(12):
            log.appendPlainText(f"[{i:02d}] " + "长日志行_" * 120)
        for _ in range(4):
            app.processEvents()
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)
    finally:
        dlg.close()
        app.processEvents()


def test_state_change_refits_between_tiers(app):
    """最大化↔普通切换后必须按新状态重对（20/10 ↔ 15/8）。

    窗口管理器可能「先发尺寸、后发状态」：resizeEvent 到达时 isMaximized()
    还是旧值，只靠 resize 排的对齐会停在旧档。changeEvent 里 state 已是新值，
    等一帧布局落定后必须再对一次。
    """
    dlg = _populated(app)
    try:
        _fit_window_height(dlg, app, 15, 8)
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)

        # ① 最大化：窗口已按最大化尺寸撑大 + 状态位翻真 → changeEvent 排出 fit → 20/10
        dlg._normal_geometry = dlg.geometry()
        dlg._fitting_rows = True
        dlg.resize(1600, 1400)
        app.processEvents()
        dlg._fitting_rows = False
        restore = _as_maximized(dlg)
        try:
            dlg.changeEvent(_StateChange(Qt.WindowState.WindowNoState))
            app.processEvents()
        finally:
            restore()
        _assert_tier(dlg, 20, 10)

        # ② 还原：oldState=Maximized → _on_window_state_change 复位几何，fit 回 15/8
        dlg._normal_geometry = dlg.geometry()
        dlg._fitting_rows = True
        dlg.resize(1600, 1400)
        app.processEvents()
        dlg._fitting_rows = False
        dlg.changeEvent(_StateChange(Qt.WindowState.WindowMaximized))
        app.processEvents()
        _fit_window_height(dlg, app, 15, 8)
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)
    finally:
        dlg.close()
        app.processEvents()


def test_growing_window_while_frozen_keeps_layout(app):
    """普通档冻结后窗口再撑大：分割区必须跟着长，连接组/状态栏不得被撑变形。

    根因：窗格 setFixedHeight 锁死时 QSplitter 的 maximum 被压到「两窗格固定高
    之和」，窗口即便拉大分割区也不长——多出的高度被连接组/状态栏吸走
    （实测连接组 89→206px、状态栏 22→205px，且不会自己缩回去）。
    resizeEvent 先 _collapsed_sizes() 再让新尺寸落布局即可避免。
    连接组允许长高，但只许走 _apply_conn_extra 的封顶余量（CONN_EXTRA_CAP）。
    """
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = _populated(app)
    try:
        _fit_window_height(dlg, app, 15, 8)
        dlg._fit_visible_rows()
        app.processEvents()
        _assert_tier(dlg, 15, 8)
        frozen_sum = dlg._list_widget.height() + dlg._log_widget.height() + dlg._splitter.handleWidth()
        assert dlg._list_widget.minimumHeight() > 0, "前置条件：窗格应处于 fit 冻结态"
        base_conn_h = dlg._conn_grid.parent().height()
        base_status_h = dlg.status_bar.height()

        dlg.resize(1600, 1400)  # 不冻结/不手工 fit，走真实事件链
        app.processEvents()
        assert dlg._splitter.height() > frozen_sum, "冻结后撑大窗口，分割区必须跟着长"
        assert dlg.status_bar.height() <= base_status_h + 2, "状态栏不得吸走高出来的高度"
        assert dlg._conn_grid.parent().height() <= base_conn_h + EmbyActorManagerDialog.CONN_EXTRA_CAP + 2, (
            "连接组只许按 CONN_EXTRA_CAP 封顶吸收富余，不得把分割区的位置整个吃掉"
        )
    finally:
        dlg.close()
        app.processEvents()


def test_surplus_goes_to_rows_and_connection(app):
    """富余按整数瓜分：表格行长高 + 连接组边距，日志不定空白垫。"""
    dlg = _populated(app)
    try:
        _fit_window_height(dlg, app, 20, 10)
        # 多给 85px：行高 +4（80px），连接组 +5（上 2 下 3），日志垫 0
        dlg._fitting_rows = True
        dlg.resize(1600, dlg.height() + 85)
        app.processEvents()
        dlg._fitting_rows = False
        restore = _as_maximized(dlg)
        try:
            dlg._fit_visible_rows()
        finally:
            restore()
        app.processEvents()
        t = dlg.table
        base_r = dlg._natural_row_h
        assert t.rowHeight(0) == base_r + 4
        assert t.viewport().height() == 20 * (base_r + 4)
        margins = dlg._conn_grid.contentsMargins()
        assert margins.top() == 4 + 2
        assert margins.bottom() == 4 + 3
        log = dlg.log_text
        assert log.viewport().height() == 10 * log.fontMetrics().lineSpacing() + int(
            log.document().documentMargin()
        )
        assert log.viewportMargins().bottom() == 0
    finally:
        dlg.close()
        app.processEvents()


def test_fit_is_idempotent(app):
    """幂等：连续对齐多次不得棘轮式抬行高（行高只从"自然行高"基准长一次）。

    背景：早前每轮 fit 都把上轮长高后的行高当基准再长，重复触发
    （show/resize/取数/滚动条显隐）会把表格顶出多一行。
    """
    dlg = _populated(app)
    try:
        dlg.resize(1920, 1080)
        app.processEvents()
        dlg._fitting_rows = False
        restore = _as_maximized(dlg)
        try:
            heights = []
            for _ in range(4):
                dlg._fit_visible_rows()
                app.processEvents()
                heights.append(dlg.table.rowHeight(0))
        finally:
            restore()
        assert len(set(heights)) == 1, f"行高被反复抬高（棘轮）: {heights}"
        row_h = heights[0]
        assert dlg.table.viewport().height() == 20 * row_h
        # 富余全部落在行高上，日志不因此多出空白
        log = dlg.log_text
        assert log.viewport().height() == 10 * log.fontMetrics().lineSpacing() + int(
            log.document().documentMargin()
        )
    finally:
        dlg.close()
        app.processEvents()


def test_short_window_fit_is_noop(app):
    """小窗实在塞不下目标行数时不干预（行高/分隔条不动，连接组恢复基准）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg._fitting_rows = True  # 冻结自动对齐，手动控制测量点
    dlg.show()
    app.processEvents()
    try:
        dlg.resize(1200, 700)
        app.processEvents()
        dlg._fitting_rows = False
        t = dlg.table
        before = t.verticalHeader().defaultSectionSize()
        sizes_before = dlg._splitter.sizes()
        dlg._fit_visible_rows()
        app.processEvents()
        assert t.verticalHeader().defaultSectionSize() == before
        assert dlg._splitter.sizes() == sizes_before
        m = dlg._conn_grid.contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (6, 4, 6, 4)
    finally:
        dlg.close()
        app.processEvents()
