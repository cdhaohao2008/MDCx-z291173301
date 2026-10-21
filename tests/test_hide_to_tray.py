"""ESC 隐藏到系统托盘回归测试。

需求：主窗口按 ESC → 隐藏到任务栏系统托盘图标区域。

实现要点（`main_window.py: hide_to_tray` / `hide_tips_widget_on_escape`）：
ESC 只有一个入口 `hide_tips_widget_on_escape`，优先级为
    1) NFO 编辑面板可见 → 关面板（脏数据仍弹保存确认）
    2) 说明弹窗可见     → 关弹窗
    3) 都没有           → 收进托盘 `hide_to_tray`
`hide_to_tray` 在隐藏前强制点亮托盘图标：默认配置 `switch_on` 含 `Switch.HIDE_MENU`，
托盘图标可能处于隐藏状态，此时再 `hide()` 主窗会让 Windows 任务栏按钮一并消失，
程序彻底无法唤出。故没有托盘图标就补建、有但隐藏就 `show()`。

防恒真策略：所有用例都断言「窗口不可见」**且**「托盘图标存在且 `isVisible()` 为真」，
并在用例里显式构造「托盘图标已存在但处于隐藏态」的前置，避免只用 hasattr 判断的
假通过；异常兜底用例反过来断言托盘彻底不可用时窗口仍被隐藏。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
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


def _show(win, app):
    win.show()
    app.processEvents()
    assert win.isVisible(), "前置失败：主窗应为可见态"


def _force_tray(win, app, visible: bool):
    """把托盘图标置成指定可见性并返回它，模拟 `load_config` 的托盘兜底结果。"""
    if not hasattr(win, "tray_icon"):
        win.Init_QSystemTrayIcon()
    if visible:
        win.tray_icon.show()
    else:
        win.tray_icon.hide()
    app.processEvents()
    return win.tray_icon


def _open_tips_dialog(win):
    """打开说明弹窗。

    `widget_show_tips` 的父级是设置页 `page_setting`，QStackedWidget 只显示当前页，
    不切到设置页时子控件 `isVisible()` 恒为 False，用例会因前置失败而假阴性。
    """
    stack = win.Ui.page_setting.parentWidget()
    for index in range(stack.count()):
        if stack.widget(index) is win.Ui.page_setting:
            stack.setCurrentIndex(index)
            break
    win.Ui.widget_show_tips.show()


# --------------------------------------------------------------------------- #
# ESC 三层优先级
# --------------------------------------------------------------------------- #
def test_escape_falls_back_to_tray_when_nothing_open(win, app):
    """兜底：NFO 面板与说明弹窗都没开时，ESC 应当收进托盘。"""
    _show(win, app)
    win.Ui.widget_nfo.hide()
    win.Ui.widget_show_tips.hide()
    app.processEvents()
    assert win.Ui.widget_nfo.isHidden() and not win.Ui.widget_show_tips.isVisible(), "前置失败"

    win.hide_tips_widget_on_escape()
    app.processEvents()

    assert not win.isVisible(), "ESC 兜底未隐藏主窗（未收进托盘）"
    assert hasattr(win, "tray_icon"), "ESC 收进托盘后托盘图标不存在，程序无法再唤出"
    assert win.tray_icon.isVisible(), "ESC 收进托盘后托盘图标仍不可见，无法从托盘恢复"


def test_escape_closes_nfo_editor_before_hiding(win, app):
    """优先级 1：NFO 编辑面板可见时 ESC 只关面板，不收托盘。"""
    _show(win, app)
    closed = []
    win._close_nfo_editor = lambda *a, **k: closed.append(True)
    win.Ui.widget_nfo.show()
    win.Ui.widget_show_tips.hide()
    app.processEvents()
    assert not win.Ui.widget_nfo.isHidden(), "前置失败：NFO 面板应可见"

    win.hide_tips_widget_on_escape()
    app.processEvents()

    assert closed == [True], "NFO 面板可见时 ESC 未走 _close_nfo_editor"
    assert win.isVisible(), "NFO 面板可见时 ESC 把主窗也收进了托盘（越级）"


def test_escape_closes_tips_dialog_before_hiding(win, app):
    """优先级 2：说明弹窗可见时 ESC 只关弹窗，不收托盘。"""
    _show(win, app)
    win.Ui.widget_nfo.hide()
    _open_tips_dialog(win)
    app.processEvents()
    assert win.Ui.widget_show_tips.isVisible(), "前置失败：说明弹窗应可见"

    win.hide_tips_widget_on_escape()
    app.processEvents()

    assert not win.Ui.widget_show_tips.isVisible(), "ESC 未关闭说明弹窗"
    assert win.isVisible(), "说明弹窗可见时 ESC 把主窗也收进了托盘（越级）"


def test_escape_key_event_really_reaches_handler(win, app):
    """真实按键事件（不是直接调函数）同样能收进托盘，防止快捷键绑定被改动后失效。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    _show(win, app)
    win.Ui.widget_nfo.hide()
    win.Ui.widget_show_tips.hide()
    win.activateWindow()
    win.raise_()
    app.processEvents()

    QTest.keyClick(win, Qt.Key.Key_Escape)
    app.processEvents()

    assert not win.isVisible(), "按 ESC 键没有隐藏主窗"
    assert hasattr(win, "tray_icon") and win.tray_icon.isVisible(), "按 ESC 键未点亮托盘图标"


