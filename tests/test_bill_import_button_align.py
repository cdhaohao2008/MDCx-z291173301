"""设置-高级-高级功能「导入账单」按钮的回归测试（2026-10-26 需求）。

需求原话：
  1. 入口做在「隐藏信息管理」按钮右侧，和「显示字段内容信息」严格上下对齐，
     「显示字段内容信息」位置保持不变；
  2. 点击选 xlsx 账单导入，导入后赞助窗口的新人榜 / 土豪榜有数据；
  3. 功能绑定本机 CPU 编号，只有作者这台电脑能看到按钮并使用。

本文件钉三件事：
  * 机器未绑定时按钮**不出现**（``_poll_bill_bind_state`` 收到 False 就保持隐藏）；
  * 绑定时按钮左缘 == ``checkBox_show_data_log`` 的实测 x（host 局部坐标）、
    y == ``checkBox_hide_nfo_nav`` 的 y，且在「隐藏信息管理」右侧不重叠；
  * 按钮存在与否都不改任何既有控件的坐标（它不在任何布局里，是 host 的游离子项）。

「上下对齐」在本项目里一律指**左缘 x 相等**（同页「不限次数刮削」与「显示字段来源
信息」就是这层含义），故断言的是 x，不是 y。
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


def _make_window(app, monkeypatch, tmp_path, bound: bool):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod
    from mdcx.utils import machine_binding

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    # 探测线程一律不打桩到真实 PowerShell：测试要的是「结果到了之后怎么显示」
    monkeypatch.setattr(machine_binding, "ensure_probe_started", lambda: None)
    monkeypatch.setattr(machine_binding, "probe_state", lambda: bound)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    window._poll_bill_bind_state()
    return window


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    window = _make_window(app, monkeypatch, tmp_path, True)
    _goto_advanced(window, app)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_advanced(win, app) -> None:
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


def _resize(win, app, width, height) -> None:
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _host_x(ui, widget) -> int:
    """控件左缘换算到 gridLayoutWidget_20 的局部坐标（跨分支经 content 中转）。"""
    content = ui.scrollAreaWidgetContents_gaoji
    return widget.mapTo(content, QPoint(0, 0)).x() - ui.gridLayoutWidget_20.mapTo(content, QPoint(0, 0)).x()


def test_button_absent_when_machine_not_bound(app, monkeypatch, tmp_path):
    """未绑定的机器：按钮从头到尾不显示（不是禁用，是看不见）。"""
    window = _make_window(app, monkeypatch, tmp_path, False)
    try:
        _goto_advanced(window, app)
        _resize(window, app, 1200, 900)
        button = window.Ui.pushButton_import_bill
        assert button.isHidden()
        assert not button.isVisible()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_button_shown_and_labelled_when_bound(win, app):
    """绑定的机器：按钮文案是「导入账单」，且确实挂在高级功能分组里。"""
    button = win.Ui.pushButton_import_bill
    assert button.isVisible()
    assert button.text() == "导入账单"
    assert button.parent() is win.Ui.gridLayoutWidget_20


def test_button_is_not_in_any_layout(win):
    """游离于布局之外——这是「不影响既有控件位置」的结构保证。"""
    host = win.Ui.gridLayoutWidget_20
    button = win.Ui.pushButton_import_bill
    assert host.layout().indexOf(button) == -1
    assert win.Ui.horizontalLayout_nav_hide.indexOf(button) == -1


@pytest.mark.parametrize("size", [(1000, 700), (1030, 753), (1200, 900), (1536, 864), (1920, 1170)])
def test_button_left_edge_matches_show_data_log(win, app, size):
    """按钮左缘 == 「显示字段内容信息」那条竖线，纵向与「隐藏信息管理」齐平。"""
    ui = win.Ui
    _resize(win, app, *size)
    button = ui.pushButton_import_bill
    src_data = ui.checkBox_show_data_log
    nfo = ui.checkBox_hide_nfo_nav
    assert button.x() == _host_x(ui, src_data), f"{size} 未对齐"
    assert button.y() == nfo.mapTo(ui.gridLayoutWidget_20, QPoint(0, 0)).y()
    assert button.height() == nfo.height()


def test_button_sits_right_of_hide_nfo_checkbox(win, app):
    """按钮在「隐藏信息管理」右侧，两者不重叠（否则会盖住复选框文字）。"""
    ui = win.Ui
    for size in ((1000, 700), (1200, 900), (1920, 1170)):
        _resize(win, app, *size)
        button = ui.pushButton_import_bill
        nfo = ui.checkBox_hide_nfo_nav
        assert button.x() >= nfo.x() + nfo.width(), f"{size} 按钮压在复选框上"


def test_button_positioned_on_first_open_without_resize(app, monkeypatch, tmp_path):
    """首次打开高级页（没 resize、没显式同步）按钮就已就位。

    按钮是在主窗口 __init__ 里建的，那一刻高级页还没被布局过（host 不可见），
    定位方法会早退，按钮暂时停在 (0,0)。切到高级 tab 时滚动区 showEvent 会跑
    宽幅同步钩子 → `_sync_advanced_page_align` → 本按钮定位，用户看到的第一帧
    就该是对齐的；漏了这条链路按钮会出现在分组框左上角。
    """
    window = _make_window(app, monkeypatch, tmp_path, True)
    try:
        _goto_advanced(window, app)
        button = window.Ui.pushButton_import_bill
        assert button.isVisible()
        assert button.x() == _host_x(window.Ui, window.Ui.checkBox_show_data_log)
        assert button.x() > 0 and button.y() > 0
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_showing_button_never_moves_existing_widgets(win, app):
    """「显示字段内容信息」位置保持不变：按钮显隐前后，整页控件坐标逐位相同。"""
    ui = win.Ui
    _resize(win, app, 1200, 900)
    button = ui.pushButton_import_bill
    watched = (
        ui.checkBox_show_data_log,
        ui.checkBox_show_from_log,
        ui.checkBox_show_web_log,
        ui.checkBox_hide_nfo_nav,
        ui.checkBox_hide_actor_nav,
        ui.checkBox_dark_mode,
        ui.checkBox_auto_exit,
        ui.checkBox_infinite_scrape,
    )
    button.hide()
    win._sync_page_layouts()
    app.processEvents()
    before = [_host_x(ui, widget) for widget in watched]
    button.show()
    win._sync_page_layouts()
    app.processEvents()
    after = [_host_x(ui, widget) for widget in watched]
    assert before == after
