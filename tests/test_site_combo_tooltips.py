"""站点下拉框悬停提示回归（软件设置→网络→网站设置→当前网站 等三个站点下拉）。

用户反馈：下拉列表里把鼠标放在某个选项上，不显示提示（截图里偶发弹出的还是别的行的旧文本）。
提示内容按用户要求只保留「上次检测：…」（定位说明已在选项显示文本里，不重复）；
没检测过的站点不弹提示。

原实现把提示完全交给 Qt 默认链路（平台侧合成 QEvent::ToolTip → delegate.helpEvent →
QToolTip），弹窗是 Qt::Popup 顶层窗，这条链路在项目里不可靠。现改为
`init._SiteComboTipFilter` 自管：viewport 的 MouseMove 直接按光标所在行取
ToolTipRole 自己弹，平台侧的 ToolTip 事件一并接管，保证提示与光标所指行一致、
且不残留上一行的内容。

测试用假的 QToolTip（替换 init 模块里的引用）记录 showText/hideText 调用，
断言不依赖具体平台是否真的画出提示窗。
"""

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QHelpEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QListView

import mdcx.controllers.main_window.init as init_mod
from mdcx.controllers.main_window.init import (
    Init_Ui,
    _install_site_combo_tips,
    _populate_site_combo,
    _SiteComboTipFilter,
)

_app: QApplication | None = None

# 三行样例：前两行有上次检测结果，第三行故意留空（模拟没检测过的站点 → 不弹提示）
_ROWS = (
    ("AVBase 有码：有码+素人", "上次检测：2026-10-09 20:51✅可连通·走代理"),
    ("AVSOX 无码：仅能无码", "上次检测：2026-10-09 20:53❌连不通·直连"),
    ("DMM 有码：仅能有码", ""),
)


class _FakeToolTip:
    """记录 QToolTip 调用的替身（offscreen 平台无真实提示窗，不能靠 QToolTip.text() 断言）。"""

    def __init__(self) -> None:
        self.shown: list[str] = []
        self.hide_count = 0

    def showText(self, pos, text, widget=None, rect=None, msecShowTime=-1, msecHideTime=-1):  # noqa: N802
        self.shown.append(text)

    def hideText(self) -> None:  # noqa: N802
        self.hide_count += 1


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _make_combo() -> QComboBox:
    _ensure_app()
    combo = QComboBox()
    combo.setView(QListView(combo))
    combo.resize(400, 30)
    for i, (text, tip) in enumerate(_ROWS):
        combo.addItem(text, f"v{i}")
        if tip:
            combo.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
    combo.show()
    _ensure_app().processEvents()
    _install_site_combo_tips(combo)
    combo.showPopup()
    _ensure_app().processEvents()
    return combo


def _row_pos(combo: QComboBox, row: int, dx: int = 10) -> QPoint:
    view = combo.view()
    assert view is not None
    rect = view.visualRect(view.model().index(row, 0))
    return QPoint(rect.left() + dx, rect.center().y())


