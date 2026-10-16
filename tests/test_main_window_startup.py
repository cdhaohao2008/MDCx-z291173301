"""启动冒烟测试：offscreen 下完整构造主窗口。

回归背景：v2.0.6 NFO 库页布局修复引入了 PyQt5 风格的
`QLayout.setStretchFactor(index, stretch)` 调用，PyQt6 严格重载下
启动即抛 TypeError 崩溃（Windows 打包版首发时暴露）。本测试
在 CI 双平台（Linux offscreen / Windows offscreen）完整执行主窗口
初始化链（setupUi → Init_Singal → Init_Ui → load_config → ...），
任何签名不兼容/属性缺失都会在此暴露，而不是留给用户运行时发现。
"""

import sys

import pytest
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


def test_main_window_startup_no_crash(app, monkeypatch, tmp_path):
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    """MyMAinWindow 完整初始化不抛异常（含 Init_Singal 全部信号/布局调用）。"""
    # 打桩启动链中与 GUI 无关的副作用：网络自检/版本检查/剩余任务保存
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)

    monkeypatch.chdir(tmp_path)  # load_config/get_success_list 会写当前目录

    win = mw_mod.MyMAinWindow()
    try:
        assert win.Ui is not None
        # NFO 库页三栏 stretch 已应用（回归点：setStretch 而非 setStretchFactor(int)）
        layout = win.Ui.nfo_lib_content_layout
        assert layout.itemAt(0) is not None
        assert layout.itemAt(1) is not None
        assert layout.itemAt(2) is not None
    finally:
        win.timer.stop()
        win.timer_scrape.stop()
        win.timer_update.stop()
        win.timer_remain_task.stop()
        win.close()
        win.deleteLater()
        app.processEvents()


