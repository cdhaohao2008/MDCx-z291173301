"""设置-刮削模式页描述列对齐与单行显示的回归测试。

用户需求（2026-10-06，截图批注）：
  ① 刮削模式 5 行描述文字（正常/分离/视频/更新/读取模式的「执行：…」
     提示词）左缘，与「设置Javdb延时…」提示行左缘严格上下对齐——
     描述列曾无故右偏，本文件把对齐钉死。
  ② 5 行提示词必须是单行显示（wordWrap=false），以后不允许再变动位置——
     任何同步逻辑不得再搬动它们。

实现方式（见 init.py 刮削模式列钉死段）：
  - gridLayout_2（8 行模式组）与 gridLayout_15（Javdb 延时组）第 0 列
    stretch 钉 0、第 1 列钉 1，两网格第 0 列最小宽取各自全部行部件
    sizeHint 最大值再统一取大，保证两网格第 1 列左缘跨网格对齐。
  - 6 个描述 label 的 wordWrap 在 .ui 里直接改为 false（单行），并配同
    文案 tooltip 防极端 DPI 下被裁剪。
  - 一次性 init 钉死，不挂 _sync_page_layouts 钩子：通用宽幅同步只拉伸
    网格容器宽度，第 0 列最小宽不受影响，故同步前后位置恒定。

本文件 10 项（纯离线 + offscreen 窗口实测）：
  1. .ui 里 6 个 label 的 wordWrap 均为 false。
  2. MDCx.py 里 6 个 label 均为 setWordWrap(False)（与 .ui 同步）。
  3. 运行时 label_26 与 label_separate_mode 左缘精确对齐（映射到
     scrollAreaWidgetContents_guaxiaomoshi 下比对）。
  4. 两网格列 stretch 为 0/1，且 6 个 label 运行时 wordWrap 均为 False、
     tooltip 非空。
  5. 窄↔宽两态 + 重复同步，6 个 label 与 label_26 的左缘逐像素不变
     （以后不允许再变动位置）。
  6. STRM 行四枚复选框（生成 / 覆盖STRM / 复用 / 覆盖元数据）同排、顺序固定、
     首枚贴齐列左缘，且复用行删除后不留空行（行距与其它行一致）。
  7. 复用框右缘与分离模式描述**文字**右缘严格上下对齐（宽态精确相等；窄态夹到
     可用余量上限，但不许挤扁/裁字、不许撑破行），窄↔宽往返冻结。
  9. Javdb 提示上移一行（静态）：label_26 移出 gridLayout_15、独立为
     groupBox_53 子件，下方 7 组框与滚动内容同步上收（值见测试断言）。
  10. Javdb 提示上移一行（运行时）：0-2 行高一致且等距（未被搬动），提示 x 与
     分离描述文本精确相等，y 符合 row2底+spacing+share−h 公式，窄↔宽冻结。
  11. 补全模式「重新下载封面图片等文件」左缘贴齐 gridLayout_2 第 1 列左缘，
     窄↔宽往返冻结；.ui 里不许再出现那枚 10px 缩进空标签。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionButton

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
PY_PATH = REPO / "mdcx" / "views" / "MDCx.py"

# gridLayout_2 第 1 列同排的四枚复选框（2026-10-23 起同处 STRM 行）：
# 生成STRM链接 / 覆盖STRM链接 / 复用元数据 / 覆盖元数据，左缘必须严格一致。
# （原「整理模式间隔行」的两枚复选框已随任务模式迁移到「设置-高级」；
#  视频模式「删除/移动」两枚复选框已随功能删除，此处都不再登记。）
_MODE_CHECKBOXES = (
    "checkBox_separate_generate_strm",
    "checkBox_separate_overwrite_strm",
    "checkBox_separate_reuse_meta",
    "checkBox_separate_overwrite_meta",
)

# gridLayout_2 第 1 列 6 个描述 label：正常 / 整理 / 分离 / 视频 / 更新 / 读取。
_DESC_LABELS = (
    "label_11",
    "label_organize_mode",
    "label_separate_mode",
    "label_15",
    "label_36",
    "label_312",
)

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
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_guaxiaomoshi(win, app):
    """切到设置页的「刮削模式」tab（objectName 是 tab1）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab1":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("刮削模式 tab1 not found")
    app.processEvents()


