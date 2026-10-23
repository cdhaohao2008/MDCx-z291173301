"""设置-高级页「移动文件」行：「覆盖目标文件」「保留目标文件」与「界面外观」行严格上下对齐。

需求（用户截图红框）：
  「覆盖目标文件」与「隐藏边框（美观样式）」严格上下对齐；
  「保留目标文件」与「使用暗黑模式」严格上下对齐；
  「隐藏边框（美观样式）」「使用暗黑模式」自身位置保持不变。

实现：_sync_advanced_page_move_file_align() 把新行前导项「覆盖目标文件」钉成与
锚点前导项「隐藏边框（美观样式）」等宽，末位「保留目标文件」即落在「使用暗黑模式」的
竖线上（末位项吃掉行内余量、自身左对齐绘制）。锚点行只读不写。
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


_SIZES = ((1920, 1170), (1366, 850), (1100, 800), (1030, 753), (1000, 700))


@pytest.mark.parametrize("width,height", _SIZES)
def test_move_file_checkboxes_align_with_appearance_row(win, app, width, height):
    """「覆盖目标文件」对齐「隐藏边框」，「保留目标文件」对齐「使用暗黑模式」。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    overwrite = _abs(ui, ui.checkBox_move_overwrite)
    keep = _abs(ui, ui.checkBox_move_keep)
    lead = _abs(ui, ui.checkBox_hide_window_title)
    dark = _abs(ui, ui.checkBox_dark_mode)

    assert overwrite == lead, f"{width} 宽下「覆盖目标文件」x={overwrite} 未对齐「隐藏边框」x={lead}"
    assert keep == dark, f"{width} 宽下「保留目标文件」x={keep} 未对齐「使用暗黑模式」x={dark}"


@pytest.mark.parametrize("width,height", _SIZES)
def test_move_file_align_does_not_move_anchor_checkboxes(win, app, width, height):
    """锚点两枚自身位置保持不变：再跑一次同步后坐标逐位不变。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    before = (_abs(ui, ui.checkBox_hide_window_title), _abs(ui, ui.checkBox_dark_mode))
    win._sync_advanced_page_move_file_align()
    app.processEvents()
    after = (_abs(ui, ui.checkBox_hide_window_title), _abs(ui, ui.checkBox_dark_mode))

    assert before == after, f"{width} 宽下同步后锚点位移：{before} -> {after}"


@pytest.mark.parametrize("width,height", _SIZES)
def test_move_file_checkboxes_are_not_squeezed(win, app, width, height):
    """两枚复选框都不得被压到裁字。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    for box in (ui.checkBox_move_overwrite, ui.checkBox_move_keep):
        assert box.width() >= box.sizeHint().width(), (
            f"{width} 宽下「{box.text()}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )
