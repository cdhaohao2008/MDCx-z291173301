import re
import traceback
import webbrowser
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QScreen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QLabel,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QTreeWidgetItem,
    QWidget,
)

from mdcx.config.extend import get_movie_path_setting
from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.consts import GITHUB_RELEASES_URL, IS_WINDOWS
from mdcx.crawlers import get_registered_crawler_site_values
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils.qt_text import left_anchor_text_edits

from .site_priority_dialog import setup_site_priority_ui
from .style import build_menu_style, build_tree_widget_style

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


_SITE_STATUS_DOT_PX = 8  # 状态圆点边长（逻辑像素）


def _effective_dpr(widget: QWidget | None = None) -> float:
    """图标绘制用的有效缩放比。

    优先取图标所在控件的 `devicePixelRatioF()`：多屏时各屏 dpr 不同，按控件取才准；
    没有控件时退到主屏。Qt6 下 `QScreen.devicePixelRatio()` 已含 main.py 写入的
    QT_SCALE_FACTOR（实测 1/1.25/2 三档与控件一致），取不到时按 1.0 退化为不缩放。
    """
    dpr = 0.0
    if widget is not None:
        try:
            dpr = widget.devicePixelRatioF()
        except Exception:
            dpr = 0.0
    if dpr <= 0:
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 0.0
    return dpr if dpr > 0 else 1.0


def _site_status_icon(level: str, widget: QWidget | None = None) -> QIcon:
    """站点检测状态圆点图标：ok 绿 / warn 黄 / fail 红；未知或 skip 返回空图标。

    画布按 dpr 放大到设备像素并挂上 `setDevicePixelRatio`，绘制仍在逻辑坐标系里做，
    于是圆点物理观感恒为 `_SITE_STATUS_DOT_PX` 逻辑像素（高 DPI 下不再被二次拉伸发虚）。
    `QIcon` 只缩不放（实测 `paint()` 进任意大小的 rect 都按图标原始尺寸绘制），
    所以画布尺寸就是下拉里圆点的实际大小。
    """
    color = {"ok": "#43a047", "warn": "#f9a825", "fail": "#e53935"}.get(level)
    if not color:
        return QIcon()
    dpr = _effective_dpr(widget)
    pixmap = QPixmap(QSize(max(1, round(_SITE_STATUS_DOT_PX * dpr)), max(1, round(_SITE_STATUS_DOT_PX * dpr))))
    if dpr != 1.0:
        pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, _SITE_STATUS_DOT_PX - 2, _SITE_STATUS_DOT_PX - 2)
    painter.end()
    return QIcon(pixmap)


def _site_combo_caption(value: str) -> str:
    """下拉选项显示文本里那段能力文案：与「编辑网站」弹窗「可用网站」候选区的悬停提示同源。

    三个站点下拉（刮削网站页「指定网站」、网络页「当前网站」「不走代理的网站」）摆的是
    与那个弹窗同一批站，同一句话必须从同一处算——例如 7mmtv 两处都是
    「综合：有码/无码/欧美/传媒」。站点值不合法时返回空串，不让一个脏值把整个
    下拉炸掉。
    """
    from mdcx.config.enums import Website
    from mdcx.controllers.main_window.site_priority_dialog import _site_capability_caption

    try:
        return _site_capability_caption(Website(value))
    except ValueError:
        return ""


def _site_check_entry(value: str, fallback_key: str = "") -> dict | None:
    """按检测键取缓存条目，取不到时回退到聚合键（official 子站行 → Official 本行）。

    official 无码五站各占一行、各自探测自己那家官网，逐站结果以 `Official·厂牌` 为键存进缓存；
    检测早于该存储的旧缓存、或用户自定义过 Official URL（只跑一条检测项）时没有子键，
    此时回退到 Official 的聚合值——与拆分子行之前的表现一致，不会退回成一片空白圆点。
    """
    entry = _load_check_cache().get(value)
    if entry is None and fallback_key:
        entry = _load_check_cache().get(fallback_key)
    return entry


def _site_combo_item_tooltip(value: str, fallback_key: str = "") -> str:
    """下拉项 tooltip：只留上次检测结果。

    能力文案（有码：有码 / 无码：无码 / 综合：…）已直接拼进选项显示文本，
    按用户要求不再在提示里重复，提示只剩「上次检测：…」；没检测过的站点返回空串、悬停不弹。
    """
    entry = _site_check_entry(value, fallback_key)
    if not entry:
        return ""
    label = {"ok": "✅可连通", "warn": "⚠️有需关注项", "fail": "❌连不通", "skip": "⏭上次未测"}.get(
        str(entry.get("status") or ""), ""
    )
    when = str(entry.get("checked_at") or "")[:16].replace("T", " ")
    if not (label and when):
        return ""
    route = {"proxy": "走代理", "direct": "直连"}.get(str(entry.get("route") or ""), "")
    return f"上次检测：{when}{label}" + (f"·{route}" if route else "")


_CHECK_CACHE: dict | None = None


def _load_check_cache() -> dict[str, dict]:
    """懒加载并缓存检测结果；refresh_network_check_badges() 调用后重新读取。"""
    global _CHECK_CACHE
    if _CHECK_CACHE is None:
        from mdcx.core.network_check import load_site_check_cache

        _CHECK_CACHE = load_site_check_cache()
    return _CHECK_CACHE


def invalidate_check_cache() -> None:
    global _CHECK_CACHE
    _CHECK_CACHE = None


def _populate_site_combo(combo: QComboBox, site_values: list[str], *, with_caption: bool = True) -> None:
    """填充站点下拉框：区域标签与能力概览直接拼入显示文本，检测状态入图标，tooltip 只留上次检测。

    显示文本里的能力概览取自 `_site_combo_caption()`——即「编辑网站」弹窗「可用网站」候选区
    站点项的悬停提示那一行，同一批站在两处说同一句话；而 tooltip 按用户要求只保留
    「上次检测：…」，不再重复能力文案。

    with_caption=False 时只显示「站点名（区域标签）」，不拼能力概览（「综合：有码/无码/…」
    那段）。仅「使用代理」下拉框用这个姿势（用户 2026-10-19 提出）：那里选的是要走代理的
    域名，能力概览（有无码/欧美/综合）与之无关，纯属噪声。区域标签、状态图标、tooltip、
    UserRole 存的纯站点值、右列网址一律照旧，另两个下拉框行为完全不变。
    """
    from mdcx.manual import ManualConfig

    for value in site_values:
        tag = ManualConfig.SITE_REGION_TAGS.get(value, "")
        cache_entry = _load_check_cache().get(value)
        icon = _site_status_icon(cache_entry.get("status", ""), combo) if cache_entry else QIcon()
        # UserRole 存纯站点值：显示文本=站点名+区域标签+能力概览（与「可用网站」同源），
        # 消费方统一经 currentData()/itemData(UserRole) 取纯值
        name = f"{value}（{tag}）" if tag else value
        if with_caption and (caption := _site_combo_caption(value)):
            name = f"{name} {caption}"
        combo.addItem(icon, name, value)
        url = _resolve_site_url(value)
        combo.setItemData(combo.count() - 1, url, _SITE_URL_ROLE)  # 当前网址：右侧网址列显示+点击跳转
        combo.setItemData(combo.count() - 1, _site_combo_item_tooltip(value), Qt.ItemDataRole.ToolTipRole)
    view = combo.view()
    if view is not None:
        view.setTextElideMode(Qt.TextElideMode.ElideRight)


def refresh_network_check_badges(self: MyMAinWindow) -> None:
    """检测完成后刷新三个站点下拉框的状态图标与 tooltip（不重排文本，保留当前选中项）。"""
    invalidate_check_cache()
    for combo in (
        self.Ui.comboBox_website_all,
        self.Ui.comboBox_custom_website,
        self.Ui.comboBox_no_proxy_sites,
    ):
        for i in range(combo.count()):
            value = (
                combo.itemData(i, Qt.ItemDataRole.UserRole) or combo.itemText(i).split(" ")[0].split("（")[0].strip()
            )
            if not value:
                continue
            # official 子站行带自己的检测键（Official·厂牌）：各显各的状态，取不到才回退 Official 聚合
            check_key = str(combo.itemData(i, _SITE_CHECK_KEY_ROLE) or "")
            fallback_key = value if check_key else ""
            entry = _site_check_entry(check_key or value, fallback_key)
            combo.setItemIcon(i, _site_status_icon(entry["status"], combo) if entry else QIcon())
            # 显式网址行（official 子站）：保留手工地址，只刷新图标与 tooltip
            url = combo.itemData(i, _SITE_URL_EXPLICIT_ROLE) or _resolve_site_url(
                value
            )  # 自定义网址保存后此处同步最新值
            combo.setItemData(i, url, _SITE_URL_ROLE)
            combo.setItemData(
                i, _site_combo_item_tooltip(check_key or value, fallback_key), Qt.ItemDataRole.ToolTipRole
            )
        _fit_site_url_popup(combo)


_SITE_URL_ROLE = Qt.ItemDataRole.UserRole + 2  # 各站点当前网址：下拉右侧网址列显示，点击跳转浏览器
_SITE_URL_EXPLICIT_ROLE = Qt.ItemDataRole.UserRole + 3  # 手工指定的行网址：刷新徽章时不被重算覆盖
_SITE_CHECK_KEY_ROLE = Qt.ItemDataRole.UserRole + 4  # 该行检测键：official 子站行为 Official·厂牌，其余行为空
_SITE_URL_GAP = 14
_SITE_URL_LINK_COLOR = "#1a73e8"
_SITE_URL_ICON_WIDTH = 24  # 状态圆点图标 + 间距预留
_SITE_NAME_MAX_W = 340  # 站点名列最大文本宽，超出省略号（防下拉过宽）
_SITE_URL_MAX_W = 240  # 网址列最大文本宽，超出省略号


# base_url_() 按设计返回空的站点，在下拉里展示这个兜底地址（official 是多站
# 路由、没有单一官网，保持空白）。
_SITE_URL_FALLBACK = {
    "DMM": "https://www.dmm.co.jp/",  # 主搜索站（另有 dmm.com 写真站）
}


def _resolve_site_url(value: str) -> str:
    """取站点当前网址：经 crawler.base_url_()（已含用户自定义 URL），只读配置不发请求。"""
    try:
        from mdcx.config.models import Website
        from mdcx.crawlers import get_crawler

        crawler_cls = get_crawler(Website(value))
        if crawler_cls is None:
            return ""
        url = str(crawler_cls.base_url_() or "").strip()
    except Exception:
        return ""
    if not url:
        url = _SITE_URL_FALLBACK.get(value, "")
    if url.startswith(("http://", "https://")):
        return url.rstrip("/") + "/"
    return url


class _SiteUrlItemDelegate(QStyledItemDelegate):
    """站点下拉双列绘制：左侧站点名，右侧当前网址；网址列各行同一起点（左对齐）。"""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def _column_metrics(self) -> tuple[int, int]:
        """返回 (网址列起点 x，相对行左 / 网址列最大文本宽）。"""
        view = self._combo.view()
        fm = view.fontMetrics() if view is not None else self._combo.fontMetrics()
        model = self._combo.model()
        name_w = 0
        url_w = 0
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            name_w = max(name_w, fm.horizontalAdvance(str(index.data(Qt.ItemDataRole.DisplayRole) or "")))
            url = str(index.data(_SITE_URL_ROLE) or "")
            if url:
                url_w = max(url_w, fm.horizontalAdvance(url))
        name_w = min(name_w, _SITE_NAME_MAX_W)
        url_w = min(url_w, _SITE_URL_MAX_W)
        return 4 + _SITE_URL_ICON_WIDTH + name_w + _SITE_URL_GAP, url_w

    def total_width(self) -> int:
        url_x, url_w = self._column_metrics()
        return url_x + url_w + 8

    def url_rect(self, index) -> QRect | None:
        """某行的网址点击区（viewport 坐标）；无网址返回 None。"""
        view = self._combo.view()
        if view is None or not str(index.data(_SITE_URL_ROLE) or ""):
            return None
        row_rect = view.visualRect(index)
        url_x, _ = self._column_metrics()
        x = row_rect.left() + url_x
        return QRect(x, row_rect.top(), max(0, row_rect.right() - x), row_rect.height())

    def paint(self, painter, option, index) -> None:
        view = self._combo.view()
        url = str(index.data(_SITE_URL_ROLE) or "")
        if view is None or not url:
            super().paint(painter, option, index)
            return
        url_x, _ = self._column_metrics()
        if option.rect.width() < url_x + 60:
            # 弹窗与框体同宽时无网址列空间：退化为单列绘制（Qt 负责省略号）；
            # 网址点击区随之失效（url_rect 宽为 0），点击即正常选中
            super().paint(painter, option, index)
            return
        narrowed = QStyleOptionViewItem(option)
        narrowed.rect.setWidth(max(0, url_x - option.rect.left()))
        super().paint(painter, narrowed, index)
        rect = self.url_rect(index)
        if rect is None or rect.width() <= 0:
            return
        painter.save()
        try:
            if option.state & QStyle.StateFlag.State_Selected:
                # 左半 super().paint 只铺了缩窄区选中背景，网址区不补就是白字画白底 → 网址“消失”
                painter.fillRect(rect, option.palette.highlight())
                painter.setPen(option.palette.highlightedText().color())
            else:
                painter.setPen(QColor(_SITE_URL_LINK_COLOR))
            text = view.fontMetrics().elidedText(url, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        finally:
            painter.restore()

    def sizeHint(self, option, index):
        # 弹窗与框体同宽：不再按网址列总宽撑开，Qt 按框宽省略号显示
        return super().sizeHint(option, index)


class _SiteUrlClickFilter(QObject):
    """下拉 viewport 事件：左键点中网址区 → 浏览器打开且不改选中；右键点网址区 → 吞掉事件保持弹窗与网址显示；悬停网址区 → 手形光标。"""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def _url_index_at(self, pos):
        view = self._combo.view()
        if view is None:
            return None
        index = view.indexAt(pos)
        if not index.isValid():
            return None
        delegate = self._combo.itemDelegate()
        if not isinstance(delegate, _SiteUrlItemDelegate):
            return None
        rect = delegate.url_rect(index)
        if rect is not None and rect.contains(pos):
            return index
        return None

    def eventFilter(self, obj, event) -> bool:
        try:
            if event.type() == QEvent.Type.MouseButtonPress:
                index = self._url_index_at(event.position().toPoint())
                if index is not None:
                    # 仅左键点击网址才跳转浏览器；右键/中键吞掉事件、不关弹窗，网址依然显示
                    if event.button() == Qt.MouseButton.LeftButton:
                        webbrowser.open(str(index.data(_SITE_URL_ROLE)))
                        self._combo.hidePopup()
                    return True
            elif event.type() == QEvent.Type.MouseMove and not event.buttons():
                view = self._combo.view()
                if view is not None:
                    over = self._url_index_at(event.position().toPoint()) is not None
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        except Exception:
            pass
        return super().eventFilter(obj, event)


def _event_pos(event) -> QPoint:
    """取事件的控件内坐标：QMouseEvent 等给的是 QPointF（position()），QHelpEvent 只给 QPoint（pos()）。"""
    point = (getattr(event, "position", None) or getattr(event, "pos", None))()
    to_point = getattr(point, "toPoint", None)  # QPointF 才有，QPoint 直接就是坐标
    return to_point() if callable(to_point) else point


_SITE_TIP_QSS = (
    # 上下内边距 9px：原 4px 时单行提示只有 36px 高（用户机器实测），字贴着上下边沿、看着
    # 又扁又窄；用户要求「再加高 10px 到 46px」，即上下各 +5px——写成内边距而不是给高度
    # 加常数，折行时每一行也跟着一起长高，仍是行高的整数倍。
    "QWidget#siteTip{border:1px solid #D8DEE9;border-radius:8px;background:#FFFFFF;color:#111827;padding:9px 10px;}"
)
_UNLIMITED_SIZE = 1 << 30  # 放开 setFixedXxx 用；PyQt6 没有导出 QWIDGETSIZE_MAX
_TIP_GAP_PX = 5  # 提示窗与 anchor（选项/框体下沿）之间的间隔：原 16px 太远，贴着选项下沿 5px


class _SiteTipLabel(QLabel):
    """站点下拉专用的悬停提示窗（三个下拉共用同一个，同一时刻只显示一份）。

    不再借道 `QToolTip`：那个提示窗（QTipLabel）是全进程共用的，它每次显示都自行重排
    版、位置也由 Qt 决定、还要靠平台侧约 1s 后合成的 ToolTip 事件驱动；而别处一次
    `QToolTip.hideText()`（或 Qt 自己收起它）就会让我们「以为提示还亮着」的记录与实际
    脱钩——记录里的行号没变、提示其实已经没了，同一行内再移动就不重弹，这就是用户
    反馈的「有时鼠标移动了也不显示」。自己建窗自己管：亮没亮、高度、位置、对齐都由此
    决定，不与全局提示窗互相干扰，也不会掀掉应用中其它控件的提示。

    高度按行高取整：字体刚加载完/没加载完会排出不同的行高，同一段「上次检测：…」的提
    示框就忽高忽低（用户反馈 1/2/3 次显示高度不一致）。故先量一次单行自然高度作为行高
    `line_h`（含 QSS 内边距与边框），再把所有提示的高度取整成 `line_h` 的整数倍——**单行恒
    定、折行按行高递增**，既不会忽高忽低，也不会出现两行半那种零头高度；同一段文本仍取历
    次最大值，宁可统一偏高也不把文字裁掉。文字对齐钉成水平+垂直居中，提示窗高度固定后不会
    随排版漂到上边沿。长文本（框体自带的说明文字）在 `MAX_WIDTH` 处折行，不会超出屏幕被裁掉。
    """

    # 折行宽度上限（逻辑像素）。取 560 是量出来的：字号大到行高 ~36px（用户机器上的样子）时，
    # 「上次检测：2026-10-09 20:51✅可连通·走代理」这句本身要 422~460px，420 会把它折成两行，
    # 于是最常见的单行提示反而变成两行高；560 能让这类提示在 14~16pt 下都保持单行。
    MAX_WIDTH = 560

    def __init__(self) -> None:
        super().__init__(None)
        self._line_h: int = 0  # 单行自然高度（含 QSS 内边距/边框）；所有提示高度都是它的整数倍
        self._pinned: dict[str, int] = {}  # 文本 → 钉住的高度（保证同一段文字每次一样高）
        self.show_count = 0  # 回归测试用：实际弹过几次
        self.setObjectName("siteTip")
        self.setStyleSheet(_SITE_TIP_QSS)  # 与全局 QSS 里的 QToolTip 同一套配色/圆角
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.setWordWrap(True)
        self.setMargin(0)

    def is_showing(self, text: str) -> bool:
        """提示窗此刻是否真的亮着，且亮的是这段文本。"""
        return self.isVisible() and self.text() == text

    def show_at(self, text: str, anchor: QPoint) -> None:
        """在 anchor（全局坐标，通常取该行下沿）弹出 text。"""
        self.setText(text)
        # 先量单行自然尺寸（含 QSS 内边距与边框）：行高由此确定，宽度超上限则折行，否则一行
        # 拉到屏幕外被裁掉
        self.setWordWrap(False)
        self._release_size()
        self.adjustSize()
        self._line_h = max(self._line_h, self.height(), 1)  # 行高只涨不跌（字体加载完可能更高）
        width = min(self.width(), self.MAX_WIDTH)
        self.setWordWrap(True)
        self.setFixedWidth(width)
        natural = max(self.heightForWidth(width), self.sizeHint().height())
        # 向上取整到行高的整数倍：单行恒定，折行按行高递增，不留「两行半」的零头高度
        lines = max(1, -(-natural // self._line_h))
        pinned = max(self._pinned.get(text, 0), lines * self._line_h)  # 同文本取历次最大，宁高不裁
        self._pinned[text] = pinned
        self.setFixedHeight(pinned)  # 钉高后 resize 被上下限夹住，视觉高度恒定
        self.move(_clamp_tip_pos(anchor, width, pinned))
        self.show()
        self.raise_()
        self.show_count += 1

    def _release_size(self) -> None:
        """放开 `setFixedXxx` 留下的上下限（PyQt6 未导出 QWIDGETSIZE_MAX，用足够大的值代替）。"""
        self.setMinimumSize(0, 0)
        self.setMaximumSize(_UNLIMITED_SIZE, _UNLIMITED_SIZE)

    def hide_tip(self) -> None:
        if self.isVisible():
            self.hide()


def _clamp_tip_pos(anchor: QPoint, width: int, height: int) -> QPoint:
    """提示窗贴 anchor 下沿弹出（间隔 `_TIP_GAP_PX`），并夹在所在屏幕可用区内（夹到屏外就等于没显示）。"""
    x = anchor.x()
    y = anchor.y() + _TIP_GAP_PX
    screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
    geo = screen.availableGeometry() if screen is not None else QRect()
    if geo.isValid():
        if x + width > geo.right():
            x = geo.right() - width + 1
        if y + height > geo.bottom():
            y = anchor.y() - height - _TIP_GAP_PX  # 下方放不下就翻到上方（间隔同样取 _TIP_GAP_PX）
        x = max(geo.left(), x)
        y = max(geo.top(), y)
    return QPoint(x, y)


_SITE_TIP_LABEL: _SiteTipLabel | None = None


def _site_tip_label() -> _SiteTipLabel:
    """站点提示窗单例（懒建；三个站点下拉共用，避免同时弹出两份）。"""
    global _SITE_TIP_LABEL
    if _SITE_TIP_LABEL is None:
        _SITE_TIP_LABEL = _SiteTipLabel()
    return _SITE_TIP_LABEL


class _SiteComboTipFilter(QObject):
    """站点下拉悬停提示：弹窗里按光标所在行显示，闭合时显示当前选中项的结果。

    提示窗是本模块自建的 `_SiteTipLabel`（见其注释：不再借道全局 QToolTip 的理由）。
    MouseMove 直接按 `view.indexAt()` 取光标所在行自己弹、自己收：

    - 同一行内移动且提示确实还亮着 → 不重弹（重弹会让提示闪一下并重置位置）；
    - 提示已经被收起（哪怕行号没变）→ 照弹，这正是「有时鼠标移动了也不显示」的修法；
    - 无提示文本、移出列表、弹窗关闭、按下鼠标、滚轮滚动（行号会挪但不一定有 MouseMove
      跟来）→ 收起；
    - 平台侧 ToolTip 事件一并接管，避免同一处出现第二份/过期提示。

    同一个过滤器也装在框体上（闭合态）：闭合时没有弹窗可接管，Qt 要等约 1s 才合成
    ToolTip 事件才弹原生提示框，那两个压根没设提示文字的下拉就是「鼠标移上去什么都不出
    现」（用户反馈的「显示不灵敏」）。这里 MouseMove 即弹当前项的上次检测结果；框体自带
    提示文字（不分流那个下拉的说明）就拼在前面一并显示。
    """

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo
        self._shown_row: int = -1  # 已显示提示所在行（-1 = 无提示）
        self._in_filter: bool = False  # 重入守卫，见 eventFilter

    def _index_at(self, pos):
        """光标所在行的 index；空白处/无 view 返回 None。"""
        view = self._combo.view()
        if view is None:
            return None
        index = view.indexAt(pos)
        return index if index.isValid() else None

    def _hide_tip(self) -> None:
        self._shown_row = -1
        self._combo._site_tip_in_popup = False  # type: ignore[attr-defined]
        _site_tip_label().hide_tip()

    def _closed_tip_text(self) -> str:
        """闭合态提示文本：框体自带说明（若有）+ 当前选中项的上次检测结果。"""
        parts = []
        own = str(self._combo.toolTip() or "").strip()
        if own:
            parts.append(own)
        picked = str(self._combo.itemData(self._combo.currentIndex(), Qt.ItemDataRole.ToolTipRole) or "").strip()
        if picked:
            parts.append(picked)
        return "\n".join(parts)

    def _show_closed_tip(self) -> None:
        """闭合态悬停：显示当前选中项的结果（弹窗开着时归弹窗内的过滤器管）。"""
        if getattr(self._combo, "_site_tip_in_popup", False) is True:
            return
        text = self._closed_tip_text()
        label = _site_tip_label()
        if not text:
            label.hide_tip()
            return
        if label.is_showing(text):
            return
        label.show_at(text, self._combo.mapToGlobal(QPoint(0, self._combo.height())))

    def _show_tip_for(self, index) -> None:
        """按 index 显示提示；index 为 None 或文本为空则收起提示。"""
        view = self._combo.view()
        row = index.row() if index is not None else -1
        text = str(index.data(Qt.ItemDataRole.ToolTipRole) or "").strip() if index is not None else ""
        label = _site_tip_label()
        if view is None or row < 0 or not text:
            self._hide_tip()
            return
        if row == self._shown_row and label.is_showing(text):
            return  # 同一行内移动且提示还亮着：不重复弹
        viewport = view.viewport()
        rect = view.visualRect(index)
        # 贴着该行下沿弹出：只有「上次检测：…」一行（定位说明已在显示文本里），鼠标停在本行即持续可见
        anchor = viewport.mapToGlobal(rect.bottomLeft() if rect.isValid() else viewport.rect().topLeft())
        label.show_at(text, anchor)
        self._shown_row = row  # 弹成功后再记账：中途异常也不会留下「以为亮着」的脏状态
        self._combo._site_tip_in_popup = True  # type: ignore[attr-defined]

    def eventFilter(self, obj, event) -> bool:
        # 重入守卫：`_SiteTipLabel.show_at()` 里的 move()/show()、hide_tip() 里的 hide()
        # 都会让 Qt 合成新的 MouseMove/Enter/Leave 再送回本过滤器。此刻两道守卫
        # 「同一行且提示还亮着」与「弹成功后才记账的 _shown_row」都还停留在旧值
        # （show() 之前 isVisible() 也是 False），于是每一次合成都再弹一次、
        # 再合成一次，无限递归把栈打爆（Windows 上表现为 `stack overflow` /
        # 0xC0000409）。重入期间一律放行：最外层那次会把状态记全，无需重复弹。
        if self._in_filter:
            return super().eventFilter(obj, event)
        self._in_filter = True
        try:
            event_type = event.type()
            view = self._combo.view()
            in_popup = view is not None and obj is view.viewport()
            if event_type == QEvent.Type.MouseMove and not event.buttons():
                # 无按键移动才做提示（拖拽选择过程中不打扰）
                if in_popup:
                    self._show_tip_for(self._index_at(_event_pos(event)))
                else:
                    self._show_closed_tip()
                return False  # 交给其余过滤器（如网址列的 _SiteUrlClickFilter）继续处理
            if event_type == QEvent.Type.ToolTip:
                if in_popup:
                    self._show_tip_for(self._index_at(_event_pos(event)))
                else:
                    self._show_closed_tip()
                return True  # 接管：不走 Qt 默认 delegate，避免同一处出现第二份/过期提示
            if event_type in (
                QEvent.Type.Hide,
                QEvent.Type.Leave,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.Wheel,
            ):
                self._hide_tip()
                return False
        except Exception:
            pass
        finally:
            self._in_filter = False
        return super().eventFilter(obj, event)


def _install_site_combo_tips(combo: QComboBox) -> None:
    """给站点下拉框装悬停提示（弹窗内按行、闭合时按当前项）。

    必须在 `_setup_combo_boxes` 换过 view 之后调用：弹窗那侧的过滤器装在
    view.viewport() 上，闭合那侧装在框体（及其 lineEdit）上。
    """
    view = combo.view()
    if view is None or getattr(combo, "_site_tip_filter_installed", False) is True:
        return
    tip_filter = _SiteComboTipFilter(combo)
    targets = [view.viewport(), combo]
    if combo.lineEdit() is not None:
        targets.append(combo.lineEdit())
    for target in targets:
        # 无按键也要有 MouseMove，否则移动到新位置时收不到事件
        target.setMouseTracking(True)
        target.installEventFilter(tip_filter)
    combo._site_tip_filter_installed = True  # type: ignore[attr-defined]


def _install_site_url_columns(combo: QComboBox) -> None:
    """给站点下拉框装网址列（delegate + 点击/悬停处理 + 弹窗宽度适配）。"""
    combo.setItemDelegate(_SiteUrlItemDelegate(combo))
    view = combo.view()
    if view is not None and getattr(combo, "_site_url_filter_installed", False) is not True:
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(_SiteUrlClickFilter(combo))
        combo._site_url_filter_installed = True  # type: ignore[attr-defined]
    if getattr(combo, "_site_popup_width_synced", False) is not True:
        # 每次打开弹窗前按框体当前宽重钉弹窗宽：窗口缩放/布局变化后不拿旧值
        _orig_show_popup = combo.showPopup

        def _show_popup_with_width(orig=_orig_show_popup, box=combo):
            _fit_site_url_popup(box)
            orig()

        combo.showPopup = _show_popup_with_width  # type: ignore[method-assign]
        combo._site_popup_width_synced = True  # type: ignore[attr-defined]
    _fit_site_url_popup(combo)


def _fit_site_url_popup(combo: QComboBox) -> None:
    """下拉弹窗宽度与框体闭合宽一致（只动弹窗 view，不碰 combo 本体宽——闭合态几何测试不受影响）。"""
    view = combo.view()
    if view is None:
        return
    w = combo.width()
    if w > 0:
        view.setFixedWidth(w)
    else:
        view.setMinimumWidth(0)


# 首启默认窗口尺寸（大屏保持此值；窗口实际尺寸另按可用区 90%/85% 收窄，见
# _adaptive_window_sizes）。同时是「界面缩放档位是否超屏」的判定基准之一。
DEFAULT_WINDOW_SIZE = (1080, 720)

# 高分屏缩放档位：与 MDCx.ui 中 comboBox_ui_scale 的下拉项逐条对应（下标即索引），
# 0.0 = 跟随系统，其余为写入 QT_SCALE_FACTOR 的实际倍率（main.py 启动时应用，
# 保存后重启生效）。改这里必须同步改 .ui 的下拉项（tests/test_ui_scale_options.py 把关）。
UI_SCALE_OPTIONS: tuple[float, ...] = (0.0, 0.8, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0)
# 缩放档位的可用性下限：低于此逻辑尺寸时界面必然撑破屏幕（Qt 的 setMinimumSize
# 也拦不住），该档位直接从下拉里隐藏。数值与 _adaptive_window_sizes 的 850/650 同源。
UI_SCALE_MIN_AVAILABLE_SIZE = (850, 650)


def ui_scale_index(value: float) -> int:
    """配置里的缩放值 → comboBox_ui_scale 下拉索引（取不超过该值的最大档位）。

    档位值取不到精确匹配时向下取档（如手改的 1.9 → 175%），再没有就是「跟随系统」。
    """
    if value in UI_SCALE_OPTIONS:
        return UI_SCALE_OPTIONS.index(value)
    lower = [i for i, option in enumerate(UI_SCALE_OPTIONS) if 0 < option <= value]
    return max(lower) if lower else 0


def ui_scale_value(index: int) -> float:
    """下拉索引 → 缩放值；越界一律回落到「跟随系统」（0.0）。"""
    if 0 <= index < len(UI_SCALE_OPTIONS):
        return UI_SCALE_OPTIONS[index]
    return 0.0


def ui_scale_hidden_flags(avail_w: int, avail_h: int, dpr: float) -> list[bool]:
    """逐档判定高分屏缩放是否要隐藏（True = 隐藏），依据是当前屏幕可用区。

    判定式：该档位下窗口的最小逻辑尺寸（850×650）必须放得进屏幕可用区——放不下就
    说明界面被撑出屏幕（用户 200% 反馈截图：设置页内容与左下角状态区互相挤压）。
    avail_* 是 Qt 报告的逻辑尺寸（已被系统缩放与 QT_SCALE_FACTOR 除过），乘回 dpr
    得物理像素再与「档位 × 最小尺寸」比较，故与当前实际缩放无关：80% 的机器上照样
    能算出 200%/300% 会不会超屏。dpr ≤ 0（异常值）时按 1.0 兜底。
    """
    min_w, min_h = UI_SCALE_MIN_AVAILABLE_SIZE
    ratio = dpr if dpr > 0 else 1.0
    phys_w, phys_h = avail_w * ratio, avail_h * ratio
    # 隐藏 = 真实档位且「档位 × 最小窗口尺寸」有一边超出屏幕可用区（0.0 跟随系统不隐藏）
    return [option > 0 and (option * min_w > phys_w or option * min_h > phys_h) for option in UI_SCALE_OPTIONS]


def apply_ui_scale_option_limits(combo: QComboBox, screen: QScreen | None) -> None:
    """把当前屏幕放不下的高分屏缩放档位从下拉里隐藏（防误选后界面撑破屏幕）。

    QComboBox 本身没有隐藏单项的接口，_setup_combo_boxes 已把所有下拉的 view 换成
    QListView，用 setRowHidden 隐藏对应行即可（跟随系统永远保留）。
    """
    if screen is None:
        return
    view = combo.view()
    if not isinstance(view, QListView):
        return
    avail = screen.availableGeometry()
    for index, hidden in enumerate(ui_scale_hidden_flags(avail.width(), avail.height(), screen.devicePixelRatio())):
        view.setRowHidden(index, hidden)


def _adaptive_window_sizes(avail_w: int, avail_h: int) -> tuple[int, int, int, int]:
    """按屏幕可用区域计算窗口最小尺寸与默认尺寸，返回 (min_w, min_h, def_w, def_h)。

    - 最小高取 min(650, 可用高×0.75)：650 可完整容纳主页面内容（设计底约 y=696，
      主页面无滚动区，低于此值底部字段不可达）；×0.75 保证 125% 缩放
      （1920x1080 → 逻辑 1536x864）下仍可缩小到 648，不回到锁死 700 的老问题。
    - 最小宽 min(850, 可用宽×0.6)：850 为历史值（92ef2437），小屏按比例收窄。
    - 默认尺寸 min(1030, 可用宽×0.9) × min(700, 可用高×0.85)：1030×700 为
      历史实际默认（showEvent），大屏保持；小屏/高缩放首启不被占满。宽高各自
      独立收缩是历史行为（用户 80% 缩放下的默认初始宽高不能变），界面缩放档位
      超屏由「高分屏缩放」下拉隐藏该档位来防（见 UI_SCALE_OPTIONS）。
      默认尺寸只允许在 showEvent 首次显示时应用——Windows 在 Init_Ui 阶段
      （窗口未展示）resize 导致单测收尾崩溃（诊断 PR #185 实证）。
    """
    min_w = min(850, max(int(avail_w * 0.6), 400))
    min_h = min(650, max(int(avail_h * 0.75), 300))
    def_w = min(1080, max(int(avail_w * 0.9), min_w))
    def_h = min(720, max(int(avail_h * 0.85), min_h))
    return min_w, min_h, def_w, def_h


def Init_Ui(self: MyMAinWindow):
    self.setWindowTitle("MDCx")  # 设置任务栏标题
    self.setWindowIcon(QIcon(resources.icon_ico))  # 设置任务栏图标
    self.setWindowOpacity(1.0)  # 设置窗口透明度
    screen = QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        min_w, min_h = _adaptive_window_sizes(avail.width(), avail.height())[:2]
    else:
        min_w, min_h = 850, 550
    # 全平台设最小尺寸（原先仅 Windows）；默认尺寸自适应在首次 showEvent
    # （见 MyMAinWindow._apply_adaptive_default_size，Init_Ui 阶段 resize 会炸 Windows）
    self.setMinimumSize(QSize(min_w, min_h))
    if not IS_WINDOWS:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    self.Ui.progressBar_scrape.setValue(0)  # 进度条清0
    self.Ui.progressBar_scrape.setTextVisible(False)  # 不显示进度条文字
    self.Ui.pushButton_start_cap.setCheckable(True)  # 主界面开始按钮可点状态
    self.init_QTreeWidget()  # 初始化树状图
    self.Ui.treeWidget_number.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
    )  # 支持 Shift/Ctrl 多选结果项
    self.Ui.treeWidget_number.setAllColumnsShowFocus(False)  # 关闭默认焦点框，避免与选中边框叠加
    self.Ui.treeWidget_number.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(False))
    # 图片不得改变原始宽高比：scaledContents 必须保持 False，否则 QLabel 会把已按
    # KeepAspectRatio 缩放好的 pixmap 再拉伸铺满整个框（正常/整理/分离/视频/更新/读取六种
    # 模式都走这里，故一处关闭即全局生效）。等比缩放由 _rescale_preview_pixmaps 用
    # KeepAspectRatio 完成，两个 label 的 alignment 均为 AlignCenter，多余部分留白居中。
    self.Ui.label_poster.setScaledContents(False)
    self.Ui.label_thumb.setScaledContents(False)
    self.Ui.pushButton_right_menu.setIcon(QIcon(resources.right_menu))
    self.Ui.pushButton_right_menu.setToolTip(" 右键菜单 ")
    self.Ui.pushButton_play.setIcon(QIcon(resources.play_icon))
    self.Ui.pushButton_play.setToolTip(" 播放 ")
    self.Ui.pushButton_open_folder.setIcon(QIcon(resources.open_folder_icon))
    self.Ui.pushButton_open_folder.setToolTip(" 打开文件夹 ")
    self.Ui.pushButton_open_nfo.setIcon(QIcon(resources.open_nfo_icon))
    self.Ui.pushButton_open_nfo.setToolTip(" 编辑 NFO ")
    self.Ui.pushButton_tree_clear.setIcon(QIcon(resources.clear_tree_icon))
    self.Ui.pushButton_tree_clear.setToolTip(" 清空结果列表 ")
    self.Ui.pushButton_close.setToolTip(" 关闭 ")
    self.Ui.pushButton_min.setToolTip(" 最小化 ")
    self.Ui.pushButton_main.setIcon(QIcon(resources.home_icon))
    self.Ui.pushButton_log.setIcon(QIcon(resources.log_icon))
    self.Ui.pushButton_tool.setIcon(QIcon(resources.tool_icon))
    self.Ui.pushButton_setting.setIcon(QIcon(resources.setting_icon))
    self.Ui.pushButton_net.setIcon(QIcon(resources.net_icon))
    help_icon = QIcon(resources.help_icon)
    self.Ui.pushButton_about.setIcon(help_icon)
    self.Ui.pushButton_nfo_library.setIcon(QIcon(resources.tool_icon))
    self.Ui.pushButton_emby_manager_nav.setIcon(QIcon(resources.tool_icon))
    self.Ui.pushButton_tips_normal_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_normal_mode.setToolTip("""<html><head/><body><p><b>正常模式：</b><br/>1）适合海报墙用户。正常模式将联网刮削视频字段信息，并执行翻译字段信息，移动和重命名视频文件及文件夹，下载图片、剧照、预告片，添加字幕、4K水印等一系列自动化操作<br/>2）刮削目录请在「设置→刮削目录」-「视频刮削目录」中设置<br/>3）刮削网站请在「设置→刮削网站」中设置。部分网站需要代理访问，可在「设置→网络」中设置代理和走代理网站。你可以点击左侧的「检测网络」查看网络连通性<br/>\
        4）字段翻译请在「设置→翻译」中设置<br/>5）图片、剧照、预告片请在「设置→下载」中设置<br/>6）视频文件命名请在「设置→命名」中设置<br/>7）如果刮削后不需要重命名，请在下面的「刮削成功后重命名文件」设置为「关」<br/>8）如果刮削后不需要移动文件，请在下面的「刮削成功后移动文件」设置为「关」<br/>9）如果想自动刮削，请在「设置→高级」中勾选「自动刮削」<br/>10）其他设置项和功能玩法可自行研究</p></body></html>""")
    self.Ui.pushButton_tips_organize_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_organize_mode.setToolTip(
        """<html><head/><body><p><b>整理模式：</b><br/>\
        1，适合已刮削完成、需要海报墙，但想按新的命名规则重新整理文件的用户。<br/>\
        2，不联网刮削、不下载图片、不生成或更新 nfo，软件读取视频或 STRM 同目录同名 nfo 中的字段，再按照「设置→命名」中的目录名、文件名、字段、长度、马赛克、分集、图片、预告片、画质等命名规则，重新组织并移动视频/STRM、图片、nfo、字幕等文件。<br/>\
        3，同目录下的「番号-mediainfo.json」会随视频同步移动并按新文件名重命名。<br/>\
        4，没有同名 nfo 的文件会跳过并记录失败原因，不会自动联网刮削。<br/>\
        5，STRM 文件会解析其指向的本地视频获取画质；无法访问时读取同名 mediainfo.json 或文件名中的画质标记。<br/>\
        6，单次整理数量复用「设置→高级」中「连续刮削」的数量，一批全部完成后再继续下一批；成功输出目录、失败输出目录和排除目录复用「设置→刮削目录」。<br/>\
        7，只有视频/STRM、图片、nfo、json、字幕等全部移动成功才算整理成功。任一文件移动失败会用管理员权限重试一次，仍失败则全部回滚原目录并记为整理失败。</p></body></html>"""
    )
    self.Ui.pushButton_tips_separate_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_separate_mode.setToolTip("""<html><head/><body><p><b>分离模式：</b><br/>1）适合海报墙用户。分离模式将联网刮削视频字段信息，并执行翻译字段信息，移动和重命名视频文件及文件夹，下载图片、剧照、预告片，添加字幕、4K水印等一系列自动化操作，视频与元数据将分开存放<br/>2）刮削目录请在「设置→刮削目录」-「视频刮削目录」中设置<br/>3）刮削网站请在「设置→刮削网站」中设置。部分网站需要代理访问，可在「设置→网络」中设置代理和走代理网站。你可以点击左侧的「检测网络」查看网络连通性<br/>\
        4）字段翻译请在「设置→翻译」中设置<br/>5）图片、剧照、预告片请在「设置→下载」中设置<br/>6）视频文件命名请在「设置→命名」中设置<br/>7）如果刮削后不需要重命名，请在下面的「刮削成功后重命名文件」设置为「关」<br/>8）如果刮削后不需要移动文件，请在下面的「刮削成功后移动文件」设置为「关」<br/>9）如果想自动刮削，请在「设置→高级」中勾选「自动刮削」<br/>10）其他设置项和功能玩法可自行研究</p></body></html>""")
    self.Ui.pushButton_tips_sort_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_sort_mode.setToolTip(
        """<html><head/><body><p><b>视频模式：</b><br/>1，适合不需要图片墙的情况。视频模式将联网刮削视频相关字段信息，然后根据「设置→命名」中设置的命名规则重命名、移动视频文件<br/>2，仅保留视频本体：视频搬到新目录后，原目录里的图片、剧照、预告片、nfo、字幕、种子等信息文件会一并删除（与视频/STRM 关联的才删，无关文件不动）<br/>3，如果是海报墙用户，请不要使用视频模式。</p></body></html>"""
    )
    self.Ui.pushButton_tips_update_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_update_mode.setToolTip("""<html><head/><body><p><b>更新模式：</b><br/>1，适合视频已经归类好的情况。更新模式将在不改动文件位置结构的前提下重新刮削更新一些信息<br/>2，更新规则在下面的「更新模式规则中」定义：<br/>-1）如果只更新视频文件名，请选择「只更新C」，视频文件名命名规则请到「设置→命名」中设置<br/>-2）如果要更新视频所在的目录名，请选择「更新B和C」；如果要更新视频目录的上层目录，请勾选「同时更新A目录」<br/>-3），如果要在视频目录为视频再创建一级目录，请选择「创建D目录」<br/>\
        3，更新模式将会对「待刮削目录」下的所有视频进行联网刮削和更新。<br/>4，当有部分内容没有更新成功，下次想只刮削这些内容时，请选择「读取模式」，同时勾选「不存在 nfo 时，刮削并执行更新模式规则」，它将查询并读取所有视频本地的 nfo 文件（不联网），当没有 nfo 文件时，则会自动进行联网刮削<br/>5，当部分内容确实无法刮削时，你可以到「软件日志」页面，点击「失败」按钮，点击左下角的保存按钮，就可以把失败列表保存到本地，然后可以手动查看和处理这些视频信息。</p></body></html>""")
    self.Ui.pushButton_tips_read_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_read_mode.setToolTip("""<html><head/><body><p><b>读取模式：</b><br/>\
        1，读取模式只做一件事：读取视频或 STRM 同目录同名 nfo 中的字段，以及目录里的封面图（poster）、缩略图（thumb）、背景图（fanart），在界面展示结果。<br/>\
        2，不联网刮削、不下载图片、不写 nfo、不移动/不重命名任何文件，适合检查媒体库、核对已刮削的信息与图片。<br/>\
        3，没有同目录同名 nfo 的文件会跳过并记录失败原因。<br/>\
        4，需要「补全缺失字段 / 补封面缩略图 / 按更新模式重新整理分类 / 重新下载图片」时，请改用「补全模式」；没有 nfo 的文件在补全模式下会自动按正常模式全量刮削。<br/>\
        5，读取模式不受断点续刮缓存影响，每次都会处理全部选中文件。</p></body></html>""")
    self.Ui.pushButton_tips_complete_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_complete_mode.setToolTip("""<html><head/><body><p><b>补全模式：</b><br/>\
        1，适合已经刮削过、但部分文件缺字段或缺图片的媒体库：优先使用本地已有的 nfo 字段、nfo 文件、封面图、缩略图、背景图、字幕与「番号-mediainfo.json」，本地确实没有的才联网刮削补齐。<br/>\
        2，与正常模式的区别：正常模式是全量重新刮削（刮削结果会覆盖本地 nfo）；补全模式是本地优先，刮削只用来填空字段，已有值一律保留。<br/>\
        3，没有同目录同名 nfo 的文件，自动切换到正常模式全量刮削（含下载封面、缩略图、背景图、写 nfo）。<br/>\
        4，已经位于「成功输出目录」内的文件只补字段和缺失的图片/字幕，不移动、不重命名；不在成功输出目录内的文件按「刮削成功后移动/重命名」开关处理，搬运与整理模式共用同一套事务，任一文件失败整体回滚到原目录。<br/>\
        5，字幕：当视频没有外挂字幕时，从「设置→字幕→添加外挂字幕→字幕存放目录」中查找同番号/同名字幕，复制到刮削后的文件夹。<br/>\
        6，下方选项说明：<br/>\
        -1）「本地刮削成功的文件，按更新模式重新整理分类」：按更新模式规则重新命名目录与文件（可无需联网）；<br/>\
        -2）「本地NFO内有链接，重新下载封面图片等文件」：勾选后本地已有的图片也会按「设置→下载」重新下载并重新打水印（不勾选时只补缺失的图片）；<br/>\
        -3）「本地NFO合并及策略」：勾选后按所选策略合并——全新数据优先（等于正常模式的覆盖行为）/ 合并数组去重 / 仅填补空字段（默认，本地已有值保留、只补本地空着的字段）。<br/>\
        7，补全模式不受断点续刮缓存影响，每次都会处理全部选中文件，方便反复运行把缺失项补齐。</p></body></html>""")
    self.Ui.pushButton_tips_soft.setIcon(help_icon)
    self.Ui.pushButton_tips_soft.setToolTip("""<html><head/><body><p><b>创建软链接：</b><br/>\
        1，软链接适合网盘用户。软链接类似快捷方式，是指向真实文件的一个符号链接。它体积小，支持跨盘指向，删除后不影响原文件（当原文件删除后，软链接会失效）。<br/>\
        <span style=" font-weight:700; color:red;">注意：\
        <br/>Windows版：软链接保存位置必须是本地磁盘（平台限制），真实文件则网盘或本地盘都可以。<br/>\
        macOS版：没有问题。<br/>\
        Docker版：挂载目录的完整路径需要和实际目录完整路径一样，这样软链接才能指向实际位置，Emby 才能播放。</span><br/>\

        2，网盘受网络等因素影响，读写慢，限制多。选择创建软链接时，将在本地盘创建指向网盘视频文件的软链接文件，同时刮削下载的图片同样放在本地磁盘，使用 Emby、Jellyfin 加载速度快！<br/>\
        3，刮削不会移动、修改、重命名原文件，仅读取原文件的路径位置，用来创建软链接<br/>\
        4，刮削成功后，将按照刮削设置创建和重命名软链接文件<br/>\
        5，刮削失败时，不会创建软链接，如果你想要把全部文件都创建软链接，可以到 【工具】-【软链接助手】-【一键创建软链接】）<br/>\
        6，如果网盘里已经有刮削好的内容，想要把刮削信息转移到本地磁盘，同样使用上述工具，勾选【复制已刮削的图片和NFO文件】即可<br/>\
        7，网盘挂载和刮削方法：<br/>\
        -1）使用 CloudDriver、Alist、RaiDrive 等第三方工具挂载网盘<br/>\
        -2）MDCx 设置待刮削目录为网盘视频目录，输出目录为本地磁盘文件夹<br/>\
        -3）设置中选择「创建软链接」，其他配置设置好后保存配置，点击开始刮削<br/>\
        -4）Emby、Jellyfin 媒体库路径设置为本地刮削后保存的磁盘文件夹扫描即可</p></body></html>""")
    self.Ui.pushButton_tips_hard.setIcon(help_icon)
    self.Ui.pushButton_tips_hard.setToolTip(
        """<html><head/><body><p><b>创建硬链接：</b><br/>1，硬链接适合 PT 用户。PT 用户视频文件一般存放在 NAS 中，为保证上传分享率，不能修改原文件信息。<br/>2，硬链接指向和原文件相同的硬盘索引，和原文件必须同盘。使用硬链接，可以在同盘单独存放刮削资料，不影响原文件信息。<br/>3，删除硬链接，原文件还在；删除原文件，硬链接还在。两个都删除，文件才会被删除。<br/><span style=" font-weight:700; color:#ff2600;">注意：Mac 平台仅支持本地磁盘创建硬链接（权限问题），非本地磁盘请选择创建软链接。Windows 平台没有这个问题。</span></p></body></html>"""
    )
    self.Ui.textBrowser_log_main_3.hide()  # 失败列表隐藏
    self.Ui.pushButton_scraper_failed_list.hide()
    self.Ui.pushButton_save_failed_list.hide()
    supported_websites = sorted(get_registered_crawler_site_values())
    self.Ui.comboBox_website_all.clear()
    self.Ui.comboBox_custom_website.clear()
    _populate_site_combo(self.Ui.comboBox_website_all, supported_websites)
    _populate_site_combo(self.Ui.comboBox_custom_website, supported_websites)
    # 初始化使用代理网站下拉框
    self.Ui.comboBox_no_proxy_sites.clear()
    self.Ui.comboBox_no_proxy_sites.addItem("选择网站...", "")
    # 使用代理下拉框不要能力概览（「综合：有码+无码」「有码：有码」等）：用户 2026-10-19 提出，
    # 这里选的是要走代理的域名，能力文案纯噪声。另两个下拉框保持原样。
    _populate_site_combo(self.Ui.comboBox_no_proxy_sites, sorted(supported_websites), with_caption=False)
    # 连接选择事件
    self.Ui.comboBox_no_proxy_sites.currentTextChanged.connect(self._add_no_proxy_site)
    _setup_combo_boxes(self)
    # 三个站点下拉框的悬停提示：光标落到哪行就显示哪行（定位说明 + 上次检测），
    # 必须装在 _setup_combo_boxes 换过 view 之后（指定网站框不装网址列，同样要提示）
    for _site_combo in (
        self.Ui.comboBox_website_all,
        self.Ui.comboBox_custom_website,
        self.Ui.comboBox_no_proxy_sites,
    ):
        _install_site_combo_tips(_site_combo)
    # 指定网站（comboBox_website_all）下拉右侧不显示网址：只装另外两框的网址列
    for _site_combo in (
        self.Ui.comboBox_custom_website,
        self.Ui.comboBox_no_proxy_sites,
    ):
        _install_site_url_columns(_site_combo)
    # 高分屏缩放：放不下当前屏幕的档位直接从下拉隐藏（_setup_combo_boxes 换过 view，必须在其后）
    apply_ui_scale_option_limits(self.Ui.comboBox_ui_scale, QApplication.primaryScreen())
    self.Ui.textBrowser_log_main.document().setMaximumBlockCount(6000)
    self.Ui.textBrowser_log_main_2.document().setMaximumBlockCount(3000)
    # 网络检测面板：10k 条清屏周期之外再加块数上限，多行日志堆积时兜底防 QTextDocument 无界增长
    self.Ui.textBrowser_net_main.document().setMaximumBlockCount(30000)
    self.Ui.textBrowser_log_main.viewport().installEventFilter(self)  # 注册事件用于识别点击控件时隐藏失败列表面板
    self.Ui.textBrowser_log_main_2.viewport().installEventFilter(self)
    self.Ui.pushButton_save_failed_list.setIcon(QIcon(resources.save_failed_list_icon))
    self.Ui.pushButton_clear_logs.setIcon(QIcon(resources.clear_tree_icon))
    self.Ui.pushButton_clear_logs.setToolTip("清空显示（不删除日志文件）")
    self.Ui.pushButton_copy_logs.setToolTip("复制当前显示的日志到剪贴板")
    # 上栏日志显示与滚动条分离：内置滚动条隐藏（.ui 里 AlwaysOff），只作滚动范围数据源；
    # 外置独立滚动条负责交互，双向镜像同步（内置值变→外置跟随，外置拖动→驱动内置）
    inner_log_bar = self.Ui.textBrowser_log_main.verticalScrollBar()
    inner_log_bar.rangeChanged.connect(self._mirror_log_scrollbar)
    inner_log_bar.valueChanged.connect(self._on_inner_log_scroll_changed)
    self.Ui.verticalScrollBar_log_main.valueChanged.connect(inner_log_bar.setValue)
    self.Ui.widget_show_success.resize(811, 511)
    self.Ui.widget_show_success.hide()
    self.Ui.widget_show_tips.resize(811, 511)
    self.Ui.widget_show_tips.hide()
    self.Ui.widget_nfo.resize(791, 681)
    self.Ui.widget_nfo.hide()
    setup_site_priority_ui(self)
    # 议题 #117：信息管理表单页底部没有配置浮框遮挡，收紧内容底部余量（默认 72px
    # 是给设置页浮框带留的），否则小窗时多余留白把「保存当前nfo文件」挤出视口、
    # 凭空多出一条垂直滚动条，滚动条还会盖住输入框右侧圆角。
    self.Ui.scrollArea_nfo_lib_form.set_content_bottom_margin(8)
    # 软件工具页卡片与软件设置页卡片右缘齐平：设置页滚动区加宽 4px（tab 右边距
    # 20→16，滚动条右缘收到页宽-18）后，两侧视口差消失、自然齐平，不再需要内收
    # （曾用 scrollArea_10.set_content_right_trim(4) 补偿恒定 4px 差，见测试文件说明）。
    # 软件工具页滚动区底部无浮框遮挡（页脚在滚动区外单独留了 75px），默认 72px
    # 底部余量（给设置页浮框带留的）会变成刮削缓存管理下方的空白滚动区。
    # 收紧到 20px（= 设计内容高 2309 - 末组框底边 2289），保留设计呼吸感。
    self.Ui.scrollArea_10.set_content_bottom_margin(20)
    # stackedWidget 中未显示的页面不会触发 resize/show 事件，统一初始化
    # 自定义滚动区内容最小高度，保证首次切换到任一页面垂直滚动即可用
    from mdcx.views.CustomClass import CustomScrollArea

    for scroll_area in self.findChildren(CustomScrollArea):
        scroll_area.sync_content_min_height()


def _setup_combo_boxes(self: MyMAinWindow) -> None:
    """给所有下拉框统一装 QListView 视图（每下拉至多露 10 行、逐像素滚动）。

    view 上**不再设 maximumHeight**（原先写死 322）：弹窗外框（`QComboBoxPrivateContainer`）
    的高度由 `maxVisibleItems × 行高` 决定，与 view 的 maximumHeight 无关，两者一旦
    对不齐，外框那套 QVBoxLayout 就会把撑不满的 view 垂直居中，于是弹窗上下各多出
    一条空白带（站点下拉行高约 40px，322 只够 8 行、外框按 10 行留高，上下各空约 40px，
    即用户截图里「指定网站」「当前网站」下拉上下那两条空白控件）。行高本身随字体/缩放
    浮动，写死上限迟早又会错位，干脆不设：外框多高 view 就多高，正好贴满。
    弹窗外框尺寸与改前完全一致（那 322 从来只裁 view、不参与外框高度计算），
    变的只是同一块地方从「8 行 + 上下空白」变成「10 行」。
    """
    for combo_box in self.findChildren(QComboBox):
        view = QListView(combo_box)
        view.setUniformItemSizes(True)
        view.setSpacing(0)
        combo_box.setMaxVisibleItems(10)
        combo_box.setView(view)
        combo_view = combo_box.view()
        assert combo_view is not None
        combo_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        combo_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        combo_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)