def _abs(ui, widget):
    """控件左缘映射到刮削模式页滚动内容的绝对 x。"""
    return widget.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def test_desc_labels_single_line_in_ui():
    """需求②（静态）：.ui 里 6 个描述 label 的 wordWrap 必须为 false。"""
    tree = ET.parse(UI_PATH)
    missing = []
    for name in _DESC_LABELS:
        found = False
        for widget in tree.iter("widget"):
            if widget.get("name") == name:
                found = True
                for prop in widget.findall("property"):
                    if prop.get("name") == "wordWrap":
                        val = prop.find("bool").text == "true"
                        assert val is False, f".ui 里 {name} 的 wordWrap 又被改回 true（必须单行）"
                        break
                else:
                    raise AssertionError(f".ui 里 {name} 找不到 wordWrap 属性")
                break
        if not found:
            missing.append(name)
    assert not missing, f".ui 里找不到描述 label：{missing}"


def test_desc_labels_single_line_in_py():
    """需求②（同步）：MDCx.py 里 6 个 label 必须为 setWordWrap(False)。"""
    text = PY_PATH.read_text(encoding="utf-8")
    for name in _DESC_LABELS:
        assert f"self.{name}.setWordWrap(False)" in text, (
            f"MDCx.py 里 {name} 不是 setWordWrap(False)，请用 pyuic6 重生成"
        )


def test_desc_column_aligns_with_javdb_tip(win, app):
    """需求①：描述列左缘与 Javdb 延时提示行左缘严格上下对齐。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)

    anchor = _abs(ui, ui.label_26)
    for name in _DESC_LABELS:
        got = _abs(ui, getattr(ui, name))
        assert got == anchor, f"{name} 未与 label_26 对齐: x={got} 期望={anchor}"


def test_grid_columns_pinned_and_tooltips(win, app):
    """列钉死 + 单行 + tooltip：两网格列 stretch 为 0/1，运行时单行且有提示。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)

    for grid_name in ("gridLayout_2", "gridLayout_15"):
        grid = getattr(ui, grid_name)
        assert grid.columnStretch(0) == 0, f"{grid_name} 第 0 列 stretch 被改动"
        assert grid.columnStretch(1) == 1, f"{grid_name} 第 1 列 stretch 被改动"

    for name in _DESC_LABELS:
        label = getattr(ui, name)
        assert label.wordWrap() is False, f"运行时 {name} 的 wordWrap 不是 False"
        assert label.toolTip(), f"{name} 缺少 tooltip（极端 DPI 下文字会被裁剪）"


def test_desc_column_never_moves_again(win, app):
    """需求②（冻结）：窄↔宽两态 + 重复同步，描述列与锚点左缘逐像素不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snapshot():
        return {name: _abs(ui, getattr(ui, name)) for name in _DESC_LABELS + ("label_26",)}

    _resize(win, app, 1030, 753)
    narrow = snapshot()
    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄态二次同步漂移（以后不允许再变动位置）"

    _resize(win, app, 1920, 1170)
    wide = snapshot()
    # 宽态下描述列左缘必须与窄态一致：只允许容器变宽，不允许列左移/右移
    assert wide == narrow, f"宽态描述列位置变动: {narrow} -> {wide}"
    _resize(win, app, 1920, 1170)
    assert snapshot() == wide, "宽态二次同步漂移"

    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄→宽→窄往返未复原"


def test_strm_row_holds_four_checkboxes(win, app):
    """STRM 行四枚复选框同排：生成 / 覆盖STRM / 复用 / 覆盖元数据，顺序与行内位置固定。

    用户需求（2026-10-23，截图批注）：复用元数据 / 覆盖元数据两枚复选框从独立的一行
    上移进 STRM 行、紧跟覆盖STRM链接之后；原复用行整行删除（下方各行上移一行，行距不变）。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    row = ui.horizontalLayout_strm
    names = []
    for i in range(row.count()):
        widget = row.itemAt(i).widget()
        names.append(widget.objectName() if widget is not None else "")
    assert names == [
        "checkBox_separate_generate_strm",
        "checkBox_separate_overwrite_strm",
        "",
        "checkBox_separate_reuse_meta",
        "checkBox_separate_overwrite_meta",
        "",
    ], f"STRM 行成员/顺序被改: {names}"

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    boxes = [pos(n) for n in _MODE_CHECKBOXES]
    assert len({y for _x, y in boxes}) == 1, f"四枚复选框不在同一行: {boxes}"
    assert [x for x, _y in boxes] == sorted(x for x, _y in boxes), f"行内顺序错: {boxes}"
    # 首枚贴齐 gridLayout_2 第 1 列左缘（与描述列同一条竖线）
    col_left = ui.gridLayoutWidget_2.mapTo(
        ui.scrollAreaWidgetContents_guaxiaomoshi, ui.gridLayout_2.cellRect(3, 1).topLeft()
    ).x()
    assert boxes[0][0] == col_left, f"首枚复选框未贴齐列左缘: {boxes[0]} 期望 x={col_left}"

    # 复用行删掉后不许留下空行：STRM 行→视频模式行的行距必须与其它相邻行一致。
    def pitch(r1, r2):
        return ui.gridLayout_2.cellRect(r2, 1).y() - ui.gridLayout_2.cellRect(r1, 1).y()

    assert pitch(3, 5) == pitch(1, 2) == pitch(2, 3), f"STRM 行与视频模式行之间残留空行: {pitch(3, 5)} vs {pitch(2, 3)}"

    # 窄↔宽往返：行内位置只随间距项变化，成员与顺序不变
    _resize(win, app, 1920, 1170)
    wide = [pos(n) for n in _MODE_CHECKBOXES]
    assert len({y for _x, y in wide}) == 1, f"宽态四枚复选框不在同一行: {wide}"
    _resize(win, app, 1030, 753)
    assert [pos(n) for n in _MODE_CHECKBOXES] == boxes, "窄→宽→窄往返未复原"