# --------------------------------------------------------------------------- #
# hide_to_tray 的托盘兜底
# --------------------------------------------------------------------------- #
def test_hide_to_tray_creates_tray_icon_when_missing(win, app):
    """托盘图标尚未创建时（默认配置 hide_menu 会走这条路），hide_to_tray 必须补建。"""
    if hasattr(win, "tray_icon"):
        del win.tray_icon
    _show(win, app)

    win.hide_to_tray()
    app.processEvents()

    assert not win.isVisible(), "hide_to_tray 未隐藏主窗"
    assert hasattr(win, "tray_icon"), "hide_to_tray 未补建托盘图标"
    assert win.tray_icon.isVisible(), "补建的托盘图标未显示，主窗将无法唤回"


def test_hide_to_tray_forces_show_on_existing_hidden_icon(win, app):
    """防恒真：托盘图标已存在但处于隐藏态时也必须 show()。

    这是本功能最容易漏的一格——只用 hasattr 判断会「看起来通过」，但默认配置
    （`Switch.HIDE_MENU`）下托盘本就是隐藏的，Windows 上主窗再隐藏就再也唤不回。
    """
    tray = _force_tray(win, app, visible=False)
    assert hasattr(win, "tray_icon") and not tray.isVisible(), "前置失败：托盘图标应已存在且隐藏"
    _show(win, app)

    win.hide_to_tray()
    app.processEvents()

    assert not win.isVisible(), "hide_to_tray 未隐藏主窗"
    assert win.tray_icon is tray, "hide_to_tray 重建了托盘图标而非复用"
    assert win.tray_icon.isVisible(), "已存在但隐藏的托盘图标没有被点亮，主窗将无法唤回"


def test_hide_to_tray_closes_preview_window(win, app):
    """收起主窗时连带关掉 NFO 预览窗口，避免预览窗成为屏幕上唯一可见窗口。"""
    from PyQt6.QtWidgets import QWidget

    _show(win, app)
    preview = QWidget()
    preview.show()
    win.nfo_lib_preview_window = preview
    app.processEvents()
    assert preview.isVisible(), "前置失败：预览窗口应可见"

    win.hide_to_tray()
    app.processEvents()

    assert not win.isVisible(), "hide_to_tray 未隐藏主窗"
    assert not preview.isVisible(), "hide_to_tray 未关闭 NFO 预览窗口，留下孤儿窗口"


