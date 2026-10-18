"""设置-网络：「状态：留空不校验（默认）」下方大片空白的回归测试。

用户需求：最大化时该处出现一大片空白，删掉它；**最小化时页面布局、组件、控件、
提示词等等全部保持不变**。

根因（离屏实测）：
  网络页内容 widget 没有布局管理器，四个分组绝对定位、高度写死在 .ui 里
  （groupBox_28「网络设置」x30 y20 w701 h627、内层容器 gridLayoutWidget_9 x20 y30
  w661 h597；下面 groupBox_10「Cookie设置」y662 / groupBox_14 y1278 /
  groupBox_44 y1523，四段组间距恒为 15px）。通用宽幅同步
  （CustomScrollArea.sync_wide_children_width）每遍都按登记的设计几何 setGeometry
  ——**只改宽、高恒为设计值**。而「网络设置」里的两段说明是 wordWrap 换行标签：
  窗口拉宽后折行数下降、文字所需高度变矮（实测 label_103 136→120→80px、
  校验服务说明 54→40→26→12px），而内层 gridLayout_9 又设了 alignment=AlignTop
  （上一轮治「文字下方留空行」时加的），于是省下的高度全部堆在网格底部——组框仍按
  627 高画、内容只到 567/513/499，多出来的就是那片空盒子，且**越宽越大**，与用户
  「最大化才出现」的描述一致。

本文件锁的东西：
  - 宽态下「网络设置」分组必须贴住内容：容器高 == 内容真实底边、组框高 ==
    容器 y + 容器高，空白严格为 0；
  - 组框矮了多少，下面三个分组就同步上移多少，四段组间距恒为设计值 15px
    （空白是被**删掉**，不是挪到别处）；
  - 对照「摘掉本控制器」的基线：每一档宽态组框都不许比基线高，且**至少有一档确实
    变矮**（否则整份文件可能在钩子根本没跑的情况下空转通过）；
  - 窄态逐像素等于设计几何——需求明写「最小化时……全部保持不变」；
  - 窄→宽→窄往返精确复位、重复同步幂等、提示词与控件提示一个字都不许动。

关于字体度量：本离屏环境 resources/fonts 下没有任何 CJK 字体（tests/conftest.py 又把
get_fonts 桩掉 -> QFontDatabase.families() 为 0），字形 advance 只剩 .notdef，度量
既不真实也不稳定——「哪一档窗宽真的开始收窄」在测试环境与生产未必同档（实测测试环境
里 1100 宽尚未收窄、1366 起才收窄）。故本文件**不写死**「宽态必须矮多少」，只断言
与环境无关的两条等式（容器高 == 内容真实底边、组框高 == 容器 y + 容器高）加上
「不高于基线、且至少一档严格低于基线」；窄态空白本轮一个像素都不许动（那是既有
行为，与本需求无关），故窄态只断言等于设计几何。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QScrollArea

_app: QApplication | None = None

# 设计几何（MDCx.ui 设计态逐字读出，与 MDCx.py 编译产物一致）
_BOX_DESIGN_XY = (30, 20)
_BOX_DESIGN_H = 627
_HOST_DESIGN_XY = (20, 30)
_HOST_DESIGN_H = 597
_FOLLOW_NAMES = ("groupBox_10", "groupBox_14", "groupBox_44")
_FOLLOW_DESIGN_Y = (662, 1278, 1523)
_FOLLOW_GAP = 15

_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _build_window(monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda *a, **k: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda *a, **k: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda *a, **k: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda *a, **k: None)
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
    return window


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    window = _build_window(monkeypatch, tmp_path)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_network(win, app):
    """切到设置页的「网络」tab（按内容 widget 名找，不写死 tab 序号）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        tab = ui.tabWidget.widget(i)
        for sa in tab.findChildren(QScrollArea):
            content = sa.widget()
            if content is not None and content.objectName() == "scrollAreaWidgetContents_wangluo":
                ui.tabWidget.setCurrentIndex(i)
                break
        else:
            continue
        break
    else:
        raise AssertionError("网络 tab not found")
    app.processEvents()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _extra(win) -> int:
    return win._scroll_stretch_extra(win._wangluo_scroll)


