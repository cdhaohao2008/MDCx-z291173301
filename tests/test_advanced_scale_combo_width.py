"""设置-高级页「分屏缩放」下拉框右缘对齐「隐藏演员管理」右缘的回归测试。

需求（2026-10-23 第三批，替换第二批的「隐藏边框样式」锚点）：「分屏缩放下拉框
右侧边界向左缩进到与隐藏演员管理右侧边界严格对齐的位置，隐藏演员管理位置保持
不变」。两枚锚点都是 6 个汉字，落点相同；第三批同时把「至少 minimumSizeHint」
那条下限撤掉了（真机 80% 缩放下它比锚点宽 20px，`max()` 会把下拉框停在最小可用
宽上、比锚点右出 20px —— 用户截图红框就是这个）。

口径（用户红线画在复选框**文字末尾**，不是它被容器均分后的控件宽）：
  - 基准 = `checkBox_hide_actor_nav.sizeHint().width()`（方框 + 文字，只随字体变）；
    必须用 sizeHint 而不是 width()：隐藏入口行两枚复选框都被 `pin_d` 钉过宽；
  - 两行同处 gridLayout_20 的 col1、左缘天然相等，故「右缘对齐」等价于
    `comboBox_ui_scale.width() == 基准宽`；
  - **严格对齐优先于「不裁字」**：即使基准比下拉框自身 minimumSizeHint 还小，
    也按基准宽钉死（第二批取 max 的写法已被用户否掉）。

根因防线：
  - 下拉框原本是 Fixed 策略 + `.ui` 里 minimumSize 90，宽度只由 sizeHint 决定，
    与锚点之间没有任何联动。
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
    """严格对齐：宽度一律取锚点（隐藏演员管理）的 sizeHint，不带任何下限。"""
    return ui.checkBox_hide_actor_nav.sizeHint().width()


def _baseline_without_combo_align(win, app, monkeypatch, width, height):
    """另起窗口、把下拉框钉宽整个摘掉，量两枚锚点与下拉框的自然几何。"""
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
            "actor": (_abs(ui, ui.checkBox_hide_actor_nav), ui.checkBox_hide_actor_nav.width()),
            "border": (_abs(ui, ui.checkBox_hide_window_title), ui.checkBox_hide_window_title.width()),
            "combo": (_abs(ui, ui.comboBox_ui_scale), ui.comboBox_ui_scale.width()),
        }
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_scale_combo_align", original)


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_combo_right_edge_lands_on_actor_nav_right_edge(win, app, width, height):
    """两态都要求：下拉框右缘 == 「隐藏演员管理」右缘（= 左缘 + sizeHint 宽）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = ui.checkBox_hide_actor_nav
    combo = ui.comboBox_ui_scale
    base_left = _abs(ui, base)
    combo_left = _abs(ui, combo)
    assert combo_left == base_left, f"{width} 宽下两行左缘不一致: combo={combo_left} base={base_left}"

    base_right = base_left + base.sizeHint().width()
    combo_right = combo_left + combo.width()
    assert combo_right == base_right, (
        f"{width} 宽下下拉框右缘 {combo_right} 未与「隐藏演员管理」右缘 {base_right} 严格对齐"
        f"（combo 宽 {combo.width()}，基准宽 {base.sizeHint().width()}）"
    )
    # 判据要比 min/max：宽度钉在控件约束上，跨调用留存，只比 width() 会假绿
    want = _want_width(ui)
    assert (combo.minimumWidth(), combo.maximumWidth()) == (want, want), (
        f"{width} 宽下下拉框约束未钉成 {want}: min={combo.minimumWidth()} max={combo.maximumWidth()}"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_actor_nav_never_moves(win, app, monkeypatch, width, height):
    """「隐藏演员管理」位置保持不变，且下拉框确实被缩窄过（不是原本就对齐）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = _baseline_without_combo_align(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    box = ui.checkBox_hide_actor_nav
    assert (_abs(ui, box), box.width()) == base["actor"], (
        f"{width} 宽下「隐藏演员管理」被本需求带偏: 基线={base['actor']} 实际={(_abs(ui, box), box.width())}"
    )
    # 顺带钉住上一批的锚点也没被这次换锚点带偏
    border = ui.checkBox_hide_window_title
    assert (_abs(ui, border), border.width()) == base["border"], (
        f"{width} 宽下「隐藏边框样式」被带偏: 基线={base['border']} 实际={(_abs(ui, border), border.width())}"
    )
    combo = ui.comboBox_ui_scale
    assert combo.width() != base["combo"][1], f"{width} 宽下下拉框宽度没变（{combo.width()}），本需求没生效"


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_strict_alignment_beats_combo_minimum_size_hint(win, app, width, height):
    """严格对齐优先于「不裁字」：宽度必须等于锚点宽，**不许**再取 max(锚点, 最小可用宽)。

    第二批的实现取 `max(锚点宽, combo.minimumSizeHint())`，真机 80% 界面缩放下
    后者更大，下拉框停在最小可用宽、比锚点右出 20px —— 用户截图红框就是这个。
    这条用例把「取 max」这个写法钉死：真机上如果 minimumSizeHint 更大，宽度必须
    仍然等于锚点宽（即允许小于 minimumSizeHint）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    combo = ui.comboBox_ui_scale
    want = ui.checkBox_hide_actor_nav.sizeHint().width()
    assert combo.width() == want, (
        f"{width} 宽下下拉框宽 {combo.width()} != 锚点宽 {want}（minimumSizeHint={combo.minimumSizeHint().width()}）"
    )
    if combo.minimumSizeHint().width() > want:
        assert combo.width() < combo.minimumSizeHint().width(), (
            f"{width} 宽下仍按 max(锚点, minimumSizeHint) 取值，严格对齐没生效"
        )


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