def test_emby_actor_manager_dialog_startup_no_crash(app):
    """Emby 演员管理工具对话框完整构造不抛异常。

    覆盖 _init_ui 全部 Qt 控件构造路径（QSplitter/表格/日志区等），
    配合主窗口冒烟测试，防止 PyQt6 签名不兼容类问题推迟到用户
    打开窗口时才暴露。
    """
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        assert dlg.windowTitle() == "Emby/Jellyfin演员管理器"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_settings_dialog_startup_no_crash(app):
    """Emby 演员管理工具设置对话框完整构造不抛异常。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorSettingsDialog

    dlg = EmbyActorSettingsDialog()
    try:
        assert dlg.windowTitle()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_table_has_birthday_and_location_columns(app):
    """议题 #134/#136 + 新规格：出生日期恒 100，状态/头像/简介取其一半 50，影片数恒 60；姓名与出生地同宽，常规等宽 100/标签×2=200，最大化 2 倍 200/标签 3 倍 300，详情铺满。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        table = dlg.table
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        assert headers == ["状态", "姓名", "头像", "简介", "出生日期", "出生地", "详情", "标签", "影片数"]

        # 常规态与宽态列宽公式一致（宽/窄靠视口自然区分）：实测生日/2 倍出生地/平分。
        import math as _math

        for _wide in (False, True):
            dlg.resize(1600, 900)
            dlg.show()
            app.processEvents()
            dlg._is_wide_state = lambda w=_wide: w
            dlg._apply_column_widths()
            app.processEvents()
            _birthday_w = dlg._measured_birthday_width()
            assert _birthday_w == int(
                _math.ceil(
                    max(
                        table.fontMetrics().horizontalAdvance(s)
                        for s in ("0000-00-00", "8888-88-88", "出生日期")
                    )
                )
            ) + int(dlg._BIRTHDAY_CELL_PADDING)
            assert table.columnWidth(4) == _birthday_w
            assert table.columnWidth(5) == _birthday_w * 2
            assert table.columnWidth(1) == _birthday_w * 2
            _half_w = int(_math.ceil(_birthday_w / 2.0))
            assert table.columnWidth(0) == _half_w
            assert table.columnWidth(2) == _half_w
            assert table.columnWidth(3) == _half_w
            assert table.columnWidth(8) == 60
            # 详情与标签平分剩余（余 1px 归详情），两者差至多 1。
            assert abs(table.columnWidth(6) - table.columnWidth(7)) <= 1
            total = sum(table.columnWidth(i) for i in range(table.columnCount()))
            assert total == pytest.approx(table.viewport().width(), abs=4), "各列总宽未铺满视口"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_populates_birthday_and_location(app):
    """议题 #134：出生日期取 Emby PremiereDate 前 10 位，出生地按逗号拼接。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        actor = ActorInfo(
            name="测试演员",
            actor_id="1",
            server_id="s",
            existing_premiere_date="1994-08-26T00:00:00.0000000Z",
            existing_production_locations=["日本", "东京都"],
        )
        dlg._actors = [actor]
        dlg._populate_table(dlg._actors)
        assert dlg.table.item(0, 4).text() == "1994-08-26"
        assert dlg.table.item(0, 5).text() == "日本, 东京都"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_detail_hides_br_and_none(app):
    """详情列不显示 <br>/（无）等字符：仅展示层清洗，数据本体不动。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog, format_detail_cell_text

    assert format_detail_cell_text("") == ""
    assert format_detail_cell_text("（无）") == ""
    assert format_detail_cell_text("(无)") == ""
    assert "<br" not in format_detail_cell_text("a<br>b<br/>c").lower()
    assert format_detail_cell_text("a<br>b") == "a b"

    dlg = EmbyActorManagerDialog()
    try:
        empty_actor = ActorInfo(name="空简介", actor_id="e1", server_id="s", has_overview=False)
        br_actor = ActorInfo(
            name="br简介",
            actor_id="e2",
            server_id="s",
            has_overview=True,
            existing_overview="<br>====== 个人资料 ======<br>本名: 牧野 左代子<br>出身地: 日本",
        )
        dlg._actors = [empty_actor, br_actor]
        dlg._populate_table(dlg._actors)
        assert dlg.table.item(0, 6).text() == ""
        detail = dlg.table.item(1, 6).text()
        assert "<br" not in detail.lower()
        assert "（无）" not in detail and "(无)" not in detail
        assert "<" not in detail and ">" not in detail
        # 数据本体不受展示清洗影响
        assert "<br>" in br_actor.existing_overview
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_blank_birthday_placeholder(app):
    """议题 #134：Emby 未设置生日时返回 0001-01-01，列表中按空值展示。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        actor = ActorInfo(
            name="无生日演员",
            actor_id="2",
            server_id="s",
            existing_premiere_date="0001-01-01T00:00:00.0000000Z",
        )
        dlg._actors = [actor]
        dlg._populate_table(dlg._actors)
        assert dlg.table.item(0, 4).text() == ""
        assert dlg.table.item(0, 5).text() == ""
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_columns_fit_after_vertical_scrollbar(app):
    """议题 #160：纵向滚动条显隐后列宽应重算，不产生横向滚动条。"""
    from PyQt6.QtCore import Qt

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        dlg.resize(1600, 900)
        dlg.show()
        app.processEvents()
        table = dlg.table
        hbar = table.horizontalScrollBar()

        # 强制显示纵向滚动条（模拟演员数量多时的场景），视口变窄
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        app.processEvents()
        total_on = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total_on == pytest.approx(table.viewport().width(), abs=4), "纵滚动条显示后列宽未铺满视口"
        assert hbar.maximum() == 0, f"纵滚动条显示后出现横向滚动条: {hbar.maximum()}"

        # 隐藏纵向滚动条，视口变宽，同样不应出现横向滚动条
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        app.processEvents()
        total_off = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total_off == pytest.approx(table.viewport().width(), abs=4), "纵滚动条隐藏后列宽未铺满视口"
        assert hbar.maximum() == 0, f"纵滚动条隐藏后出现横向滚动条: {hbar.maximum()}"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_copyable_cells(app):
    """新规格：姓名/出生日期/出生地/详情/标签可选中复制（整格 Ctrl+C + 双击只读编辑器子串复制）。"""
    import math

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QAbstractItemView, QStyleOptionViewItem, QTableWidget

    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import (
        _COPYABLE_COLUMNS,
        EmbyActorManagerDialog,
    )

    assert sorted(_COPYABLE_COLUMNS) == [1, 4, 5, 6, 7]
    dlg = EmbyActorManagerDialog()
    try:
        table = dlg.table
        assert table.selectionBehavior() == QTableWidget.SelectionBehavior.SelectItems
        assert table.editTriggers() == QAbstractItemView.EditTrigger.DoubleClicked
        actor = ActorInfo(
            name="复制演员",
            actor_id="c1",
            server_id="s",
            existing_premiere_date="2000-01-02T00:00:00",
            existing_production_locations=["日本"],
            existing_overview="可复制简介",
            existing_taglines=["标1", "标2"],
        )
        dlg._actors = [actor]
        dlg._populate_table([actor])
        for col in range(table.columnCount()):
            editable = bool(table.item(0, col).flags() & Qt.ItemFlag.ItemIsEditable)
            assert editable == (col in _COPYABLE_COLUMNS), f"列 {col} Editable 标记错误"
        assert dlg._measured_birthday_width() == int(
            math.ceil(
                max(
                    table.fontMetrics().horizontalAdvance(s)
                    for s in ("0000-00-00", "8888-88-88", "出生日期")
                )
            )
        ) + int(dlg._BIRTHDAY_CELL_PADDING)
        dlg._on_table_double_clicked(0, 1)
        assert dlg._detail_dialogs == {}
        delegate = table.itemDelegate()
        opt = QStyleOptionViewItem()
        editor = delegate.createEditor(table, opt, table.model().index(0, 1))
        assert editor is not None and editor.isReadOnly()
        delegate.setEditorData(editor, table.model().index(0, 1))
        assert editor.text() == "复制演员"
        editor.setText("HACK")
        delegate.setModelData(editor, table.model(), table.model().index(0, 1))
        assert table.item(0, 1).text() == "复制演员"
        assert delegate.createEditor(table, opt, table.model().index(0, 0)) is None
        dlg._on_table_double_clicked(0, 0)
        app.processEvents()
        assert set(dlg._detail_dialogs) == {"c1"}
        table.clearSelection()
        table.selectAll()
        assert dlg._copy_selected_cells_to_clipboard() is True
        assert QGuiApplication.clipboard().text() == "复制演员\t2000-01-02\t日本\t可复制简介\t标1, 标2"
        for d in list(dlg._detail_dialogs.values()):
            d.close()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
