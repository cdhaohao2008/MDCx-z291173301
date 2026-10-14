"""信息管理页「批量操作」分组贴合内容收紧、省下的高度回到 NFO 列表。

症状（用户截图）：「批量保存」按钮下方的用法提示是一大片空白，标注「删掉空白，
整体高度压缩，多出来的高度加入到NFO文件列表」。

根因两块，都在 `groupBox_nfo_lib_batch` 里：
1. `label_nfo_lib_batch_hint`（wordWrap 说明文字）在 .ui 里钉了 64px 硬下限
   （v2.2.x 为防 Windows 字体/DPI 缩放下末行被裁而加）。而 wordWrap 的展开高度
   恰恰只由 minimumHeight 撑着，下限给大了，文字底下就空一片。
2. `label_nfo_lib_batch_status` 空文本时照样占一整行（14px）+ 6px 间隔，批量
   处理没在跑时也一直白占。

修复：`_sync_nfo_lib_batch_panel` 把提示 label 的下限换成「当前字体在当前宽度下
折行后的实测高」（heightForWidth，运行时算，不能写死常数），`_sync_nfo_lib_batch_status`
让空状态 label 不占位。分组是 `nfo_lib_list_layout` 末位、列表是 Expanding，
省下的高度自动回到 `listWidget_nfo_lib`，故「分组高 + 列表高」恒定。

本文件按「相对关系」断言而非写死像素：离屏环境无中文字体，heightForWidth 会明显
低估（同一份代码在 Windows 正常字体下折行数不同），写死数值必假红。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# .ui 给提示 label 钉的原始硬下限，本用例拿它当「收紧前」的对照
_DESIGN_FLOOR = 64

_SIZES = ((480, 600), (1030, 700), (1080, 750), (1280, 800), (1920, 1080))


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
def nfo_lib_page(win, app, tmp_path):
    """切到信息管理页，灌一批番号，展开分组，并同步一次布局。"""
    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            break
    else:
        raise AssertionError("page_nfo_library not found")

    # 分组默认折叠：本文件测的是展开态下的收紧，先走用户真实路径勾选展开
    win.Ui.groupBox_nfo_lib_batch.setChecked(True)
    for number in range(1, 40):
        win.Ui.listWidget_nfo_lib.addItem(f"MKBD-S{number:02d}-U")
    win.resize(1030, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    return page


def _needed_hint_height(hint) -> int:
    """量出提示文字真正需要多高。

    `QLabel::heightForWidth` 会被 `minimumHeight` 钳住（下限 64 时就返回 64），
    量之前必须先归零，否则量到的永远是当前下限。"""
    previous = hint.minimumHeight()
    hint.setMinimumHeight(0)
    try:
        return hint.heightForWidth(hint.width())
    finally:
        hint.setMinimumHeight(previous)


@pytest.mark.parametrize("size", _SIZES)
def test_hint_floor_is_measured_not_the_design_constant(win, app, nfo_lib_page, size):
    """提示 label 的下限 = 真实字体折行高，而不是 .ui 里那个 64px 硬钉。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    hint = win.Ui.label_nfo_lib_batch_hint
    needed = _needed_hint_height(hint)
    assert needed > 0, f"窗口 {size} 下量不到提示文字高度"
    assert hint.minimumHeight() == needed, f"窗口 {size} 下提示下限 {hint.minimumHeight()} != 实测折行高 {needed}"


