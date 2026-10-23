"""设置-高级页两条 teal 提示词右移到「显示字段来源信息」竖线的回归测试。

需求沿革（锚点自身全程不动）：
  2026-10-23 第一批：四条提示词右移——隐藏图标行的「保存后重启生效」与隐藏入口行的
    提示词 →「显示字段内容信息」，改对话框行与分屏缩放行的两条 →「显示字段来源信息」。
  2026-10-23 第二批：**删除**前两条（`ui.label_42` / `ui.label_nav_hide_hint` 已从
    MDCx.ui 移除，本文件不再引用它们），只剩下面两条要守：

  - 改对话框行「目录中的文件较多时，可以勾选此项提高文件打开速度」→ 显示字段来源信息；
  - 分屏缩放行「保存后重启生效，可能会有点模糊」→ 显示字段来源信息。

根因防线（任一回归都会让本文件失败）：
  - 这两条提示词都是所在 QHBoxLayout 的末位项、horizontal sizePolicy 为 Minimum：
    末位项吃掉行内全部余量，左缘恒等于「前导控件右缘 + spacing」，与半页之外的锚点
    之间没有任何联动。修法是在末位项之前插 Fixed 间隔。
  - 间隔插在**前导控件之后**，前导控件的坐标不受间隔影响，故 gap 用实测值算即自洽
    （往返幂等）。分屏缩放行的前导控件是下拉框，它自身的宽度由另一条需求钉死
    （见 tests/test_advanced_scale_combo_width.py），本文件按实测值跟随。
  - 跨分支 mapTo（锚点在 groupBox_3、目标在 groupBox_12 的行里）必须经公共祖先
    scrollAreaWidgetContents_gaoji 中转。
  - 离屏环境没有 CJK 字体（见 test_advanced_page_tail_align.py 文件头那段），
    字形宽度不真实但稳定；故断言一律用「与锚点逐位相等」，不写死像素。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
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


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda *a, **k: None)
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


def _goto_advanced(win, app):
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


def _abs(ui, widget) -> int:
    return widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _extra(win) -> int:
    return win._scroll_stretch_extra(win._adv_scroll)


# 两条提示词 → (所在行内布局, 前导控件, 目标锚点)。
# 锚点取「左缘」而不是文字起点：本页所有竖线需求（隐藏菜单图标、使用暗黑模式、
# 隐藏NFO库管理…）一律以复选框方框的左缘为准，这里保持一致。
_HINTS = (
    ("label_421", "horizontalLayout_149", "checkBox_dialog_qt", "checkBox_show_from_log"),
    ("label_427", "horizontalLayout_dock_2", "comboBox_ui_scale", "checkBox_show_from_log"),
)

_ANCHORS = ("checkBox_show_from_log", "checkBox_show_data_log")

_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


def _natural_x(ui, lay_name, lead_name) -> int:
    """提示词在不插间隔时的自然左缘（前导控件右缘 + spacing）。"""
    lay = getattr(ui, lay_name)
    lead = getattr(ui, lead_name)
    return _abs(ui, lead) + lead.width() + lay.spacing()


def _baseline_without_hint_align(win, app, monkeypatch, width, height):
    """另起窗口、把「插间隔」这个动作整体摘掉，量同一组控件的几何。

    `_set_adv_hint_gap` 是两条提示词落点的唯一写入口，桩成 no-op 就等于回到本需求
    之前的自然位。不能在同一窗口上摘掉再跑一次：间隔项落在布局里、跨调用留存，
    量到的「基线」会带着新竖线（同 test_advanced_page_tail_align.py 里
    _without_feature 的坑）。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    original = mw_mod.MyMAinWindow._set_adv_hint_gap
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_set_adv_hint_gap", lambda self, *a, **k: False)
    probe = None
    try:
        probe = mw_mod.MyMAinWindow()
        for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
            getattr(probe, timer_name).stop()
        probe.show()
        _goto_advanced(probe, app)
        _resize(probe, app, width, height)
        ui = probe.Ui
        names = [h for h, *_ in _HINTS] + list(_ANCHORS)
        return {n: (_abs(ui, getattr(ui, n)), getattr(ui, n).width()) for n in names}
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        monkeypatch.setattr(mw_mod.MyMAinWindow, "_set_adv_hint_gap", original)


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_hints_land_on_from_log(win, app, width, height):
    """两态都要精确落在「显示字段来源信息」左缘上。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    want = _abs(ui, ui.checkBox_show_from_log)
    for hint_name, _, _, _ in _HINTS:
        got = _abs(ui, getattr(ui, hint_name))
        assert got == want, f"{width} 宽下「{hint_name}」未与「显示字段来源信息」严格上下对齐: x={got} 期望={want}"


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_anchors_never_move(win, app, monkeypatch, width, height):
    """两枚锚点逐位不动（需求原话「位置保持不变」），且提示词确实被搬走过。

    两条一起断言才有判别力：只比锚点的话，把整个控制器删掉也会「通过」；
    只比提示词的话，看不出是不是靠推走锚点换来的对齐。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = _baseline_without_hint_align(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for name in _ANCHORS:
        box = getattr(ui, name)
        assert (_abs(ui, box), box.width()) == base[name], (
            f"{width} 宽下锚点「{name}」被本需求带偏: 基线={base[name]} 实际={(_abs(ui, box), box.width())}"
        )
    for hint_name, lay_name, lead_name, _ in _HINTS:
        assert _abs(ui, getattr(ui, hint_name)) != _natural_x(ui, lay_name, lead_name), (
            f"{width} 宽下「{hint_name}」还停在自然位，本需求没生效"
        )


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_hints_never_clip(win, app, width, height):
    """提示词自身宽度不得被压到 sizeHint 以下（需求原话「提示词不许变」）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    for hint_name, *_ in _HINTS:
        box = getattr(ui, hint_name)
        assert box.width() >= box.sizeHint().width(), (
            f"{width} 宽下「{hint_name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_round_trip_matches_first_pass(win, app, width, height):
    """窄→宽→窄往返：两条提示词的落点与间隔宽度必须与第一遍逐位一致。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    _resize(win, app, width, height)
    first = {h: _abs(ui, getattr(ui, h)) for h, *_ in _HINTS}
    first_gaps = dict(win._adv_hint_gaps)

    _resize(win, app, 1920, 1170)
    _resize(win, app, width, height)

    assert {h: _abs(ui, getattr(ui, h)) for h, *_ in _HINTS} == first, "往返后提示词落点漂移"
    assert dict(win._adv_hint_gaps) == first_gaps, f"往返后间隔宽度漂移: {first_gaps} -> {win._adv_hint_gaps}"


def test_repeated_sync_is_idempotent(win, app):
    """重复调用全量同步不应再改动任何提示词几何（间隔宽度已封死成终态）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    for width, height in _WIDE_SIZES + _NARROW_SIZES:
        _resize(win, app, width, height)
        before = {h: (_abs(ui, getattr(ui, h)), getattr(ui, h).width()) for h, *_ in _HINTS}
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
            now = {h: (_abs(ui, getattr(ui, h)), getattr(ui, h).width()) for h, *_ in _HINTS}
            assert now == before, f"{width} 宽下重复同步仍在改几何: {before} -> {now}"


@pytest.mark.parametrize("width,height", ((900, 700), (820, 700)))
def test_extreme_narrow_never_makes_it_worse(win, app, monkeypatch, width, height):
    """极窄窗宽下放不下就保持自然位，且绝不比本需求之前更窄（不新增裁字）。

    这一档 `label_421` 的 sizeHint 本来就装不进行内剩余宽度，是**既有**的挤压，
    不是本需求造成的；故判据取「不劣于关掉本功能的基线」，而不是绝对的
    `width >= sizeHint`（那会在这一档恒红，且与本需求无关）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base = _baseline_without_hint_align(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for hint_name, lay_name, lead_name, _ in _HINTS:
        box = getattr(ui, hint_name)
        assert box.width() >= min(box.sizeHint().width(), base[hint_name][1]), (
            f"{width} 宽下「{hint_name}」比本需求之前更窄: {box.width()} < 基线 {base[hint_name][1]}"
            f"（sizeHint {box.sizeHint().width()}）"
        )
        # 放不下时必须回到自然位（左移越过锚点是不允许的）
        natural = _natural_x(ui, lay_name, lead_name)
        assert _abs(ui, box) >= min(natural, _abs(ui, ui.checkBox_show_from_log)), (
            f"{width} 宽下「{hint_name}」越过了自然位: x={_abs(ui, box)} natural={natural}"
        )
