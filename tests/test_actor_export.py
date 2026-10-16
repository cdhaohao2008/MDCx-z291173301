"""演员数据导出 xlsx：列顺序/取值口径/样式与样例文件一致，UI 接线不断言业务细节。

样例文件（用户给定）：表头 姓名|详情|出生日期|出生地|标签|头像|简介|状态，
对齐为姓名/出生日期/头像/简介/状态居中、详情/出生地/标签居左，全表宋体 11pt，
出生日期为 Excel 日期型（`[$-409]yyyy\\-mm\\-dd;@`）。
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


def _actor(**kwargs):
    """构造真实 ActorInfo（status_icon 为真实属性，与表格同口径）。"""
    from mdcx.tools.emby_actor_manager import ActorInfo

    params = {
        "name": "测试演员",
        "actor_id": "id-测试演员",
        "server_id": "srv",
        "has_image": True,
        "has_overview": True,
        "existing_overview": "一行简介",
    }
    params.update(kwargs)
    if "actor_id" not in kwargs:
        params["actor_id"] = f"id-{params['name']}"
    return ActorInfo(**params)


def test_export_headers_order():
    from mdcx.tools.emby_actor_export import EXPORT_HEADERS

    assert EXPORT_HEADERS == ("姓名", "详情", "出生日期", "出生地", "标签", "头像", "简介", "状态")


def test_export_row_complete_actor():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(
        name="AAA",
        existing_overview="详情正文",
        existing_premiere_date="1990-02-03T00:00:00",
        existing_production_locations=["日本", "仙台"],
        existing_taglines=["AA", "BB", "CC"],
    )
    assert ex.actor_export_row(a) == (
        "AAA",
        "详情正文",
        datetime.datetime(1990, 2, 3),
        "日本，仙台",
        "AA，BB，CC",
        "✅",
        "✅",
        "✅",
    )


def test_export_row_missing_actor():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(name="缺员", has_image=False, has_overview=False, existing_overview="")
    row = ex.actor_export_row(a)
    assert row[0] == "缺员"
    assert row[1] == ""
    assert row[2] == ""
    assert row[5] == "❌" and row[6] == "❌" and row[7] == "❌"


def test_export_row_half_missing_status_warn():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(has_image=True, has_overview=False, existing_overview="")
    row = ex.actor_export_row(a)
    # ⚠️ 左侧补一个空格再导出，使其与 ✅/❌ 上下对齐。
    assert (row[5], row[6], row[7]) == ("✅", "❌", " ⚠️")


def test_export_row_placeholder_overview_counts_missing():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(
        has_image=False,
        has_overview=True,
        existing_overview="无维基百科信息，从 minnano-av 数据库补全女优信息",
    )
    row = ex.actor_export_row(a)
    assert row[6] == "❌" and row[7] == "❌"
    assert row[1] == ""


def test_export_row_unset_birthday_empty():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(existing_premiere_date="0001-01-01T00:00:00")
    assert ex.actor_export_row(a)[2] == ""


def test_export_row_detail_full_text_not_truncated():
    from mdcx.tools import emby_actor_export as ex

    long_text = "详" * 200
    a = _actor(existing_overview=long_text)
    assert ex.actor_export_row(a)[1] == long_text


def test_export_row_detail_strips_html():
    from mdcx.tools import emby_actor_export as ex

    a = _actor(existing_overview="第一行<br>第二行 <b>加粗</b>")
    assert ex.actor_export_row(a)[1] == "第一行 第二行 加粗"


def test_export_filename_format():
    from mdcx.tools import emby_actor_export as ex

    name = ex.export_filename(datetime.datetime(2026, 10, 12, 13, 52, 1))
    assert name == "演员数据表2026-10-12 13-52-01.xlsx"


def test_resolve_export_dir():
    from mdcx.tools import emby_actor_export as ex

    assert ex.resolve_export_dir("") is None
    assert ex.resolve_export_dir(None) is None
    assert ex.resolve_export_dir("Z:/不存在的目录-xyz") is None


def test_resolve_export_dir_valid(tmp_path):
    from mdcx.tools import emby_actor_export as ex

    assert ex.resolve_export_dir(str(tmp_path)) == tmp_path


def test_write_xlsx_roundtrip(tmp_path):
    import openpyxl

    from mdcx.tools import emby_actor_export as ex

    actors = [
        _actor(
            name="AAA",
            existing_overview="详情正文",
            existing_premiere_date="1990-02-03T00:00:00",
            existing_production_locations=["日本", "仙台"],
            existing_taglines=["AA", "BB", "CC"],
        ),
        _actor(name="缺员", has_image=False, has_overview=False, existing_overview=""),
    ]
    path = ex.write_actor_export_xlsx(tmp_path / "演员数据表2026-10-12 13-52-01.xlsx", actors)
    assert path.exists()

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    assert [c.value for c in ws[1]] == ["姓名", "详情", "出生日期", "出生地", "标签", "头像", "简介", "状态"]
    assert ws.max_row == 3  # 表头 + 2 行数据，无尾部空行
    row2 = [c.value for c in ws[2]]
    assert row2[0] == "AAA" and row2[3] == "日本，仙台" and row2[4] == "AA，BB，CC"
    assert row2[5] == row2[6] == row2[7] == "✅"
    assert row2[2] == datetime.datetime(1990, 2, 3)
    assert ws.cell(row=2, column=3).number_format == ex.EXPORT_DATE_NUMBER_FORMAT
    # 样式：全表宋体 11pt；表头全部居中，数据行姓名/日期/头像/简介/状态居中、
    # 详情/出生地/标签居左；纵向全部居中。
    for row in ws.iter_rows(min_row=1, max_row=3):
        for idx, cell in enumerate(row):
            assert cell.font.name == "宋体" and cell.font.size == 11
            assert cell.alignment.vertical == "center"
            if row[0].row == 1:
                assert cell.alignment.horizontal == "center"
            else:
                assert cell.alignment.horizontal == ("center" if idx in (0, 2, 5, 6, 7) else "left")
    # 列宽：头像/简介/状态（F/G/H）保持默认列宽，出生日期（C）收窄到刚好放下日期，
    # 姓名/详情/出生地/标签（A/B/D/E）1:1:1:1 均分剩余列宽（右侧空白默认摊进这四列）。
    assert ws.column_dimensions["C"].width == ex.EXPORT_BIRTHDAY_COL_WIDTH
    for col in ("F", "G", "H"):
        assert ws.column_dimensions[col].width == ex.EXPORT_ICON_COL_WIDTH == 8.43
    text_widths = {ws.column_dimensions[c].width for c in ("A", "B", "D", "E")}
    assert len(text_widths) == 1
    assert text_widths.pop() == ex.EXPORT_TEXT_COL_WIDTH == pytest.approx(
        (ex.EXPORT_TABLE_WIDTH - ex.EXPORT_BIRTHDAY_COL_WIDTH - 3 * ex.EXPORT_ICON_COL_WIDTH) / 4
    )
    # H 列之后的列（I:XFD）全部隐藏，表右侧无空白列。
    assert ws.column_dimensions["I"].hidden is True
    assert ws.column_dimensions["H"].hidden is not True
    # 首行冻结：表头始终置顶显示。
    assert ws.freeze_panes == "A2"
    # 状态列：✅/❌ 无前后空格；⚠️ 仅左侧补一个对齐空格（多一个少一个都不行）。
    for r in range(2, ws.max_row + 1):
        value = ws.cell(row=r, column=8).value
        assert isinstance(value, str) and value in ("✅", "❌", " ⚠️")


def test_text_col_width_for_screen_width():
    """屏幕宽度换算：扣序号列/滚动条/安全边距/固定列后均分，非法与小屏兜底。"""
    from mdcx.tools import emby_actor_export as ex

    def _expect(px):
        return (
            (px - ex.SCREEN_ROW_HEADER_PX - ex.SCREEN_VSCROLL_PX - ex.EXPORT_TABLE_MARGIN_PX)
            - ex.EXCEL_TABLE_PADDING_PX
        ) / ex.EXCEL_UNIT_PX - ex.EXPORT_BIRTHDAY_COL_WIDTH - 3 * ex.EXPORT_ICON_COL_WIDTH

    assert ex.text_col_width_for_screen_width(1920) == pytest.approx(_expect(1920) / 4)
    # 屏幕越宽，分到的列越宽（头像/简介/状态三列无需横向滚动即默认可见）。
    assert ex.text_col_width_for_screen_width(2560) > ex.text_col_width_for_screen_width(1366)
    assert ex.text_col_width_for_screen_width("非法") == ex.EXPORT_MIN_TEXT_COL_WIDTH
    assert ex.text_col_width_for_screen_width(None) == ex.EXPORT_MIN_TEXT_COL_WIDTH
    assert ex.text_col_width_for_screen_width(100) == ex.EXPORT_MIN_TEXT_COL_WIDTH


def test_export_table_fits_viewport():
    """表总宽恒比视口可视区窄一个安全边距：八列默认一屏放下，无需横向滚动。"""
    from mdcx.tools import emby_actor_export as ex

    for px in (1366, 1536, 1920, 2560):
        text_w = ex.text_col_width_for_screen_width(px)
        total_units = 4 * text_w + ex.EXPORT_BIRTHDAY_COL_WIDTH + 3 * ex.EXPORT_ICON_COL_WIDTH
        table_px = total_units * ex.EXCEL_UNIT_PX + ex.EXCEL_TABLE_PADDING_PX
        content_px = px - ex.SCREEN_ROW_HEADER_PX - ex.SCREEN_VSCROLL_PX
        assert table_px == pytest.approx(content_px - ex.EXPORT_TABLE_MARGIN_PX)


def _fake_screen(width: float, dpr: float, dpi: float):
    """构造屏幕桩：availableGeometry().width()/devicePixelRatio()/logicalDotsPerInchX()。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        availableGeometry=lambda: SimpleNamespace(width=lambda: width),
        devicePixelRatio=lambda: dpr,
        logicalDotsPerInchX=lambda: dpi,
    )


