"""全局输入框「内容优先从左展示」回归测试。

需求：「信息管理-选择目录左侧显示框的内容也要从左向右展示，软件所有显示框的内容都
优先从左向右展示」——程序回填长路径 / 长 URL 后，视图必须停在最左侧露出 `https://`
这类前缀，而不是停在末尾把开头滚出可视区。

做法与本文件锁定的三条要点：

1. `left_anchor_text_edits(root)` 对树里的 QLineEdit 挂 `textChanged` 回调，仅在控件
   **无焦点**时把插入点拉回 0（有焦点 = 用户正在输入/粘贴，一律不插手）；
2. **只钩 QLineEdit**——QPlainTextEdit / QTextEdit 的 `setPlainText` 自会把光标复位到 0，
   而在它们的 `textChanged` 里动光标会让 Qt 硬崩（0xC0000409），必须由「只钩单行框」
   从结构上避开（见 `test_multiline_edits_are_not_hooked`）；
3. 幂等：已挂过的控件用动态属性标记，重复调用不再挂钩。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from mdcx.utils.qt_text import anchor_if_idle, left_anchor_text_edits

_HOOK_FLAG = "_left_anchor_hooked"

_app: QApplication | None = None

_LONG = "https://example.com/a/very/long/path/that/would/otherwise/scroll/the/beginning/away"


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def root(app):
    """一棵含 3 个单行框 + 1 个多行框的最小控件树。"""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    for _ in range(3):
        layout.addWidget(QLineEdit(widget))
    layout.addWidget(QPlainTextEdit(widget))
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def _line_edits(root):
    return root.findChildren(QLineEdit)


# ============= 1. 钩子只挂单行框，且幂等 =============


def test_hooks_line_edits_only(root):
    """只钩 QLineEdit；多行框必须排除（在 textChanged 里动它的光标会让 Qt 硬崩）。"""
    hooked = left_anchor_text_edits(root)
    assert hooked == 3, f"应恰好挂 3 个单行框，实际 {hooked}"

    multiline = root.findChildren(QPlainTextEdit)[0]
    assert not multiline.property(_HOOK_FLAG), "多行框不应被挂钩"
    for edit in _line_edits(root):
        assert edit.property(_HOOK_FLAG), "单行框未挂上钩子"


def test_hook_is_idempotent(root):
    """重复调用不再挂钩（init 与后续动态建控件可能各调一次）。"""
    assert left_anchor_text_edits(root) == 3
    assert left_anchor_text_edits(root) == 0
    assert left_anchor_text_edits(None) == 0


def test_root_itself_is_covered(app):
    """root 本身就是 QLineEdit 时也要能挂上（findChildren 不含自身）。"""
    edit = QLineEdit()
    edit.show()
    app.processEvents()
    assert left_anchor_text_edits(edit) == 1
    edit.clearFocus()  # 焦点在框内时不抢光标（见 test_focused_edit_keeps_cursor）
    app.processEvents()
    edit.setText(_LONG)
    app.processEvents()
    assert edit.cursorPosition() == 0
    edit.close()


# ============= 2. 无焦点才拉回，有焦点不插手 =============


def test_unfocused_edit_anchors_to_start(root, app):
    """程序回填（控件无焦点）→ 光标回到 0，露出开头。"""
    left_anchor_text_edits(root)
    for edit in _line_edits(root):
        edit.clearFocus()  # offscreen 会把焦点给首个可聚焦子控件，先全部清掉
    app.processEvents()
    for edit in _line_edits(root):
        edit.setText(_LONG)
    app.processEvents()
    assert [e.cursorPosition() for e in _line_edits(root)] == [0, 0, 0]


def test_focused_edit_keeps_cursor(root, app):
    """用户正在输入（有焦点）→ 绝不能抢光标。"""
    left_anchor_text_edits(root)
    edit = _line_edits(root)[0]
    edit.setFocus()
    app.processEvents()
    edit.setText(_LONG)
    app.processEvents()
    assert edit.cursorPosition() == len(_LONG), "用户输入时光标被拽回开头了"
    edit.clearFocus()


def test_cursor_anchored_again_after_blur(root, app):
    """失焦后再次被程序回填 → 又回到 0（钩子一直有效）。"""
    left_anchor_text_edits(root)
    edit = _line_edits(root)[0]
    edit.setFocus()
    app.processEvents()
    edit.setText(_LONG)
    app.processEvents()
    edit.clearFocus()
    app.processEvents()
    edit.setText(_LONG + "/second")
    app.processEvents()
    assert edit.cursorPosition() == 0


def test_multiline_set_plain_text_alone_does_not_crash(root, app):
    """多行框只靠 setPlainText 自复位（光标本就回 0），不挂钩也不会崩。"""
    multiline = root.findChildren(QPlainTextEdit)[0]
    multiline.setPlainText("内容" * 500)
    app.processEvents()
    assert multiline.textCursor().position() == 0


def test_anchor_if_idle_helper(root, app):
    """单点工具：焦点在外时立即拉回，焦点在内时不动。"""
    multiline = root.findChildren(QPlainTextEdit)[0]
    anchor_if_idle(multiline)
    assert multiline.textCursor().position() == 0

    edit = _line_edits(root)[0]
    edit.setFocus()
    app.processEvents()
    edit.setText(_LONG)
    edit.setCursorPosition(10)
    anchor_if_idle(edit)
    assert edit.cursorPosition() == 10, "焦点在框内时不应动光标"
    edit.clearFocus()
    anchor_if_idle(edit)
    assert edit.cursorPosition() == 0


# ============= 3. 主窗口真实接线 =============


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


def test_main_window_nfo_lib_dir_box_starts_from_left(win, app):
    """用户点名的框：信息管理-「选择目录」左侧显示框回填后从左展示。"""
    win.Ui.lineEdit_nfo_lib_dir.setText(_LONG + "/nfo_lib")
    app.processEvents()
    assert win.Ui.lineEdit_nfo_lib_dir.cursorPosition() == 0


def test_main_window_form_fields_start_from_left(win, app):
    """信息管理表单的 15 个回填框同样从左展示。"""
    fields = [
        win.Ui.lineEdit_nfo_lib_number,
        win.Ui.lineEdit_nfo_lib_title,
        win.Ui.lineEdit_nfo_lib_actor,
        win.Ui.lineEdit_nfo_lib_release,
        win.Ui.lineEdit_nfo_lib_year,
        win.Ui.lineEdit_nfo_lib_runtime,
        win.Ui.lineEdit_nfo_lib_director,
        win.Ui.lineEdit_nfo_lib_studio,
        win.Ui.lineEdit_nfo_lib_publisher,
        win.Ui.lineEdit_nfo_lib_series,
        win.Ui.lineEdit_nfo_lib_score,
        win.Ui.lineEdit_nfo_lib_cover_url,
        win.Ui.lineEdit_nfo_lib_poster_url,
    ]
    for index, edit in enumerate(fields):
        edit.setText(f"{_LONG}?field={index}")
    app.processEvents()
    assert [e.cursorPosition() for e in fields] == [0] * len(fields)


def test_main_window_hooks_settings_page_edits(win, app):
    """软件设置页等其它页面的输入框同样生效（init 一次性对整窗挂钩）。"""
    settings_edit = win.Ui.lineEdit_nfo_lib_filter
    assert settings_edit.property(_HOOK_FLAG), "主窗输入框未挂钩"
    settings_edit.setText(_LONG + "/settings")
    app.processEvents()
    assert settings_edit.cursorPosition() == 0
