"""信息管理页底部动作行：提示在上批量保存在下，三按钮 3:4:3 水平对齐。

需求：
1. 批量保存按钮与提示词调换：提示词在上、批量保存在下
   （grid row4=hint、row5=status、row6=save，save 是分组末行）。
2. 批量保存 / 保存当前nfo文件 / 裁剪封面按 3:4:3 分配宽度，最大化同步放大
   （三栏 stretch 3:4:3，三按钮各自铺满所在栏，中栏最宽）。
3. 裁剪封面沉到与保存当前nfo文件齐平：右栏海报/缩略图 1:1 均分裁剪封面上方
   高度，三按钮底边严格对齐（`_sync_nfo_lib_action_row` 以表单保存按钮底边
   为基准，左右各垫一个间隙 widget）。

精度说明：两侧列（stretch 3）严格相等（整数像素分配余数，容差 ≤2px）；
中栏是侧栏的 4/3（按 3×中栏 ≈ 4×侧栏断言，舍入累积容差 ≤10px）。
按钮宽度：保存当前nfo文件最宽；批量保存与裁剪封面差 ≤8px——批量保存
装在 QGroupBox 里，自身边框占掉约 6px（grid 边距已是 0），跨容器像素级
绝对相等做不到；比例验证用保存 vs 裁剪（两者都铺满所在栏，无边框不对称）。
y 与高度必须严格相等（这是需求 3 的字面要求）。

本文件只按「相对关系」断言，不写死像素（离屏无中文字体）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# 两侧按钮（批量保存 vs 裁剪封面）的宽度容差
# （见模块 docstring：GroupBox 边框约 6px + 整数像素余数 1~2px）
_WIDTH_TOLERANCE = 8
# 3:4:3 比例断言的舍入累积容差（列宽各自 ±1 舍入，3×/4× 放大后 ≤7，取 10 裕量）
_RATIO_TOLERANCE = 10
# 宽度断言只在最小值不捣乱的尺寸下做：480x600 时左栏 200px 下限会打破均分
_WIDE_SIZES = ((1030, 700), (1280, 800), (1920, 1080))
_ALL_SIZES = ((480, 600), (1030, 700), (1280, 800), (1920, 1080))


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
    from mdcx.config.manager import manager
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
    # 展开态 deterministic + 落盘桩（同 test_nfo_lib_batch_layout）。
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
    """切到信息管理页，灌一批番号，走一遍布局（分组默认展开）。"""
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


def _content_y(win, widget) -> int:
    """控件在内容区（nfo_lib_content）坐标系下的 y（跨列比较的统一标尺）。"""
    return widget.mapTo(win.Ui.nfo_lib_content, QPoint(0, 0)).y()


def _grid_row(win, widget) -> int:
    """控件在批量分组 grid 里的行号。"""
    grid = win.Ui.gridLayout_nfo_lib_batch
    index = grid.indexOf(widget)
    assert index >= 0, f"{widget.objectName()} 不在批量分组 grid 里"
    return grid.getItemPosition(index)[0]


def _action_buttons(win):
    ui = win.Ui
    return (ui.pushButton_nfo_lib_batch_save, ui.pushButton_nfo_lib_save, ui.pushButton_nfo_lib_crop)


def test_hint_sits_above_batch_save(win, app, nfo_lib_page):
    """提示词在上、批量保存在下：hint row4、status row5、save row6 且 save 是末行。"""
    ui = win.Ui
    assert _grid_row(win, ui.label_nfo_lib_batch_hint) == 4, "提示词不在第 4 行"
    assert _grid_row(win, ui.label_nfo_lib_batch_status) == 5, "状态行不在第 5 行"
    assert _grid_row(win, ui.pushButton_nfo_lib_batch_save) == 6, "批量保存不在第 6 行"
    assert _grid_row(win, ui.pushButton_nfo_lib_batch_save) == ui.gridLayout_nfo_lib_batch.rowCount() - 1, (
        "批量保存不是分组末行"
    )
    assert _content_y(win, ui.label_nfo_lib_batch_hint) < _content_y(win, ui.pushButton_nfo_lib_batch_save), (
        "提示词不在批量保存上方"
    )


def test_content_columns_split_3_4_3(win, app, nfo_lib_page):
    """三栏 stretch 3:4:3：两侧等宽、中栏是侧栏的 4/3（最小值不捣乱时）。"""
    ui = win.Ui
    layout = ui.nfo_lib_content_layout
    assert [layout.stretch(i) for i in range(3)] == [3, 4, 3], "三栏 stretch 不是 3:4:3"
    for size in _WIDE_SIZES:
        win.resize(*size)
        app.processEvents()
        win._sync_page_layouts()
        app.processEvents()
        widths = (ui.nfo_lib_list_panel.width(), ui.scrollArea_nfo_lib_form.width(), ui.nfo_lib_preview_panel.width())
        left, middle, right = widths
        # 两侧同为 stretch 3：整数像素分配余数，最多差 2。
        assert abs(left - right) <= 2, f"窗口 {size} 下两侧栏不等宽: {widths}"
        # 中栏最宽，且满足 3×中栏 ≈ 4×侧栏（每栏 ±1 舍入，放大后误差 ≤7）。
        assert middle > left and middle > right, f"窗口 {size} 下中栏不是最宽: {widths}"
        assert abs(3 * middle - 4 * left) <= _RATIO_TOLERANCE, f"窗口 {size} 下列宽不是 3:4:3: {widths}"
        assert abs(3 * middle - 4 * right) <= _RATIO_TOLERANCE, f"窗口 {size} 下列宽不是 3:4:3: {widths}"


@pytest.mark.parametrize("size", _WIDE_SIZES)
def test_three_buttons_share_width_3_4_3(win, app, nfo_lib_page, size):
    """三按钮按 3:4:3 分配宽度：保存当前nfo文件最宽，两侧差 ≤8px（GroupBox 边框）。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    batch, save, crop = (button.width() for button in _action_buttons(win))
    assert save > batch and save > crop, f"窗口 {size} 下保存按钮不是最宽: {(batch, save, crop)}"
    assert abs(batch - crop) <= _WIDTH_TOLERANCE, f"窗口 {size} 下两侧按钮不等宽: {(batch, save, crop)}"
    # 比例用保存 vs 裁剪验证（两者都铺满所在栏，无边框不对称）：3×保存 ≈ 4×裁剪。
    assert abs(3 * save - 4 * crop) <= _RATIO_TOLERANCE, f"窗口 {size} 下三按钮不是 3:4:3: {(batch, save, crop)}"
    assert min((batch, save, crop)) > 0, "有按钮宽度被压成 0"


