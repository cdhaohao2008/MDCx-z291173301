"""信息管理页左栏结构：标题删掉、全选顶上、分组默认折叠。

用户需求：「NFO文件列表」标题 label 删掉，全选/全不选按钮上移到选择目录按钮
下方（顶栏顺序被 `test_top_bar_order_and_dir_box_expands_left` 锁死不能进顶栏，
故放在左栏首行，紧贴顶栏下方）；以及之前发现的遗留问题：`groupBox_nfo_lib_batch`
在 .ui 里声明了 checkable + unchecked，本意默认折叠，但 pyuic6 在子控件建好之前
就调了 setCheckable / setChecked，Qt 当时无子控件可管，分组从未真正折叠过——
只剩 unchecked 自带的「子控件全 disabled」：控件灰着，却照样占满 200 多 px。

修复：删标题 label（.ui + 重编译 MDCx.py）；`toggled` 接到
`_on_nfo_lib_batch_toggled` 做真正的显隐折叠，init 里调一次完成默认折叠。
Qt 自己管 enabled（勾选自动 enable、去勾自动 disable），与显隐管理不冲突。

本文件只按「相对关系」断言，不写死像素（离屏无中文字体，高度与实机不同）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

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
    """切到信息管理页，灌一批番号，走一遍布局（分组保持默认折叠）。"""
    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            break
    else:
        raise AssertionError("page_nfo_library not found")

    for number in range(1, 40):
        win.Ui.listWidget_nfo_lib.addItem(f"MKBD-S{number:02d}-U")
    win.resize(1030, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    return page


def _batch_children(win) -> list:
    """分组的直属子控件（按钮/输入框/提示/状态行共 11 个，不含布局）。"""
    gb = win.Ui.groupBox_nfo_lib_batch
    return [c for c in gb.findChildren(QWidget) if c.parentWidget() is gb]


def test_list_title_label_removed(win, app, nfo_lib_page):
    """「NFO文件列表」标题 label 已删掉（Ui 上无残留）。"""
    assert not hasattr(win.Ui, "label_nfo_lib_list_title"), "Ui 仍残留 label_nfo_lib_list_title 属性"
    assert win.findChild(QLabel, "label_nfo_lib_list_title") is None, "界面里仍有 NFO文件列表 标题"


def test_select_buttons_are_first_row_of_left_column(win, app, nfo_lib_page):
    """左栏只剩三项：全选行 → 列表 → 分组，全选行是首项。"""
    ui = win.Ui
    layout = ui.nfo_lib_list_layout
    assert layout.count() == 3, f"左栏项数不对: {layout.count()}"
    assert layout.itemAt(0).layout() is ui.nfo_lib_select_btns_layout, "左栏首项不是全选/全不选行"
    assert layout.itemAt(1).widget() is ui.listWidget_nfo_lib, "左栏第二项不是 NFO 列表"
    assert layout.itemAt(2).widget() is ui.groupBox_nfo_lib_batch, "左栏末项不是批量操作分组"
    members = {layout.itemAt(0).layout().itemAt(i).widget() for i in range(2)}
    assert members == {ui.pushButton_nfo_lib_select_all, ui.pushButton_nfo_lib_select_none}, "全选行成员不对"


def test_select_buttons_sit_below_top_bar_above_list(win, app, nfo_lib_page):
    """全选行在顶栏下方、列表上方（同一父控件下比 y）。"""
    ui = win.Ui
    assert ui.nfo_lib_content.y() >= ui.nfo_lib_top_bar.y() + ui.nfo_lib_top_bar.height(), "左栏不在顶栏下方"
    assert ui.pushButton_nfo_lib_select_all.y() < ui.listWidget_nfo_lib.y(), "全选行不在列表上方"
    assert ui.pushButton_nfo_lib_select_none.y() < ui.listWidget_nfo_lib.y(), "全不选行不在列表上方"


def test_batch_panel_collapsed_by_default(win, app, nfo_lib_page):
    """新窗口分组默认就是折叠的：未勾选 + 子控件全隐藏。"""
    gb = win.Ui.groupBox_nfo_lib_batch
    assert gb.isCheckable() and not gb.isChecked(), "分组应保持 checkable + unchecked"
    kids = _batch_children(win)
    assert kids, "分组里没有直属子控件"
    assert all(c.isHidden() for c in kids), "默认折叠下仍有子控件没藏起来"


def test_toggle_expands_and_collapses(win, app, nfo_lib_page):
    """勾选展开 / 去勾折叠往返：高度在分组与列表之间等量转移。"""
    ui = win.Ui
    gb = ui.groupBox_nfo_lib_batch
    fired = []
    gb.toggled.connect(lambda on: fired.append(on))

    collapsed_gb = gb.height()
    collapsed_list = ui.listWidget_nfo_lib.height()

    gb.setChecked(True)  # 用户勾选标题：展开
    app.processEvents()
    assert fired == [True], "勾选没有发射 toggled"
    kids = _batch_children(win)
    assert all(not c.isHidden() for c in kids if c is not ui.label_nfo_lib_batch_status), "展开后子控件仍被隐藏"
    assert all(c.isEnabled() for c in kids), "展开后子控件仍被 disable"
    assert gb.height() > collapsed_gb, f"展开后分组没有变高: {collapsed_gb} -> {gb.height()}"
    assert ui.listWidget_nfo_lib.height() < collapsed_list, "展开后列表没有让出高度"
    assert gb.height() + ui.listWidget_nfo_lib.height() == collapsed_gb + collapsed_list, "高度没有等量转移"

    gb.setChecked(False)  # 用户去勾：折叠回去
    app.processEvents()
    assert fired == [True, False], "去勾没有发射 toggled"
    assert all(c.isHidden() for c in _batch_children(win)), "折叠后仍有子控件可见"
    assert gb.height() == collapsed_gb, f"折叠后分组没有回到原高: {gb.height()} != {collapsed_gb}"
    assert ui.listWidget_nfo_lib.height() == collapsed_list, "折叠后列表没有拿回高度"


def test_status_row_follows_text_across_toggle(win, app, nfo_lib_page):
    """状态行显隐跟着文本走，不受折叠干扰：折叠时不冒头，展开后文本还在就显形。"""
    ui = win.Ui
    gb = ui.groupBox_nfo_lib_batch
    status = ui.label_nfo_lib_batch_status
    win.show()  # 有效可见性（isVisibleTo）必须在 show 后才有意义，离屏 show 无副作用
    app.processEvents()

    gb.setChecked(True)
    app.processEvents()
    win._set_nfo_lib_batch_status("完成: 成功 3 / 失败 0 / 共 3")
    app.processEvents()
    assert not status.isHidden(), "展开态写入文本后状态行仍被隐藏"

    gb.setChecked(False)
    app.processEvents()
    assert not status.isVisibleTo(win), "折叠后状态行仍可见"
    assert status.text(), "折叠不应清空状态文本"

    gb.setChecked(True)
    app.processEvents()
    assert not status.isHidden() and status.isVisibleTo(win), "重新展开后状态行没有恢复"

    win._set_nfo_lib_batch_status("")
    app.processEvents()
    assert status.isHidden(), "清空文本后状态行仍占位"
