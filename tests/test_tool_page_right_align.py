"""软件工具页右边界与软件设置页对齐回归测试.

需求：工具页卡片右缘与设置页同类卡片齐平，左缘不动。
设置页滚动区加宽 4px（tab 右边距 20→16，滚动条右缘收到页宽-18）后两侧视口差
消失、自然齐平（曾用 scrollArea_10 内收 4px 补偿恒定差，现已取消）。
本测试在两个窗宽下断言对齐。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QGroupBox

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
    # check_version / apply_site_priority_theme 随 WindowOpsMixin 一起移出 main_window.py
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    orig_cwd = os.getcwd()
    tmp = str(tmp_path_factory.mktemp("toolalign"))
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
    orig_style = mw_mod.MyMAinWindow.set_style
    mw_mod.MyMAinWindow.set_style = lambda self: None
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
    mw_mod.MyMAinWindow.set_style = orig_style
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _max_group_right(content) -> int:
    return max(
        (c.x() + c.width() for c in content.findChildren(QGroupBox) if c.parentWidget() == content),
        default=-1,
    )


@pytest.mark.parametrize("width", [1170, 1600])
def test_tool_right_aligns_with_setting(win, app, width):
    from mdcx.views.CustomClass import CustomScrollArea as CSA

    ui = win.Ui
    win.resize(width, 800)
    win.show()
    app.processEvents()
    for page in (ui.page_tool, ui.page_setting):
        ui.stackedWidget.setCurrentWidget(page)
        app.processEvents()
        app.processEvents()
        win._sync_page_layouts()
        app.processEvents()
    tool_right = _max_group_right(ui.scrollArea_10.widget())
    cur = ui.tabWidget.currentWidget()
    sa = next((a for a in cur.findChildren(CSA) if a.parentWidget() == cur), None)
    assert sa is not None and sa.widget() is not None
    setting_right = _max_group_right(sa.widget())
    assert tool_right == setting_right, (width, tool_right, setting_right)
    # 左缘不动：演员库分组左缘保持设计值 30
    assert ui.groupBox_actor_db_maintenance.x() == 30