def _hover(combo: QComboBox, row: int, dx: int = 10) -> None:
    """模拟鼠标无按键移动到第 row 行。"""
    viewport = combo.view().viewport()
    pos = _row_pos(combo, row, dx)
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pos),
            QPointF(viewport.mapToGlobal(pos)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    _ensure_app().processEvents()


@pytest.fixture
def fake_tip(monkeypatch) -> _FakeToolTip:
    tip = _FakeToolTip()
    monkeypatch.setattr(init_mod, "QToolTip", tip)
    return tip


def test_hover_shows_tooltip_of_row_under_cursor(fake_tip):
    """悬停哪一行就弹哪一行的上次检测结果（用户要的就是这个）。"""
    combo = _make_combo()
    _hover(combo, 0)
    assert fake_tip.shown[-1] == _ROWS[0][1]
    _hover(combo, 1)
    assert fake_tip.shown[-1] == _ROWS[1][1]


def test_same_row_move_does_not_reshow(fake_tip):
    """行内移动不重复弹：重弹会让提示闪一下并重置位置。"""
    combo = _make_combo()
    _hover(combo, 1, dx=10)
    count = len(fake_tip.shown)
    _hover(combo, 1, dx=40)
    assert len(fake_tip.shown) == count


def test_row_without_tip_text_hides_instead_of_keeping_stale(fake_tip):
    """提示文本为空的行收起提示，不留着上一行的内容（截图里的旧文本就是这么来的）。"""
    combo = _make_combo()
    _hover(combo, 0)
    fake_tip.shown.clear()
    hide_before = fake_tip.hide_count
    _hover(combo, 2)
    assert fake_tip.shown == []
    assert fake_tip.hide_count == hide_before + 1


def test_platform_tooltip_event_is_taken_over(fake_tip):
    """平台侧 ToolTip 事件被接管（返回 True）：不与 Qt 默认 delegate 抢着弹两份。"""
    combo = _make_combo()
    viewport = combo.view().viewport()
    pos = _row_pos(combo, 1)
    tip_filter = _SiteComboTipFilter(combo)
    handled = tip_filter.eventFilter(viewport, QHelpEvent(QEvent.Type.ToolTip, pos, viewport.mapToGlobal(pos)))
    assert handled is True
    assert fake_tip.shown[-1] == _ROWS[1][1]


def test_help_event_position_falls_back_to_pos(fake_tip):
    """QHelpEvent 没有 position()（只有 pos()）：坐标取错会退化成「无提示」。"""
    from mdcx.controllers.main_window.init import _event_pos

    pos = QPoint(7, 9)
    help_event = QHelpEvent(QEvent.Type.ToolTip, pos, QPoint(70, 90))
    assert _event_pos(help_event) == pos


def test_hide_event_hides_tip_and_allows_reshow(fake_tip):
    """弹窗关闭即收起；重新打开后再悬停同一行仍要能弹出来。"""
    combo = _make_combo()
    _hover(combo, 1)
    QApplication.sendEvent(combo.view().viewport(), QEvent(QEvent.Type.Hide))
    assert fake_tip.hide_count >= 1
    shown_before = len(fake_tip.shown)
    _hover(combo, 1)
    assert len(fake_tip.shown) == shown_before + 1


def test_install_is_idempotent_and_enables_mouse_tracking():
    """重复安装不叠加过滤器；且必须开 mouseTracking，否则无按键移动收不到 MouseMove。"""
    combo = _make_combo()
    first = combo.view().viewport().eventFilter
    _install_site_combo_tips(combo)
    assert combo.view().viewport().hasMouseTracking() is True
    assert getattr(combo, "_site_tip_filter_installed", False) is True
    # 二次安装直接返回（标记为真即代表已装过），过滤行为仍正常
    _hover(combo, 0)
    assert callable(first)


def test_populated_site_combo_tooltip_only_carries_check_result(monkeypatch):
    """tooltip 只留「上次检测」一行：定位说明按用户要求删除（选项显示文本里本来就有）。"""
    _ensure_app()
    monkeypatch.setattr(
        init_mod,
        "_CHECK_CACHE",
        {"AVBase": {"status": "ok", "route": "proxy", "checked_at": "2026-10-09T20:51:00"}},
    )
    combo = QComboBox()
    combo.setView(QListView(combo))
    _populate_site_combo(combo, ["AVBase", "AVSOX", "DMM"])

    assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole) == "上次检测：2026-10-09 20:51✅可连通·走代理"
    # 没检测过的站点不弹提示（tooltip 为空）
    assert combo.itemData(1, Qt.ItemDataRole.ToolTipRole) == ""
    for i in range(combo.count()):
        tip = str(combo.itemData(i, Qt.ItemDataRole.ToolTipRole) or "")
        assert tip == "" or tip.startswith("上次检测："), f"第 {i} 行提示混入了别的内容：{tip!r}"
        for label in ("有码：", "无码：", "综合：", "麻豆：", "MyWife："):
            assert label not in tip, f"第 {i} 行提示里不该再出现定位说明「{label}」：{tip!r}"
    # 定位说明仍在显示文本里，删的只是提示里的重复
    assert "有码：有码+素人" in combo.itemText(0)


def test_init_ui_installs_tips_on_all_three_site_combos():
    """三个站点下拉都装上悬停提示（指定网站框不装网址列，但同样需要提示）。"""
    source = inspect.getsource(Init_Ui)
    call_at = source.index("_install_site_combo_tips(")
    loop_at = source.rindex("for _site_combo in (", 0, call_at)
    block = source[loop_at:call_at]
    for combo_name in ("comboBox_website_all", "comboBox_custom_website", "comboBox_no_proxy_sites"):
        assert combo_name in block, f"{combo_name} 未装悬停提示"
