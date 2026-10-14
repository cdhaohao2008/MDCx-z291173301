"""信息管理页左栏「NFO 列表」与「批量操作」面板不得重叠。

症状（用户截图反馈）：窗口不够高时，左栏 QVBoxLayout 里最后一项「批量操作」
分组的顶边被顶进列表里，分组标题「批量操作（选中多条后使用）」压在
列表最后几行番号上（截图里正好压住 MKBD-S100-U / MKBD-S102-U）。

根因：`listWidget_nfo_lib` 在 .ui 里钉了 `minimumSize = 280×320` 的硬下限，
左栏放不下时 Qt 布局引擎在约束无解时会给出互相穿插的几何（实测窗口 1030×700
重叠 30px、480×600 重叠 82px），于是分组盖住列表尾部。

修复：列表硬下限 320 降到 120（宽度下限 280 不动）；「NFO文件列表」标题 label
删掉，全选/全不选行顶到左栏首行；分组默认折叠。本文件统一在展开态下断言
（最占地方的最坏情况），折叠态只会更宽松。
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
    """切到信息管理页并完成一次布局；展开分组，测最占地方的展开态。"""
    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            app.processEvents()
            break
    else:
        raise AssertionError("page_nfo_library not found")
    # 分组默认折叠：重叠只可能发生在展开态，先走用户真实路径勾选展开
    win.Ui.groupBox_nfo_lib_batch.setChecked(True)
    app.processEvents()
    return page


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