def _content_bottom(ui) -> int:
    """gridLayoutWidget_9 内内容的真实底边（相对容器上缘），与字体度量无关。"""
    host = ui.gridLayoutWidget_9
    layout = host.layout()
    layout.invalidate()
    layout.activate()
    return host.childrenRect().bottom() + 1


def _snapshot(ui):
    box = ui.groupBox_28
    host = ui.gridLayoutWidget_9
    return {
        "box": (box.x(), box.y(), box.width(), box.height()),
        "host": (host.x(), host.y(), host.width(), host.height()),
        "follow": [getattr(ui, n).y() for n in _FOLLOW_NAMES],
    }


def _gaps(ui):
    """四个分组之间相邻的三段间距。"""
    box = ui.groupBox_28
    bottoms = [box.y() + box.height()]
    for name in _FOLLOW_NAMES:
        bottoms.append(getattr(ui, name).y() + getattr(ui, name).height())
    tops = [getattr(ui, n).y() for n in _FOLLOW_NAMES]
    return [tops[i] - bottoms[i] for i in range(len(_FOLLOW_NAMES))]


def _baseline_without_hug(win, app, monkeypatch, tmp_path):
    """另起一个窗口、全程摘掉本控制器，量同一处的组框高（宽态基线）。

    不能在同一个窗口上摘掉方法再跑一次同步——本方法留下的是 setGeometry 的终态，
    摘掉钩子再量到的「基线」已经带着收紧，比对就成了自己对自己（与
    test_advanced_page_tail_align._without_feature 同一个坑）。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_wangluo_net_box_hug", lambda self, *a, **k: None)
    probe = None
    try:
        probe = _build_window(monkeypatch, tmp_path)
        probe.show()
        _goto_network(probe, app)
        out = {}
        for width, height in _WIDE_SIZES:
            _resize(probe, app, width, height)
            out[(width, height)] = probe.Ui.groupBox_28.height()
        return out
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()


# ---------------------------------------------------------------------------
# 宽态：空白必须被删掉（而不是挪到别处）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_group_box_hugs_content(win, app, width, height):
    """最大化：「网络设置」分组收紧到贴住内容，组框底部不得再留空白。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    box = ui.groupBox_28
    host = ui.gridLayoutWidget_9
    content_bottom = _content_bottom(ui)
    assert host.height() == content_bottom, (
        f"{width} 宽下容器仍比内容高 {host.height() - content_bottom}px——那就是那片空白"
    )
    assert box.height() == _HOST_DESIGN_XY[1] + content_bottom, (
        f"{width} 宽下组框底部与内容底边之间还剩 {box.height() - _HOST_DESIGN_XY[1] - content_bottom}px 空白"
    )
    assert box.height() == _HOST_DESIGN_XY[1] + host.height(), (
        f"{width} 宽下组框高 {box.height()} 应恒等于「容器 y({_HOST_DESIGN_XY[1]}) + 容器高({host.height()})」"
    )
    # 收紧只许动高度：x / y / 宽度一律不许碰
    assert (box.x(), box.y()) == _BOX_DESIGN_XY, f"{width} 宽下组框左上角被挪动: ({box.x()}, {box.y()})"
    assert (host.x(), host.y()) == _HOST_DESIGN_XY, f"{width} 宽下容器左上角被挪动: ({host.x()}, {host.y()})"


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_following_boxes_close_up_by_same_delta(win, app, width, height):
    """最大化：组框矮了多少，下面三个分组就上移多少，三段组间距恒为 15px。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0

    delta = ui.groupBox_28.height() - _BOX_DESIGN_H
    assert delta <= 0, f"{width} 宽下本该只收紧不该撑高，实际 delta={delta}"
    for name, design_y in zip(_FOLLOW_NAMES, _FOLLOW_DESIGN_Y, strict=True):
        assert getattr(ui, name).y() == design_y + delta, (
            f"{width} 宽下「{name}」未随组框同步移动 {delta}px: y={getattr(ui, name).y()} 期望={design_y + delta}"
        )
    for i, gap in enumerate(_gaps(ui)):
        assert gap == _FOLLOW_GAP, f"{width} 宽下第 {i + 1} 段组间距={gap}，设计值 {_FOLLOW_GAP}"


def test_wide_never_taller_than_baseline_and_shrinks_somewhere(win, app, monkeypatch, tmp_path):
    """对照「摘掉本控制器」的基线：宽态组框不许更高，且至少有一档确实变矮。

    这一条是整份文件的判别力所在——上面两条断言在钩子根本没跑的时候也可能整份通过
    （内容恰好等于设计高时空白本就是 0），必须另有一条能证明收紧真的发生了。
    """
    ui = win.Ui
    win.show()
    _goto_network(win, app)

    got = {}
    for size in _WIDE_SIZES:
        _resize(win, app, *size)
        got[size] = ui.groupBox_28.height()
    base = _baseline_without_hug(win, app, monkeypatch, tmp_path)

    for size, want in base.items():
        assert got[size] <= want, (
            f"{size[0]} 宽下组框比「摘掉本控制器」的基线还高: {got[size]} > {want}（本需求只许收紧）"
        )
    shrunk = [size for size, want in base.items() if got[size] < want]
    assert shrunk, (
        f"宽态下没有任何一档收紧（各档 {got} / 基线 {base}）——本控制器没生效，"
        "或说明文字在本环境里根本不换行（那样这条需求也就无从验证）"
    )


# ---------------------------------------------------------------------------
# 窄态：需求明写「最小化时页面布局、组件、控件、提示词等等全部保持不变」
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_keeps_design_geometry(win, app, width, height):
    """最小化：四个分组与容器逐像素等于 .ui 设计几何，窄态一个像素都不碰。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    box = ui.groupBox_28
    host = ui.gridLayoutWidget_9
    assert (box.y(), box.height()) == (_BOX_DESIGN_XY[1], _BOX_DESIGN_H), (
        f"窄态 {width} 宽下「网络设置」分组几何被改: (y={box.y()}, h={box.height()}) "
        f"期望=({_BOX_DESIGN_XY[1]}, {_BOX_DESIGN_H})"
    )
    assert (host.y(), host.height()) == (_HOST_DESIGN_XY[1], _HOST_DESIGN_H), (
        f"窄态 {width} 宽下容器几何被改: (y={host.y()}, h={host.height()}) "
        f"期望=({_HOST_DESIGN_XY[1]}, {_HOST_DESIGN_H})"
    )
    for name, design_y in zip(_FOLLOW_NAMES, _FOLLOW_DESIGN_Y, strict=True):
        assert getattr(ui, name).y() == design_y, (
            f"窄态 {width} 宽下「{name}」被移动: y={getattr(ui, name).y()} 期望={design_y}"
        )


