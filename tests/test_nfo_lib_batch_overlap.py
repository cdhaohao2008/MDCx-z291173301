"""信息管理页左栏「NFO 文件列表」与「批量操作」面板不得重叠。

症状（用户截图反馈）：窗口不够高时，左栏 QVBoxLayout 里最后一项「批量操作」
分组的顶边被顶进列表里，分组标题「批量操作（选中多条后使用）」压在
列表最后几行番号上（截图里正好压住 MKBD-S100-U / MKBD-S102-U）。

根因：`listWidget_nfo_lib` 在 .ui 里钉了 `minimumSize = 280×320` 的硬下限，
而左栏内容最小高合计 653px（标题 14 + 全选行 22 + 列表 320 + 分组 279 + 间隔），
窗口一矮面板就放不下，Qt 布局引擎在约束无解时会给出互相穿插的几何（实测
窗口 1030×700 重叠 30px、480×600 重叠 82px），于是分组盖住列表尾部。

修复：把列表的硬下限从 320 降到 120（宽度下限 280 不动，保住左栏不被挤窄）。
列表是自带滚动条的 QListWidget，本就吃富余高度（1920×1080 下仍是 663px），
下限只在窗口矮到放不下时才起作用；120 远低于面板在任何合法窗口尺寸下的
自然份额（480×600 时也有 183px），故列表不会再把分组顶出可视区。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# 主窗允许的最小尺寸（MyMAinWindow.minimumSize = 480×600）到常用大窗
_SIZES = ((480, 600), (800, 600), (900, 650), (1030, 700), (1080, 750), (1280, 800), (1366, 768), (1920, 1080))


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

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
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


@pytest.fixture()
def nfo_lib_page(win, app):
    """切到信息管理页并完成一次布局。"""
    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            app.processEvents()
            return page
    raise AssertionError("page_nfo_library not found")


@pytest.mark.parametrize("size", _SIZES)
def test_batch_panel_never_overlaps_nfo_list(win, app, nfo_lib_page, size):
    """任意合法窗口尺寸下，批量操作分组的顶边都不得落进列表矩形内。"""
    win.resize(*size)
    app.processEvents()

    list_geo = win.Ui.listWidget_nfo_lib.geometry()
    batch_geo = win.Ui.groupBox_nfo_lib_batch.geometry()
    assert list_geo.bottom() <= batch_geo.top(), (
        f"窗口 {size} 下「批量操作」压住 NFO 列表：列表底 {list_geo.bottom()} > 分组顶 {batch_geo.top()}"
    )


@pytest.mark.parametrize("size", _SIZES)
def test_batch_panel_stays_inside_left_column(win, app, nfo_lib_page, size):
    """分组整体不得被挤出左栏（否则底部按钮会掉到面板外看不见）。"""
    win.resize(*size)
    app.processEvents()

    panel_height = win.Ui.nfo_lib_list_panel.height()
    batch_geo = win.Ui.groupBox_nfo_lib_batch.geometry()
    assert batch_geo.bottom() <= panel_height, (
        f"窗口 {size} 下「批量操作」底部 {batch_geo.bottom()} 超出左栏 {panel_height}"
    )


def test_nfo_list_keeps_usable_height_at_common_sizes(win, app, nfo_lib_page):
    """治本不能治到列表头上：常用窗口尺寸下列表仍要够高，且富余高度仍归它。"""
    win.resize(1920, 1080)
    app.processEvents()
    assert win.Ui.listWidget_nfo_lib.height() >= 320, "大窗下列表被压扁了"

    win.resize(1030, 700)
    app.processEvents()
    assert win.Ui.listWidget_nfo_lib.height() >= 200, "常用窗口下列表被压扁了"