def Init_Singal(self: MyMAinWindow):
    # region 外部信号量连接
    signal_qt.log_text.connect(self.show_log_text)  # 可视化日志输出
    signal_qt.scrape_info.connect(self.show_scrape_info)  # 可视化日志输出
    signal_qt.net_info.connect(self.show_net_info)  # 可视化日志输出
    signal_qt.exec_set_main_info.connect(self.set_main_info)
    signal_qt.change_buttons_status.connect(self.change_buttons_status)
    signal_qt.reset_buttons_status.connect(self.reset_buttons_status)
    signal_qt.logs_failed_settext.connect(self.Ui.textBrowser_log_main_3.setText)
    signal_qt.label_result.connect(self.Ui.label_result.setText)
    signal_qt.set_label_file_path.connect(self.Ui.label_file_path.setText)
    signal_qt.view_success_file_settext.connect(self.Ui.pushButton_view_success_file.setText)
    signal_qt.exec_set_processbar.connect(self.set_processbar)
    signal_qt.view_failed_list_settext.connect(self.Ui.pushButton_view_failed_list.setText)
    signal_qt.exec_show_list_name.connect(self.show_list_name)
    signal_qt.exec_exit_app.connect(self.exit_app)
    signal_qt.logs_failed_show.connect(self.Ui.textBrowser_log_main_3.append)
    # endregion

    # region 控件点击
    # self.Ui.treeWidget_number.clicked.connect(self.treeWidget_number_clicked)
    self.Ui.treeWidget_number.selectionModel().selectionChanged.connect(self.treeWidget_number_clicked)
    self.Ui.treeWidget_number.customContextMenuRequested.connect(self._tree_result_context_menu)
    self.Ui.pushButton_close.clicked.connect(self.pushButton_close_clicked)
    self.Ui.pushButton_min.clicked.connect(self.pushButton_min_clicked)
    self.Ui.pushButton_main.clicked.connect(self.pushButton_main_clicked)
    self.Ui.pushButton_log.clicked.connect(self.pushButton_show_log_clicked)
    self.Ui.pushButton_net.clicked.connect(self.pushButton_show_net_clicked)
    self.Ui.pushButton_tool.clicked.connect(self.pushButton_tool_clicked)
    self.Ui.pushButton_setting.clicked.connect(self.pushButton_setting_clicked)
    self.Ui.pushButton_about.clicked.connect(self.pushButton_about_clicked)
    self.Ui.pushButton_nfo_library.clicked.connect(self.pushButton_nfo_library_clicked)
    self.Ui.pushButton_emby_manager_nav.clicked.connect(self.pushButton_emby_actor_manager_clicked)
    self.Ui.pushButton_nfo_lib_select_dir.clicked.connect(self.pushButton_nfo_lib_select_dir_clicked)
    self.Ui.pushButton_nfo_lib_refresh.clicked.connect(self.pushButton_nfo_lib_refresh_clicked)
    self.Ui.pushButton_nfo_lib_save.clicked.connect(self.pushButton_nfo_lib_save_clicked)
    self.Ui.pushButton_nfo_lib_crop.clicked.connect(self.pushButton_nfo_lib_crop_clicked)
    self.Ui.pushButton_nfo_lib_select_all.clicked.connect(self.pushButton_nfo_lib_select_all_clicked)
    self.Ui.pushButton_nfo_lib_select_none.clicked.connect(self.pushButton_nfo_lib_select_none_clicked)
    self.Ui.listWidget_nfo_lib.itemSelectionChanged.connect(self.listWidget_nfo_lib_item_clicked)
    self.Ui.listWidget_nfo_lib.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.Ui.listWidget_nfo_lib.customContextMenuRequested.connect(self.listWidget_nfo_lib_context_menu)
    self.Ui.lineEdit_nfo_lib_filter.textChanged.connect(self.lineEdit_nfo_lib_filter_changed)
    self.Ui.lineEdit_nfo_lib_dir.returnPressed.connect(self.lineEdit_nfo_lib_dir_return_pressed)
    self.nfo_lib_data_loaded.connect(self.on_nfo_lib_data_loaded)
    self.nfo_lib_images_changed.connect(self.on_nfo_lib_images_changed)
    self.nfo_lib_save_done.connect(self.on_nfo_lib_save_done)
    self.nfo_lib_batch_done.connect(self.on_nfo_lib_batch_done)
    self.nfo_lib_batch_progress.connect(self.on_nfo_lib_batch_progress)
    self.Ui.pushButton_nfo_lib_batch_actor.clicked.connect(self.pushButton_nfo_lib_batch_actor_clicked)
    self.Ui.pushButton_nfo_lib_batch_add_tag.clicked.connect(self.pushButton_nfo_lib_batch_add_tag_clicked)
    self.Ui.pushButton_nfo_lib_batch_del_tag.clicked.connect(self.pushButton_nfo_lib_batch_del_tag_clicked)
    self.Ui.pushButton_nfo_lib_batch_series.clicked.connect(self.pushButton_nfo_lib_batch_series_clicked)
    self.Ui.pushButton_nfo_lib_batch_save.clicked.connect(self.pushButton_nfo_lib_batch_save_clicked)
    self.Ui.groupBox_nfo_lib_batch.toggled.connect(self._on_nfo_lib_batch_toggled)
    # 批量操作默认勾选展开，去勾隐藏；状态记入配置文件，重启恢复（需求 4）。
    # manager 在导入时已从磁盘加载配置，这里读到的是上次退出的真实值。
    self._nfo_lib_batch_ready = False  # 恢复期间 toggled 只做显隐，不写盘
    self.Ui.groupBox_nfo_lib_batch.setChecked(manager.config.nfo_lib_batch_expanded)
    self._nfo_lib_batch_ready = True
    # QLayout.setStretchFactor 只接受 QWidget/QLayout 对象；按 index 设置用 QBoxLayout.setStretch
    # 三栏 3:4:3：左栏（列表 + 批量保存）/ 中栏（表单 + 保存当前nfo文件）/
    # 右栏（预览 + 裁剪封面），三按钮各自铺满所在栏 → 三按钮 3:4:3，
    # 最大化时布局同步放大（需求 2）。
    self.Ui.nfo_lib_content_layout.setStretch(0, 3)
    self.Ui.nfo_lib_content_layout.setStretch(1, 4)
    self.Ui.nfo_lib_content_layout.setStretch(2, 3)
    # 右栏：海报 / 缩略图 1:1 均分裁剪封面上方的高度，裁剪封面沉底，
    # 末尾间隙 widget 高度由 _sync_nfo_lib_action_row 按对齐基准重算（需求 3）。
    self.Ui.nfo_lib_preview_layout.setStretch(0, 1)
    self.Ui.nfo_lib_preview_layout.setStretch(1, 1)
    self.Ui.nfo_lib_preview_layout.setStretch(2, 0)
    self.Ui.nfo_lib_preview_layout.setStretch(3, 0)
    # 所有显示用的文本框都「内容优先从左展示」：程序回填时控件无焦点 → 光标自动归 0，
    # 长路径 / 长 URL 不再把开头（http://、https://）滚出可视区；用户正在输入（有焦点）
    # 时一律不插手。覆盖设置 / 信息管理 / 软件工具 / 网络等全部页面（需求：所有显示框）。
    left_anchor_text_edits(self)
    self.Ui.pushButton_select_local_library.clicked.connect(self.pushButton_select_local_library_clicked)
    self.Ui.pushButton_select_netdisk_path.clicked.connect(self.pushButton_select_netdisk_path_clicked)
    self.Ui.pushButton_select_localdisk_path.clicked.connect(self.pushButton_select_localdisk_path_clicked)
    self.Ui.pushButton_select_media_folder.clicked.connect(self.pushButton_select_media_folder_clicked)
    self.Ui.pushButton_select_media_folder_setting_page.clicked.connect(self.pushButton_select_media_folder_clicked)
    self.Ui.pushButton_select_data_dir.clicked.connect(self.pushButton_select_data_dir_clicked)
    self.Ui.pushButton_select_softlink_folder.clicked.connect(self.pushButton_select_softlink_folder_clicked)
    self.Ui.pushButton_select_sucess_folder.clicked.connect(self.pushButton_select_sucess_folder_clicked)
    self.Ui.pushButton_select_failed_folder.clicked.connect(self.pushButton_select_failed_folder_clicked)
    self.Ui.pushButton_view_success_file.clicked.connect(self.pushButton_view_success_file_clicked)
    self.Ui.pushButton_select_subtitle_folder.clicked.connect(self.pushButton_select_subtitle_folder_clicked)
    self.Ui.pushButton_select_actor_photo_folder.clicked.connect(self.pushButton_select_actor_photo_folder_clicked)
    self.Ui.pushButton_select_gfriends_local.clicked.connect(self.pushButton_select_gfriends_local_clicked)
    self.Ui.pushButton_sync_gfriends.clicked.connect(self.pushButton_sync_gfriends_clicked)
    self.Ui.pushButton_select_config_folder.clicked.connect(self.pushButton_select_config_folder_clicked)
    self.Ui.pushButton_select_actor_info_db.clicked.connect(self.pushButton_select_actor_info_db_clicked)
    self.Ui.pushButton_select_file.clicked.connect(self.pushButton_select_file_clicked)
    self.Ui.pushButton_start_cap.clicked.connect(self.pushButton_start_scrape_clicked)
    self.Ui.pushButton_start_cap2.clicked.connect(self.pushButton_start_scrape_clicked)
    self.Ui.pushButton_show_hide_logs.clicked.connect(self.pushButton_show_hide_logs_clicked)
    self.Ui.pushButton_clear_logs.clicked.connect(self.pushButton_clear_logs_clicked)
    self.Ui.pushButton_copy_logs.clicked.connect(self.pushButton_copy_logs_clicked)
    self.Ui.pushButton_view_failed_list.clicked.connect(self.pushButton_show_hide_failed_list_clicked)
    self.Ui.pushButton_save_new_config.clicked.connect(self.pushButton_save_new_config_clicked)
    self.Ui.pushButton_save_new_config_tool.clicked.connect(self.pushButton_save_new_config_clicked)
    self.Ui.pushButton_save_config.clicked.connect(self.pushButton_save_config_clicked)
    self.Ui.pushButton_save_config_tool.clicked.connect(self.pushButton_save_config_clicked)
    self.Ui.pushButton_init_config.clicked.connect(self.pushButton_init_config_clicked)
    self.Ui.pushButton_init_config_tool.clicked.connect(self.pushButton_init_config_clicked)
    self.Ui.pushButton_move_mp4.clicked.connect(self.pushButton_move_mp4_clicked)
    self.Ui.pushButton_check_net.clicked.connect(self.pushButton_check_net_clicked)
    self.Ui.pushButton_net_retry.clicked.connect(self.pushButton_net_retry_clicked)
    self.Ui.pushButton_net_copy.clicked.connect(self.pushButton_net_copy_clicked)
    self.Ui.pushButton_check_javdb_cookie.clicked.connect(self.pushButton_check_javdb_cookie_clicked)
    self.Ui.pushButton_check_fc2ppvdb_cookie.clicked.connect(self.pushButton_check_fc2ppvdb_cookie_clicked)
    self.Ui.pushButton_check_javbus_cookie.clicked.connect(self.pushButton_check_javbus_cookie_clicked)
    self.Ui.pushButton_check_and_clean_files.clicked.connect(self.pushButton_check_and_clean_files_clicked)
    self.Ui.pushButton_add_all_extras.clicked.connect(self.pushButton_add_all_extras_clicked)
    self.Ui.pushButton_del_all_extras.clicked.connect(self.pushButton_del_all_extras_clicked)
    self.Ui.pushButton_add_all_extrafanart_copy.clicked.connect(self.pushButton_add_all_extrafanart_copy_clicked)
    self.Ui.pushButton_del_all_extrafanart_copy.clicked.connect(self.pushButton_del_all_extrafanart_copy_clicked)
    self.Ui.pushButton_add_all_theme_videos.clicked.connect(self.pushButton_add_all_theme_videos_clicked)
    self.Ui.pushButton_del_all_theme_videos.clicked.connect(self.pushButton_del_all_theme_videos_clicked)
    self.Ui.pushButton_add_sub_for_all_video.clicked.connect(self.pushButton_add_sub_for_all_video_clicked)
    self.Ui.pushButton_add_actor_info.clicked.connect(self.pushButton_add_actor_info_clicked)
    self.Ui.pushButton_add_actor_pic.clicked.connect(self.pushButton_add_actor_pic_clicked)
    self.Ui.pushButton_add_actor_pic_kodi.clicked.connect(self.pushButton_add_actor_pic_kodi_clicked)
    self.Ui.pushButton_del_actor_folder.clicked.connect(self.pushButton_del_actor_folder_clicked)
    self.Ui.pushButton_show_pic_actor.clicked.connect(self.pushButton_show_pic_actor_clicked)
    self.Ui.pushButton_select_thumb.clicked.connect(self.pushButton_select_thumb_clicked)
    self.Ui.pushButton_find_missing_number.clicked.connect(self.pushButton_find_missing_number_clicked)
    self.Ui.pushButton_creat_symlink.clicked.connect(self.pushButton_creat_symlink_clicked)
    self.Ui.pushButton_cover_backfill_start.clicked.connect(self.pushButton_cover_backfill_start_clicked)
    self.Ui.pushButton_actor_db_translate.clicked.connect(self.pushButton_actor_db_translate_clicked)
    self.Ui.pushButton_actor_db_link.clicked.connect(self.pushButton_actor_db_link_clicked)
    self.Ui.pushButton_actor_db_sync_aliases.clicked.connect(self.pushButton_actor_db_sync_aliases_clicked)
    self.Ui.pushButton_actor_db_fill_Minnano.clicked.connect(self.pushButton_actor_db_fill_Minnano_clicked)
    self.Ui.pushButton_actor_db_fill_zh_javdb.clicked.connect(self.pushButton_actor_db_fill_zh_javdb_clicked)
    self.Ui.pushButton_actor_db_open.clicked.connect(self.pushButton_actor_db_open_clicked)
    self.Ui.pushButton_actor_db_stop.clicked.connect(self.pushButton_actor_db_stop_clicked)
    self.Ui.pushButton_actor_db_clean_male.clicked.connect(self.pushButton_actor_db_clean_male_clicked)
    self.Ui.pushButton_scrape_cache_refresh.clicked.connect(self.pushButton_scrape_cache_refresh_clicked)
    self.Ui.pushButton_scrape_cache_export.clicked.connect(self.pushButton_scrape_cache_export_clicked)
    self.Ui.pushButton_scrape_cache_reset.clicked.connect(self.pushButton_scrape_cache_reset_clicked)
    self.Ui.pushButton_scrape_cache_clear.clicked.connect(self.pushButton_scrape_cache_clear_clicked)
    # 议题 #179: 失败列表列宽按 4:2:6:3 加权分摊视口（失败次数按内容），杜绝窄窗横向滚动条/宽窗右侧空白
    self._apply_scrape_cache_header_modes()
    self.Ui.pushButton_actor_db_verify_tmdbid.clicked.connect(self.pushButton_actor_db_verify_tmdbid_clicked)
    self.Ui.pushButton_actor_db_check.clicked.connect(self.pushButton_actor_db_check_clicked)
    self.Ui.pushButton_actor_db_pick_nfo_dir.clicked.connect(self.pushButton_actor_db_pick_nfo_dir_clicked)
    self.Ui.pushButton_actor_db_update_nfo_tmdbid.clicked.connect(self.pushButton_actor_db_update_nfo_tmdbid_clicked)
    self.Ui.pushButton_start_single_file.clicked.connect(self.pushButton_start_single_file_clicked)
    self.Ui.pushButton_select_file_clear_info.clicked.connect(self.pushButton_select_file_clear_info_clicked)
    self.Ui.pushButton_scrape_note.clicked.connect(self.pushButton_scrape_note_clicked)
    self.Ui.pushButton_field_tips_nfo.clicked.connect(self.pushButton_field_tips_nfo_clicked)
    self.Ui.pushButton_tips_normal_mode.clicked.connect(self.pushButton_tips_normal_mode_clicked)
    self.Ui.pushButton_tips_organize_mode.clicked.connect(self.pushButton_tips_organize_mode_clicked)
    self.Ui.pushButton_tips_separate_mode.clicked.connect(self.pushButton_tips_separate_mode_clicked)
    self.Ui.pushButton_tips_sort_mode.clicked.connect(self.pushButton_tips_sort_mode_clicked)
    self.Ui.pushButton_tips_update_mode.clicked.connect(self.pushButton_tips_update_mode_clicked)
    self.Ui.pushButton_tips_read_mode.clicked.connect(self.pushButton_tips_read_mode_clicked)
    # 刮削模式页两网格列钉死：gridLayout_2（刮削模式组）第 1 列左缘必须与
    # gridLayout_15（Javdb 延时提示 label_26 所在列）左缘上下严格对齐，且永不再动。
    # 做法：第 0 列 stretch=0（只占最小宽）、第 1 列 stretch=1（吸收全部拉伸富余），
    # 故第 1 列左缘恒为设计值，不随窗口宽度右移；两网格第 0 列最小宽取较大者，
    # 保证两列左缘跨网格对齐。setColumnStretch/setColumnMinimumWidth 是持久设置，
    # 无其他代码碰这两个网格，一次设置永久生效。描述 label 已在 .ui 设 wordWrap=false
    # 保证单行（tooltip 同文案防极端 DPI 下裁剪）。
    for _grid in (self.Ui.gridLayout_2, self.Ui.gridLayout_15):
        _grid.setColumnStretch(0, 0)
        _grid.setColumnStretch(1, 1)
    _col0_w = 0
    for _grid, _rows in (
        (self.Ui.gridLayout_2, range(11)),
        (self.Ui.gridLayout_15, range(3)),
    ):
        for _r in _rows:
            _item = _grid.itemAtPosition(_r, 0)
            _w = _item.widget() if _item is not None else None
            if _w is not None:
                _col0_w = max(_col0_w, _w.sizeHint().width())
    if _col0_w > 0:
        self.Ui.gridLayout_2.setColumnMinimumWidth(0, _col0_w)
        self.Ui.gridLayout_15.setColumnMinimumWidth(0, _col0_w)
    # STRM 行四枚复选框（生成 / 覆盖STRM / 复用 / 覆盖元数据）同排：行内间距由主窗口
    # _sync_strm_row_meta_align 按实测差值闭环收敛（sizeHint 在 show 前后会变，初始化
    # 公式一次算不准），此处不预设 gap 宽度。
    # 复用/覆盖元数据互斥：只允许同时选中一个（界面层），运行时覆盖优先兜底。
    self.Ui.checkBox_separate_reuse_meta.toggled.connect(self.checkBox_separate_reuse_meta_changed)
    self.Ui.checkBox_separate_overwrite_meta.toggled.connect(self.checkBox_separate_overwrite_meta_changed)
    # STRM：覆盖是生成的后置动作，勾选覆盖时同步勾选生成（取消生成则覆盖一并取消）
    self.Ui.checkBox_separate_generate_strm.toggled.connect(self.checkBox_separate_generate_strm_changed)
    self.Ui.checkBox_separate_overwrite_strm.toggled.connect(self.checkBox_separate_overwrite_strm_changed)
    # 高级页-任务模式：本地存储文件 / 网盘存储文件互斥
    self.Ui.checkBox_task_store_local.toggled.connect(self.checkBox_task_store_local_changed)
    self.Ui.checkBox_task_store_netdisk.toggled.connect(self.checkBox_task_store_netdisk_changed)
    # 高级页「移动文件」：覆盖目标文件 / 保留目标文件互斥（同一时刻只能选中一个；
    # 都不勾选=保持原有移动行为）
    self.Ui.checkBox_move_overwrite.toggled.connect(self.checkBox_move_overwrite_changed)
    self.Ui.checkBox_move_keep.toggled.connect(self.checkBox_move_keep_changed)
    for _lbl in (
        self.Ui.label_11,
        self.Ui.label_organize_mode,
        self.Ui.label_separate_mode,
        self.Ui.label_15,
        self.Ui.label_36,
        self.Ui.label_312,
    ):
        _lbl.setToolTip(_lbl.text())
    self.Ui.pushButton_tips_soft.clicked.connect(self.pushButton_tips_soft_clicked)
    self.Ui.pushButton_tips_hard.clicked.connect(self.pushButton_tips_hard_clicked)
    self.Ui.checkBox_cover.stateChanged.connect(self.checkBox_cover_clicked)
    self.Ui.checkBox_amazon_big_pic.stateChanged.connect(self.update_amazon_strict_pic_verify_state)
    self.Ui.radioButton_scrape_info.toggled.connect(self.update_field_priority_try_all_images_state)
    self.Ui.checkBox_i_agree_clean.stateChanged.connect(self.checkBox_i_agree_clean_clicked)
    self.Ui.checkBox_cd_part_a.stateChanged.connect(self.checkBox_cd_part_a_clicked)
    self.Ui.checkBox_i_understand_clean.stateChanged.connect(self.checkBox_i_agree_clean_clicked)
    self.Ui.horizontalSlider_timeout.valueChanged.connect(self.lcdNumber_timeout_change)
    self.Ui.horizontalSlider_retry.valueChanged.connect(self.lcdNumber_retry_change)
    self.Ui.horizontalSlider_mark_size.valueChanged.connect(self.lcdNumber_mark_size_change)
    self.Ui.horizontalSlider_thread.valueChanged.connect(self.lcdNumber_thread_change)
    self.Ui.horizontalSlider_javdb_time.valueChanged.connect(self.lcdNumber_javdb_time_change)
    self.Ui.horizontalSlider_thread_time.valueChanged.connect(self.lcdNumber_thread_time_change)
    self.Ui.comboBox_change_config.textActivated.connect(self.config_file_change)
    self.Ui.comboBox_change_config_tool.textActivated.connect(self.config_file_change)
    self.Ui.comboBox_custom_website.textActivated.connect(self.switch_custom_website_change)
    self.Ui.pushButton_right_menu.clicked.connect(self.main_open_right_menu)
    self.Ui.pushButton_play.clicked.connect(self.main_play_click)
    self.Ui.pushButton_open_folder.clicked.connect(self.main_open_folder_click)
    self.Ui.pushButton_open_nfo.clicked.connect(self.main_open_nfo_click)
    self.Ui.pushButton_tree_clear.clicked.connect(self.init_QTreeWidget)
    self.Ui.pushButton_scraper_failed_list.clicked.connect(self.pushButton_scraper_failed_list_clicked)
    self.Ui.pushButton_save_failed_list.clicked.connect(self.pushButton_save_failed_list_clicked)
    self.Ui.pushButton_success_list_close.clicked.connect(self.Ui.widget_show_success.hide)
    self.Ui.pushButton_success_list_save.clicked.connect(self.pushButton_success_list_save_clicked)
    self.Ui.pushButton_success_list_clear.clicked.connect(self.pushButton_success_list_clear_clicked)
    self.Ui.pushButton_show_tips_close.clicked.connect(self.Ui.widget_show_tips.hide)
    self.Ui.pushButton_nfo_close.clicked.connect(self._close_nfo_editor)
    self.Ui.pushButton_nfo_save.clicked.connect(self.save_nfo_info)
    # 关闭按钮刻意不设 shortcut：ESC 由主窗口唯一的全局 QShortcut
    # （hide_tips_widget_on_escape）统一处理，NFO 可见时等同点关闭；按钮上再挂一条
    # 相同键序列的 shortcut 会被 Qt 判为 ambiguous，两条都不触发。
    # endregion

    # region 鼠标点击
    def n(a): ...  # mousePressEvent 的返回值必须是 None, 用这个包装一下

    self.Ui.label_show_version.mousePressEvent = lambda ev: n(webbrowser.open(GITHUB_RELEASES_URL))
    self.Ui.label_local_number.mousePressEvent = self.label_local_number_clicked

    self.Ui.label_download_actor_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://github.com/moyy996/AVDC/releases/tag/%E5%A4%B4%E5%83%8F%E5%8C%85-2")
    )
    self.Ui.label_download_sub_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://www.dropbox.com/sh/vkbxawm6mwmwswr/AADqZiF8aUHmK6qIc7JSlURIa")
    )
    self.Ui.label_download_mark_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://www.dropbox.com/sh/vkbxawm6mwmwswr/AADqZiF8aUHmK6qIc7JSlURIa")
    )
    self.Ui.label_get_cookie_url.mousePressEvent = lambda ev: n(webbrowser.open("https://tieba.baidu.com/p/5492736764"))
    self.Ui.label_download_actor_db.mousePressEvent = lambda ev: n(
        webbrowser.open(f"{GITHUB_RELEASES_URL}/tag/actor_info_database")
    )

    # 日志窗口链接仅外部打开，避免 QTextBrowser 内部跳转导致日志页变空
    self.Ui.textBrowser_log_main.setOpenLinks(False)
    self.Ui.textBrowser_log_main_2.setOpenLinks(False)
    self.Ui.textBrowser_net_main.setOpenLinks(False)

    def _open_safe_url(url):
        raw = url.toString()
        m = re.match(r"^(https?://[^\s\"'<>]+)", raw)
        target = m.group(1) if m else raw
        webbrowser.open(target)

    self.Ui.textBrowser_log_main.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    self.Ui.textBrowser_log_main_2.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    self.Ui.textBrowser_net_main.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    # endregion

    # region 控件更新
    # 上栏/下栏日志追加不抢滚动条：保持用户当前位置（默认最上方），不自动拉到底
    self.main_logs_show.connect(self._on_main_logs_show)
    self.main_logs_clear.connect(self.Ui.textBrowser_log_main.clear)
    self.req_logs_clear.connect(self.Ui.textBrowser_log_main_2.clear)
    self.main_req_logs_show.connect(self._on_main_req_logs_show)
    self.net_logs_show.connect(self.Ui.textBrowser_net_main.append)
    self.set_javdb_cookie.connect(self.Ui.plainTextEdit_cookie_javdb.setPlainText)
    self.set_javdb_status.connect(self.Ui.label_javdb_cookie_result.setText)
    self.set_fc2ppvdb_status.connect(self.Ui.label_fc2ppvdb_cookie_result.setText)
    self.set_javbus_cookie.connect(self.Ui.plainTextEdit_cookie_javbus.setPlainText)
    self.set_javbus_status.connect(self.Ui.label_javbus_cookie_result.setText)
    self.exec_save_config.connect(self.pushButton_save_config_clicked)
    self.set_pic_pixmap.connect(self.resize_label_and_setpixmap)
    self.set_pic_text.connect(self.Ui.label_poster_size.setText)
    self.change_to_mainpage.connect(self.change_mainpage)  # endregion
    self.request_preview_images.connect(self._on_request_preview_images)

    # region 文本更新
    self.set_label_file_path.connect(self.Ui.label_file_path.setText)
    self.pushButton_start_cap.connect(self.Ui.pushButton_start_cap.setText)
    self.pushButton_start_cap2.connect(self.Ui.pushButton_start_cap2.setText)
    self.pushButton_start_single_file.connect(self.Ui.pushButton_start_single_file.setText)
    self.pushButton_add_sub_for_all_video.connect(self.Ui.pushButton_add_sub_for_all_video.setText)
    self.pushButton_show_pic_actor.connect(self.Ui.pushButton_show_pic_actor.setText)
    self.pushButton_add_actor_info.connect(self.Ui.pushButton_add_actor_info.setText)
    self.pushButton_add_actor_pic.connect(self.Ui.pushButton_add_actor_pic.setText)
    self.pushButton_add_actor_pic_kodi.connect(self.Ui.pushButton_add_actor_pic_kodi.setText)
    self.pushButton_del_actor_folder.connect(self.Ui.pushButton_del_actor_folder.setText)
    self.pushButton_check_and_clean_files.connect(self.Ui.pushButton_check_and_clean_files.setText)
    self.pushButton_move_mp4.connect(self.Ui.pushButton_move_mp4.setText)
    self.pushButton_find_missing_number.connect(self.Ui.pushButton_find_missing_number.setText)
    self.pushButton_cover_backfill_start.connect(self.Ui.pushButton_cover_backfill_start.setText)
    self.pushButton_actor_db_translate.connect(self.Ui.pushButton_actor_db_translate.setText)
    self.pushButton_actor_db_link.connect(self.Ui.pushButton_actor_db_link.setText)
    self.pushButton_actor_db_sync_aliases.connect(self.Ui.pushButton_actor_db_sync_aliases.setText)
    self.pushButton_actor_db_fill_Minnano.connect(self.Ui.pushButton_actor_db_fill_Minnano.setText)
    self.pushButton_actor_db_fill_zh_javdb.connect(self.Ui.pushButton_actor_db_fill_zh_javdb.setText)
    self.pushButton_actor_db_clean_male.connect(self.Ui.pushButton_actor_db_clean_male.setText)
    self.pushButton_actor_db_verify_tmdbid.connect(self.Ui.pushButton_actor_db_verify_tmdbid.setText)
    self.pushButton_actor_db_check.connect(self.Ui.pushButton_actor_db_check.setText)
    self.pushButton_actor_db_update_nfo_tmdbid.connect(self.Ui.pushButton_actor_db_update_nfo_tmdbid.setText)
    self.actor_db_finished.connect(self._on_actor_db_finished)
    self.label_result.connect(self.Ui.label_result.setText)
    # 不直接连 QLabel.setText：状态文字行数会随刮削进度变化（顶部多一行进度），
    # 而收款码块是按文字顶定位的，文本变了必须重排贴底区，否则新行被二维码盖住。
    self.label_show_version.connect(self.set_dock_status_text)  # endregion
    self.version_check_done.connect(self._on_version_check_done)
    self.net_check_done.connect(self._on_net_check_done)
    self.net_check_progress.connect(self._on_net_check_progress)
    self.net_check_item_done.connect(self._on_net_check_item)