def test_narrow_never_touches_control_text_or_tooltips(win, app):
    """最小化：本需求不许改任何控件的提示词与控件提示（往返前后逐字比对）。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)
    _resize(win, app, 1030, 753)

    names = (
        "label_103",
        "label_cf_bypass_trusted_hosts",
        "label_cf_bypass_trusted_hosts_desc",
        "label_cf_bypass_trusted_hosts_check",
    )
    before = {n: (getattr(ui, n).text(), getattr(ui, n).toolTip()) for n in names}
    _resize(win, app, 1920, 1170)
    _resize(win, app, 1030, 753)
    for n, value in before.items():
        now = (getattr(ui, n).text(), getattr(ui, n).toolTip())
        assert now == value, f"往返后「{n}」的提示词/控件提示被本需求改动: {value} -> {now}"


# ---------------------------------------------------------------------------
# 往返与幂等
# ---------------------------------------------------------------------------


def test_round_trip_restores_design_geometry(win, app):
    """窄→宽→窄：窄态必须精确回到设计几何（不能残留上一态的收紧）。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)

    _resize(win, app, 1030, 753)
    first = _snapshot(ui)
    _resize(win, app, 1920, 1170)
    assert ui.groupBox_28.height() < _BOX_DESIGN_H, "宽态应处于收紧状态"
    _resize(win, app, 1030, 753)
    assert _snapshot(ui) == first, f"窄→宽→窄往返后窄态几何漂移: {first} -> {_snapshot(ui)}"


def test_repeated_sync_is_idempotent(win, app):
    """重复跑全量同步不应再改动任何几何（收紧量已封死成终态）。"""
    ui = win.Ui
    win.show()
    _goto_network(win, app)

    for width, height in _WIDE_SIZES + _NARROW_SIZES:
        _resize(win, app, width, height)
        before = _snapshot(ui)
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
            assert _snapshot(ui) == before, f"{width} 宽下重复同步仍在改几何: {before} -> {_snapshot(ui)}"