def test_three_buttons_grow_together_on_maximize(win, app, nfo_lib_page):
    """最大化时三按钮同步放大：都变宽，且仍保持 3:4:3（中按钮最宽、两侧差 ≤8px）。"""
    win.resize(1030, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    narrow = [button.width() for button in _action_buttons(win)]

    win.resize(1920, 1080)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    wide = [button.width() for button in _action_buttons(win)]

    assert all(w > n for w, n in zip(wide, narrow, strict=True)), f"最大化后按钮没有同步放大: {narrow} -> {wide}"
    batch, save, crop = wide
    assert save > batch and save > crop, f"最大化后保存按钮不是最宽: {wide}"
    assert abs(batch - crop) <= _WIDTH_TOLERANCE, f"最大化后两侧按钮不等宽: {wide}"
    assert abs(3 * save - 4 * crop) <= _RATIO_TOLERANCE, f"最大化后三按钮不是 3:4:3: {wide}"


@pytest.mark.parametrize("size", _ALL_SIZES)
def test_three_buttons_share_baseline(win, app, nfo_lib_page, size):
    """三按钮底边严格对齐：y 与高度都必须精确相等。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    buttons = _action_buttons(win)
    ys = [_content_y(win, button) for button in buttons]
    heights = [button.height() for button in buttons]
    assert ys[0] == ys[1] == ys[2], f"窗口 {size} 下三按钮 y 不对齐: {ys}"
    assert heights[0] == heights[1] == heights[2], f"窗口 {size} 下三按钮高度不一致: {heights}"


@pytest.mark.parametrize("size", _WIDE_SIZES)
def test_previews_split_evenly_above_crop(win, app, nfo_lib_page, size):
    """海报/缩略图 1:1 均分裁剪封面上方的高度，裁剪封面沉底不溢出。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    ui = win.Ui
    poster = ui.label_nfo_lib_poster_preview
    thumb = ui.label_nfo_lib_thumb_preview
    crop = ui.pushButton_nfo_lib_crop
    assert [ui.nfo_lib_preview_layout.stretch(i) for i in range(3)] == [1, 1, 0], "右栏 stretch 不是 1:1:0"
    assert poster.height() == thumb.height() > 0, (
        f"窗口 {size} 下两预览没有均分高度: 海报 {poster.height()} vs 缩略图 {thumb.height()}"
    )
    assert _content_y(win, thumb) + thumb.height() <= _content_y(win, crop), f"窗口 {size} 下缩略图压住裁剪封面"
    panel_bottom = ui.nfo_lib_preview_panel.height()
    crop_bottom = crop.mapTo(ui.nfo_lib_preview_panel, QPoint(0, 0)).y() + crop.height()
    assert crop_bottom <= panel_bottom, f"窗口 {size} 下裁剪封面掉出右栏: {crop_bottom} > {panel_bottom}"


def test_collapsed_action_row_left_gap_zero_but_crop_stays_aligned(win, app, nfo_lib_page):
    """折叠态下批量保存藏着，左间隙归零；但右间隙照样按保存按钮底边重算——
    右列海报/缩略图 stretch 会吸走富余高度把裁剪封面顶下去，不垫的话裁剪封面
    与保存按钮错开（需求：勾不勾选都必须水平对齐）。"""
    ui = win.Ui
    ui.groupBox_nfo_lib_batch.setChecked(False)
    app.processEvents()
    assert ui.widget_nfo_lib_left_gap.height() == 0, "折叠后左间隙没有归零"
    assert _content_y(win, ui.pushButton_nfo_lib_crop) == _content_y(win, ui.pushButton_nfo_lib_save), (
        "折叠后裁剪封面与保存按钮错开: "
        f"{_content_y(win, ui.pushButton_nfo_lib_crop)} != {_content_y(win, ui.pushButton_nfo_lib_save)}"
    )


@pytest.mark.parametrize("size", _ALL_SIZES)
def test_collapsed_crop_aligned_at_all_sizes(win, app, nfo_lib_page, size):
    """折叠态全尺寸下裁剪封面与保存按钮 y 严格相等。"""
    ui = win.Ui
    ui.groupBox_nfo_lib_batch.setChecked(False)
    app.processEvents()
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    assert _content_y(win, ui.pushButton_nfo_lib_crop) == _content_y(win, ui.pushButton_nfo_lib_save), (
        f"窗口 {size} 折叠后错开: {_content_y(win, ui.pushButton_nfo_lib_crop)} != "
        f"{_content_y(win, ui.pushButton_nfo_lib_save)}"
    )


@pytest.mark.parametrize("size", _ALL_SIZES)
def test_action_row_sync_is_idempotent(win, app, nfo_lib_page, size):
    """按钮行同步多跑几遍不抖动（增量式间隙必须收敛，不能来回振荡）。"""
    win.resize(*size)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    ui = win.Ui
    first = (
        _content_y(win, ui.pushButton_nfo_lib_crop),
        ui.widget_nfo_lib_left_gap.height(),
        ui.widget_nfo_lib_preview_gap.height(),
    )
    for _ in range(3):
        win._sync_nfo_lib_action_row()
    app.processEvents()
    again = (
        _content_y(win, ui.pushButton_nfo_lib_crop),
        ui.widget_nfo_lib_left_gap.height(),
        ui.widget_nfo_lib_preview_gap.height(),
    )
    assert again == first, f"窗口 {size} 下重复同步后按钮行漂移: {first} -> {again}"
