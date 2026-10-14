import re
import traceback
import webbrowser
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QEvent, QPoint, QRect, QSize, QTimer, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QScreen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QListView,
    QMenu,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QToolTip,
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


def _effective_dpr(widget: "QWidget | None" = None) -> float:
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


def _site_status_icon(level: str, widget: "QWidget | None" = None) -> QIcon:
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


def _site_combo_item_tooltip(value: str) -> str:
    """下拉项 tooltip：只留上次检测结果。

    定位说明（有码：有码+素人 / 无码：仅能无码 / 综合：…）已直接拼进选项显示文本，
    按用户要求不再在提示里重复，提示只剩「上次检测：…」；没检测过的站点返回空串。
    """
    entry = _load_check_cache().get(value)
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


def _populate_site_combo(combo: QComboBox, site_values: list[str]) -> None:
    """填充站点下拉框：区域标签与定位说明直接拼入显示文本，检测状态入图标，上次检测结果入 tooltip。"""
    from mdcx.config.models import Website
    from mdcx.crawlers import get_crawler
    from mdcx.manual import ManualConfig

    for value in site_values:
        tag = ManualConfig.SITE_REGION_TAGS.get(value, "")
        cache_entry = _load_check_cache().get(value)
        icon = _site_status_icon(cache_entry.get("status", ""), combo) if cache_entry else QIcon()
        # UserRole 存纯站点值：显示文本=站点名+区域标签+定位说明（说明直接展示，不再只藏 tooltip），
        # 消费方统一经 currentData()/itemData(UserRole) 取纯值
        description = ""
        try:
            crawler_cls = get_crawler(Website(value))
            if crawler_cls is not None and hasattr(crawler_cls, "site_description"):
                description = crawler_cls.site_description() or ""
        except Exception:
            pass
        name = f"{value}（{tag}）" if tag else value
        if description:
            name = f"{name} {description}"
        combo.addItem(icon, name, value)
        url = _resolve_site_url(value)
        combo.setItemData(combo.count() - 1, url, _SITE_URL_ROLE)  # 当前网址：右侧网址列显示+点击跳转
        combo.setItemData(combo.count() - 1, _site_combo_item_tooltip(value), Qt.ItemDataRole.ToolTipRole)
    view = combo.view()
    if view is not None:
        view.setTextElideMode(Qt.TextElideMode.ElideRight)


def refresh_network_check_badges(self: "MyMAinWindow") -> None:
    """检测完成后刷新三个站点下拉框的状态图标与 tooltip（不重排文本，保留当前选中项）。"""
    invalidate_check_cache()
    for combo in (
        self.Ui.comboBox_website_all,
        self.Ui.comboBox_custom_website,
        self.Ui.comboBox_no_proxy_sites,
    ):
        for i in range(combo.count()):
            value = combo.itemData(i, Qt.ItemDataRole.UserRole) or combo.itemText(i).split(" ")[0].split("（")[0].strip()
            if not value:
                continue
            entry = _load_check_cache().get(value)
            combo.setItemIcon(i, _site_status_icon(entry["status"], combo) if entry else QIcon())
            # 显式网址行（official 子站）：保留手工地址，只刷新图标与 tooltip
            url = combo.itemData(i, _SITE_URL_EXPLICIT_ROLE) or _resolve_site_url(value)  # 自定义网址保存后此处同步最新值
            combo.setItemData(i, url, _SITE_URL_ROLE)
            combo.setItemData(i, _site_combo_item_tooltip(value), Qt.ItemDataRole.ToolTipRole)
        _fit_site_url_popup(combo)


_SITE_URL_ROLE = Qt.ItemDataRole.UserRole + 2  # 各站点当前网址：下拉右侧网址列显示，点击跳转浏览器
_SITE_URL_EXPLICIT_ROLE = Qt.ItemDataRole.UserRole + 3  # 手工指定的行网址：刷新徽章时不被重算覆盖
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


# official 无码官网子站行的下拉展示名（仅展示用；抓取落盘的 studio 仍用 spec.studio，
# 见 official_uncensored.py 的 studio 回退值，未列出的站名原样显示）
_OFFICIAL_STUDIO_DISPLAY: dict[str, str] = {
    "Caribbeancom": "加勒比",
    "1Pondo": "一本道",
    "Pacopacomama": "Paco",
}


