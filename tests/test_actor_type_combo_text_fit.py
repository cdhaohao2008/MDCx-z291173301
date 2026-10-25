"""工具页「类型」下拉框文案不被截字（自动判断 / 有码番号 / … 四个汉字要完整显示）。

用户 2026-10-25 报：「自动判断」最后一个字只显示一半。

根因：这个下拉框的宽度被「与选择目录按钮严格上下对齐」钉死在 110px，而通用
`QComboBox` 样式给了 `padding: 3px 30px 3px 8px`——右内边距 30px 与 26px 的
drop-down 箭头**重复占位**（Qt 已从内容区扣过箭头宽），110px 的框里文本区只剩
44px，而四个 13px 汉字要 52px，末字被截掉一半。`comboBox_ui_scale` 早就踩过同一个坑
（见 style.py 里那段注释），这里沿用同一修法：`QComboBox#comboBox_actor_type`
把右内边距清零，文本区 44→74px，外框宽度与箭头位置都不动。

本文件在真实主窗口上量 `SC_ComboBoxEditField` 的实际宽度，明暗两套主题各测一次。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    orig_cwd = os.getcwd()
    tmp = str(tmp_path_factory.mktemp("combofit"))
    os.chdir(tmp)
    orig = []
    for owner, name, fn in (
        (mw_mod, "run_startup_health_checks", lambda: None),
        (mw_mod, "show_netstatus", lambda: None),
        (window_ops_mod, "check_version", lambda: None),
        (mw_mod, "save_remain_list", lambda: None),
        (window_ops_mod, "apply_site_priority_theme", lambda _w: None),
    ):
        orig.append((owner, name, getattr(owner, name)))
        setattr(owner, name, fn)
    orig_qtr = style_mod.resources.qtr
    style_mod.resources.qtr = lambda path: str(MAIN_PATH / "resources" / path)
    window = mw_mod.MyMAinWindow()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        try:
            getattr(window, t).stop()
        except Exception:
            pass
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    for owner, name, value in orig:
        setattr(owner, name, value)
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _edit_field_width(combo) -> int:
    """下拉框里真正画文字的矩形宽度（样式算出来的，不是自己按 padding 推）。"""
    opt = QStyleOptionComboBox()
    combo.initStyleOption(opt)
    rect = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, combo
    )
    return rect.width()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_actor_type_combo_text_area_fits_four_cjk_chars(win, app, theme):
    ui = win.Ui
    win.resize(1050, 800)
    win.show()
    app.processEvents()
    ui.stackedWidget.setCurrentWidget(ui.page_tool)
    app.processEvents()

    if theme == "light":
        # set_style() 在 dark_mode 为真时会转调 set_dark_style() 并直接返回，
        # 想测亮色那套 QSS 必须先把开关压回 False（配置里开着暗色时尤其重要）
        win.dark_mode = False
        win.set_style()
    else:
        win.dark_mode = True
        win.set_dark_style()
    app.processEvents()

    combo = ui.comboBox_actor_type
    # 汉字在 13px 字号下按 1em 宽算，四项里最长的是四个汉字
    longest = max((combo.itemText(i) for i in range(combo.count())), key=len)
    need = combo.font().pixelSize() * len(longest)
    assert _edit_field_width(combo) >= need, (
        f"{theme}: 文本区 {_edit_field_width(combo)}px 放不下「{longest}」的 {need}px"
    )
    # 外框仍是 110×30（与「选择目录」按钮对齐的硬约束），修的是内部留白不是外框
    assert (combo.width(), combo.height()) == (110, 30)
