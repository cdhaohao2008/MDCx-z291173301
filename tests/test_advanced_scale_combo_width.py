"""设置-高级页「分屏缩放」下拉框右缘对齐「隐藏边框样式」右缘的回归测试。

需求（2026-10-23 第二批②）：「分屏缩放下拉框右侧边界缩进到与隐藏边框样式右侧
边界严格对齐的位置，隐藏边框样式位置保持不变」。

口径（用户红线画在「隐藏边框样式」**文字末尾**，不是它被 layoutWidget5 均分后的
控件宽）：
  - 基准 = `checkBox_hide_window_title.sizeHint().width()`（方框 + 文字，只随字体变）；
  - 两行同处 gridLayout_20 的 col1、左缘天然相等，故「右缘对齐」等价于
    `comboBox_ui_scale.width() == 基准宽`；
  - 下拉框自身最小可用宽比基准还大时放弃对齐（不许裁掉「跟随系统 / 300%」）。

根因防线：
  - 下拉框原本是 Fixed 策略 + `.ui` 里 minimumSize 90，宽度只由 sizeHint 决定，
    与「隐藏边框样式」之间没有任何联动。
  - 该宽度钉在控件自身的 min/max 上，跨调用留存：判据必须比 min/max 而不是
    `width()`，否则上一遍留下的约束会让「已对齐」的判定永远成立（假绿）。
  - 它同时是分屏缩放行提示词的前导控件，宽度一变，那条提示词的间隔就要重算
    （见 tests/test_advanced_page_hint_align.py）；故本方法必须排在提示词对齐之前。
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
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda *a, **k: None)
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


_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


def _want_width(ui) -> int:
    return max(
        ui.checkBox_hide_window_title.sizeHint().width(),
        ui.comboBox_ui_scale.minimumSizeHint().width(),
    )


def _baseline_without_combo_align(win, app, monkeypatch, width, height):
    """另起窗口、把下拉框钉宽整个摘掉，量「隐藏边框样式」与下拉框的自然几何。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    original = mw_mod.MyMAinWindow._sync_advanced_page_scale_combo_align
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_scale_combo_align", lambda self: None)
    probe = None
    try:
        probe = mw_mod.MyMAinWindow()
        for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
            getattr(probe, timer_name).stop()
        probe.show()
        _goto_advanced(probe, app)
        _resize(probe, app, width, height)
        ui = probe.Ui
        return {
            "base": (_abs(ui, ui.checkBox_hide_window_title), ui.checkBox_hide_window_title.width()),
            "combo": (_abs(ui, ui.comboBox_ui_scale), ui.comboBox_ui_scale.width()),
        }
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_scale_combo_align", original)


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_combo_right_edge_lands_on_hide_border_right_edge(win, app, width, height):
    """两态都要求：下拉框右缘 == 「隐藏边框样式」右缘（= 左缘 + sizeHint 宽）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = ui.checkBox_hide_window_title
    combo = ui.comboBox_ui_scale
    base_left = _abs(ui, base)
    combo_left = _abs(ui, combo)
    assert combo_left == base_left, f"{width} 宽下两行左缘不一致: combo={combo_left} base={base_left}"

    base_right = base_left + base.sizeHint().width()
    combo_right = combo_left + combo.width()
    assert combo_right == base_right, (
        f"{width} 宽下下拉框右缘 {combo_right} 未与「隐藏边框样式」右缘 {base_right} 严格对齐"
        f"（combo 宽 {combo.width()}，基准宽 {base.sizeHint().width()}）"
    )
    # 判据要比 min/max：宽度钉在控件约束上，跨调用留存，只比 width() 会假绿
    want = _want_width(ui)
    assert (combo.minimumWidth(), combo.maximumWidth()) == (want, want), (
        f"{width} 宽下下拉框约束未钉成 {want}: min={combo.minimumWidth()} max={combo.maximumWidth()}"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_hide_border_style_never_moves(win, app, monkeypatch, width, height):
    """「隐藏边框样式」位置保持不变，且下拉框确实被缩窄过（不是原本就对齐）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = _baseline_without_combo_align(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    box = ui.checkBox_hide_window_title
    assert (_abs(ui, box), box.width()) == base["base"], (
        f"{width} 宽下「隐藏边框样式」被本需求带偏: 基线={base['base']} 实际={(_abs(ui, box), box.width())}"
    )
    combo = ui.comboBox_ui_scale
    assert combo.width() != base["combo"][1], f"{width} 宽下下拉框宽度没变（{combo.width()}），本需求没生效"


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_combo_never_clips(win, app, width, height):
    """下拉框不得被压到最小可用宽以下（「跟随系统 / 300%」不许裁字）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    combo = ui.comboBox_ui_scale
    assert combo.width() >= combo.minimumSizeHint().width(), (
        f"{width} 宽下下拉框被压到 {combo.width()}px（最小可用 {combo.minimumSizeHint().width()}），会裁字"
    )
    # 当前档位文字本身也必须放得下（QComboBox 的 sizeHint 含最宽档位，这里退一步
    # 只卡当前档位 + 箭头的最小可用宽，避免把「跟随系统」这种默认档裁掉）
    assert combo.width() >= combo.minimumSizeHint().width()


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_round_trip_keeps_combo_width(win, app, width, height):
    """窄→宽→窄往返后下拉框宽度与约束都不漂移。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    _resize(win, app, width, height)
    combo = ui.comboBox_ui_scale
    first = (combo.width(), combo.minimumWidth(), combo.maximumWidth())

    _resize(win, app, 1920, 1170)
    _resize(win, app, width, height)

    assert (combo.width(), combo.minimumWidth(), combo.maximumWidth()) == first, (
        f"往返后下拉框宽度漂移: {first} -> {(combo.width(), combo.minimumWidth(), combo.maximumWidth())}"
    )