def _append_official_subsite_rows(combo: QComboBox) -> None:
    """网站设置下拉：把 official 旗下 5 个无码官网拆成独立行（Official·Studio + 各自网址），Official 本行隐藏.

    行 UserRole 仍存 Official（选中走 official 爬虫，各消费端的 Website 防护不受影响）；
    真实网址存显式角色，刷新徽章时不被重算覆盖。
    """
    try:
        from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES
    except Exception:
        return
    cache_entry = _load_check_cache().get("Official")
    icon = _site_status_icon(cache_entry.get("status", ""), combo) if cache_entry else QIcon()
    anchor = -1
    for i in range(combo.count()):
        if (combo.itemData(i, Qt.ItemDataRole.UserRole) or "") == "Official":
            anchor = i
    insert_at = anchor + 1 if anchor >= 0 else combo.count()
    for offset, (name, spec) in enumerate(sorted(UNCENSORED_OFFICIAL_SITES.items())):
        url = spec.base_url.rstrip("/") + "/"
        description = f"无码：{_OFFICIAL_STUDIO_DISPLAY.get(spec.studio, spec.studio)}"
        row = insert_at + offset
        combo.insertItem(row, icon, f"Official·{spec.studio} {description}", "Official")
        combo.setItemData(row, url, _SITE_URL_ROLE)
        combo.setItemData(row, url, _SITE_URL_EXPLICIT_ROLE)
        combo.setItemData(row, _site_combo_item_tooltip("Official"), Qt.ItemDataRole.ToolTipRole)
    # official 本行不显示：只留 5 个子站行（插入位置均在 anchor 之后，anchor 下标仍有效）
    if anchor >= 0:
        combo.removeItem(anchor)


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
            painter.drawText(
                rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text
            )
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
                    view.viewport().setCursor(
                        Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor
                    )
        except Exception:
            pass
        return super().eventFilter(obj, event)


def _event_pos(event) -> QPoint:
    """取事件的控件内坐标：QMouseEvent 等给的是 QPointF（position()），QHelpEvent 只给 QPoint（pos()）。"""
    point = (getattr(event, "position", None) or getattr(event, "pos", None))()
    to_point = getattr(point, "toPoint", None)  # QPointF 才有，QPoint 直接就是坐标
    return to_point() if callable(to_point) else point


def _tip_label() -> QWidget | None:
    """QToolTip 内部复用的那个提示窗（QTipLabel，全进程只有这一个）。

    它每次显示都按当前排版结果自行 `resize()`；Windows 侧首显那次与随后几次排出的高度
    可能不同（同一段「上次检测：…」提示框忽高忽低），所以站点下拉的提示高度由我们自己钉。
    """
    for widget in QApplication.allWidgets():
        if widget.metaObject().className() == "QTipLabel":
            return widget
    return None