def test_effective_screen_width_px(monkeypatch):
    """逻辑宽度 = 物理宽 / 缩放比，Qt 缩放开/关两种模式收敛到同一值。"""
    from mdcx.tools import emby_actor_export as ex

    # Qt 侧刻度可用时不依赖系统：先屏蔽 Win32 来源，保证测试与测试机缩放比无关。
    monkeypatch.setattr(ex, "_windows_system_scale", lambda: None)
    # 1920 物理像素 @125% 缩放 → 1536（用户机器）。
    assert ex.effective_screen_width_px(_fake_screen(1536, 1.25, 120)) == pytest.approx(1536.0)
    assert ex.effective_screen_width_px(_fake_screen(1920, 1.0, 120)) == pytest.approx(1536.0)
    # 100% 缩放：两种模式都是 1920。
    assert ex.effective_screen_width_px(_fake_screen(1920, 1.0, 96)) == pytest.approx(1920.0)
    # 150% 缩放：1920 物理 → 1280 逻辑。
    assert ex.effective_screen_width_px(_fake_screen(1280, 1.5, 144)) == pytest.approx(1280.0)
    assert ex.effective_screen_width_px(_fake_screen(1920, 1.0, 144)) == pytest.approx(1280.0)
    # 取不到屏幕信息时兜底。
    assert ex.effective_screen_width_px(None) == ex.EXPORT_FALLBACK_SCREEN_PX
    assert ex.effective_screen_width_px(object()) == ex.EXPORT_FALLBACK_SCREEN_PX


