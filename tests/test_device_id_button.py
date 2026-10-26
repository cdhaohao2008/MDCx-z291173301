"""设置-高级「设备编号」按钮的回归测试（2026-10-26 需求）。

需求原话：「在软件设置-高级-隐藏图标右侧加上设备编号按钮，样式宽度同导入账单一致，
点击后获取设备 ID 并生成一个 txt 弹出窗口让用户选择存放位置」。

本文件钉四件事：
  * 按钮挂在「隐藏图标」行末（「隐藏菜单图标」右侧），不重叠、同行同高；
  * 宽度与「导入账单」一致（``_bill_button_width``）；
  * **不绑定机器**——未绑定的机器上「导入账单」隐藏，本按钮照样在；
  * 点击后按用户选的位置写出 txt，正文首行就是设备编号。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import platform
import sys

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QFileDialog

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _make_window(app, monkeypatch, tmp_path, bound: bool = True):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod
    from mdcx.utils import machine_binding

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(machine_binding, "ensure_probe_started", lambda: None)
    monkeypatch.setattr(machine_binding, "probe_state", lambda: bound)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    window._poll_bill_bind_state()
    return window


def _goto_advanced(win, app) -> None:
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


def _resize(win, app, width, height) -> None:
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    window = _make_window(app, monkeypatch, tmp_path, True)
    _goto_advanced(window, app)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


# ---------------------------------------------------------------- 按钮本身


def test_button_exists_and_labelled(win):
    """文案是「设备编号」，挂在 gridLayoutWidget_20 下，且不进任何布局。"""
    ui = win.Ui
    button = ui.pushButton_device_id
    assert button.text() == "设备编号"
    assert button.parent() is ui.gridLayoutWidget_20
    assert ui.gridLayoutWidget_20.layout().indexOf(button) == -1
    assert ui.horizontalLayout_dock.indexOf(button) == -1


def test_button_visible_on_unbound_machine(app, monkeypatch, tmp_path):
    """不绑定机器：未绑定时「导入账单」隐藏，本按钮照样显示（它就是给用户导号用的）。"""
    window = _make_window(app, monkeypatch, tmp_path, False)
    try:
        _goto_advanced(window, app)
        _resize(window, app, 1200, 900)
        assert window.Ui.pushButton_import_bill.isHidden()
        assert window.Ui.pushButton_device_id.isVisible()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_button_width_matches_bill_button(win, app):
    """宽度与「导入账单」一致（同款样式、同款宽度）。"""
    ui = win.Ui
    for size in ((1000, 700), (1200, 900), (1920, 1170)):
        _resize(win, app, *size)
        assert ui.pushButton_device_id.width() == ui.pushButton_import_bill.width(), f"{size} 宽度不一致"
    assert win._device_button_width == win._bill_button_width


@pytest.mark.parametrize("size", [(1000, 700), (1030, 753), (1200, 900), (1536, 864), (1920, 1170)])
def test_button_sits_right_of_hide_menu_icon(win, app, size):
    """紧贴「隐藏菜单图标」右侧：不重叠、同行同高、留在 host 内。"""
    ui = win.Ui
    _resize(win, app, *size)
    button = ui.pushButton_device_id
    menu = ui.checkBox_hide_menu_icon
    host = ui.gridLayoutWidget_20
    menu_right = menu.mapTo(host, QPoint(menu.width(), 0)).x()
    assert button.x() >= menu_right, f"{size} 按钮压在复选框上"
    assert button.x() - menu_right == win._ADV_DEVICE_BUTTON_GAP
    assert button.y() == menu.mapTo(host, QPoint(0, 0)).y()
    assert button.height() == menu.height()
    assert button.x() + button.width() <= host.width(), f"{size} 按钮超出右侧边界"


def test_button_positioned_on_first_open_without_resize(app, monkeypatch, tmp_path):
    """首次打开高级页（没 resize、没显式同步）按钮就已就位，不在 (0,0)。"""
    window = _make_window(app, monkeypatch, tmp_path, True)
    try:
        _goto_advanced(window, app)
        ui = window.Ui
        button = ui.pushButton_device_id
        assert button.isVisible()
        assert button.x() > 0 and button.y() > 0
        menu = ui.checkBox_hide_menu_icon
        assert button.x() >= menu.mapTo(ui.gridLayoutWidget_20, QPoint(menu.width(), 0)).x()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_showing_button_never_moves_existing_widgets(win, app):
    """按钮显隐前后，整页既有控件坐标逐位相同（它是游离子项，不参与布局）。"""
    ui = win.Ui
    _resize(win, app, 1200, 900)
    button = ui.pushButton_device_id
    content = ui.scrollAreaWidgetContents_gaoji
    watched = (
        ui.checkBox_hide_dock_icon,
        ui.checkBox_hide_menu_icon,
        ui.checkBox_dark_mode,
        ui.checkBox_auto_exit,
        ui.checkBox_hide_nfo_nav,
        ui.checkBox_show_data_log,
        ui.pushButton_import_bill,
    )
    button.hide()
    win._sync_page_layouts()
    app.processEvents()
    before = [widget.mapTo(content, QPoint(0, 0)).x() for widget in watched]
    button.show()
    win._sync_page_layouts()
    app.processEvents()
    after = [widget.mapTo(content, QPoint(0, 0)).x() for widget in watched]
    assert before == after


# ---------------------------------------------------------------- 点击导出


class _FakeDialog:
    """替掉 QFileDialog：直接返回测试指定的保存路径。"""

    Option = QFileDialog.Option

    def __init__(self, target: str) -> None:
        self._target = target
        self.calls: list[tuple] = []

    def getSaveFileName(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._target, "文本文件 (*.txt)"


class _FakeMessageBox:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def information(self, _parent, _title, text, *args, **kwargs):
        self.infos.append(text)

    def warning(self, _parent, _title, text, *args, **kwargs):
        self.warnings.append(text)


def test_export_writes_txt_at_chosen_path(win, monkeypatch, tmp_path):
    """点击按钮 → 选位置 → 按 UTF-8 写出 txt，首行是设备编号。"""
    from mdcx.controllers.main_window import device_id_ui
    from mdcx.utils import device_id as device_id_mod

    target = tmp_path / "设备编号_测试机.txt"
    dialog = _FakeDialog(str(target))
    box = _FakeMessageBox()
    monkeypatch.setattr(device_id_ui, "QFileDialog", dialog)
    monkeypatch.setattr(device_id_ui, "QMessageBox", box)
    monkeypatch.setattr(device_id_mod, "device_id", lambda: "{TEST-DEVICE-ID}")
    monkeypatch.setattr(device_id_mod, "system_name", lambda: "Windows 11 Pro 测试")

    win.export_device_id()

    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "设备编号：{TEST-DEVICE-ID}"
    assert lines[1] == "系统：Windows 11 Pro 测试"
    assert any(line.startswith("计算机名：") for line in lines)
    assert any(line.startswith("生成时间：") for line in lines)
    assert box.warnings == []
    assert box.infos and str(target) in box.infos[0]
    # 默认文件名带计算机名、落在桌面（取不到桌面时退回用户主目录）
    default_path = dialog.calls[0][0][2]
    assert default_path.endswith(".txt") and "设备编号_" in os.path.basename(default_path)


def test_export_warns_when_device_id_unavailable(win, monkeypatch, tmp_path):
    """取不到设备编号：提示用户手动查看，不写空文件。"""
    from mdcx.controllers.main_window import device_id_ui
    from mdcx.utils import device_id as device_id_mod

    target = tmp_path / "设备编号.txt"
    dialog = _FakeDialog(str(target))
    box = _FakeMessageBox()
    monkeypatch.setattr(device_id_ui, "QFileDialog", dialog)
    monkeypatch.setattr(device_id_ui, "QMessageBox", box)
    monkeypatch.setattr(device_id_mod, "device_id", lambda: "")

    win.export_device_id()

    assert not target.exists()
    assert dialog.calls == []  # 连保存对话框都不弹
    assert box.warnings and "未能读取本机设备编号" in box.warnings[0]


def test_export_cancel_writes_nothing(win, monkeypatch, tmp_path):
    """用户取消保存：不写文件、不弹提示。"""
    from mdcx.controllers.main_window import device_id_ui
    from mdcx.utils import device_id as device_id_mod

    dialog = _FakeDialog("")
    box = _FakeMessageBox()
    monkeypatch.setattr(device_id_ui, "QFileDialog", dialog)
    monkeypatch.setattr(device_id_ui, "QMessageBox", box)
    monkeypatch.setattr(device_id_mod, "device_id", lambda: "{TEST-DEVICE-ID}")

    win.export_device_id()

    assert box.infos == [] and box.warnings == []


# ---------------------------------------------------------------- 取号工具


def test_build_report_starts_with_device_id(monkeypatch):
    from mdcx.utils import device_id as mod

    monkeypatch.setattr(mod, "device_id", lambda: "{ABC-123}")
    monkeypatch.setattr(mod, "system_name", lambda: "Windows 11 Pro 25H2")
    text = mod.build_report()
    assert text.splitlines()[0] == "设备编号：{ABC-123}"
    assert text.endswith("\n")


@pytest.mark.skipif(platform.system() != "Windows", reason="只有 Windows 有注册表这一路")
def test_windows_device_id_reads_about_page_value():
    """Windows 取的就是「设置 → 系统 → 关于 → 设备 ID」，即 SQMClient\\MachineId。"""
    from mdcx.utils import device_id as mod

    expected = mod._read_registry(r"SOFTWARE\Microsoft\SQMClient", "MachineId")
    if not expected:
        pytest.skip("本机没有 SQMClient\\MachineId")
    assert mod.device_id() == expected