class _SiteComboTipFilter(QObject):
    """站点下拉弹窗悬停提示：光标落到哪一行就立刻显示哪一行的 ToolTipRole 文本。

    此前完全交给 Qt 默认链路（平台侧合成 QEvent::ToolTip → `QStyledItemDelegate.helpEvent`
    → `QToolTip`），在「软件设置→网络→网站设置→当前网站」等站点下拉里实测 hover 不出
    提示：弹窗是 Qt::Popup 顶层窗，Windows 侧要停住约 1s 才合成该事件，事件还未必送达
    弹窗 viewport；即便偶发显示，也常是上一行/空白处遗留的旧文本（提示与光标所指行对不
    上）。这里改为自管：viewport 的 MouseMove 直接按 `view.indexAt()` 取光标所在行自己
    弹（行内移动不重弹、换行即换内容，无提示文本则收起），平台侧的 ToolTip 事件也一并
    接管掉，保证同一时刻只有一份提示、且与光标所在行一致；移出列表/弹窗关闭即隐藏。
    """

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo
        self._shown_row: int = -1  # 已显示提示所在行（-1 = 无提示）；行内移动据此跳过重弹
        self._tip_height: int = 0  # 首显时提示窗的高度，之后每次显示都锁成这个高度（0 = 尚未记录）

    def _index_at(self, pos):
        """光标所在行的 index；空白处/无 view 返回 None。"""
        view = self._combo.view()
        if view is None:
            return None
        index = view.indexAt(pos)
        return index if index.isValid() else None

    def _show_tip_for(self, index) -> None:
        """按 index 显示 tooltip；index 为 None 或文本为空则收起提示。"""
        view = self._combo.view()
        if view is None:
            return
        row = index.row() if index is not None else -1
        if row == self._shown_row and row != -1:
            return  # 同一行内移动：不重复弹（重弹会让提示闪一下并重置位置）
        self._shown_row = row
        text = str(index.data(Qt.ItemDataRole.ToolTipRole) or "").strip() if index is not None else ""
        if not text:
            QToolTip.hideText()
            return
        viewport = view.viewport()
        rect = view.visualRect(index)
        # 贴着该行下沿弹出：只有「上次检测：…」一行（定位说明已在显示文本里），鼠标停在本行即持续可见
        QToolTip.showText(viewport.mapToGlobal(rect.bottomLeft()), text, viewport, rect)
        self._sync_tip_label()

    def _sync_tip_label(self, *, allow_defer: bool = True) -> None:
        """把 QToolTip 那个提示窗收拾成稳定的样子：文字恒居中 + 高度按首显钉死。

        QTipLabel 每次显示都按当下排版结果自己 `resize()`，字体刚加载/没加载完会排出不同
        高度，同一段「上次检测：…」的提示框就忽高忽低（用户反馈第 1/2/3 次显示高度不一致）。
        钉上固定高度后 `resize()` 被上下限夹住、视觉高度恒定；取历次最大值是兜住万一某次
        排版更高，不把文字裁掉。文字对齐则钉成水平+垂直居中：QTipLabel 默认只 AlignLeft，
        钉高后多出来的那点空白会把字顶到上边沿（看着就是「飘」），居中后每次显示都稳在同一
        位置；水平居中在提示窗宽度正好等于文字宽度时是无害的。
        """
        label = _tip_label()
        if label is None:
            if allow_defer:
                # 首显这一次提示窗还没挂上控件树，下一轮事件循环再来（趁用户还没移到下一行）
                QTimer.singleShot(0, lambda: self._sync_tip_label(allow_defer=False))
            return
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        pinned = label.minimumHeight()
        if pinned > 0:
            # 临时解除再量：钉死后 sizeHint 会被固定高度夹住，读出来没意义。
            # 解除与复原都在同一轮事件内完成，Qt 本来每次显示也会 resize，看不到闪烁。
            label.setFixedHeight(0)
        natural = label.sizeHint().height()
        if natural <= 0:
            if pinned > 0:
                label.setFixedHeight(pinned)  # 量不出来就把原钉高还回去，别把提示窗压扁
            return
        self._tip_height = max(self._tip_height, natural)  # 首显那次的自然高度为准
        if label.minimumHeight() != self._tip_height or label.maximumHeight() != self._tip_height:
            label.setFixedHeight(self._tip_height)

    def _release_tip_height(self) -> None:
        """解除钉高：QTipLabel 是全进程共用的，不能把固定高度留给应用里其它提示。"""
        label = _tip_label()
        if label is not None and label.minimumHeight() > 0:
            label.setFixedHeight(0)

    def eventFilter(self, obj, event) -> bool:
        try:
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove and not event.buttons():
                # 无按键移动才做提示（拖拽选择过程中不打扰）
                self._show_tip_for(self._index_at(_event_pos(event)))
                return False  # 交给其余过滤器（如网址列的 _SiteUrlClickFilter）继续处理
            if event_type == QEvent.Type.ToolTip:
                self._show_tip_for(self._index_at(_event_pos(event)))
                return True  # 接管：不走 Qt 默认 delegate，避免同一处出现第二份/过期提示
            if event_type in (QEvent.Type.Hide, QEvent.Type.Leave):
                self._shown_row = -1
                QToolTip.hideText()
                self._release_tip_height()
                return False
        except Exception:
            pass
        return super().eventFilter(obj, event)