def test_effective_screen_width_uses_windows_scale(monkeypatch):
    """DPI-unaware 模式（Qt 侧刻度全为 1.0/96）改走 Win32 系统 DPI。

    这正是用户机器的现状：Qt 上报物理像素 1920 且刻度为 1.0，
    靠系统 125% 缩放比换算出 1536（之前未走这里，错按 1920 计算导致列过宽）。
    """
    from mdcx.tools import emby_actor_export as ex

    monkeypatch.setattr(ex, "_windows_system_scale", lambda: 1.25)
    assert ex.effective_screen_width_px(_fake_screen(1920, 1.0, 96)) == pytest.approx(1536.0)
    # Qt 侧已有真实刻度时，Win32 来源不干扰（取较大者，结果一致）。
    assert ex.effective_screen_width_px(_fake_screen(1536, 1.25, 120)) == pytest.approx(1536.0)


def test_write_xlsx_custom_text_width(tmp_path):
    """调用方传入的列宽覆盖缺省均分值。"""
    import openpyxl

    from mdcx.tools import emby_actor_export as ex

    path = ex.write_actor_export_xlsx(tmp_path / "t.xlsx", [_actor(name="甲")], text_col_width=30)
    ws = openpyxl.load_workbook(path).active
    assert {ws.column_dimensions[c].width for c in ("A", "B", "D", "E")} == {30}
    assert ws.freeze_panes == "A2"