@pytest.mark.parametrize("size", _SIZES)
def test_hint_text_never_clipped(win, app, nfo_lib_page, size):
    """收紧不能收掉字：控件实际高度必须够放下折行后的文字。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    hint = win.Ui.label_nfo_lib_batch_hint
    assert hint.height() >= _needed_hint_height(hint), (
        f"窗口 {size} 下提示被裁：控件高 {hint.height()} < 需要 {_needed_hint_height(hint)}"
    )


def test_empty_status_label_takes_no_room(win, app, nfo_lib_page):
    """批量处理没在跑时，空状态 label 不占位。"""
    status = win.Ui.label_nfo_lib_batch_status
    status.setText("")
    win._sync_page_layouts()
    app.processEvents()
    assert status.isHidden(), "空状态 label 仍占着一整行"


def test_status_label_reappears_when_text_written(win, app, nfo_lib_page):
    """写入状态文本后 label 立刻显形（三个写入点都走 _set_nfo_lib_batch_status）。"""
    status = win.Ui.label_nfo_lib_batch_status
    status.setText("")
    win._sync_page_layouts()
    app.processEvents()
    assert status.isHidden()

    win._set_nfo_lib_batch_status("完成: 成功 3 / 失败 0 / 共 3")
    app.processEvents()
    assert not status.isHidden(), "写入状态文本后 label 仍被隐藏"
    assert "成功 3" in status.text()


def test_writing_status_text_does_not_need_manual_sync(win, app, nfo_lib_page):
    """_set_nfo_lib_batch_status 自带显隐同步，不依赖再手动调一次布局同步。"""
    status = win.Ui.label_nfo_lib_batch_status
    win._sync_page_layouts()
    app.processEvents()
    assert status.isHidden()

    win._set_nfo_lib_batch_status("开始批量处理 3 个文件...")
    app.processEvents()
    assert not status.isHidden(), "写入后必须立刻显形，不得等下一次布局同步"


def test_height_is_transferred_from_panel_to_list(win, app, nfo_lib_page, monkeypatch):
    """省下的高度确实回到 NFO 列表：分组高 + 列表高恒定（既没丢也没多）。"""
    ui = win.Ui
    hint = ui.label_nfo_lib_batch_hint
    win.resize(1280, 800)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    tight_group = ui.groupBox_nfo_lib_batch.height()
    tight_list = ui.listWidget_nfo_lib.height()

    # 屏蔽本轮同步、把下限钉回 .ui 设计值 = 还原「收紧前」的旧状态。
    # 必须屏蔽：_sync_page_layouts 内含 _sync_nfo_lib_batch_panel，会把下限又按实测改回去。
    monkeypatch.setattr(win, "_sync_nfo_lib_batch_panel", lambda: None)
    hint.setMinimumHeight(_DESIGN_FLOOR)
    app.processEvents()

    loose_group = ui.groupBox_nfo_lib_batch.height()
    loose_list = ui.listWidget_nfo_lib.height()
    assert loose_group > tight_group, f"钉回 {_DESIGN_FLOOR}px 下限后分组没有变高: {tight_group} -> {loose_group}"
    assert loose_list < tight_list, f"分组变高时列表没有让出等量高度: {tight_list} -> {loose_list}"
    assert loose_group + loose_list == tight_group + tight_list, (
        f"高度没有等量转移: 收紧 {tight_group}+{tight_list} vs 钉死 {loose_group}+{loose_list}"
    )


def test_blank_actually_removed_below_batch_save(win, app, nfo_lib_page, monkeypatch):
    """收紧后「批量保存」下缘到分组底边的空白要比钉死 64px 时小。"""
    ui = win.Ui
    save = ui.pushButton_nfo_lib_batch_save
    group = ui.groupBox_nfo_lib_batch
    hint = ui.label_nfo_lib_batch_hint
    win.resize(1030, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    tight_gap = group.height() - (save.geometry().y() + save.height())

    monkeypatch.setattr(win, "_sync_nfo_lib_batch_panel", lambda: None)
    hint.setMinimumHeight(_DESIGN_FLOOR)
    app.processEvents()
    loose_gap = group.height() - (save.geometry().y() + save.height())

    assert tight_gap < loose_gap, f"「批量保存」下方空白未减少: {tight_gap} vs {loose_gap}"


@pytest.mark.parametrize("size", _SIZES)
def test_sync_is_idempotent(win, app, nfo_lib_page, size):
    """多跑几遍不抖动（下限不能来回跳，也不得把文字裁了）。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    hint = win.Ui.label_nfo_lib_batch_hint
    first = hint.minimumHeight()
    for _ in range(3):
        win._sync_nfo_lib_batch_panel()
    app.processEvents()
    assert hint.minimumHeight() == first, f"重复同步后下限漂移: {first} -> {hint.minimumHeight()}"


@pytest.mark.parametrize("size", _SIZES)
def test_still_no_overlap_after_compacting(win, app, nfo_lib_page, size):
    """收紧不得把上一轮修好的「分组压住列表」问题带回来。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    list_geo = win.Ui.listWidget_nfo_lib.geometry()
    batch_geo = win.Ui.groupBox_nfo_lib_batch.geometry()
    assert list_geo.bottom() <= batch_geo.top(), (
        f"窗口 {size} 下「批量操作」压住 NFO 列表: {list_geo.bottom()} > {batch_geo.top()}"
    )
