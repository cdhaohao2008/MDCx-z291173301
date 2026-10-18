"""设置-网络：「全部走代理」右留白 ≡「使用代理」左留白的回归测试。

用户需求：「软件设置-网络-全部走代理向左移动使得全部走代理最右侧到右边界的间距与
使用代理最左侧到左边界的间距相等，使用代理位置保持不变，只向左移动全部走代理」。

改法（`mdcx/views/MDCx.ui` + 重编译产物 `mdcx/views/MDCx.py` +
`mdcx/controllers/main_window/layout_settings.py`）：
  - 代理开关行由 `gridLayout_9` 的 `row 0 column 1`（占 1 格）改为
    `row 0 column 1 colspan 3`：右界从 col 1 右缘换到网格内容右缘（col 1 右边还有
    col 2 / col 3 两个零宽格和两个 spacing，只占 col 1 时右界天生偏左 12px）；
  - 该行加 `rightMargin=138`（= 本机离屏实测 col0 132 + spacing 6，即「使用代理」
    左缘到网格内容左缘的距离），富余宽度仍由行内 Expanding spacer 吃掉，
    「使用代理」按自然宽度钉在行首；
  - 138 只是设计态初值，左留白由网格按字体度量算出、右留白由内边距写死，两者不同源，
    故 `_sync_wangluo_proxy_row_margin` 每遍用 `mapTo` 实测左留白回写右内边距。

本文件锁的东西（全部是与字体度量无关的**等式**，不写死任何绝对像素）：
  - 左右留白恒等（窄态、宽态各档窗口宽度都成立）；
  - 「使用代理」左缘恒等于 `lineEdit_proxy` 左缘（同为 col 1 起点，一个像素没动）；
  - 两个开关仍同行同高（`y` / `height` 逐像素相等）；
  - 重复同步幂等，窄↔宽往返自愈；
  - 对照「摘掉本控制器」的基线：摘掉后右留白必须**变小**（回到行右缘），否则这份
    文件可能在钩子根本没跑的情况下空转通过。

关于字体度量：本离屏环境无 CJK 字体（`tests/conftest.py` 把 `get_fonts` 桩掉），
`col 0` 实际宽多少随环境而变——所以只断言「两侧相等」，不写死 138。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QScrollArea

_app: QApplication | None = None

_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850))
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


def _margins(ui):
    """(左留白, 右留白)：都以 gridLayout_9 的内容左右缘为界，与字体度量无关。

    网格 contentsMargins 为 0 且铺满容器 gridLayoutWidget_9，故容器坐标即网格坐标。
    """

    host = ui.gridLayoutWidget_9
    use = ui.checkBox_use_proxy
    route = ui.checkBox_proxy_route_all
    lead = use.mapTo(host, QPoint(0, 0)).x()
    trail = host.width() - (route.mapTo(host, QPoint(0, 0)).x() + route.width())
    return lead, trail


def _without_feature(win, app, monkeypatch, tmp_path):
    """另起一个窗口、全程摘掉本控制器，量同一处的两侧留白（基线）。

    不能在同一个窗口上摘掉钩子再量：本控制器留下的是 setContentsMargins 的终态，
    摘钩后量到的「基线」已带着对齐，比对就成了自己对自己。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_wangluo_proxy_row_margin", lambda self: None)
    probe = None
    try:
        probe = _build_window(monkeypatch, tmp_path)
        probe.show()
        _goto_network(probe, app)
        out = {}
        for width, height in _WIDE_SIZES + _NARROW_SIZES:
            _resize(probe, app, width, height)
            out[(width, height)] = _margins(probe.Ui)
        return out
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()


# ---------------------------------------------------------------------------
# 等式：左右留白相等（窄态 + 宽态逐档）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_row_margins_are_equal(win, app, width, height):
    """「全部走代理」右缘到网格右缘的留白 ≡「使用代理」左缘到网格左缘的留白。"""
    win.show()
    _goto_network(win, app)
    _resize(win, app, width, height)

    lead, trail = _margins(win.Ui)
    assert lead > 0, f"{width} 宽下左留白读数为 {lead}，页面尚未布局"
    assert lead == trail, (
        f"{width} 宽下两侧留白不等：左(使用代理)={lead} 右(全部走代理)={trail}，"
        f"「全部走代理」还停在行右缘，未按左留白向左让出等量空白"
    )