def test_data_tool_combobox_wiring(app):
    """数据工具下拉框：三选项齐备，btn_clean 别名仍指向它（既有测试不断）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        combo = dlg.cmb_data_tool
        assert isinstance(combo, QComboBox)
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "数据获取",
            "数据清洗",
            "数据导出",
            "数据导入",
        ]
        assert dlg.btn_clean is combo
    finally:
        dlg.close()
        app.processEvents()


def test_button_widths_narrow_and_wide(app):
    """六个按钮任何窗口状态都按文字实际占用宽度定宽（最大化与最小化一致）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    try:
        app.processEvents()
        assert (dlg.cmb_fetch_mode.minimumWidth(), dlg.cmb_fetch_mode.maximumWidth()) == (210, 210)
        assert (dlg.cmb_data_tool.minimumWidth(), dlg.cmb_data_tool.maximumWidth()) == (
            dlg._data_tool_hint_w,
            dlg._data_tool_hint_w,
        )
        text_btns = [getattr(dlg, name) for name, _ in dlg._TEXT_FIT_BUTTONS] + [dlg.btn_sync]
        # 各按文字实际占用宽度定宽：静态五按钮等于首次显示记录的自然宽度。
        for name, hint_attr in dlg._TEXT_FIT_BUTTONS:
            b = getattr(dlg, name)
            hint = getattr(dlg, hint_attr)
            assert (b.minimumWidth(), b.maximumWidth()) == (hint, hint)
        # 谁都不裁字。
        for b in text_btns:
            assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 8
        # 同步按钮文案变长（计数后缀）时仅它自己跟随变宽，仍不裁字。
        sync_before = dlg.btn_sync.width()
        others_before = [b.width() for b in text_btns if b is not dlg.btn_sync]
        dlg._actors = [_actor(name=f"演员{i:02d}") for i in range(3)]
        for a in dlg._actors:
            a.need_update_info = True
        dlg._update_sync_button()
        app.processEvents()
        assert dlg.btn_sync.width() >= sync_before
        assert [b.width() for b in text_btns if b is not dlg.btn_sync] == others_before
        assert dlg.btn_sync.width() >= dlg.btn_sync.fontMetrics().horizontalAdvance(
            dlg.btn_sync.text()
        ) + 8
        # 重复调用幂等。
        widths_before = tuple(b.width() for b in text_btns)
        dlg._apply_button_widths()
        dlg._apply_button_widths()
        assert tuple(b.width() for b in text_btns) == widths_before
        # 宽态：六个按钮宽度与窄态一致（不再恢复自适应）；下拉仍按宽态规则。
        dlg.isMaximized = lambda: True
        dlg._apply_button_widths()
        assert tuple(b.width() for b in text_btns) == widths_before
        assert dlg.cmb_data_tool.minimumWidth() == 0
        assert dlg.cmb_data_tool.maximumWidth() == dlg._HELP_MAX_W
        assert (dlg.cmb_fetch_mode.minimumWidth(), dlg.cmb_fetch_mode.maximumWidth()) == (220, 220)
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_button_row_compact_narrow_and_wide(app):
    """窄态按钮行无项间距、连接组左 0/右 0（1/10 号空白删掉，按钮贴边紧贴）；宽态恢复原样。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    try:
        app.processEvents()
        assert dlg._btn_layout is not None and dlg._conn_grid is not None
        group = dlg._conn_grid.parentWidget()
        height_before = group.height()
        # 窄态：项间距 0，左 0、右 0（1-10 号空白删掉，按钮之间紧贴），上下边距保持 4/4。
        assert dlg._btn_layout.spacing() == 0
        margins = dlg._conn_grid.contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 4, 0, 4)
        # 窄态：按钮行按内容宽左对齐——窗口富余宽度整条让给上一行输入框，
        # 不再被这一行平摊成 1-10 号空白（这是「空白没删掉」的真正原因）。
        assert dlg._btn_layout.alignment() == Qt.AlignmentFlag.AlignLeft
        items = [
            dlg._btn_layout.itemAt(i).widget()
            for i in range(dlg._btn_layout.count())
            if dlg._btn_layout.itemAt(i).widget() is not None
        ]
        row_gaps = [
            items[i + 1].x() - (items[i].x() + items[i].width()) for i in range(len(items) - 1)
        ]
        assert set(row_gaps) == {0}, "窄态按钮之间不得有任何空隙"
        assert items[0].x() == 1, "窄态首个按钮应贴组左边框"
        # 窄态：服务器地址文本与组标题、连接按钮三处文字首笔同列（标题 QSS padding 与
        # 标签 padding-left 同为 `_CONN_ALIGN_PAD`，真机 Windows 实测同为设备像素 11），
        # 按钮本身仍贴组左边框。
        assert dlg._CONN_ALIGN_PAD == 5
        assert dlg._lbl_server.styleSheet() == dlg._CONN_LABEL_QSS == "padding-left: 5px;"
        assert dlg._conn_group.styleSheet() == dlg._CONN_TITLE_QSS
        assert dlg._conn_group.title() == "Emby/Jellyfin连接设置"
        # 窄态：帮助标签恒两行、按文字实宽定宽，不再吸收富余宽度（曾致 23~37px 大缝）。
        assert dlg.help_label.text() == dlg._help_narrow
        assert dlg.help_label.maximumWidth() == dlg._narrow_help_width()
        # 紧凑操作本身不影响高度：重复调用后连接组高度不变。
        dlg._apply_button_row_compact()
        dlg._apply_button_row_compact()
        app.processEvents()
        assert group.height() == height_before
        # 宽态：间距与边距恢复原样，帮助标签恢复自适应单行（布局、控件逐像素不变）。
        dlg.isMaximized = lambda: True
        dlg._apply_button_widths()
        assert dlg._btn_layout.spacing() == 4
        assert dlg.help_label.maximumWidth() == dlg._HELP_MAX_W
        assert dlg._lbl_server.styleSheet() == ""
        # 宽态按钮行恢复填满整行（最大化逐像素不变）。
        assert dlg._btn_layout.alignment() == Qt.AlignmentFlag(0)
        margins = dlg._conn_grid.contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == tuple(
            dlg.CONN_BASE_MARGINS
        )
        # 切回窄态：再次收紧，幂等。
        dlg.isMaximized = real
        dlg._apply_button_widths()
        assert dlg._btn_layout.spacing() == 0
        margins = dlg._conn_grid.contentsMargins()
        assert margins.left() == 0 and margins.right() == 0
        assert dlg._lbl_server.styleSheet() == dlg._CONN_LABEL_QSS
        assert dlg._conn_group.styleSheet() == dlg._CONN_TITLE_QSS
        assert dlg._btn_layout.alignment() == Qt.AlignmentFlag.AlignLeft
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def _first_ink_x(image, row0, row1, *, bright: bool):
    """在图像 [row0, row1) 行区间内扫描，返回第一列「文字像素」的 x。

    dark 模式找深色字（黑字/白底，标题与服务器地址标签用），bright 模式找亮色字
    （白字/蓝底，按钮内文字用）。用于比对三处文字的**首笔**是否同列。
    """
    for x in range(image.width()):
        for y in range(row0, row1):
            px = image.pixel(x, y)
            r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
            if bright:
                if r > 170 and g > 170 and b > 170:
                    return x
            elif r < 120:
                return x
    return -1


def test_narrow_title_server_connect_button_align(app):
    """窄态组标题、服务器地址、连接按钮三处文字首笔严格同列（真机 Windows：设备像素 11）。

    组标题走本控件级 QSS（把全局 `left:10 + padding:0 4px` 覆盖成 `left:0 + padding:0 _CONN_ALIGN_PAD`），
    服务器地址标签走 `padding-left: _CONN_ALIGN_PAD`，两者同值：真机实测两者的首笔墨迹映射表
    完全一致（padding 0→5 / 1→6 / 2→7 / 3→8 / 4→10 / 5→11 设备像素），而「连接Emby/Jellyfin」
    按钮内白字首笔恒在设备像素 11（蓝色背景只贴到 x=1，其内文字另有边框内边距 2px + 居中余量 6px），
    故 `_CONN_ALIGN_PAD = 5` 即三处严格同列。
    """
    from PyQt6.QtGui import QGuiApplication

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    real = dlg.isMaximized
    try:
        dlg.show()
        for _ in range(3):
            app.processEvents()
        group = dlg._conn_group
        group_img = group.grab().toImage()
        title_x = _first_ink_x(group_img, 0, 15, bright=False)
        label = dlg._lbl_server
        server_x = label.x() + _first_ink_x(label.grab().toImage(), 0, label.height(), bright=False)
        button = dlg.btn_connect
        btn_x = button.x() + _first_ink_x(button.grab().toImage(), 0, button.height(), bright=True)
        assert title_x >= 0 and server_x >= 0 and btn_x >= 0, "三处文字均未扫描到首笔"
        # 标题与标签同 padding、同字体，首笔必同列（容差 1 设备像素，跨 QPA 平台留余量）。
        assert abs(title_x - server_x) <= 1, f"标题与服务器地址未同列：标题 {title_x} 服务器 {server_x}"
        # `_CONN_ALIGN_PAD` 是按真机 Windows 平台（QPA=windows）标定的；offscreen QPA 的
        # 按钮样式/字体不同（实测按钮白字首笔在 x=8），那里不做三处同列的断言。
        if QGuiApplication.platformName() != "offscreen":
            assert title_x == server_x == btn_x, f"三处文字未同列：标题 {title_x} 服务器 {server_x} 按钮 {btn_x}"
        # 宽态：三处都恢复全局原样（标题 17 / 服务器 17 / 按钮 24），互不覆盖。
        dlg.isMaximized = lambda: True
        dlg._apply_button_row_compact()
        for _ in range(3):
            app.processEvents()
        assert dlg._conn_group.styleSheet() == ""
        assert label.styleSheet() == ""
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_narrow_default_width_shrinks_to_content(app):
    """窄态默认宽度缩进：窗口收到按钮行内容宽，设置按钮右侧空白归零；
    统计栏「双击行可编辑」右侧与详情列是同一段富余宽度，跟着一起缩；最大化不动。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    real = dlg.isMaximized
    try:
        dlg.resize(1520, dlg.height())
        dlg.show()
        app.processEvents()
        app.processEvents()
        assert dlg.width() == dlg._narrow_min_width(), "窄态默认宽度应缩到内容宽"
        group = dlg._conn_grid.parentWidget()
        items = [
            dlg._btn_layout.itemAt(i).widget()
            for i in range(dlg._btn_layout.count())
            if dlg._btn_layout.itemAt(i).widget() is not None
        ]
        last = items[-1]
        assert group.width() - (last.x() + last.width()) == 1, "设置按钮右侧应只剩边框"
        # 幂等：再调一次宽度不动。
        width_before = dlg.width()
        dlg._shrink_narrow_width()
        app.processEvents()
        assert dlg.width() == width_before
        # 最大化：不参与缩窄，最小宽与几何保持系统值。
        dlg.isMaximized = lambda: True
        dlg._apply_button_widths()
        app.processEvents()
        assert dlg.minimumWidth() == dlg._BASE_MIN_W
        assert dlg.width() == width_before, "最大化不应被窄态缩宽逻辑改动"
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_narrow_shrink_recenters_on_screen(app, monkeypatch):
    """窄态缩宽后重新居中：resize() 不动左上角，不重定位就会整体偏左半个差值。

    `__init__` 的 `_center_on_screen()` 是按缩宽前的宽度（屏幕 80%）算的，
    缩到 `_narrow_min_width()` 后右边界内收，几何中心左移 `(1800-1392)//2`，
    所以缩宽后必须再居中一次，回到屏幕可用区正中央。
    """
    from PyQt6.QtCore import QRect

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog
    from mdcx.utils import window_center

    avail = QRect(0, 0, 3000, 2000)  # 放宽虚拟屏，使窗口小于可用区才谈得上居中
    monkeypatch.setattr(window_center, "available_geometry", lambda widget: avail)
    dlg = EmbyActorManagerDialog()
    try:
        dlg.resize(1800, dlg.height())
        dlg.show()
        for _ in range(3):
            app.processEvents()
        assert dlg.width() == dlg._narrow_min_width(), "窄态应缩到内容宽"
        frame = dlg.frameGeometry()
        want_x = avail.x() + (avail.width() - frame.width()) // 2
        want_y = avail.y() + (avail.height() - frame.height()) // 2
        assert abs(frame.x() - want_x) <= 1, f"缩宽后应重新居中，实际 x={frame.x()} 期望 {want_x}"
        assert abs(frame.y() - want_y) <= 1, f"纵向同样应居中，实际 y={frame.y()} 期望 {want_y}"
    finally:
        dlg.close()
        app.processEvents()