def test_overwrite_meta_right_edge_aligns_with_separate_desc(win, app):
    """覆盖元数据右缘与分离模式描述文字右缘严格上下对齐，复用元数据紧随其左。

    用户需求（2026-10-23 第二轮截图批注）：四枚复选框整体左移，改成让**最后一枚
    「覆盖元数据」**的文字右缘落在上一行描述文字「…视频与元数据分开存放」右缘那条
    竖线上；描述行本身一个像素都不动。

    锚点是描述 label 的**文字**右缘（label 被拉宽到整格，width() 比文字宽出几十像素，
    见 DADA/MEMORY.md「锚点必须用 sizeHint 而不是 width」）；复选框同理要用
    SE_CheckBoxContents 起点 + 文字宽，widget 右缘多出几像素尾部留白。
    调节顺序：先收 gap spacer，收没了再压行内 spacing —— 两态都必须严格对齐，
    且不许把复选框挤扁/裁字、不许把行撑破。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    content = ui.scrollAreaWidgetContents_guaxiaomoshi

    def snapshot():
        label = ui.label_separate_mode
        reuse = ui.checkBox_separate_reuse_meta
        over = ui.checkBox_separate_overwrite_meta
        row = ui.horizontalLayout_strm
        lp = label.mapTo(content, QPoint(0, 0))
        rp = reuse.mapTo(content, QPoint(0, 0))
        op = over.mapTo(content, QPoint(0, 0))
        cell = ui.gridLayout_2.cellRect(3, 1)
        row_right = ui.gridLayoutWidget_2.mapTo(content, cell.topLeft()).x() + cell.width()
        # 复选框的文字右缘：内容区起点（样式给的 SE_CheckBoxContents）+ 文字宽，
        # widget 右缘比它多出几像素尾部留白，不能直接拿 width() 当文字右缘。
        option = QStyleOptionButton()
        over.initStyleOption(option)
        text_rect = over.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, over)
        return {
            "text_right": lp.x() + label.fontMetrics().horizontalAdvance(label.text()),
            "over_text_right": op.x() + text_rect.x() + over.fontMetrics().horizontalAdvance(over.text()),
            "reuse_right": rp.x() + reuse.width(),
            "over_left": op.x(),
            "over_right": op.x() + over.width(),
            "row_right": row_right,
            "gap": row.itemAt(2).geometry().width(),
            "spacing": row.spacing(),
            "widths": [getattr(ui, n).width() for n in _MODE_CHECKBOXES],
            "size_hints": [getattr(ui, n).sizeHint().width() for n in _MODE_CHECKBOXES],
        }

    for width, height in ((1030, 753), (1920, 1170)):
        _resize(win, app, width, height)
        snap = snapshot()
        assert snap["over_text_right"] == snap["text_right"], (
            f"{width} 宽下覆盖元数据文字右缘未与描述文字右缘对齐: {snap['over_text_right']} vs {snap['text_right']}"
        )
        assert snap["over_left"] > snap["reuse_right"], f"{width} 宽下复用框未排在覆盖元数据左侧: {snap}"
        assert snap["over_right"] <= snap["row_right"], f"{width} 宽下覆盖元数据超出 STRM 行: {snap}"
        assert snap["widths"] == snap["size_hints"], f"{width} 宽下复选框被挤扁: {snap}"
        assert snap["gap"] >= 0 and snap["spacing"] >= 0, f"{width} 宽下出现负间距: {snap}"

    # 往返冻结：宽→窄→宽 回到同一组数值（spacing 每遍先复位成设计值，幂等）
    _resize(win, app, 1030, 753)
    narrow = snapshot()
    _resize(win, app, 1920, 1170)
    wide = snapshot()
    assert wide["over_text_right"] == wide["text_right"] == narrow["over_text_right"], "往返后对齐漂移"
    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "宽→窄往返后窄态数值漂移"


def test_again_download_checkbox_at_column_left(win, app):
    """补全模式「重新下载封面图片等文件」左缘贴齐 gridLayout_2 第 1 列左缘。

    用户需求（2026-10-23，截图批注）：重新下载框原先被行首一枚 10px 空标签
    （label_252）+ 行间距右推 16px，看起来像缩进在上一行之下；要求左移到与该列
    其它复选框同一条竖线上。视频模式「删除/移动」两枚复选框已随功能删除，
    这里改用列左缘（cellRect(10, 1)）作为锚点。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    again = pos("checkBox_read_download_file_again")

    # 锚点：gridLayout_2 第 1 列的左缘（同列复选框都在这一条竖线上）。
    col_left = ui.gridLayoutWidget_2.mapTo(
        ui.scrollAreaWidgetContents_guaxiaomoshi, ui.gridLayout_2.cellRect(10, 1).topLeft()
    ).x()
    assert again[0] == col_left, f"重新下载框被挪离列左缘: {again} 期望 x={col_left}"

    # 补全模式三行选项（重新整理分类 / 重新下载 / 合并策略）左缘一致。
    for name in ("checkBox_read_has_nfo_update", "checkBox_nfo_merge_strategy"):
        assert pos(name)[0] == again[0], f"{name} 与重新下载框左缘不一致"

    # 窄↔宽往返冻结。
    _resize(win, app, 1920, 1170)
    assert pos("checkBox_read_download_file_again") == again, "宽态重新下载框位置变动"
    _resize(win, app, 1030, 753)
    assert pos("checkBox_read_download_file_again") == again, "窄→宽→窄往返未复原"