def Init_QSystemTrayIcon(self: MyMAinWindow):
    self.tray_icon = QSystemTrayIcon(self)
    self.tray_icon.setIcon(QIcon(resources.icon_ico))
    self.tray_icon.activated.connect(self.tray_icon_click)
    self.tray_icon.setToolTip(f"MDCx {self.localversion}（左键显示/隐藏 | 右键退出）")
    show_action = QAction("显示", self)
    # 托盘菜单只写功能名，不带快捷键提示：Q / Esc 是主窗口级的快捷键
    # （QShortcut(Q) 与 hide_tips_widget_on_escape），提示写在主窗口右键菜单里，
    # 托盘菜单再挂一遍会被 Qt 用制表符对齐成一段空隙（看着像多截空白）。
    hide_action = QAction("隐藏到托盘", self)
    quit_action = QAction("退出 MDCx", self)
    show_action.triggered.connect(self.tray_icon_show)
    hide_action.triggered.connect(self.hide_to_tray)
    quit_action.triggered.connect(self.ready_to_exit)
    tray_menu = QMenu()
    tray_menu.setStyleSheet(build_menu_style(self.dark_mode))
    tray_menu.addAction(show_action)
    tray_menu.addAction(hide_action)
    tray_menu.addSeparator()
    tray_menu.addAction(quit_action)
    self.tray_icon.setContextMenu(tray_menu)
    self.tray_icon.show()
    # self.tray_icon.showMessage(f"MDCx {self.localversion}", u'已启动！欢迎使用!', QIcon(self.icon_ico), 3000)
    # icon的值  0没有图标  1是提示  2是警告  3是错误


def init_QTreeWidget(self: MyMAinWindow):
    # 初始化树状控件
    try:
        movie_path_text = ";".join(str(path) for path in get_movie_path_setting().movie_paths)
        self.set_label_file_path.emit(f"🎈 当前刮削路径: \n {movie_path_text}")  # 主界面右上角显示提示信息
    except Exception:
        signal_qt.show_traceback_log(traceback.format_exc())
    signal_qt.set_main_info()
    Flags.count_claw = 0  # 批量刮削次数
    if self.Ui.pushButton_start_cap.text() != "开始":
        Flags.count_claw = 1  # 批量刮削次数
    else:
        self.label_result.emit(" 刮削中：0 成功：0 失败：0")
    self.Ui.treeWidget_number.clear()
    self.item_succ = QTreeWidgetItem(self.Ui.treeWidget_number)
    self.item_succ.setText(0, "成功")
    self.item_fail = QTreeWidgetItem(self.Ui.treeWidget_number)
    self.item_fail.setText(0, "失败")
    self.Ui.treeWidget_number.expandAll()  # 展开主界面树状内容