def _install_site_combo_tips(combo: QComboBox) -> None:
    """给站点下拉框装悬停提示（按光标所在行实时显示 ToolTipRole）。

    必须在 `_setup_combo_boxes` 换过 view 之后调用（过滤器装在 view.viewport() 上）。
    """
    view = combo.view()
    if view is None or getattr(combo, "_site_tip_filter_installed", False) is True:
        return
    view.viewport().setMouseTracking(True)  # 无按键也要有 MouseMove，才能定位光标所在行
    view.viewport().installEventFilter(_SiteComboTipFilter(combo))
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


def Init_Ui(self: "MyMAinWindow"):
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
    # KeepAspectRatio 缩放好的 pixmap 再拉伸铺满整个框（正常/分离/视频/更新/读取五种
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
    self.Ui.pushButton_tips_separate_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_separate_mode.setToolTip("""<html><head/><body><p><b>分离模式：</b><br/>1）适合海报墙用户。分离模式将联网刮削视频字段信息，并执行翻译字段信息，移动和重命名视频文件及文件夹，下载图片、剧照、预告片，添加字幕、4K水印等一系列自动化操作，视频与元数据将分开存放<br/>2）刮削目录请在「设置→刮削目录」-「视频刮削目录」中设置<br/>3）刮削网站请在「设置→刮削网站」中设置。部分网站需要代理访问，可在「设置→网络」中设置代理和走代理网站。你可以点击左侧的「检测网络」查看网络连通性<br/>\
        4）字段翻译请在「设置→翻译」中设置<br/>5）图片、剧照、预告片请在「设置→下载」中设置<br/>6）视频文件命名请在「设置→命名」中设置<br/>7）如果刮削后不需要重命名，请在下面的「刮削成功后重命名文件」设置为「关」<br/>8）如果刮削后不需要移动文件，请在下面的「刮削成功后移动文件」设置为「关」<br/>9）如果想自动刮削，请在「设置→高级」中勾选「自动刮削」<br/>10）其他设置项和功能玩法可自行研究</p></body></html>""")
    self.Ui.pushButton_tips_sort_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_sort_mode.setToolTip(
        """<html><head/><body><p><b>视频模式：</b><br/>1，适合不需要图片墙的情况。视频模式将联网刮削视频相关字段信息，然后根据「设置→命名」中设置的命名规则重命名、移动视频文件<br/>2，仅整理视频，不会下载和重命名图片、nfo 文件<br/>3，如果是海报墙用户，请不要使用视频模式。</p></body></html>"""
    )
    self.Ui.pushButton_tips_update_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_update_mode.setToolTip("""<html><head/><body><p><b>更新模式：</b><br/>1，适合视频已经归类好的情况。更新模式将在不改动文件位置结构的前提下重新刮削更新一些信息<br/>2，更新规则在下面的「更新模式规则中」定义：<br/>-1）如果只更新视频文件名，请选择「只更新C」，视频文件名命名规则请到「设置→命名」中设置<br/>-2）如果要更新视频所在的目录名，请选择「更新B和C」；如果要更新视频目录的上层目录，请勾选「同时更新A目录」<br/>-3），如果要在视频目录为视频再创建一级目录，请选择「创建D目录」<br/>\
        3，更新模式将会对「待刮削目录」下的所有视频进行联网刮削和更新。<br/>4，当有部分内容没有更新成功，下次想只刮削这些内容时，请选择「读取模式」，同时勾选「不存在 nfo 时，刮削并执行更新模式规则」，它将查询并读取所有视频本地的 nfo 文件（不联网），当没有 nfo 文件时，则会自动进行联网刮削<br/>5，当部分内容确实无法刮削时，你可以到「软件日志」页面，点击「失败」按钮，点击左下角的保存按钮，就可以把失败列表保存到本地，然后可以手动查看和处理这些视频信息。</p></body></html>""")
    self.Ui.pushButton_tips_read_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_read_mode.setToolTip("""<html><head/><body><p><b>读取模式：</b><br/>\
        1，读取模式通过读取本地的 nfo 文件中的字段信息，可以无需联网，实现查看或更新视频命名等操作<br/>\
        2，如果仅想查看和检查已刮削的视频信息和图片是否存在问题，可以：<br/>\
        -1）不勾选「本地刮削成功的文件，重新整理分类」；<br/>\
        -2）不勾选「本地自取刮削失败的文件，重新刮削」。<br/>\
        3，如果想要快速重新整理分类(不联网)，可以：<br/>\
        -1）勾选「本地刮削成功的文件，重新整理分类」；<br/>\
        -2）在下面的「更新模式规则」中自定义更新规则。<br/>\
        软件将按照「更新模式规则」，和「设置→命名」中的设置项，进行重命名等操作。<br/>\
        4，如果仅想更新 nfo 文件（包括补全演员 tmdbid、emby 标题、tag、翻译等），可以：<br/>\
        -1）勾选「允许更新 nfo 文件」。<br/>\
        软件将按照「设置→刮削模式」-「Emby视频标题」、「设置→翻译」、「设置→NFO」等的设置项，利用本地 nfo 更新 nfo 信息。<br/>\
        5，如果想要重新下载图片等文件（需联网），可以：<br/>\
        -1）勾选「重新下载图片等文件」。<br/>\
        软件将按照「设置→下载」中的设置项，进行下载、保留等操作。<br/>\
        6，文件移动、重命名、创建软硬链接等操作，由「设置→刮削模式」中的对应开关独立控制，不再依赖读取模式选项。</p></body></html>""")
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
    _append_official_subsite_rows(self.Ui.comboBox_custom_website)  # official 拆 5 个无码官网子行
    # 初始化使用代理网站下拉框
    self.Ui.comboBox_no_proxy_sites.clear()
    self.Ui.comboBox_no_proxy_sites.addItem("选择网站...", "")
    _populate_site_combo(self.Ui.comboBox_no_proxy_sites, sorted(supported_websites))
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