def test_use_proxy_stays_put(win, app):
    """「使用代理」位置保持不变：左缘恒等于 lineEdit_proxy 左缘（本需求不许挪它）。"""
    win.show()
    _goto_network(win, app)
    for width, height in _NARROW_SIZES + _WIDE_SIZES:
        _resize(win, app, width, height)
        ui = win.Ui
        use_x = ui.checkBox_use_proxy.mapTo(ui.gridLayoutWidget_9, QPoint(0, 0)).x()
        edit_x = ui.lineEdit_proxy.mapTo(ui.gridLayoutWidget_9, QPoint(0, 0)).x()
        assert use_x == edit_x, (
            f"{width} 宽下「使用代理」左缘 x={use_x} 与代理地址输入框左缘 x={edit_x} 不一致——被本需求挪动了"
        )


def test_two_switches_share_row_and_height(win, app):
    """两个开关仍同行同高（用户要求里「严格水平对齐」的那一条不许退化）。"""
    win.show()
    _goto_network(win, app)
    for width, height in _NARROW_SIZES + _WIDE_SIZES:
        _resize(win, app, width, height)
        ui = win.Ui
        use = ui.checkBox_use_proxy.geometry()
        route = ui.checkBox_proxy_route_all.geometry()
        assert (use.y(), use.height()) == (route.y(), route.height()), (
            f"{width} 宽下两个开关不同高: 使用代理 y={use.y()} h={use.height()} / "
            f"全部走代理 y={route.y()} h={route.height()}"
        )


def test_controller_actually_writes_right_margin(win, app, monkeypatch, tmp_path):
    """判别力：摘掉本控制器后右留白必须与在位时不同，否则整份文件可能空转通过。

    .ui 里的 rightMargin=138 只是设计态初值；本控制器负责按实测左留白回写，故摘掉
    它之后行内右内边距就停在那个初值上。字体度量随环境而变（测试环境无 CJK 字体），
    故不比「基线是否恰好不等」，只断言「基线的右留白与在位时至少有一档不同」——
    不同即证明控制器真的动了手；配合 test_row_margins_are_equal 的等式即可反证
    「相等」是控制器挣来的，不是 .ui 初值碰巧撞上的。
    """
    win.show()
    _goto_network(win, app)

    mine = {}
    for width, height in _WIDE_SIZES + _NARROW_SIZES:
        _resize(win, app, width, height)
        mine[(width, height)] = _margins(win.Ui)
    base = _without_feature(win, app, monkeypatch, tmp_path)

    assert base, "基线没量到任何一档"
    changed = [size for size, (lead, trail) in base.items() if trail != mine[size][1]]
    assert changed, (
        f"摘掉本控制器后各档右留白与在位时完全相同（基线 {base} / 在位 {mine}）——"
        "本控制器根本没生效，剩下几条等式可能全是 .ui 初值碰巧撞上的"
    )


def test_sync_is_idempotent_and_round_trips(win, app):
    """重复同步幂等；窄→宽→窄往返后两侧留白仍相等，无累积漂移。"""
    win.show()
    _goto_network(win, app)
    _resize(win, app, 1030, 753)
    first = _margins(win.Ui)
    for _ in range(3):
        win._sync_wangluo_proxy_row_margin()
        app.processEvents()
    assert _margins(win.Ui) == first, f"重复同步后几何漂移: {first} -> {_margins(win.Ui)}"

    for width, height in ((1920, 1170), (1030, 753)):
        _resize(win, app, width, height)
        lead, trail = _margins(win.Ui)
        assert lead == trail, f"{width} 宽下往返后两侧留白不等: 左={lead} 右={trail}"
