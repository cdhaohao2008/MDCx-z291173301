"""设置-高级页「任务模式」行：「网盘存储文件」与「使用暗黑模式」严格上下对齐 + 隐藏窗口行不再压字。

需求（2026-10-23，最小化 / 最大化两张用户截图）：
  ① 还原态「网盘存储文件」**向左**、最大化态**向右**，都落在「使用暗黑模式」那条竖线上；
     「使用暗黑模式」自身位置保持不变。
  ② 「隐藏窗口」行的三枚单选（点击关闭按钮 / 点最小化按钮 / 无）原先与「隐藏Dock图标
     （Mac）/ 隐藏菜单栏图标（Mac）/ 保存后重启生效」挤在同一个网格格里互相压字，
     现在单选独占一行、复选框行下移一行，两行不得有任何垂直重叠。

实现：
  - `_sync_advanced_page_task_mode_align()`：任务模式行容器取「界面外观」行同宽，
    前导项「本地存储文件」钉成「隐藏边框（美观样式）」等宽，末位即落「使用暗黑模式」竖线。
  - .ui：gridLayout_20 里 horizontalLayout_dock 从 row9 挪到 row10（独占一行），
    其后各行 +1，组框与内嵌 grid 各加高 30px。
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
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda *args, **kwargs: None)
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


def _pos(ui, widget):
    p = widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0))
    return (p.x(), p.y())


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


_SIZES = ((1920, 1170), (1536, 864), (1366, 850), (1200, 800), (1085, 793), (1030, 753))


@pytest.mark.parametrize("width,height", _SIZES)
def test_task_mode_netdisk_aligns_with_dark_mode(win, app, width, height):
    """「网盘存储文件」与「使用暗黑模式」严格上下对齐；「使用暗黑模式」自身不因本需求移动。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    netdisk = _pos(ui, ui.checkBox_task_store_netdisk)
    dark = _pos(ui, ui.checkBox_dark_mode)
    assert netdisk[0] == dark[0], f"{width}x{height} 下「网盘存储文件」x={netdisk[0]} 与「使用暗黑模式」x={dark[0]} 未对齐"
    # 末位项必须完整显示：容器被压窄到裁字时本需求就不成立
    assert ui.checkBox_task_store_netdisk.width() >= ui.checkBox_task_store_netdisk.sizeHint().width(), (
        f"{width}x{height} 下「网盘存储文件」被压窄到裁字"
    )


def test_task_mode_alignment_survives_round_trip(win, app):
    """窄→宽→窄往返后仍对齐（钉宽与容器宽度都是幂等的）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    _resize(win, app, 1085, 793)
    narrow = _pos(ui, ui.checkBox_task_store_netdisk)
    assert narrow[0] == _pos(ui, ui.checkBox_dark_mode)[0]

    _resize(win, app, 1920, 1170)
    wide = _pos(ui, ui.checkBox_task_store_netdisk)
    assert wide[0] == _pos(ui, ui.checkBox_dark_mode)[0]

    _resize(win, app, 1085, 793)
    assert _pos(ui, ui.checkBox_task_store_netdisk) == narrow, "窄→宽→窄往返未复原"


@pytest.mark.parametrize("width,height", _SIZES)
def test_hide_window_rows_do_not_overlap(win, app, width, height):
    """「隐藏窗口」单选行与下方「隐藏Dock图标」复选框行不得垂直重叠。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    radios = (ui.radioButton_hide_close, ui.radioButton_hide_mini, ui.radioButton_hide_none)
    boxes = (ui.checkBox_hide_dock_icon, ui.checkBox_hide_menu_icon, ui.label_42)

    radio_bottom = max(_pos(ui, w)[1] + w.height() for w in radios)
    box_top = min(_pos(ui, w)[1] for w in boxes)
    assert radio_bottom <= box_top, f"{width}x{height} 下单选行底 {radio_bottom} 压到复选框行顶 {box_top}"

    # 单选行必须与「隐藏窗口：」垂直居中（行高一致，不允许再靠偏移凑位置）
    label_313 = ui.label_313  # 隐藏窗口：
    for w in radios:
        center = _pos(ui, w)[1] + w.height() / 2
        label_center = _pos(ui, label_313)[1] + label_313.height() / 2
        assert abs(center - label_center) <= 1, f"{w.objectName()} 未与「隐藏窗口：」垂直居中"
    # 「隐藏图标：」与「隐藏Dock图标（Mac）」那一行同行居中
    label_314 = ui.label_314
    label_314_center = _pos(ui, label_314)[1] + label_314.height() / 2
    for w in (ui.checkBox_hide_dock_icon, ui.checkBox_hide_menu_icon, ui.label_42):
        center = _pos(ui, w)[1] + w.height() / 2
        assert abs(center - label_314_center) <= 1, f"{w.objectName()} 未与「隐藏图标：」垂直居中"
    # 「界面外观：」与「隐藏边框（美观样式）」「使用暗黑模式」同行居中
    label_246 = ui.label_246
    label_246_center = _pos(ui, label_246)[1] + label_246.height() / 2
    for w in (ui.checkBox_hide_window_title, ui.checkBox_dark_mode):
        center = _pos(ui, w)[1] + w.height() / 2
        assert abs(center - label_246_center) <= 1, f"{w.objectName()} 未与「界面外观：」垂直居中"