def test_no_indent_label_before_again_checkbox():
    """静态哨兵：补全模式「重新下载」行首不许再出现 10px 缩进空标签（label_252）。"""
    tree = ET.parse(UI_PATH)
    names = {w.get("name") for w in tree.iter("widget")}
    assert "label_252" not in names, "「重新下载」行首的缩进空标签又回来了（会把整行右推 16px）"


def test_read_mode_options_not_squeezed(win, app):
    """读取模式区的选项不能被压扁裁切（用户 2026-10-21 截图：两行文字被遮挡重叠）。

    根因：gridLayout_2 的布局最小高度（482px）超过其容器 gridLayoutWidget_2 的设计高度
    （447px），Qt 会把差出来的 35px 从最后一行（读取模式选项区 verticalLayout_5）硬挤掉，
    该区只剩 87px（最小需要 122px），里面两行复选框被压到 6px/5px，文字互相裁切重叠。
    修复：.ui 里把容器高度抬到 488px（下方分组整体下移 41px）。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    # 2026-10-23 精简：删掉「允许更新NFO文件」「无 NFO 按正常模式重新刮削」两项，
    # 补全模式下方只剩两枚复选框 + 合并策略勾选框与下拉框。
    widgets = (
        "checkBox_read_has_nfo_update",
        "checkBox_read_download_file_again",
        "checkBox_nfo_merge_strategy",
        "comboBox_nfo_merge_strategy",
        "label_345",
        "label_347",
    )
    for width, height in ((1030, 753), (860, 600)):
        _resize(win, app, width, height)
        for name in widgets:
            widget = getattr(ui, name)
            got = widget.height()
            need = widget.minimumSizeHint().height()
            assert got >= need, f"{width}x{height} 下 {name} 被压扁：{got} < 最小 {need}"
        box = ui.verticalLayout_5
        assert box.geometry().height() >= box.minimumSize().height(), (
            f"{width}x{height} 下读取模式区高度 {box.geometry().height()} < 最小 {box.minimumSize().height()}"
        )
        # 三行（两枚复选框 + 合并策略行）依次排开，不许重叠
        rows = (ui.checkBox_read_has_nfo_update, ui.checkBox_read_download_file_again, ui.checkBox_nfo_merge_strategy)
        tops = [row.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0)).y() for row in rows]
        for upper, lower, top in zip(rows, rows[1:], tops[1:], strict=False):
            assert top >= upper.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0)).y() + upper.height(), (
                f"补全模式区选项行重叠：{upper.objectName()} 与 {lower.objectName()}"
            )


def test_reuse_overwrite_meta_mutually_exclusive(win, app):
    """复用/覆盖元数据互斥：勾选其一自动去勾另一，去勾不动作。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)
    reuse = ui.checkBox_separate_reuse_meta
    overwrite = ui.checkBox_separate_overwrite_meta
    reuse.setChecked(False)
    overwrite.setChecked(False)
    app.processEvents()
    reuse.setChecked(True)
    app.processEvents()
    assert reuse.isChecked() and not overwrite.isChecked(), "勾选复用后覆盖应自动去勾"
    overwrite.setChecked(True)
    app.processEvents()
    assert overwrite.isChecked() and not reuse.isChecked(), "勾选覆盖后复用应自动去勾"
    overwrite.setChecked(False)
    app.processEvents()
    assert not overwrite.isChecked() and not reuse.isChecked(), "去勾不应影响另一方"
    reuse.setChecked(False)
    app.processEvents()


