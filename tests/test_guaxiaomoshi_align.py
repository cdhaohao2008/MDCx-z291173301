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
  6. 同列 4 个复选框（STRM 生成 / STRM 覆盖 / 元数据复用 / 视频模式删除）
     左缘严格一致，窄↔宽往返不变。
  9. Javdb 提示落进网格第 2 行（静态）：label_26 进 gridLayout_15 的
     (row2,col1)、javdb 延时行下移到 row3，容器高 129→155；组框高与其后
     7 组框、滚动内容均不动（值见测试断言）。
  10. Javdb 提示夹在两行之间（运行时）：提示在线程间隔下方、javdb 行上方且
     不重叠，x 与描述列相等，组框底部空白不超过一行行距，窄↔宽冻结。
  11. 补全模式「重新下载封面图片等文件」左缘与视频模式「删除本地已下载的图片和
     信息文件」严格上下对齐（锚点删除框不动），窄↔宽往返冻结；.ui 里不许再出现
     那枚 10px 缩进空标签。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
PY_PATH = REPO / "mdcx" / "views" / "MDCx.py"

# gridLayout_2 第 1 列同列复选框：STRM 生成 / STRM 覆盖 / 元数据复用 / 视频模式删除。
# 全部同处第 1 列，左缘必须严格一致。
# （原「整理模式间隔行」的两枚复选框已随任务模式迁移到「设置-高级」，此处不再登记。）
_MODE_CHECKBOXES = (
    "checkBox_separate_generate_strm",
    "checkBox_separate_overwrite_strm",
    "checkBox_separate_reuse_meta",
    "checkBox_sortmode_delpic",
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


def test_mode_checkboxes_left_aligned(win, app):
    """同列 3 复选框（生成/复用/删除）左缘严格一致，覆盖框同行居右，窄↔宽往返不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snapshot():
        return {name: _abs(ui, getattr(ui, name)) for name in _MODE_CHECKBOXES}

    _resize(win, app, 1030, 753)
    narrow = snapshot()
    aligned = {
        k: narrow[k]
        for k in (
            "checkBox_separate_generate_strm",
            "checkBox_separate_reuse_meta",
            "checkBox_sortmode_delpic",
        )
    }
    assert len(set(aligned.values())) == 1, f"同列复选框左缘不一致: {narrow}"
    assert narrow["checkBox_separate_overwrite_strm"] > narrow["checkBox_separate_generate_strm"], (
        f"覆盖框应同行居右: {narrow}"
    )
    _resize(win, app, 1920, 1170)
    wide = snapshot()
    assert wide == narrow, f"宽态复选框位置变动: {narrow} -> {wide}"
    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄→宽→窄往返未复原"


def test_overwrite_meta_aligns_under_overwrite_strm(win, app):
    """覆盖元数据框与覆盖 STRM 框上下严格对齐、与复用框同行，窄↔宽往返不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    narrow_meta = pos("checkBox_separate_overwrite_meta")
    narrow_strm = pos("checkBox_separate_overwrite_strm")
    narrow_reuse = pos("checkBox_separate_reuse_meta")
    assert narrow_meta[0] == narrow_strm[0], f"覆盖元数据框未与覆盖 STRM 框对齐: {narrow_meta} vs {narrow_strm}"
    assert narrow_meta[1] == narrow_reuse[1], f"覆盖元数据框未与复用框同行: {narrow_meta} vs {narrow_reuse}"
    assert narrow_meta[1] > narrow_strm[1], "覆盖元数据框应在覆盖 STRM 框下方"
    _resize(win, app, 1920, 1170)
    wide_meta = pos("checkBox_separate_overwrite_meta")
    wide_strm = pos("checkBox_separate_overwrite_strm")
    assert wide_meta == narrow_meta, f"宽态覆盖元数据框位置变动: {narrow_meta} -> {wide_meta}"
    assert wide_meta[0] == wide_strm[0], "宽态两覆盖框不对齐"
    _resize(win, app, 1030, 753)
    assert pos("checkBox_separate_overwrite_meta") == narrow_meta, "窄→宽→窄往返未复原"


def test_video_move_checkbox_aligns_with_overwrite_strm(win, app):
    """视频模式「移动已下载图片和文件到新目录」与「覆盖本地已存在的STRM链接文本」严格上下对齐。

    锚点框（覆盖 STRM）位置保持不变，只把新复选框右移到与它同 x；
    该 x 与复用行的右侧框一致（同一列的右对齐基准）。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    narrow_move = pos("checkBox_sortmode_movefile")
    narrow_strm = pos("checkBox_separate_overwrite_strm")
    narrow_meta = pos("checkBox_separate_overwrite_meta")
    narrow_delete = pos("checkBox_sortmode_delpic")
    assert narrow_move[0] == narrow_strm[0], f"移动框未与覆盖 STRM 框对齐: {narrow_move} vs {narrow_strm}"
    assert narrow_move[0] == narrow_meta[0], f"移动框未与其它行右侧框对齐: {narrow_move} vs {narrow_meta}"
    # 锚点框位置保持不变：仍与同列其它右侧框同 x
    assert narrow_strm[0] == narrow_meta[0], f"覆盖 STRM 框位置被改动: {narrow_strm}"
    # 移动框在「删除…」框右侧（同行的第二枚复选框）
    assert narrow_move[0] > narrow_delete[0], f"移动框应在删除框右侧: {narrow_move} vs {narrow_delete}"
    _resize(win, app, 1920, 1170)
    assert pos("checkBox_sortmode_movefile") == narrow_move, f"宽态移动框位置变动: {narrow_move}"
    assert pos("checkBox_separate_overwrite_strm") == narrow_strm, f"宽态覆盖 STRM 框位置变动: {narrow_strm}"
    _resize(win, app, 1030, 753)
    assert pos("checkBox_sortmode_movefile") == narrow_move, "窄→宽→窄往返未复原"
    assert pos("checkBox_separate_overwrite_strm") == narrow_strm, "窄→宽→窄往返未复原"


def test_again_download_checkbox_aligns_with_delpic(win, app):
    """补全模式「重新下载封面图片等文件」与视频模式「删除…」左缘严格上下对齐。

    用户需求（2026-10-23，截图批注）：重新下载框原先被行首一枚 10px 空标签
    （label_252）+ 行间距右推 16px，看起来像缩进在上一行之下；要求左移到与
    「删除本地已下载的图片和信息文件」同一条竖线上，且删除框位置保持不变。
    """
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    again = pos("checkBox_read_download_file_again")
    delete = pos("checkBox_sortmode_delpic")
    assert again[0] == delete[0], f"重新下载框未与删除框对齐: {again} vs {delete}"
    assert again[1] > delete[1], "重新下载框应在删除框下方（两行不同，只对齐左缘）"

    # 锚点（删除框）位置保持不变：仍落在 gridLayout_2 第 1 列的左缘。
    col_left = ui.gridLayoutWidget_2.mapTo(
        ui.scrollAreaWidgetContents_guaxiaomoshi, ui.gridLayout_2.cellRect(10, 1).topLeft()
    ).x()
    assert delete[0] == col_left, f"删除框被挪离列左缘: {delete} 期望 x={col_left}"

    # 补全模式三行选项（重新整理分类 / 重新下载 / 合并策略）左缘一致。
    for name in ("checkBox_read_has_nfo_update", "checkBox_nfo_merge_strategy"):
        assert pos(name)[0] == again[0], f"{name} 与重新下载框左缘不一致"

    # 窄↔宽往返冻结。
    _resize(win, app, 1920, 1170)
    assert pos("checkBox_read_download_file_again") == again, "宽态重新下载框位置变动"
    assert pos("checkBox_sortmode_delpic") == delete, "宽态删除框位置变动"
    _resize(win, app, 1030, 753)
    assert pos("checkBox_read_download_file_again") == again, "窄→宽→窄往返未复原"
    assert pos("checkBox_sortmode_delpic") == delete, "窄→宽→窄往返未复原"


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


def test_javdb_tip_between_rows_static():
    """事项9（静态）：提示已是 gridLayout_15 第 2 行（线程间隔与 javdb 延时之间）。

    用户需求（2026-10-23，截图批注）：提示原挂在 grid 外、落在 javdb 行下方，
    组框底部因此留出一大片空白；改为放进网格第 2 行、javdb 行下移到第 3 行，
    网格容器 129 → 155 吸收新增行，组框高与其后各组位置保持不变（空白由组框
    内部消化，页面不增高）。
    """
    tree = ET.parse(UI_PATH)
    grid = next((layout for layout in tree.iter("layout") if layout.get("name") == "gridLayout_15"), None)
    assert grid is not None, "找不到 gridLayout_15"
    cells: dict[tuple[str | None, str | None], tuple[str, str | None]] = {}
    for item in grid.findall("item"):
        child = list(item)[0]
        cells[(item.get("row"), item.get("column"))] = (child.tag, child.get("name"))
    assert cells.get(("1", "0")) == ("widget", "label_238"), f"线程间隔标签不在第 1 行: {cells}"
    assert cells.get(("2", "1")) == ("widget", "label_26"), f"提示不在第 2 行第 1 列: {cells}"
    assert cells.get(("3", "0")) == ("widget", "label_237"), f"javdb 延时标签不在第 3 行: {cells}"
    assert cells.get(("3", "1")) == ("layout", "horizontalLayout_57"), f"javdb 延时控件不在第 3 行: {cells}"

    # 提示不再自带 geometry（由网格排布），也不再是 groupBox_53 的直接子件。
    tip = next(widget for widget in tree.iter("widget") if widget.get("name") == "label_26")
    assert tip.find("property[@name='geometry']") is None, "label_26 还带 geometry，说明又脱离网格了"
    gb53 = next(widget for widget in tree.iter("widget") if widget.get("name") == "groupBox_53")
    assert "label_26" not in [w.get("name") for w in gb53.findall("widget")], "label_26 又挂回 groupBox_53"

    assert _ui_geometry("gridLayoutWidget_15")[3] == 155, "grid 容器高不是 155"
    assert _ui_geometry("groupBox_53")[3] == 193, "多线程刮削组框高变了（其下各组会跟着漂）"
    # 刮削模式组与其后各组：读取模式区被裁切修复后整体下移 41px（详见 test_read_mode_options_not_squeezed）；
    # 补全模式新增一行（2026-10-23）后再整体下移 37px；同日删掉两项后组框高 569 → 523，
    # 其下各组与滚动内容同步上收 46px。多线程刮削组框高未变，故本次全部不动。
    for name, y in (
        ("groupBox", 218),
        ("groupBox_5", 760),
        ("groupBox_2", 1240),
        ("groupBox_18", 1470),
        ("groupBox_27", 1600),
        ("groupBox_15", 1730),
        ("groupBox_30", 1860),
    ):
        assert _ui_geometry(name)[1] == y, f"{name} 的 y 不是 {y}"
    assert _ui_geometry("groupBox")[3] == 523, "刮削模式组框高不是 523"
    assert _ui_geometry("scrollAreaWidgetContents_guaxiaomoshi")[3] == 2060, "滚动内容高不是 2060"


def _content_pos(ui, widget):
    p = widget.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
    return (p.x(), p.y())


def test_javdb_tip_between_rows_and_frozen(win, app):
    """事项10（运行时）：提示夹在线程间隔与 javdb 延时两行之间、与描述列同 x，
    组框底部不再留大片空白，窄↔宽往返冻结。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snap():
        grid = ui.gridLayout_15
        grid.activate()  # 强制重布局，防读到未激活的陈旧几何（offscreen 下曾读到 pitch 42 的中间态）
        app.processEvents()
        win._sync_page_layouts()  # 用激活后的几何再收敛一次，方法与断言读同一份输入
        app.processEvents()
        content = ui.scrollAreaWidgetContents_guaxiaomoshi
        gb = ui.groupBox_53
        return {
            "interval": _content_pos(ui, ui.label_238),
            "tip": _content_pos(ui, ui.label_26),
            "javdb": _content_pos(ui, ui.label_237),
            "sep": _content_pos(ui, ui.label_separate_mode),
            "gb_bottom": gb.mapTo(content, QPoint(0, 0)).y() + gb.height(),
            "tip_h": ui.label_26.height(),
            "javdb_h": ui.label_237.height(),
            "pitch": grid.itemAtPosition(1, 1).geometry().y() - grid.itemAtPosition(0, 1).geometry().y(),
        }

    def check(a):
        assert a["interval"][1] < a["tip"][1], f"提示未排到线程间隔行下方: {a}"
        assert a["tip"][1] + a["tip_h"] <= a["javdb"][1], f"提示与 javdb 延时行重叠: {a}"
        assert a["tip"][0] == a["sep"][0], f"提示未与描述列同 x: {a['tip']} vs {a['sep']}"
        blank = a["gb_bottom"] - (a["javdb"][1] + a["javdb_h"])
        assert blank <= a["pitch"], f"组框底部空白 {blank}px 超过一行行距 {a['pitch']}px（多余空白没删干净）"

    _resize(win, app, 1030, 753)
    narrow = snap()
    check(narrow)
    _resize(win, app, 1920, 1170)
    wide = snap()
    # 宽态只锁结构与 x：提示是 wordWrap 标签，宽态折行减少会让行高变化（真机单行时两态一致）。
    check(wide)
    assert wide["tip"][0] == narrow["tip"][0], "宽态提示左缘被推走"
    _resize(win, app, 1030, 753)
    assert snap() == narrow, "窄→宽→窄往返未复原"
