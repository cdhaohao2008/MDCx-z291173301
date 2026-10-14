"""运行日志贴底不留缝：无论行数、视口高、换行、上限、日志窗格多矮，拖到底末行都贴视口底。

背景（用户报障）：最小化时日志超过 9 条、最大化时超过 11 条，滚动条拉到底，末行
下方会浮出 10~20px 空白。根因是 Qt 竖向滚动按整行换档，而它给滚动条算的 pageStep
比视口真正装得下的整行数少一行（`pageStep = (视口高 - 1) // 行距`），于是「Qt 少算的
那一整行」＋「视口高除不尽行距的余量」叠加成缝隙。消除手段分两层：
`_FlushLogTextEdit._flush_tail` 压滚动上限治整行，对话框
`_snap_log_viewport_to_whole_lines` / 控件 `_absorb_viewport_residue` 把视口高落到行距
整数倍治余量。

量法：文档内容底 = Σ 各块 `blockBoundingRect` 高度之和（实测精确等于「可视行数 x 行
距」），滚动位移 = 档位 x 行距 ⇒ 末行文字底边在视口坐标 = 内容底 - 位移，缝隙 = 视口
高 - 那个值。内容不满视口时不存在缝隙。
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


def _pump(app, n: int = 12):
    for _ in range(n):
        app.processEvents()


def _populated(app, dlg, count: int = 30):
    dlg.table.setRowCount(count)
    for r in range(count):
        dlg.table.setItem(r, 1, QTableWidgetItem(f"actor{r:02d}"))
    app.processEvents()


def _tail_gap(log) -> int:
    """把滚动条拉到底，量末行文字底边到视口底边的缝隙（内容不满视口记 0）。"""
    doc = log.document()
    block = doc.begin()
    bottom = 0.0
    while block.isValid():
        bottom += log.blockBoundingRect(block).height()
        block = block.next()
    vp = log.viewport().height()
    if bottom <= vp:
        return 0
    bar = log.verticalScrollBar()
    line_h = log.fontMetrics().lineSpacing()
    shown_bottom = bottom - bar.value() * line_h
    return int(round(vp - shown_bottom))


def _scroll_to_end(app, dlg) -> int:
    bar = dlg.log_text.verticalScrollBar()
    bar.setValue(bar.maximum())
    _pump(app)
    return _tail_gap(dlg.log_text)


def _make(app, maximized: bool = False):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    dlg._real_is_maximized = dlg.isMaximized
    if maximized:
        dlg.isMaximized = lambda: True
    _populated(app, dlg)
    dlg.resize(1600, 1100)
    _pump(app)
    return dlg


def _close(app, dlg):
    if hasattr(dlg, "_real_is_maximized"):
        dlg.isMaximized = dlg._real_is_maximized
        del dlg._real_is_maximized
    dlg.close()
    _pump(app)


@pytest.mark.parametrize("count", [1, 5, 9, 12, 30, 200])
def test_normal_window_tail_flushes(app, count):
    """普通窗：日志 1~200 条，拖到底都不留缝（含用户报障的 9/12 条）。"""
    dlg = _make(app)
    try:
        for i in range(count):
            dlg.log(f"probe {i:03d} " + "X" * 30)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"{count} 条日志拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


@pytest.mark.parametrize("count", [9, 11, 12, 30])
def test_maximized_tail_flushes(app, count):
    """最大化（桩）：日志 9~30 条，拖到底都不留缝（含用户报障的 11/12 条）。"""
    dlg = _make(app, maximized=True)
    try:
        for i in range(count):
            dlg.log(f"max probe {i:03d} " + "X" * 30)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"最大化 {count} 条拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


def test_wrapped_long_lines_tail_flushes(app):
    """换行长文本：块高不再是单行距，仍须贴底。"""
    dlg = _make(app)
    try:
        for i in range(12):
            dlg.log(f"wrapped {i:03d} " + "很长的中文内容" * 40)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"换行长文本拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


def test_block_cap_500_tail_flushes(app):
    """块数上限 500：装不下的历史被裁掉后，末行仍贴底。"""
    dlg = _make(app)
    try:
        for i in range(640):
            dlg.log(f"cap probe {i:03d}")
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        assert dlg.log_text.blockCount() == 500, f"块数上限应为 500, 实得 {dlg.log_text.blockCount()}"
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"500 块上限下拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


def test_appended_lines_stay_flushed(app):
    """持续追加日志：新行落进内容底后仍即时贴底，缝隙不会回来。"""
    dlg = _make(app)
    try:
        for i in range(20):
            dlg.log(f"append probe {i:03d}")
        _pump(app)
        assert _scroll_to_end(app, dlg) == 0
        for i in range(20, 60):
            dlg.log(f"append probe {i:03d}")
        _pump(app)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"追加后拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


@pytest.mark.parametrize("delta", [7, 13, 29, 47])
def test_user_dragged_splitter_tail_flushes(app, delta):
    """用户拖过分隔条：行高不再重排，但日志视口仍须吸附整行、拖到底不留缝。"""
    dlg = _make(app)
    try:
        for i in range(25):
            dlg.log(f"drag probe {i:03d} " + "X" * 30)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        dlg._splitter.splitterMoved.emit(100, 1)
        sizes = dlg._splitter.sizes()
        dlg._splitter.setSizes([sizes[0] + delta, max(80, sizes[1] - delta)])
        _pump(app)
        log = dlg.log_text
        line_h = log.fontMetrics().lineSpacing()
        assert log.viewport().height() % line_h == 0, (
            f"拖动后日志视口高应落到行距整数倍, 实得 {log.viewport().height()} % {line_h}"
        )
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"拖分隔条后 {delta}px 偏移, 拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


@pytest.mark.parametrize("size", [(900, 420), (900, 500)])
def test_tiny_window_bail_tail_flushes(app, size):
    """窗太小、fit 提前 bail：日志窗格到 minimumSizeHint 后缩不动，缝隙仍须归零。"""
    dlg = _make(app)
    try:
        for i in range(25):
            dlg.log(f"tiny probe {i:03d} " + "X" * 30)
        _pump(app)
        dlg.resize(*size)
        _pump(app, 20)
        dlg._fit_visible_rows()
        _pump(app, 12)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"{size[0]}x{size[1]} 拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


def test_resize_cycles_tail_flushes(app):
    """反复改变窗口尺寸（还原/最大化来回）：每次落定后拖到底都不留缝。"""
    dlg = _make(app)
    try:
        for i in range(30):
            dlg.log(f"cycle probe {i:03d} " + "X" * 30)
        for w, h in ((1600, 1100), (1400, 900), (1920, 1400), (1200, 760), (1600, 1100)):
            dlg.resize(w, h)
            _pump(app, 12)
            gap = _scroll_to_end(app, dlg)
            assert gap == 0, f"{w}x{h} 拖到底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)


def test_scroll_back_then_down_still_flushes(app):
    """上滚回看历史再拖到底：回到底部依旧零缝隙（贴底档没被改坏）。"""
    dlg = _make(app)
    try:
        for i in range(60):
            dlg.log(f"history probe {i:03d} " + "X" * 30)
        _pump(app)
        dlg._fit_visible_rows()
        _pump(app)
        bar = dlg.log_text.verticalScrollBar()
        bar.setValue(0)
        _pump(app)
        gap = _scroll_to_end(app, dlg)
        assert gap == 0, f"上滚再回底应贴视口底, 实得 {gap}px 缝隙"
    finally:
        _close(app, dlg)