def test_overwrite_strm_links_generate_checkbox(win, app):
    """覆盖是生成的后置动作：勾覆盖自动带上生成，取消生成则覆盖一并取消。

    覆盖框不再置灰（用户要能先勾覆盖），改由勾选时的联动保证组合合法。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    generate = ui.checkBox_separate_generate_strm
    overwrite = ui.checkBox_separate_overwrite_strm
    generate.setChecked(False)
    overwrite.setChecked(False)
    app.processEvents()
    assert overwrite.isEnabled(), "覆盖框不应被置灰（勾选覆盖会自动带上生成）"

    # 勾选覆盖 → 同步勾选生成
    overwrite.setChecked(True)
    app.processEvents()
    assert generate.isChecked(), "勾选覆盖时必须同步勾选生成"
    assert overwrite.isEnabled(), "勾选生成后覆盖框应可用"

    # 取消生成 → 覆盖一并取消
    generate.setChecked(False)
    app.processEvents()
    assert not overwrite.isChecked(), "取消生成后覆盖项应同步取消"
    assert overwrite.isEnabled(), "覆盖框不应被置灰"

    generate.setChecked(False)
    overwrite.setChecked(False)
    app.processEvents()


def _ui_geometry(name):
    """静态辅助：.ui 里 widget 的 design geometry，返回 (x, y, w, h)。"""
    tree = ET.parse(UI_PATH)
    for widget in tree.iter("widget"):
        if widget.get("name") == name:
            for prop in widget.findall("property"):
                if prop.get("name") == "geometry":
                    rect = prop.find("rect")
                    return tuple(int(rect.find(k).text) for k in ("x", "y", "width", "height"))
    raise AssertionError(f".ui 里找不到 widget：{name}")


def test_javdb_tip_moved_up_one_line_static():
    """事项9（静态）：label_26 移出 grid，7 组框与内容同步上收（值见下方断言）。"""
    tree = ET.parse(UI_PATH)
    for layout in tree.iter("layout"):
        if layout.get("name") == "gridLayout_15":
            assert "3" not in [item.get("row") for item in layout.findall("item")], (
                "gridLayout_15 里还有 row3，label_26 又被塞回 grid"
            )
            assert "label_26" not in ET.tostring(layout, encoding="unicode"), "label_26 还在 grid 内"
            break
    else:
        raise AssertionError("找不到 gridLayout_15")
    for widget in tree.iter("widget"):
        if widget.get("name") == "groupBox_53":
            assert "label_26" in [w.get("name") for w in widget.findall("widget")], (
                "label_26 不是 groupBox_53 的直接子件"
            )
            break
    else:
        raise AssertionError("找不到 groupBox_53")
    assert _ui_geometry("label_26") == (146, 160, 513, 28), "label_26 设计几何被改动"
    assert _ui_geometry("gridLayoutWidget_15")[3] == 129, "grid 容器高不是 129"
    # 刮削模式组与其后各组：读取模式区被裁切修复后整体下移 41px（详见 test_read_mode_options_not_squeezed）；
    # 补全模式新增一行（2026-10-23）后再整体下移 37px；同日删掉两项后组框高 569 → 523，
    # 其下各组与滚动内容同步上收 46px。同日「复用元数据 / 覆盖元数据」并入 STRM 行、
    # 原复用行删除：模式组再上收 52px（gridLayoutWidget_2 479 → 427，行距保持 43）。
    for name, y in (
        ("groupBox", 218),
        ("groupBox_5", 708),
        ("groupBox_2", 1188),
        ("groupBox_18", 1418),
        ("groupBox_27", 1548),
        ("groupBox_15", 1678),
        ("groupBox_30", 1808),
    ):
        assert _ui_geometry(name)[1] == y, f"{name} 的 y 不是 {y}"
    assert _ui_geometry("groupBox")[3] == 471, "刮削模式组框高不是 471"
    assert _ui_geometry("gridLayoutWidget_2")[3] == 427, "刮削模式网格容器高不是 427"
    assert _ui_geometry("scrollAreaWidgetContents_guaxiaomoshi")[3] == 2008, "滚动内容高不是 2008"


def _content_pos(ui, widget):
    p = widget.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
    return (p.x(), p.y())


def test_javdb_tip_up_one_line_and_frozen(win, app):
    """事项10（运行时）：0-2 行 pitch 保持 45，提示 x 与分离文本精确相等，
    y 符合公式，窄↔宽往返冻结。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snapshot():
        grid = ui.gridLayout_15
        grid.activate()  # 强制重布局，防读到未激活的陈旧几何（offscreen 下曾读到 pitch 42 的中间态）
        app.processEvents()
        win._sync_page_layouts()  # 用激活后的几何再收敛一次，方法与断言读同一份输入
        app.processEvents()
        widget = ui.gridLayoutWidget_15
        content = ui.scrollAreaWidgetContents_guaxiaomoshi
        tops, heights = [], []
        for r in range(3):
            g = grid.itemAtPosition(r, 1).geometry()
            tops.append(widget.mapTo(content, g.topLeft()).y())
            heights.append(g.height())
        s = grid.verticalSpacing()
        if s < 0:
            s = grid.spacing()
        share = (widget.height() - sum(heights) - 2 * s) / 3
        h = ui.label_26.fontMetrics().height()
        return (
            tops,
            heights,
            s,
            share,
            h,
            _content_pos(ui, ui.label_26),
            _content_pos(ui, ui.label_separate_mode),
            _content_pos(ui, widget),
        )

    _resize(win, app, 1030, 753)
    tops, heights, s, share, h, tip, sep, wpos = snapshot()
    # 行高一致且等距（不同字体环境行高不同，不锁死 45，只锁结构不变）。
    assert heights[0] == heights[1] == heights[2], f"0-2 行高不一致: {heights}"
    pitch = tops[1] - tops[0]
    assert tops[2] - tops[1] == pitch, f"0-2 行间距不均匀: {tops}"
    assert tip[0] == sep[0], f"提示未与分离文本对齐: {tip} vs {sep}"
    row2bottom = tops[2] - wpos[1] + heights[2]
    assert tip[1] == wpos[1] + row2bottom + s + share - h, f"提示 y 不符合公式: {tip}"
    _resize(win, app, 1920, 1170)
    wide = snapshot()
    assert wide[0] == tops, f"宽态 0-2 行位置变动: {tops} -> {wide[0]}"
    assert wide[5] == tip and wide[6] == sep, f"宽态提示/锚点变动: {tip} -> {wide[5]}"
    _resize(win, app, 1030, 753)
    back = snapshot()
    assert back[0] == tops and back[5] == tip, "窄→宽→窄往返未复原"
