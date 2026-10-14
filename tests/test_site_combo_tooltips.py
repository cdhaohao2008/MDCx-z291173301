"""站点下拉框悬停提示回归（软件设置→网络→网站设置→当前网站 等三个站点下拉）。

用户反馈：
- 一开始：下拉列表里把鼠标放在某个选项上不显示提示（截图里偶发弹出的还是别的行的旧文本）。
- 后来：QToolTip 感觉显示不灵敏，大部分时间能显示，但有时鼠标移动了也不显示。
- 再后来：提示框高度忽高忽低、提示文字不居中。

提示内容按用户要求只保留「上次检测：…」（定位说明已在选项显示文本里，不重复）；
没检测过的站点不弹提示。

实现（`init._SiteComboTipFilter` + `init._SiteTipLabel`）：
- 提示窗自建（`Qt::ToolTip` 无边框窗 + 全局 QSS 同款配色），不再借道 `QToolTip`。
  全局提示窗是全进程共用的，它自己决定尺寸/位置/时序，别的控件一次 `hideText()` 就能让
  「以为提示还亮着」的记录与实际脱钩——行号没变、提示已经没了，同一行内再移动就不重弹，
  这正是「有时鼠标移动了也不显示」。现在亮没亮由提示窗自己说了算。
- 高度按行高取整：单行提示恒定同一高度，折行按行高递增（同一文本取历次最大值，宁高不裁），
  文字恒水平+垂直居中。
- 收起时机：移出列表 / 弹窗关闭 / 按下鼠标 / 滚轮滚动 / 落到无提示文本的行。

测试用真实的自建提示窗（`_site_tip_label()`）断言，不再替换成假 QToolTip —— 之前的假对象
让高度、对齐这类真实渲染行为完全没被覆盖。
"""

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QFont, QHelpEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QListView

import mdcx.controllers.main_window.init as init_mod
from mdcx.controllers.main_window.init import (
    Init_Ui,
    _install_site_combo_tips,
    _populate_site_combo,
    _SiteComboTipFilter,
)

_app: QApplication | None = None

# 四行样例：前三行有上次检测结果，第四行故意留空（模拟没检测过的站点 → 不弹提示）
_ROWS = (
    ("AVBase 有码：有码+素人", "上次检测：2026-10-09 20:51✅可连通·走代理"),
    ("AVSOX 无码：仅能无码", "上次检测：2026-10-09 20:53❌连不通·直连"),
    ("DMM 有码：仅能有码", ""),
    ("MissAV 综合：有码+无码", "上次检测：2026-10-09 20:55⚠️有需关注项·走代理"),
)


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture
def tip():
    """每个用例一个全新的提示窗：钉高与弹过次数不串味。"""
    _ensure_app()
    old = init_mod._SITE_TIP_LABEL
    if old is not None:
        old.hide_tip()
    init_mod._SITE_TIP_LABEL = None
    label = init_mod._site_tip_label()
    try:
        yield label
    finally:
        label.hide_tip()
        init_mod._SITE_TIP_LABEL = old


def _make_combo(*, opened: bool = True) -> QComboBox:
    _ensure_app()
    combo = QComboBox()
    combo.setView(QListView(combo))
    combo.resize(400, 30)
    for i, (text, tip_text) in enumerate(_ROWS):
        combo.addItem(text, f"v{i}")
        if tip_text:
            combo.setItemData(i, tip_text, Qt.ItemDataRole.ToolTipRole)
    combo.show()
    _ensure_app().processEvents()
    _install_site_combo_tips(combo)
    if opened:
        combo.showPopup()
        _ensure_app().processEvents()
    return combo


def _row_pos(combo: QComboBox, row: int, dx: int = 10) -> QPoint:
    view = combo.view()
    assert view is not None
    rect = view.visualRect(view.model().index(row, 0))
    return QPoint(rect.left() + dx, rect.center().y())


def _hover(combo: QComboBox, row: int, dx: int = 10) -> None:
    """模拟鼠标无按键移动到第 row 行（弹窗内）。"""
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