def test_narrow_help_two_lines_and_min_width(app):
    """窄态帮助恒两行（断在「③选择模式获取数据」），最小宽随之下调；宽态复原。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.show()
    real = dlg.isMaximized
    try:
        app.processEvents()
        assert "\n" in dlg._help_narrow, "窄态文案应为两行"
        first, second = dlg._help_narrow.split("\n", 1)
        assert first.endswith("③选择模式获")
        assert second.startswith("取数据→④绿色行==待更新")
        assert dlg.help_label.text() == dlg._help_narrow
        narrow_w = dlg._narrow_min_width()
        assert dlg.minimumWidth() == narrow_w, "窄态最小宽应等于实测两行态最宽"
        # 两行化后帮助标签确实比单行窄（单行态最小宽高于两行态）。
        fm = dlg.help_label.fontMetrics()
        assert dlg._narrow_help_width() < fm.horizontalAdvance(dlg._help_single)
        # 窄态最小宽由布局实测决定（按钮行实宽和 + 组边框 2 + 主布局左右 12+12）。
        row_sum = sum(
            dlg._btn_layout.itemAt(i).widget().width()
            for i in range(dlg._btn_layout.count())
            if dlg._btn_layout.itemAt(i).widget() is not None
        )
        main = dlg.layout()
        outer = 2
        if main is not None:
            mg = main.contentsMargins()
            outer += int(mg.left() + mg.right())
        assert narrow_w == row_sum + outer, "最小宽应等于按钮行实宽和加外层边框/边距"
        # 高度不变（两行文案仍在一行按钮行内，不占额外行高）。
        assert dlg.minimumHeight() == 720
        # 宽态：最小宽复原、帮助标签放开限宽（恢复自适应）。
        # 文案是否单行取决于实际可用宽度：真实最大化（1920 宽）放得下单行，
        # 桩最大化下窗口仍是窄态宽度、单行放不下时保持两行是正确行为，故不钉死。
        dlg.isMaximized = lambda: True
        dlg._apply_button_widths()
        app.processEvents()
        assert dlg.minimumWidth() == dlg._BASE_MIN_W
        assert dlg.help_label.maximumWidth() == dlg._HELP_MAX_W
        assert dlg.help_label.minimumWidth() == 0
        # 真实最大化宽度下单行放得下：按实宽复算一次文案选择。
        dlg.resize(1920, dlg.height())
        app.processEvents()
        dlg._update_help_line_break()
        assert "\n" not in dlg.help_label.text()
    finally:
        dlg.isMaximized = real
        dlg.close()
        app.processEvents()


def test_settings_dialog_export_folder_saved(app, monkeypatch):
    """设置窗口：数据导出目录行在本地头像目录行上方，保存落盘。"""
    from mdcx.tools import emby_actor_manager_ui as ui

    seen = {}

    def _replace_config(cfg):
        seen["cfg"] = cfg

    monkeypatch.setattr(ui.manager, "_replace_config", _replace_config, raising=False)
    monkeypatch.setattr(ui.manager, "save", lambda: seen.update(saved=True), raising=False)

    dlg = ui.EmbyActorSettingsDialog()
    try:
        from PyQt6.QtWidgets import QLabel

        layout = dlg.layout()
        dir_labels = []
        for i in range(layout.count()):
            row = layout.itemAt(i).layout()
            if row is None or row.count() == 0:
                continue
            first = row.itemAt(0).widget()
            if isinstance(first, QLabel) and first.text().endswith("目录:"):
                dir_labels.append(first.text())
        assert dir_labels == ["数据导出目录:", "本地头像目录:"]
        dlg.export_folder_edit.setText("D:/导出目录")
        dlg.photo_folder_edit.setText("D:/头像目录")
        dlg._save()
        assert seen["cfg"].actor_export_folder == "D:/导出目录"
        assert seen["cfg"].actor_photo_folder == "D:/头像目录"
        assert seen.get("saved") is True
    finally:
        dlg.close()
        app.processEvents()


def test_export_action_routes(monkeypatch, app):
    """下拉框四选项分别路由到获取/清洗/导出/导入入口。"""
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog()
    try:
        called = []
        dlg._on_prepare_preview = lambda: called.append("fetch")
        dlg._on_clean_data = lambda: called.append("clean")
        dlg._on_export_data = lambda: called.append("export")
        dlg._on_import_data = lambda: called.append("import")
        for i, want in enumerate(("fetch", "clean", "export", "import")):
            dlg._on_data_tool_chosen(i)
            assert called[-1] == want
    finally:
        dlg.close()
        app.processEvents()


def test_data_tool_guard_while_preview_running(app, monkeypatch):
    """取数中下拉框保持可用作停止开关：数据获取走取消，其他选项提示稍候不执行。"""
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog()
    try:
        calls = []

        class _Running:
            def isRunning(self):
                return True

            def cancel(self):
                calls.append("cancel")

            def wait(self, *_a):
                return True

        dlg._preview_thread = _Running()
        infos = []
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QMessageBox.information", lambda *a, **k: infos.append(a[-1])
        )
        dlg._on_export_data = lambda: calls.append("export")  # 不应被调用
        dlg._on_data_tool_chosen(0)  # 数据获取 → 停止开关
        assert calls == ["cancel"]
        for i in (1, 2, 3):
            dlg._on_data_tool_chosen(i)
        assert calls == ["cancel"]  # 清洗/导出/导入均被拦截
        assert infos and "正在获取中" in infos[-1]
    finally:
        dlg.close()
        app.processEvents()


def test_do_export_uses_filtered_actors_and_dir(app, monkeypatch, tmp_path):
    """导出用当前筛选后的演员；保存框预填文件名、默认打开配置目录；列宽随屏幕计算。"""
    from mdcx.tools import emby_actor_export as ex
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog()
    try:
        cfg = ui.manager.config.model_copy(deep=True)
        cfg.actor_export_folder = str(tmp_path)
        monkeypatch.setattr(ui.manager, "config", cfg, raising=False)
        seen = {}
        monkeypatch.setattr(
            ui.manager, "_replace_config", lambda c: seen.update(cfg=c), raising=False
        )
        monkeypatch.setattr(ui.manager, "save", lambda: seen.update(saved=True), raising=False)
        opened = {}
        target = tmp_path / "演员数据表2026-10-16 10-42-27.xlsx"

        def _fake_save(*a, **k):
            opened["default"] = a[2] if len(a) > 2 else k.get("directory", "")
            return (str(target), "Excel 工作簿 (*.xlsx)")

        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", _fake_save)
        dlg._actors = [_actor(name="可见"), _actor(name="隐藏")]
        dlg.txt_search.setText("可见")
        app.processEvents()
        infos = []
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QMessageBox.information", lambda *a, **k: infos.append(a[-1])
        )
        dlg._do_export_actors()
        # 保存框默认路径 = 配置目录 + 本次导出的文件名。
        default = opened["default"]
        assert default.startswith(str(tmp_path))
        assert Path(default).name.startswith("演员数据表") and default.endswith(".xlsx")
        # 确认后所选目录写回配置，文件落到所选路径。
        assert seen["cfg"].actor_export_folder == str(tmp_path)
        assert seen.get("saved") is True
        assert target.exists()
        import openpyxl

        ws = openpyxl.load_workbook(target).active
        assert ws.max_row == 2 and ws.cell(row=2, column=1).value == "可见"
        # 列宽确系按本机屏幕逻辑宽度（物理宽/缩放比）换算，与纯函数同值。
        screen = dlg.screen()
        if screen is None:
            screen_px = ex.EXPORT_FALLBACK_SCREEN_PX
        else:
            screen_px = ex.effective_screen_width_px(screen)
        assert ws.column_dimensions["A"].width == pytest.approx(
            ex.text_col_width_for_screen_width(screen_px)
        )
        assert "共导出 1 个演员" in infos[-1]
    finally:
        dlg.close()
        app.processEvents()


def test_do_export_prompts_when_config_dir_invalid(app, monkeypatch, tmp_path):
    """配置目录无效时保存框默认只有文件名；用户所选路径用于导出，其目录写回配置。"""
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog()
    try:
        cfg = ui.manager.config.model_copy(deep=True)
        cfg.actor_export_folder = "Z:/不存在的目录-xyz"
        monkeypatch.setattr(ui.manager, "config", cfg, raising=False)
        seen = {}
        monkeypatch.setattr(
            ui.manager, "_replace_config", lambda c: seen.update(cfg=c), raising=False
        )
        monkeypatch.setattr(ui.manager, "save", lambda: seen.update(saved=True), raising=False)
        opened = {}
        target = tmp_path / "演员数据表2026-10-16 10-42-27.xlsx"

        def _fake_save(*a, **k):
            opened["default"] = a[2] if len(a) > 2 else k.get("directory", "")
            return (str(target), "Excel 工作簿 (*.xlsx)")

        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", _fake_save)
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QMessageBox.information", lambda *a, **k: None
        )
        dlg._actors = [_actor(name="可见")]
        dlg._do_export_actors()
        assert Path(opened["default"]).name.startswith("演员数据表")
        assert seen["cfg"].actor_export_folder == str(tmp_path)
        assert target.exists()
    finally:
        dlg.close()
        app.processEvents()


def test_do_export_cancelled_when_no_dir_chosen(app, monkeypatch):
    """保存框取消时中止导出，不写文件。"""
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog()
    try:
        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
        monkeypatch.setattr(
            "PyQt6.QtWidgets.QMessageBox.information", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应弹窗"))
        )
        dlg._actors = [_actor(name="可见")]
        dlg._do_export_actors()  # 不抛异常即通过
        assert "已取消数据导出" in dlg.log_text.toPlainText()
    finally:
        dlg.close()
        app.processEvents()
