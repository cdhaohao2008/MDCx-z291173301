"""设置-高级页保留任务行：「不限次数刮削」与「当停止刮削时」严格上下对齐（宽窄两态）。

需求（用户截图红框）：
  最小化时「不限次数刮削」向右移到与「当停止刮削时」上下对齐；
  最大化时「不限次数刮削」向左移到与「当停止刮削时」上下对齐；
  「当停止刮削时」自身位置保持不变。

实现：_sync_advanced_page_align 内在弹窗确认行落定后，钉死前导项
「重启续刮任务」，使末位「不限次数刮削」落到「当停止刮削时」实测 x。
只断言「精确落在锚点左缘」，不断言移动方向（离屏无 CJK 字体，方向不可比）。

v2.7.6 需求③：最小化时「不限次数刮削」改为与「无按钮」（radioButton_hide_none）
严格上下对齐，且「无按钮」位置保持不变——真机上「当停止刮削时」因前导项
「当退出软件时」的 sizeHint 过大而钉不上（停在竖线左侧），「无按钮」却钉得上，
故窄态的目标竖线换成「无按钮」的实测 x。实现上这一段整段挪到
_sync_advanced_page_tail_align() 之后（「无按钮」的终态 x 是那里钉出来的）；
宽态仍取「当停止刮削时」，逐位不变。

v2.7.6 需求④：最小化时「不限次数刮削」改为与「显示字段内容信息」
（checkBox_show_data_log）严格上下对齐，且「显示字段内容信息」位置保持不变。
**根因在判态**：这一批需求原先用几何拉伸量（`_scroll_stretch_extra() > 0`）区分
最大化/还原态，但真机（dpr=1.25、屏幕 1536×864）**还原态**窗口 1085×793 的拉伸
量已经是 +33 > 0 → 还原态被误判成最大化，「最小化时」那一支根本不执行（用户
截图：目标纹丝不动）。故判态改成窗口管理器给的「真·最大化」状态
（`_advanced_page_window_maximized()`：isMaximized()/isFullScreen()）：
  最大化：目标竖线仍是「当停止刮削时」，页面布局、控件、组件、提示词全部不变；
  还原态：目标竖线是「显示字段内容信息」col_x(src_data)。
离屏环境里窗口从未 maximized，故默认走还原态那一支；最大化那一支用
monkeypatch 替换 isMaximized 来覆盖（几何仍是还原态的，但断的是「选哪条竖线」）。

v3.0 需求①（最新一条）：还原态的目标竖线再改一次——由「显示字段内容信息」
改为「显示字段来源信息」（checkBox_show_from_log）：用户要的是「不限次数刮削
**向左**移动到与『显示字段来源信息』严格上下对齐的位置」，而「显示字段内容信息」
那条竖线太靠右（真机 787），不是用户要的那条。「显示字段来源信息」自己不许动，
实现同样只钉前导项「重启续刮任务」。最大化态仍取「当停止刮削时」，逐位不变。

可行性门控（与「隐藏菜单栏图标」行同款手法）：落点落在前导项文本自然宽
之内时硬钉会裁字，此时整行放弃、保持设计态原样。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


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
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_advanced(win, app):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab5":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("高级 tab5 not found")
    app.processEvents()


def _abs(ui, widget) -> int:
    return widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _remain_row(ui, maximized):
    """保留任务行的实测可行性（与实现同式）：钉宽放得下才算可行。

    目标竖线按「窗口是否真·最大化」取（不能用几何拉伸量——真机还原态窗口的
    拉伸量已经 > 0，会把还原态误判成最大化）：
      最大化：「当停止刮削时」col_x(stop_scrape)（逐位不变）；
      还原态：「显示字段来源信息」col_x(src_from)（v3.0 需求①点名的那条竖线）。
    """
    host = ui.gridLayoutWidget_20
    content = ui.scrollAreaWidgetContents_gaoji
    host_x = host.mapTo(content, QPoint(0, 0)).x()
    row5_x = _abs(ui, ui.checkBox_remain_task) - host_x
    target = ui.checkBox_show_dialog_stop_scrape if maximized else ui.checkBox_show_from_log
    want = _abs(ui, target) - host_x
    lay = ui.horizontalLayout_89
    col_w = host.width() - row5_x
    pin = want - row5_x - lay.spacing()
    feasible = (
        want > row5_x
        and pin >= ui.checkBox_remain_task.sizeHint().width()
        and col_w - pin - lay.spacing() >= ui.checkBox_infinite_scrape.sizeHint().width()
    )
    return {"pin": pin, "feasible": feasible}


_WIDE_SIZES = ((1920, 1170), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_infinite_aligns_to_stop_or_defers(win, app, width, height):
    """放得下就必须精确对齐；放不下就整行放弃（不钉宽、不裁字）。

    目标竖线按「窗口是否真·最大化」取：最大化取「当停止刮削时」（逐位不变），
    还原态取「显示字段来源信息」（v3.0 需求①；离屏窗口从未 maximized，故本用例
    走还原态那一支）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    maximized = win._advanced_page_window_maximized()
    row = _remain_row(ui, maximized)
    got = _abs(ui, ui.checkBox_infinite_scrape)
    target = ui.checkBox_show_dialog_stop_scrape if maximized else ui.checkBox_show_from_log
    want = _abs(ui, target)
    remain = ui.checkBox_remain_task
    infinite = ui.checkBox_infinite_scrape

    if row["feasible"]:
        assert got == want, f"{width} 宽下放得下（pin={row['pin']}）却未对齐: x={got} 期望={want}"
    else:
        # 放弃态：落点在前导项文本自然宽之内，硬钉必然裁字，故保持自然位
        # （末项停在竖线右侧）；钉宽必须处于解除态，下次放得下时才能重新钉上。
        assert got > want, f"{width} 宽下放不下（pin={row['pin']}）本应整行放弃，却对到了 x={got}（可能裁字）"
        assert remain.minimumWidth() == 0 and remain.maximumWidth() == 16777215, (
            f"{width} 宽下放弃态里前导项钉宽未解除: min={remain.minimumWidth()} max={remain.maximumWidth()}"
        )

    # 两种情形下两项都不许被压到裁字；目标竖线上的控件自身一律不动。
    assert remain.width() >= remain.sizeHint().width(), (
        f"{width} 宽下「重启续刮任务」被压到 {remain.width()}px（sizeHint {remain.sizeHint().width()}），会裁字"
    )
    assert infinite.width() >= infinite.sizeHint().width(), (
        f"{width} 宽下「不限次数刮削」被压到 {infinite.width()}px（sizeHint {infinite.sizeHint().width()}），会裁字"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_infinite_aligns_to_stop_when_window_maximized(win, app, monkeypatch, width, height):
    """最大化那一支仍取「当停止刮削时」——页面布局、控件、组件、提示词全部不变。

    离屏窗口不会真·最大化，故用 monkeypatch 替换 isMaximized 来覆盖这一支
    （断的是「选哪条竖线」，几何仍是当前尺寸的）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    monkeypatch.setattr(win, "isMaximized", lambda: True)
    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    assert win._advanced_page_window_maximized()
    _resize(win, app, width, height)

    row = _remain_row(ui, True)
    got = _abs(ui, ui.checkBox_infinite_scrape)
    want = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    if row["feasible"]:
        assert got == want, f"{width} 宽下最大化态未对齐「当停止刮削时」: x={got} 期望={want}"
    else:
        assert got > want, f"{width} 宽下最大化态放不下（pin={row['pin']}）本应整行放弃，却对到了 x={got}"


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_restored_infinite_lands_on_show_from_log(win, app, width, height):
    """v3.0 需求①：还原态「不限次数刮削」与「显示字段来源信息」严格上下对齐。

    并且「显示字段来源信息」位置保持不变——本用例连跑两遍同步，断言第二遍不再
    挪动它（同步是幂等的，且不许动的那一列确实没动）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert not win._advanced_page_window_maximized(), f"{width} 宽下离屏窗口应处于还原态"

    from_x = _abs(ui, ui.checkBox_show_from_log)
    win._sync_page_layouts()
    app.processEvents()
    assert _abs(ui, ui.checkBox_show_from_log) == from_x, (
        f"{width} 宽下「显示字段来源信息」被带偏: {from_x} -> {_abs(ui, ui.checkBox_show_from_log)}"
    )

    row = _remain_row(ui, False)
    if row["feasible"]:
        assert _abs(ui, ui.checkBox_infinite_scrape) == from_x, (
            f"{width} 宽下还原态「不限次数刮削」未与「显示字段来源信息」严格上下对齐: "
            f"x={_abs(ui, ui.checkBox_infinite_scrape)} 期望={from_x}"
        )
    # 「无按钮」在「显示字段内容信息」那条竖线上（离屏环境两者同列），与本需求
    # 的目标竖线不同，故这里只断言它没被带偏。
    assert _abs(ui, ui.radioButton_hide_none) == _abs(ui, ui.checkBox_show_data_log), (
        f"{width} 宽下「无按钮」被带偏: x={_abs(ui, ui.radioButton_hide_none)} "
        f"期望={_abs(ui, ui.checkBox_show_data_log)}"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_stop_stays_on_spec_line_in_wide(win, app, width, height):
    """宽态「当停止刮削时」仍精确落在既有竖线（显示字段来源信息）上，本需求未搬动它。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert win._scroll_stretch_extra(win._adv_scroll) > 0
    got = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    anchor = _abs(ui, ui.checkBox_show_from_log)
    assert got == anchor, f"{width} 宽下「当停止刮削时」被搬动: x={got} 既有竖线={anchor}"


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_stop_stays_on_spec_line_in_narrow(win, app, width, height):
    """窄态「当停止刮削时」仍精确落在既有竖线（显示字段内容信息）上，本需求未搬动它。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert win._scroll_stretch_extra(win._adv_scroll) <= 0
    got = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    anchor = _abs(ui, ui.checkBox_show_data_log)
    assert got == anchor, f"{width} 宽下「当停止刮削时」被搬动: x={got} 既有竖线={anchor}"