def test_hide_to_tray_hides_even_if_tray_unavailable(win, app, monkeypatch):
    """托盘彻底不可用时仍要隐藏窗口，否则用户按了 ESC 毫无反应。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    _show(win, app)
    if hasattr(win, "tray_icon"):
        del win.tray_icon

    def _boom():
        raise RuntimeError("no system tray")

    monkeypatch.setattr(win, "Init_QSystemTrayIcon", _boom)
    monkeypatch.setattr(mw_mod.signal_qt, "show_traceback_log", lambda *a, **k: None)

    win.hide_to_tray()
    app.processEvents()

    assert not win.isVisible(), "托盘不可用时 hide_to_tray 没有隐藏窗口"


# --------------------------------------------------------------------------- #
# 其它隐藏入口统一到 hide_to_tray
# --------------------------------------------------------------------------- #
def test_context_menu_hide_action_uses_hide_to_tray(win, app):
    """右键菜单「隐藏到托盘」与 ESC 走同一条路径。"""
    tray = _force_tray(win, app, visible=False)
    _show(win, app)

    win.menu_hide.trigger()
    app.processEvents()

    assert not win.isVisible(), "右键菜单「隐藏」未隐藏主窗"
    assert win.tray_icon is tray and win.tray_icon.isVisible(), "右键菜单「隐藏」未点亮托盘图标"


def test_tray_hidden_window_restores_via_tray_icon(win, app, monkeypatch):
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    """收进托盘后托盘图标点击仍能恢复（议题 #132 的恢复通道不被本次改动破坏）。"""
    from PyQt6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(window_ops_mod, "IS_WINDOWS", True)
    _force_tray(win, app, visible=False)
    _show(win, app)

    win.hide_to_tray()
    app.processEvents()
    assert not win.isVisible() and win.tray_icon.isVisible(), "前置失败：未成功收进托盘"

    win.tray_icon_click(QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()

    assert win.isVisible(), "托盘图标点击无法恢复主窗"


def test_no_extra_escape_shortcut_registered(win):
    """防回归：ESC 全应用只允许 `hide_tips_widget_on_escape` 一条窗口级快捷键。

    重复绑定同一键序列会被 Qt 判为 ambiguous shortcut，两条都不触发——
    这正是历史上 ESC 毫无反应的根因，因此作为本功能的守卫测试。
    """
    from PyQt6.QtGui import QKeySequence, QShortcut

    esc_seq = QKeySequence("Esc").toString(QKeySequence.SequenceFormat.PortableText)
    esc_shortcuts = [
        shortcut
        for shortcut in win.findChildren(QShortcut)
        if shortcut.key().toString(QKeySequence.SequenceFormat.PortableText) == esc_seq
    ]

    assert len(esc_shortcuts) == 1, f"ESC 窗口级快捷键应只有 1 条，实际 {len(esc_shortcuts)} 条"

    # 该快捷键必须接到 ESC 统一入口（内部才会转发到 hide_to_tray）
    calls = []
    win.hide_to_tray = lambda: calls.append("tray")
    esc_shortcuts[0].activated.emit()
    assert calls == ["tray"], "ESC 快捷键没有接到 hide_to_tray 路径上"


def test_tray_menu_hide_action_has_no_shortcut_suffix(win, app):
    """托盘右键菜单的「隐藏到托盘」不再带「Q / Esc」后缀。

    用户 2026-10-21：托盘菜单里「隐藏到托盘」后面跟的「Q / Esc」在系统托盘里
    被 Qt 用制表符对齐渲染成一段空隙（看着像多截空白），要求只留「隐藏到托盘」。
    Q / Esc 两条快捷键绑在主窗口上（QShortcut(Q) 与 hide_tips_widget_on_escape），
    去掉菜单里的提示文字不影响快捷键本身。
    """
    _force_tray(win, app, visible=True)

    menu = win.tray_icon.contextMenu()
    assert menu is not None, "前置失败：托盘图标没有上下文菜单"

    texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert "隐藏到托盘" in texts, f"托盘菜单里找不到「隐藏到托盘」项：{texts}"
    assert "隐藏到托盘\tQ / Esc" not in texts, "托盘菜单「隐藏到托盘」仍带着「Q / Esc」后缀"
