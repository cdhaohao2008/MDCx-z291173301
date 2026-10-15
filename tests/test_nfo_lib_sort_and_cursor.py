"""信息管理页：NFO 列表自然排序 + 回填展示框光标归零。

需求 ①：列表按 01-09、10、11……自然排序，而不是字典序（01-09 后直接 100、101）。
根因两处：插入时按 `p.name.lower()` 字典序排；且 listWidget 开着 `sortingEnabled`
（`.ui` 里 true，`retranslateUi` 会调 `setSortingEnabled(True)`），插入顺序再好
也会被视图按字典序重排。修复：插入改自然键 `_natural_sort_key`，
`.ui` 里 sortingEnabled 改 false（重编译 MDCx.py，`test_mdcx_py_in_sync_with_ui` 锁死同步）。

需求 ②：所有回填展示框光标归零，从左向右展示（优先看到 http(s):// 前缀）。
`QLineEdit.setText` 后光标停末尾；`QPlainTextEdit.setPlainText` 后光标位置不保证在头。
修复都在 `on_nfo_lib_data_loaded`：单行框逐个 `setCursorPosition(0)`，
多行框 `setTextCursor(QTextCursor(document))`（构造出的光标恒在 0 位）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

_app: QApplication | None = None

# 用户截图里的番号段：01-09 紧跟 10、11，而不是 100、101
_SORT_NAMES = (
    "MKBD-S01-U",
    "MKBD-S02-U",
    "MKBD-S03-U",
    "MKBD-S04-U",
    "MKBD-S05-U",
    "MKBD-S06-U",
    "MKBD-S07-U",
    "MKBD-S08-U",
    "MKBD-S09-U",
    "MKBD-S10-U",
    "MKBD-S11-U",
    "MKBD-S100-U",
    "MKBD-S101-U",
)

# on_nfo_lib_data_loaded 回填的全部单行展示框
_LINE_FIELDS = (
    "number",
    "title",
    "actor",
    "release",
    "year",
    "runtime",
    "director",
    "studio",
    "publisher",
    "series",
    "score",
    "cover_url",
    "poster_url",
)


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
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "nfo_lib_batch_expanded", True)
    monkeypatch.setattr(manager, "save", lambda: None, raising=False)
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
    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            app.processEvents()
            return page
    raise AssertionError("page_nfo_library not found")


def test_natural_sort_key_orders_numbers_numerically():
    """自然键：数字段按数值比（S100 > S11），前导零不影响相等性。"""
    from mdcx.controllers.main_window.nfo_library import _natural_sort_key

    assert _natural_sort_key("mkbd-s100-u") > _natural_sort_key("mkbd-s11-u")
    assert _natural_sort_key("mkbd-s10-u") > _natural_sort_key("mkbd-s09-u")
    assert _natural_sort_key("mkbd-s01-u") == _natural_sort_key("mkbd-s1-u")
    ordered = sorted(
        ["MKBD-S100-U", "MKBD-S11-U", "MKBD-S02-U", "MKBD-S10-U", "MKBD-S01-U"],
        key=lambda name: _natural_sort_key(name.lower()),
    )
    assert ordered == ["MKBD-S01-U", "MKBD-S02-U", "MKBD-S10-U", "MKBD-S11-U", "MKBD-S100-U"]


def test_list_sorts_naturally_after_refresh(win, app, nfo_lib_page, tmp_path):
    """真实目录刷新后，列表按 01-09、10、11、100、101 排列（非字典序）。"""
    folder = tmp_path / "nfo_lib"
    folder.mkdir()
    # 故意打乱写入顺序：插入顺序不得影响最终排列
    for name in ("MKBD-S101-U", "MKBD-S02-U", "MKBD-S100-U", "MKBD-S11-U", "MKBD-S01-U"):
        (folder / f"{name}.nfo").write_text("<movie><title>T</title></movie>", encoding="utf-8")
    for name in _SORT_NAMES:
        if not (folder / f"{name}.nfo").exists():
            (folder / f"{name}.nfo").write_text("<movie><title>T</title></movie>", encoding="utf-8")

    win.Ui.lineEdit_nfo_lib_dir.setText(str(folder))
    win.pushButton_nfo_lib_refresh_clicked()
    app.processEvents()

    assert win.Ui.listWidget_nfo_lib.isSortingEnabled() is False, "视图自动排序必须关闭，否则自然序会被字典序重排"
    order = [win.Ui.listWidget_nfo_lib.item(i).text() for i in range(win.Ui.listWidget_nfo_lib.count())]
    assert order == list(_SORT_NAMES), f"列表不是自然序: {order}"


def test_all_display_fields_cursor_at_start(win, app, nfo_lib_page):
    """回填后全部单行展示框光标归零，简介/标签多行框光标也在开头。"""
    from mdcx.models.model_types import CrawlersResult

    long_text = "https://example.com/" + "very/long/path/" * 20
    data = CrawlersResult.empty()
    data.number = "MKBD-S01"
    data.title = long_text
    data.actor = "actor1," * 30
    data.release = "2011-06-16-extra-long-suffix"
    data.year = "2011-extra"
    data.runtime = "110-extra"
    data.directors = ["director-with-a-very-long-name", "d2"]
    data.studio = long_text
    data.publisher = long_text
    data.series = long_text
    data.score = "4.6-extra"
    data.outline = "line1\nline2\nline3\nline4\nline5\n" * 10
    data.tag = "tag1," * 40
    data.thumb = long_text + "/cover.jpg"
    data.poster = long_text + "/poster.jpg"
    win._nfo_lib_pending_data = data
    win._nfo_lib_pending_info = None
    win.on_nfo_lib_data_loaded("dummy")
    app.processEvents()

    for field in _LINE_FIELDS:
        widget = getattr(win.Ui, "lineEdit_nfo_lib_" + field)
        assert isinstance(widget, QWidget) and widget.cursorPosition() == 0, f"{field} 光标不在开头"
    assert win.Ui.plainTextEdit_nfo_lib_outline.textCursor().position() == 0, "简介光标不在开头"
    assert win.Ui.plainTextEdit_nfo_lib_tag.textCursor().position() == 0, "标签光标不在开头"