def _setup_combo_boxes(self: "MyMAinWindow") -> None:
    for combo_box in self.findChildren(QComboBox):
        view = QListView(combo_box)
        view.setUniformItemSizes(True)
        view.setSpacing(0)
        view.setMaximumHeight(322)
        combo_box.setMaxVisibleItems(10)
        combo_box.setView(view)
        combo_view = combo_box.view()
        assert combo_view is not None
        combo_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        combo_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        combo_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)


def Init_Singal(self: "MyMAinWindow"):
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
        (self.Ui.gridLayout_2, range(9)),
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
    # 复用行第二复选框与 STRM 行第二复选框同 x 上下严格对齐：由主窗口
    # _sync_reuse_meta_gap_align 按实测差值闭环收敛（sizeHint 在 show 前后会变，
    # 初始化公式一次算不准），此处不预设 gap 宽度。
    # 复用/覆盖元数据互斥：只允许同时选中一个（界面层），运行时覆盖优先兜底。
    self.Ui.checkBox_separate_reuse_meta.toggled.connect(self.checkBox_separate_reuse_meta_changed)
    self.Ui.checkBox_separate_overwrite_meta.toggled.connect(self.checkBox_separate_overwrite_meta_changed)
    # STRM：生成是覆盖的前提，未勾选生成时覆盖框置灰（不影响其勾选值）
    self.Ui.checkBox_separate_generate_strm.toggled.connect(self.checkBox_separate_generate_strm_changed)
    for _lbl in (
        self.Ui.label_11,
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


def Init_QSystemTrayIcon(self: "MyMAinWindow"):
    self.tray_icon = QSystemTrayIcon(self)
    self.tray_icon.setIcon(QIcon(resources.icon_ico))
    self.tray_icon.activated.connect(self.tray_icon_click)
    self.tray_icon.setToolTip(f"MDCx {self.localversion}（左键显示/隐藏 | 右键退出）")
    show_action = QAction("显示", self)
    hide_action = QAction("隐藏\tQ", self)
    quit_action = QAction("退出 MDCx", self)
    show_action.triggered.connect(self.tray_icon_show)
    hide_action.triggered.connect(self.hide)
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


def init_QTreeWidget(self: "MyMAinWindow"):
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