def _hover_closed(combo: QComboBox, dx: int = 10) -> None:
    """模拟鼠标无按键移动到闭合状态的框体上。"""
    pos = QPoint(dx, combo.height() // 2)
    QApplication.sendEvent(
        combo,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pos),
            QPointF(combo.mapToGlobal(pos)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    _ensure_app().processEvents()


def test_hover_shows_tip_of_row_under_cursor(tip):
    """悬停哪一行就弹哪一行的上次检测结果（用户要的就是这个）。"""
    combo = _make_combo()
    _hover(combo, 0)
    assert tip.isVisible() is True
    assert tip.text() == _ROWS[0][1]
    _hover(combo, 1)
    assert tip.text() == _ROWS[1][1]


def test_same_row_move_does_not_reshow(tip):
    """行内移动且提示还亮着时不重复弹：重弹会让提示闪一下并重置位置。"""
    combo = _make_combo()
    _hover(combo, 1, dx=10)
    count = tip.show_count
    _hover(combo, 1, dx=40)
    assert tip.show_count == count
    assert tip.isVisible() is True


def test_tip_reshown_after_hidden_while_row_unchanged(tip):
    """提示被收起后，同一行内再移动必须重弹。

    这是「有时鼠标移动了也不显示」的回归：旧实现只看「行号没变」就跳过重弹，一旦提示
    其实已经被 Qt 或别处收起，同一行怎么移动都不会再出现。
    """
    combo = _make_combo()
    _hover(combo, 1)
    assert tip.isVisible() is True
    tip.hide()  # 模拟提示被别处收起：行号记录没变，提示其实已经没了
    _ensure_app().processEvents()
    assert tip.isVisible() is False
    count = tip.show_count
    _hover(combo, 1, dx=40)  # 同一行内移动
    assert tip.isVisible() is True, "提示已收起时行内移动也必须重弹"
    assert tip.text() == _ROWS[1][1]
    assert tip.show_count == count + 1


def test_row_without_tip_text_hides_instead_of_keeping_stale(tip):
    """提示文本为空的行收起提示，不留着上一行的内容（截图里的旧文本就是这么来的）。"""
    combo = _make_combo()
    _hover(combo, 0)
    assert tip.isVisible() is True
    _hover(combo, 2)
    assert tip.isVisible() is False


def test_platform_tooltip_event_is_taken_over(tip):
    """平台侧 ToolTip 事件被接管（返回 True）：不与 Qt 默认 delegate 抢着弹两份。"""
    combo = _make_combo()
    viewport = combo.view().viewport()
    pos = _row_pos(combo, 1)
    tip_filter = _SiteComboTipFilter(combo)
    handled = tip_filter.eventFilter(viewport, QHelpEvent(QEvent.Type.ToolTip, pos, viewport.mapToGlobal(pos)))
    assert handled is True
    assert tip.text() == _ROWS[1][1]
    assert tip.isVisible() is True


def test_help_event_position_falls_back_to_pos(tip):
    """QHelpEvent 没有 position()（只有 pos()）：坐标取错会退化成「无提示」。"""
    from mdcx.controllers.main_window.init import _event_pos

    pos = QPoint(7, 9)
    help_event = QHelpEvent(QEvent.Type.ToolTip, pos, QPoint(70, 90))
    assert _event_pos(help_event) == pos


def test_hide_event_hides_tip_and_allows_reshow(tip):
    """弹窗关闭即收起；重新打开后再悬停同一行仍要能弹出来。"""
    combo = _make_combo()
    _hover(combo, 1)
    QApplication.sendEvent(combo.view().viewport(), QEvent(QEvent.Type.Hide))
    assert tip.isVisible() is False
    count = tip.show_count
    _hover(combo, 1)
    assert tip.isVisible() is True
    assert tip.show_count == count + 1


def test_wheel_hides_tip_because_row_under_cursor_moves(tip):
    """滚轮会挪动行号却不一定有 MouseMove 跟来，先收起，别让提示停在旧行上。"""
    combo = _make_combo()
    _hover(combo, 0)
    assert tip.isVisible() is True
    QApplication.sendEvent(combo.view().viewport(), QEvent(QEvent.Type.Wheel))
    assert tip.isVisible() is False
    _hover(combo, 1)
    assert tip.isVisible() is True
    assert tip.text() == _ROWS[1][1]


def test_mouse_press_hides_tip(tip):
    """按下鼠标即收起提示（要开始选择了就别再挡着）。"""
    combo = _make_combo()
    _hover(combo, 0)
    viewport = combo.view().viewport()
    pos = _row_pos(combo, 0)
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(pos),
            QPointF(viewport.mapToGlobal(pos)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    _ensure_app().processEvents()
    assert tip.isVisible() is False


def test_install_is_idempotent_and_enables_mouse_tracking():
    """重复安装不叠加过滤器；且必须开 mouseTracking，否则无按键移动收不到 MouseMove。"""
    combo = _make_combo()
    first = combo.view().viewport().eventFilter
    _install_site_combo_tips(combo)
    assert combo.view().viewport().hasMouseTracking() is True
    assert getattr(combo, "_site_tip_filter_installed", False) is True
    # 二次安装直接返回（标记为真即代表已装过），过滤行为仍正常
    assert callable(first)


def test_tip_height_pinned_and_text_centered(tip):
    """提示窗高度按首显钉死、提示文字恒居中（用户反馈 1/2/3 次显示高度不一致）。

    断言用 minimumHeight/maximumHeight 而非 height()：离屏平台提示窗不排版，height()
    不随上下限更新，拿它断言会假失败。
    """
    combo = _make_combo()
    _hover(combo, 0)
    first = tip.minimumHeight()
    assert first > 0, "首显就要钉住高度，否则忽高忽低的那一次仍会露出来"
    assert tip.maximumHeight() == first
    centered = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    assert tip.alignment() == centered, "提示文字要恒为居中，不能随排版漂到上边沿"

    _hover(combo, 1)
    assert tip.minimumHeight() == first, "后续显示应被钉回首显高度"
    assert tip.alignment() == centered

    _hover(combo, 3)  # 文本更长的另一行，高度与对齐同样不能变
    assert tip.minimumHeight() == first
    assert tip.alignment() == centered

    # 万一某次排版更高（字体没加载完走了 fallback，或字体被换大），钉高只涨不跌：
    # 宁可统一偏高也不把文字裁掉
    big = QFont(tip.font())
    big.setPointSize(big.pointSize() + 8)
    tip.setFont(big)
    _hover(combo, 0)
    assert tip.minimumHeight() > first, "排版更高时钉高要跟着涨"
    assert tip.maximumHeight() == tip.minimumHeight()
    assert tip.alignment() == centered


def test_single_line_tips_share_one_height_and_wrap_grows_by_line_height(tip):
    """单行提示恒定同一高度，折行按行高递增（用户要求：单行同一高度、折行按字体高度递增）。

    高度必须取整到行高的整数倍，否则会出现「两行半」这种零头高度，看着仍是不一致。
    """
    combo = _make_combo()
    heights = set()
    for row in (0, 1, 3):  # 文本长度不同，但都是单行
        _hover(combo, row)
        assert tip.isVisible() is True
        heights.add(tip.minimumHeight())
    line_h = tip._line_h
    assert heights == {line_h}, f"单行提示高度应恒为行高 {line_h}，实测 {heights}"

    long_text = "开启后所有请求都发给代理地址；上次检测：2026-10-09 20:51✅可连通·走代理；" * 6
    tip.show_at(long_text, QPoint(10, 10))
    assert tip.minimumHeight() >= 2 * line_h, "长文本折行后应至少两行高"
    assert tip.minimumHeight() % line_h == 0, "折行高度必须是行高的整数倍，不能留零头"

    tip.show_at(_ROWS[0][1], QPoint(10, 10))
    assert tip.minimumHeight() == line_h, "长文本不能把单行提示的高度带高"


def test_closed_combo_hover_shows_selected_item_tip(tip):
    """闭合态悬停框体即弹当前选中项的上次检测结果，不必等 Qt 那 1s 的原生提示。"""
    combo = _make_combo(opened=False)
    _hover_closed(combo)
    assert tip.isVisible() is True
    assert tip.text() == _ROWS[0][1]
    count = tip.show_count
    _hover_closed(combo, dx=60)  # 同一项内移动不重弹
    assert tip.show_count == count


def test_closed_combo_hover_prepends_own_tooltip_text(tip):
    """框体自带说明文字（不分流那个下拉）时拼在前面一起显示，不再只靠原生提示框。"""
    combo = _make_combo(opened=False)
    combo.setToolTip("开启后所有请求都发给代理地址")
    _hover_closed(combo)
    assert tip.text() == f"开启后所有请求都发给代理地址\n{_ROWS[0][1]}"


def test_closed_combo_ignores_while_popup_open(tip):
    """弹窗开着时归弹窗内的过滤器管，闭合那侧不抢着弹。"""
    combo = _make_combo(opened=True)
    _hover(combo, 3)
    assert tip.text() == _ROWS[3][1]
    _hover_closed(combo)
    assert tip.text() == _ROWS[3][1], "弹窗开着时闭合侧不该改提示内容"
    assert tip.isVisible() is True


def test_closed_combo_press_hides_tip(tip):
    """按下鼠标即收起（准备打开弹窗了）。"""
    combo = _make_combo(opened=False)
    _hover_closed(combo)
    assert tip.isVisible() is True
    pos = QPoint(10, combo.height() // 2)
    QApplication.sendEvent(
        combo,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(pos),
            QPointF(combo.mapToGlobal(pos)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    _ensure_app().processEvents()
    assert tip.isVisible() is False


def test_tip_window_does_not_disturb_combo_popup(tip):
    """自建提示窗不能把下拉弹窗顶掉，也不能吃掉鼠标事件。"""
    combo = _make_combo()
    assert combo.view().isVisible() is True
    _hover(combo, 0)
    assert tip.isVisible() is True
    assert combo.view().isVisible() is True, "提示窗不能抢走/关闭下拉弹窗"
    assert tip.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
    assert tip.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    assert tip.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_tip_pos_clamped_inside_screen(tip):
    """提示窗位置必须夹在屏幕可用区内：弹到屏外等于「没显示」。"""
    _ensure_app()
    screen = QApplication.primaryScreen()
    assert screen is not None
    geo = screen.availableGeometry()

    pos = init_mod._clamp_tip_pos(QPoint(geo.right() - 2, geo.bottom() - 2), 300, 40)
    assert pos.x() >= geo.left(), "不能被顶出可用区左边"
    assert pos.y() >= geo.top(), "不能被顶出可用区上边"
    assert pos.x() + 300 <= geo.right() + 1, "右边越界"
    assert pos.y() + 40 <= geo.bottom() + 1, "下方放不下要翻到上方"

    pos = init_mod._clamp_tip_pos(QPoint(geo.left(), geo.top()), 300, 40)
    assert pos.x() >= geo.left() and pos.y() >= geo.top()


def test_tip_sits_five_px_below_anchor(tip):
    """提示窗上边界紧贴选项下沿、间隔 5px（用户要求；原 16px 看着离选项太远）。

    下方放不下翻到上方时，间隔同样取 5px，两个方向不能一边近一边远。
    """
    _ensure_app()
    screen = QApplication.primaryScreen()
    assert screen is not None
    geo = screen.availableGeometry()
    gap = init_mod._TIP_GAP_PX
    assert gap == 5, "间隔按用户要求固定 5px"

    anchor = QPoint(geo.left() + 100, geo.top() + 100)
    pos = init_mod._clamp_tip_pos(anchor, 300, 40)
    assert pos.y() - anchor.y() == gap, "弹在下方时上边界应距 anchor 下沿 5px"

    anchor_low = QPoint(geo.left() + 100, geo.bottom() - 10)
    pos = init_mod._clamp_tip_pos(anchor_low, 300, 40)
    assert anchor_low.y() - (pos.y() + 40) == gap, "翻到上方时下边界应距 anchor 上沿 5px"


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
        tip_text = str(combo.itemData(i, Qt.ItemDataRole.ToolTipRole) or "")
        assert tip_text == "" or tip_text.startswith("上次检测："), f"第 {i} 行提示混入了别的内容：{tip_text!r}"
        for label in ("有码：", "无码：", "综合：", "麻豆：", "MyWife："):
            assert label not in tip_text, f"第 {i} 行提示里不该再出现定位说明「{label}」：{tip_text!r}"
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
