# mypy: ignore-errors
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.config.models import (
    SCRAPING_TYPE_SITE_FIELDS,
    TYPE_DEFAULT_SITES,
    FieldPriorityConfig,
    expand_site_groups,
    filter_poster_default_sites,
    site_group_of,
    str_to_list,
)
from mdcx.crawlers import get_registered_crawler_site_values
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.signals import signal_qt
from mdcx.utils.window_center import CenterOnFirstShowMixin

from .style import build_scrollbar_style, get_theme_tokens

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


@dataclass
class TypeWebsiteUi:
    scraping_type: FixedScrapingType
    title: str
    line_edit: QLineEdit
    row: int
    edit_button: QPushButton | None = None
    priority_button: QPushButton | None = None


TYPE_TITLES = {
    FixedScrapingType.YOUMA: "有码",
    FixedScrapingType.WUMA: "无码",
    FixedScrapingType.SUREN: "素人",
    FixedScrapingType.FC2: "FC2",
    FixedScrapingType.OUMEI: "欧美",
    FixedScrapingType.GUOCHAN: "国产",
    FixedScrapingType.DONGMAN: "动漫里番",
}


FIELD_TITLES = {
    CrawlerResultFields.TITLE: "标题",
    CrawlerResultFields.ORIGINALTITLE: "原标题",
    CrawlerResultFields.OUTLINE: "简介",
    CrawlerResultFields.ORIGINALPLOT: "原简介",
    CrawlerResultFields.ACTORS: "演员",
    CrawlerResultFields.ALL_ACTORS: "全部演员",
    CrawlerResultFields.THUMB: "缩略图",
    CrawlerResultFields.POSTER: "海报",
    CrawlerResultFields.EXTRAFANART: "剧照",
    CrawlerResultFields.TAGS: "标签",
    CrawlerResultFields.RELEASE: "发行日期",
    CrawlerResultFields.RUNTIME: "时长",
    CrawlerResultFields.SCORE: "评分",
    CrawlerResultFields.DIRECTORS: "导演",
    CrawlerResultFields.SERIES: "系列",
    CrawlerResultFields.STUDIO: "片商",
    CrawlerResultFields.PUBLISHER: "发行商",
    CrawlerResultFields.TRAILER: "预告片",
    CrawlerResultFields.WANTED: "想看人数",
}

FIELD_PRIORITY_FIELDS = (
    CrawlerResultFields.TITLE,
    CrawlerResultFields.ORIGINALTITLE,
    CrawlerResultFields.OUTLINE,
    CrawlerResultFields.ORIGINALPLOT,
    CrawlerResultFields.ACTORS,
    CrawlerResultFields.ALL_ACTORS,
    CrawlerResultFields.THUMB,
    CrawlerResultFields.POSTER,
    CrawlerResultFields.EXTRAFANART,
    CrawlerResultFields.TRAILER,
    CrawlerResultFields.TAGS,
    CrawlerResultFields.RELEASE,
    CrawlerResultFields.RUNTIME,
    CrawlerResultFields.SCORE,
    CrawlerResultFields.DIRECTORS,
    CrawlerResultFields.SERIES,
    CrawlerResultFields.STUDIO,
    CrawlerResultFields.PUBLISHER,
    CrawlerResultFields.WANTED,
)


def _sync_field_sites_after_type_sites_changed(
    current_sites: list[Website],
    previous_type_sites: list[Website],
    new_type_sites: list[Website],
) -> list[Website]:
    if not current_sites:
        return []
    new_type_set = set(new_type_sites)
    kept_sites = [site for site in current_sites if site in new_type_set]
    previous_type_set = set(previous_type_sites)
    added_sites = [site for site in new_type_sites if site not in previous_type_set and site not in kept_sites]
    return kept_sites + added_sites


def _parse_sites(text: str) -> list[Website]:
    return list(dict.fromkeys(Website(site) for site in str_to_list(text, ",") if site in Website))


def _sites_text(sites: list[Website]) -> str:
    return ",".join(site.value for site in sites)


class PaletteEntry(NamedTuple):
    """「可用网站」候选区的一行：要么是分组标题，要么是站点本身。"""

    title: str  # 分组标题（如「有码」）；站点行为空串
    site: Website | None  # 分组行为 None；站点行为该站点


# 候选区的分组顺序：与 TYPE_TITLES 的声明序一致（不含动漫里番——那一组只有 Getchu 等
# 零星几个站，单列一个标题反而更碎，用户实际是按前六组挑网站源）。
PALETTE_GROUP_TYPES: tuple[FixedScrapingType, ...] = (
    FixedScrapingType.YOUMA,
    FixedScrapingType.WUMA,
    FixedScrapingType.SUREN,
    FixedScrapingType.FC2,
    FixedScrapingType.OUMEI,
    FixedScrapingType.GUOCHAN,
)

# 落在六组之外、又确实已注册爬虫的站点（目前只有 MyWife）统一归到这里。
OTHER_PALETTE_GROUP_TITLE = "其他"


def grouped_palette_entries(sites: Iterable[Website]) -> list[PaletteEntry]:
    """把候选站点按有码/无码/素人/FC2/欧美/国产分组成带标题的行序列。

    组内顺序 = TYPE_DEFAULT_SITES 里该组的默认名单顺序（优先级从高到低），不重排。
    一个站点可同属多组，会在每个组里各出现一次——它确实是这几个类型的可用来源，
    而「全部添加」用的是 self._all_sites 原序，不会因此重复添加。
    没落进任何组的站点（如 MyWife）按传入次序收在「其他」里，保证一个都不丢。
    """
    available = list(dict.fromkeys(sites))
    available_set = set(available)
    entries: list[PaletteEntry] = []
    placed: set[Website] = set()
    for scraping_type in PALETTE_GROUP_TYPES:
        group = [site for site in TYPE_DEFAULT_SITES.get(scraping_type, ()) if site in available_set]
        if not group:
            # 该类型在本机没有已注册爬虫的站点时不留空标题，否则会出现一个没有内容的分组
            continue
        entries.append(PaletteEntry(TYPE_TITLES[scraping_type], None))
        entries.extend(PaletteEntry("", site) for site in group)
        placed.update(group)
    rest = [site for site in available if site not in placed]
    if rest:
        entries.append(PaletteEntry(OTHER_PALETTE_GROUP_TITLE, None))
        entries.extend(PaletteEntry("", site) for site in rest)
    return entries


def _site_priority_colors(dark: bool) -> dict[str, str]:
    tokens = get_theme_tokens(dark)
    if dark:
        return {
            "window": tokens["window"],
            "surface": "#18222D",
            "surface_muted": "#202B37",
            "surface_hover": "#263442",
            "surface_pressed": "#303D4B",
            "text": tokens["text"],
            "text_muted": tokens["text_muted"],
            "border": tokens["border"],
            "border_active": "#657384",
        }
    return {
        "window": tokens["window"],
        "surface": "#FFFFFF",
        "surface_muted": "#F8FAFC",
        "surface_hover": "#F3F4F6",
        "surface_pressed": "#E5E7EB",
        "text": tokens["text"],
        "text_muted": tokens["text_muted"],
        "border": tokens["border"],
        "border_active": "#9CA3AF",
    }


def _list_sites(list_widget: QListWidget) -> list[Website]:
    """列表里的站点，按行序去重。

    候选区按类型分组后，同一站点会因同属多个组而在多行各出现一次（DMM 同时落在
    有码和素人）。去重让「这张列表有哪些站点」只有一个答案——复制、拖拽、移除、
    启用列表的快照全都拿它做依据，不会因为站点重复出现而多带一次。
    """
    return list(
        dict.fromkeys(
            Website(item.data(Qt.ItemDataRole.UserRole))
            for row in range(list_widget.count())
            if (item := list_widget.item(row)) is not None and item.data(Qt.ItemDataRole.UserRole) in Website
        )
    )


def _selected_sites(list_widget: QListWidget) -> list[Website]:
    items = list_widget.selectedItems()
    if not items and list_widget.currentItem():
        items = [list_widget.currentItem()]
    return [
        Website(item.data(Qt.ItemDataRole.UserRole)) for item in items if item.data(Qt.ItemDataRole.UserRole) in Website
    ]


def _make_site_item(site: Website) -> QListWidgetItem:
    item = QListWidgetItem(site.value)
    item.setData(Qt.ItemDataRole.UserRole, site.value)
    item.setToolTip("\n".join(_site_tooltip_lines(site)) or site.value)
    item.setFlags(
        item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    )
    return item


# 分组标题行不带 UserRole（_list_sites / _selected_sites 靠 UserRole 过滤站点行，
# 自然把标题行排除在外），这里只用一个额外的角色把「这一行是标题」标出来，
# 好让 SiteGroupDelegate 认得它并改画成章节标签。
SITE_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1


def _make_group_item(title: str) -> QListWidgetItem:
    item = QListWidgetItem(f"【{title}】")
    item.setData(SITE_GROUP_ROLE, title)
    item.setToolTip(f"{title}类型网站；本组按优先级从高到低排列")
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return item


def _is_group_item(item: QListWidgetItem | None) -> bool:
    return item is not None and item.data(SITE_GROUP_ROLE) is not None


def _is_site_item(item: QListWidgetItem | None) -> bool:
    """是否站点行。分组标题行没有 UserRole，靠它把两者分开。"""
    return item is not None and item.data(Qt.ItemDataRole.UserRole) in Website


def _site_tooltip_lines(site: Website) -> list[str]:
    """站点项的悬停提示：定位说明 + 联动组成员（说明加入一个会带上哪些）。"""
    lines: list[str] = []
    if description := _site_description(site):
        lines.append(description)
    if group := site_group_of(site):
        lines.append("联动组（加入其一即默认加入全组）：" + "、".join(member.value for member in group))
    return lines


def _site_description(site: Website) -> str:
    """获取站点定位说明（爬虫类 site_description），失败返回空串。"""
    try:
        from mdcx.crawlers import get_crawler

        crawler_cls = get_crawler(site)
        if crawler_cls is not None and hasattr(crawler_cls, "site_description"):
            return crawler_cls.site_description()
    except Exception:
        pass
    return ""


def _setup_site_list(list_widget: QListWidget, sites: Iterable[Website], *, grouped: bool = False) -> None:
    """把 sites 铺进列表。grouped=True 时先按六个类型插入分组标题行。

    默认（grouped=False）保持传入的原序——「启用网站」和各字段名单的原序就是用户的
    优先级序列，任何排序都不能掺进来；候选区才用 grouped=True。
    """
    list_widget.clear()
    entries: Iterable[PaletteEntry]
    if grouped:
        entries = grouped_palette_entries(sites)
    else:
        entries = (PaletteEntry("", site) for site in sites)
    for entry in entries:
        list_widget.addItem(_make_group_item(entry.title) if entry.site is None else _make_site_item(entry.site))


def _set_site_summary(line_edit: QLineEdit) -> None:
    sites = _parse_sites(line_edit.text())
    line_edit.setText(_sites_text(sites))
    line_edit.setToolTip(" -> ".join(site.value for site in sites))
    line_edit.setCursorPosition(0)


def _style_config_line_edit(line_edit: QLineEdit, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    line_edit.setReadOnly(True)
    line_edit.setCursorPosition(0)
    line_edit.setToolTip(line_edit.text())
    line_edit.setStyleSheet(
        f"""
        QLineEdit {{
            font: "Courier";
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 8px;
            padding: 3px 8px;
            background: {colors["surface"]};
        }}
        """
    )


def _style_site_list(list_widget: QListWidget, min_height: int, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    list_widget.setMinimumHeight(min_height)
    list_widget.setStyleSheet(
        f"""
        QListWidget {{
            color: {colors["text"]};
            selection-color: {colors["text"]};
            selection-background-color: {colors["surface_pressed"]};
            border: 1px solid {colors["border"]};
            border-radius: 8px;
            padding: 5px;
            background: {colors["surface"]};
        }}
        QListWidget::item {{
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 7px;
            padding: 5px 9px;
            margin: 3px;
            background: {colors["surface_muted"]};
        }}
        QListWidget::item:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_hover"]};
        }}
        QListWidget::item:selected,
        QListWidget::item:selected:active,
        QListWidget::item:selected:!active,
        QListWidget::item:selected:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_pressed"]};
        }}
        """
    )
    # 右键：点在某个站点上复制该站点，点在空白处（或分组标题上）复制整张列表。
    # 复制出的文本用逗号分隔，和设置页输入框里的格式一致，粘回去就能被 _parse_sites 认出来。
    list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    list_widget.customContextMenuRequested.connect(partial(_site_list_context_menu, list_widget))


def _copy_to_clipboard(text: str, message: str) -> None:
    QApplication.clipboard().setText(text)
    signal_qt.show_log_text(f"✅ {message}已复制到剪贴板")


def _site_list_context_menu(list_widget: QListWidget, pos) -> None:
    """站点列表的右键菜单：复制单个站点 / 复制整张列表。"""
    item = list_widget.itemAt(pos)
    site_value = item.data(Qt.ItemDataRole.UserRole) if _is_site_item(item) else None
    sites = _list_sites(list_widget)
    if site_value is None and not sites:
        return

    menu = QMenu(list_widget)
    site_action = menu.addAction(f"复制站点：{site_value}") if site_value is not None else None
    if site_action is not None:
        menu.addSeparator()
    list_action = menu.addAction(f"复制列表（{len(sites)} 个站点）")

    if (chosen := menu.exec(list_widget.viewport().mapToGlobal(pos))) is None:
        return
    if site_action is not None and chosen is site_action:
        _copy_to_clipboard(str(site_value), f"站点「{site_value}」")
        return
    if chosen is list_action:
        _copy_to_clipboard(_sites_text(sites), f"{len(sites)} 个站点的列表")


def _style_dialog(dialog: QDialog, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    dialog.setStyleSheet(
        f"""
        QDialog {{
            color: {colors["text"]};
            background: {colors["window"]};
        }}
        QScrollArea {{
            border: 0;
            background: {colors["window"]};
        }}
        {build_scrollbar_style(dark)}
        """
    )


def _localize_dialog_buttons(buttons: QDialogButtonBox) -> None:
    if ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok):
        ok_button.setText("保存")
    if cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel):
        cancel_button.setText("取消")


class SiteGroupDelegate(QStyledItemDelegate):
    """把分组标题行画成章节标签：加粗、accent 边框、压深的底色、比站点略高。

    标题行不能只靠 item 的 FontRole 区分——样式表里 `QListWidget::item { color: … }`
    会盖掉 delegate 设的前景色，只有 font 因为没被样式表声明才留得住，太脆弱；
    背景更是完全由样式表的 `background` 说了算。所以标题行干脆不调 super().paint()，
    整块自己画，样式表一点都插不上手。底色取 surface_pressed（比站点的 surface_muted
    明显更深一档），隔着两行也能一眼看出「这里换了一个组」。
    """

    def __init__(self, colors: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self._colors = colors

    def paint(self, painter: QPainter, option, index) -> None:
        if not index.data(SITE_GROUP_ROLE):
            super().paint(painter, option, index)
            return
        rect = option.rect.adjusted(2, 2, -2, -2)
        title = str(index.data(Qt.ItemDataRole.DisplayRole))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self._colors["border_active"]), 1))
        painter.setBrush(QColor(self._colors["surface_pressed"]))
        painter.drawRoundedRect(rect, 7, 7)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(self._colors["text"]))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        if index.data(SITE_GROUP_ROLE):
            # 标题是章节分隔，给它多几像素高度，扫视时能一眼分出「换了一个组」
            hint.setHeight(hint.height() + 6)
        return hint


class SitePaletteList(QListWidget):
    def __init__(
        self,
        sites: list[Website],
        parent: QWidget | None = None,
        *,
        removable_source=None,
        dark: bool = False,
        grouped: bool = False,
    ):
        super().__init__(parent)
        self._removable_source = removable_source
        self.on_removed = None
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        _style_site_list(self, 150, dark)
        # grouped：是否按类型插入分组标题行。_setup_site_list 之后每次重建都要带着这个标志，
        # 否则刷新一次分组就没了，故存成公开属性给调用方原样传回去。
        self.grouped = grouped
        if grouped:
            self.setItemDelegate(SiteGroupDelegate(_site_priority_colors(dark), self))
        _setup_site_list(self, sites, grouped=grouped)

    def _removable_drop_source(self, source) -> QListWidget | None:
        if self._removable_source is not None:
            return self._removable_source if source is self._removable_source else None
        return source if isinstance(source, PrioritySiteList) else None

    def dragEnterEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        if self._removable_drop_source(event.source()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        if self._removable_drop_source(event.source()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        removable_source = self._removable_drop_source(event.source())
        if removable_source is not None:
            self.remove_sites_from(
                removable_source,
                set(getattr(removable_source, "drag_sites", []) or _selected_sites(removable_source)),
            )
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def remove_sites_from(self, source_list: QListWidget, sites: set[Website]) -> None:
        """从启用列表里摘掉 sites（拖回「可用网站」= 移除）。

        按旧规则只删 sites 里那几个站点，**不连带同组站点**——移动才整组同行，
        移除仍是一次一个，否则用户永远无法只用组内的一个通道。
        """
        if not sites and source_list.currentItem() is not None:
            site_value = source_list.currentItem().data(Qt.ItemDataRole.UserRole)
            sites = {Website(site_value)} if site_value in Website else set()
        _setup_site_list(source_list, [site for site in _list_sites(source_list) if site not in sites])
        if self.on_removed is not None:
            self.on_removed()


class PrioritySiteList(QListWidget):
    def __init__(
        self,
        allowed_sites: list[Website],
        height: int = 74,
        parent: QWidget | None = None,
        dark: bool = False,
        auto_group: bool = False,
    ):
        super().__init__(parent)
        self._allowed_sites = list(dict.fromkeys(allowed_sites))
        # auto_group：新增站点时按 SITE_GROUPS 补齐同组站点（仅「编辑网站」对话框开启，
        # 「字段优先级」对话框里的每字段名单仍完全由用户手动指定）
        self._auto_group = auto_group
        self.drag_sites: list[Website] = []
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFixedHeight(height)
        _style_site_list(self, height, dark)

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), QListWidget):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if isinstance(event.source(), QListWidget):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        source = event.source()
        if isinstance(source, QListWidget) and source is not self:
            sites = _selected_sites(source)
            self._insert_sites(sites, self._drop_row(event))
            event.acceptProposedAction()
            return
        if self._auto_group:
            # 启用列表内部的拖动重排：交给自实现而非 Qt 默认移动，好让整组一起挪。
            # 默认实现只搬被拖的那一个站点，会把同组站点拆散、破坏它们的相对优先次序。
            self._move_sites(self._drop_row(event))
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.normalize()

    def _move_sites(self, row: int) -> None:
        """在启用列表内部把被拖动的站点（auto_group 开启时含整组）挪到 row 行之前。"""
        original = _list_sites(self)
        present = set(original)
        # 只认当前列表里真实存在的站点：drag_sites 是上次拖拽的快照，取交集可挡住陈旧值
        moved = [site for site in (self.drag_sites or _selected_sites(self)) if site in present]
        if not moved:
            return
        if self._auto_group:
            # 只补齐「已经在列表里」的同组站点：移动是重排，不能凭空把未启用的站点加进来
            moved = expand_site_groups(moved, available=present)
        # 整块按其在列表中的原有次序排列：移动是「把这一块整体挪走」，
        # 若改成「被拖的在前、其余按组声明序补在后面」，就会顺带改掉块内站点的相对优先级。
        order = {site: index for index, site in enumerate(original)}
        moved.sort(key=lambda site: order[site])
        moved_set = set(moved)
        # 落点行号取自移除前的坐标系；向下移动时要扣掉落在落点之前的那些被移动项，
        # 否则整组会多跳过同样数量的行、落点比指针所指的位置偏后。
        dropped_before = sum(1 for site in original[:row] if site in moved_set)
        current = [site for site in original if site not in moved_set]
        row = max(0, min(row - dropped_before, len(current)))
        _setup_site_list(self, current[:row] + moved + current[row:])
        # 保留被移动项的选中态，便于用户接着拖下一次（_setup_site_list 会重建列表）
        self.clearSelection()
        for list_row in range(self.count()):
            item = self.item(list_row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in moved_set:
                item.setSelected(True)

    def mimeData(self, items: list[QListWidgetItem]):
        self.drag_sites = _selected_sites(self)
        return super().mimeData(items)

    def normalize(self) -> None:
        allowed_set = set(self._allowed_sites)
        _setup_site_list(self, [site for site in _list_sites(self) if site in allowed_set])

    def _drop_row(self, event) -> int:
        try:
            row = self.indexAt(event.position().toPoint()).row()
        except AttributeError:
            row = self.indexAt(event.pos()).row()
        return self.count() if row < 0 else row

    def _insert_sites(self, sites: list[Website], row: int) -> None:
        allowed_set = set(self._allowed_sites)
        inserted = [site for site in sites if site in allowed_set]
        if not inserted:
            return
        if self._auto_group:
            # 拖拽加入与「添加选中」保持一致：组内任一站点加入即补齐同组其余站点
            inserted = expand_site_groups(inserted, available=allowed_set)
        current = [site for site in _list_sites(self) if site not in inserted]
        row = max(0, min(row, len(current)))
        _setup_site_list(self, current[:row] + inserted + current[row:])


class SiteListEditorDialog(CenterOnFirstShowMixin, QDialog):
    def __init__(
        self, title: str, selected_sites: list[Website], all_sites: list[Website], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 640)
        self._dark = bool(getattr(parent, "dark_mode", False))
        _style_dialog(self, self._dark)
        self._all_sites = list(dict.fromkeys(all_sites))
        self._selected_sites = list(dict.fromkeys(selected_sites))
        # 可用网站（网址源）按有码/无码/素人/FC2/欧美/国产分组展示，组内用该类型默认名单
        # 的优先级次序（见 grouped_palette_entries）。_all_sites 的原序仍然保留着：
        # 它是「全部添加」写入启用列表的顺序，也是拖拽插入时的落点参照，都属于用户
        # 自定的优先级序列，不受这里的分组影响。
        self._palette_sites = self._all_sites

        layout = QVBoxLayout(self)

        self.selected_list = PrioritySiteList(self._all_sites, 168, self, self._dark, auto_group=True)
        self.available_list = SitePaletteList(
            self._palette_sites, self, removable_source=self.selected_list, dark=self._dark, grouped=True
        )
        self.available_list.on_removed = self._sync_selected_from_list

        layout.addWidget(self._build_panel("可用网站（按类型分组）", self.available_list))
        layout.addWidget(self._build_panel("启用网站（从左到右优先级递减）", self.selected_list), 1)

        group_hint = QLabel("联动组：加入组内任意一个站点即自动加入组内其余站点，加入后可在「启用网站」中手动移除")
        group_hint.setWordWrap(True)
        group_hint.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text_muted']};")
        layout.addWidget(group_hint)

        copy_hint = QLabel("右键点击：站点上复制该站点、空白处复制整张列表（逗号分隔，可直接粘回上方输入框）")
        copy_hint.setWordWrap(True)
        copy_hint.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text_muted']};")
        layout.addWidget(copy_hint)

        actions = QHBoxLayout()
        add_button = QPushButton("添加选中")
        remove_button = QPushButton("移除选中")
        add_all_button = QPushButton("全部添加")
        clear_button = QPushButton("清空")
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addWidget(add_all_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        for button in (add_button, remove_button, add_all_button, clear_button):
            _style_inline_button(button, self._dark)

        add_button.clicked.connect(self._add_selected)
        remove_button.clicked.connect(self._remove_selected)
        add_all_button.clicked.connect(self._add_all)
        clear_button.clicked.connect(self._clear_selected)
        self.available_list.itemDoubleClicked.connect(self._on_available_double_clicked)
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for button in buttons.buttons():
            _style_inline_button(button, self._dark)

        self._refresh_lists()

    def selected_sites(self) -> list[Website]:
        return _list_sites(self.selected_list)

    def _sync_selected_from_list(self) -> None:
        self._selected_sites = self.selected_sites()

    def _build_panel(self, title: str, list_widget: QListWidget) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        label = QLabel(title)
        label.setStyleSheet(f"font-weight: bold; color: {get_theme_tokens(self._dark)['text']};")
        layout.addWidget(label)
        layout.addWidget(list_widget)
        return panel

    def _on_available_double_clicked(self, item) -> None:
        # 双击分组标题不做任何事：标题行不可选中，若照旧调 _add_selected，
        # 会把「上一次选中残留」当成双击结果顺带加进去。
        if _is_site_item(item):
            self._add_selected()

    def _refresh_lists(self) -> None:
        _setup_site_list(self.available_list, self._palette_sites, grouped=self.available_list.grouped)
        _setup_site_list(self.selected_list, self._selected_sites)

    def _add_selected(self) -> None:
        current = self.selected_sites()
        self._selected_sites = current
        added = [site for site in _selected_sites(self.available_list) if site not in current]
        # 只让「本次新加入」的站点触发组联动：用户手动移除过的同组站点不会借机复活，
        # 而新加入组内任一站点时同组其余站点默认一并加入（随后可在上方列表手动移除）
        triggered = expand_site_groups(added, available=self._all_sites)
        self._selected_sites = current + [site for site in triggered if site not in current]
        self._refresh_lists()

    def _remove_selected(self) -> None:
        selected = set(_selected_sites(self.selected_list))
        self._selected_sites = [site for site in self.selected_sites() if site not in selected]
        self._refresh_lists()

    def _add_all(self) -> None:
        self._selected_sites = list(self._all_sites)
        self._refresh_lists()

    def _clear_selected(self) -> None:
        self._selected_sites = []
        self._refresh_lists()


class FieldPriorityDialog(CenterOnFirstShowMixin, QDialog):
    def __init__(
        self,
        title: str,
        scraping_type: FixedScrapingType,
        type_sites: list[Website],
        field_configs: dict[CrawlerResultFields, FieldPriorityConfig],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 680)
        self._dark = bool(getattr(parent, "dark_mode", False))
        _style_dialog(self, self._dark)
        self._scraping_type = scraping_type
        self._type_sites = list(dict.fromkeys(type_sites))
        self._field_configs = field_configs
        self._field_lists: dict[CrawlerResultFields, QListWidget] = {}
        self._skip_checks: dict[CrawlerResultFields, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_palette_panel())

        quick_actions = QHBoxLayout()
        reset_button = QPushButton("全部使用类型顺序")
        keep_button = QPushButton("只保留已启用网站")
        clear_button = QPushButton("清空全部字段")
        quick_actions.addWidget(reset_button)
        quick_actions.addWidget(keep_button)
        quick_actions.addWidget(clear_button)
        quick_actions.addStretch(1)
        layout.addLayout(quick_actions)
        for button in (reset_button, keep_button, clear_button):
            _style_inline_button(button, self._dark)

        reset_button.clicked.connect(self._reset_all)
        keep_button.clicked.connect(self._keep_enabled_only)
        clear_button.clicked.connect(self._clear_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        for row, field in enumerate(FIELD_PRIORITY_FIELDS):
            label = QLabel(FIELD_TITLES.get(field, field.value))
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setMinimumWidth(88)
            label.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text']};")
            list_widget = PrioritySiteList(self._type_sites, 58, self, self._dark)
            existing_config = self._field_configs.get(field, FieldPriorityConfig())
            configured = existing_config.site_prority
            sites = [site for site in configured if site in self._type_sites]
            _setup_site_list(list_widget, sites)
            remove_button = QPushButton("移除")
            reset_field_button = QPushButton("重置")
            _style_inline_button(remove_button, self._dark)
            _style_inline_button(reset_field_button, self._dark)
            remove_button.clicked.connect(partial(self._remove_from_field, field))
            reset_field_button.clicked.connect(partial(self._reset_field, field))

            skip_check = QCheckBox("跳过")
            skip_check.setToolTip("勾选后该字段不从任何来源抓取")
            skip_check.setChecked(existing_config.skip)
            _style_inline_button(skip_check, self._dark)
            skip_check.toggled.connect(partial(self._on_skip_toggled, field))

            button_layout = QHBoxLayout()
            button_layout.addWidget(remove_button)
            button_layout.addWidget(reset_field_button)
            button_layout.addWidget(skip_check)

            grid.addWidget(label, row, 0)
            grid.addWidget(list_widget, row, 1)
            grid.addLayout(button_layout, row, 2)
            self._field_lists[field] = list_widget
            self._skip_checks[field] = skip_check

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for button in buttons.buttons():
            _style_inline_button(button, self._dark)

    def field_configs(self) -> dict[CrawlerResultFields, FieldPriorityConfig]:
        return {
            field: FieldPriorityConfig(
                site_prority=_list_sites(list_widget),
                skip=self._skip_checks.get(field, QCheckBox()).isChecked(),
            )
            for field, list_widget in self._field_lists.items()
        }

    def _on_skip_toggled(self, field: CrawlerResultFields, checked: bool) -> None:
        """跳过复选框状态变化时，禁用/启用对应的网站列表和按钮。"""
        list_widget = self._field_lists.get(field)
        if list_widget:
            list_widget.setEnabled(not checked)

    def _build_palette_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        label = QLabel("可用网站（拖到下方字段中；字段内从左到右优先级递减）")
        label.setStyleSheet(f"font-weight: bold; color: {get_theme_tokens(self._dark)['text']};")
        panel_layout.addWidget(label)
        panel_layout.addWidget(SitePaletteList(self._type_sites, self, dark=self._dark))
        return panel

    def _remove_from_field(self, field: CrawlerResultFields) -> None:
        list_widget = self._field_lists[field]
        selected = set(_selected_sites(list_widget))
        _setup_site_list(list_widget, [site for site in _list_sites(list_widget) if site not in selected])

    def _reset_field(self, field: CrawlerResultFields) -> None:
        if field == CrawlerResultFields.POSTER:
            _setup_site_list(self._field_lists[field], filter_poster_default_sites(self._type_sites))
            return
        _setup_site_list(self._field_lists[field], self._type_sites)

    def _reset_all(self) -> None:
        for field, list_widget in self._field_lists.items():
            if field == CrawlerResultFields.POSTER:
                _setup_site_list(list_widget, filter_poster_default_sites(self._type_sites))
            else:
                _setup_site_list(list_widget, self._type_sites)
            skip_check = self._skip_checks.get(field)
            if skip_check:
                skip_check.setChecked(False)

    def _keep_enabled_only(self) -> None:
        type_site_set = set(self._type_sites)
        for list_widget in self._field_lists.values():
            _setup_site_list(list_widget, [site for site in _list_sites(list_widget) if site in type_site_set])

    def _clear_all(self) -> None:
        for field, list_widget in self._field_lists.items():
            list_widget.clear()
            skip_check = self._skip_checks.get(field)
            if skip_check:
                skip_check.setChecked(False)


def setup_site_priority_ui(window: "MyMAinWindow") -> None:
    ui = window.Ui
    window._type_website_ui = {
        FixedScrapingType.YOUMA: TypeWebsiteUi(FixedScrapingType.YOUMA, "有码", ui.lineEdit_website_youma, 0),
        FixedScrapingType.WUMA: TypeWebsiteUi(FixedScrapingType.WUMA, "无码", ui.lineEdit_website_wuma, 2),
        FixedScrapingType.SUREN: TypeWebsiteUi(FixedScrapingType.SUREN, "素人", ui.lineEdit_website_suren, 4),
        FixedScrapingType.FC2: TypeWebsiteUi(FixedScrapingType.FC2, "FC2", ui.lineEdit_website_fc2, 6),
        FixedScrapingType.OUMEI: TypeWebsiteUi(FixedScrapingType.OUMEI, "欧美", ui.lineEdit_website_oumei, 8),
        FixedScrapingType.GUOCHAN: TypeWebsiteUi(FixedScrapingType.GUOCHAN, "国产", ui.lineEdit_website_guochan, 10),
    }
    for info in window._type_website_ui.values():
        key = info.scraping_type.name.lower()
        info.edit_button = getattr(ui, f"pushButton_edit_website_{key}")
        info.priority_button = getattr(ui, f"pushButton_priority_website_{key}")
        info.edit_button.clicked.connect(partial(_open_site_editor, window, info.scraping_type))
        info.priority_button.clicked.connect(partial(_open_priority_editor, window, info.scraping_type))

    _hide_legacy_field_website_group(window)
    apply_site_priority_theme(window)


def apply_site_priority_theme(window: "MyMAinWindow") -> None:
    dark = bool(getattr(window, "dark_mode", False))
    for info in getattr(window, "_type_website_ui", {}).values():
        _style_config_line_edit(info.line_edit, dark)
        if info.edit_button is not None:
            _style_inline_button(info.edit_button, dark)
        if info.priority_button is not None:
            _style_inline_button(info.priority_button, dark)


def refresh_site_priority_ui(window: "MyMAinWindow") -> None:
    for info in getattr(window, "_type_website_ui", {}).values():
        _set_site_summary(info.line_edit)


def _style_inline_button(button: QPushButton, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    button.setStyleSheet(
        f"""
        QPushButton {{
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 7px;
            padding: 3px 8px;
            background: {colors["surface"]};
        }}
        QPushButton:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_hover"]};
        }}
        QPushButton:pressed {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_pressed"]};
        }}
        """
    )


def _open_site_editor(window: "MyMAinWindow", scraping_type: FixedScrapingType) -> None:
    info = window._type_website_ui[scraping_type]
    selected_sites = _parse_sites(info.line_edit.text())
    registered_sites: list[Website] = []
    for site in get_registered_crawler_site_values():
        try:
            registered_sites.append(Website(site))
        except ValueError:
            pass
    all_sites = list(dict.fromkeys(selected_sites + registered_sites))
    dialog = SiteListEditorDialog(f"编辑{info.title}网站源", selected_sites, all_sites, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    sites = dialog.selected_sites()
    if not sites:
        QMessageBox.warning(window, "网站源不能为空", f"{info.title}至少需要保留一个网站。")
        return
    info.line_edit.setText(_sites_text(sites))
    _set_site_summary(info.line_edit)
    from mdcx.config.manager import manager

    manager.config.fill_missing_type_field_configs()
    previous_sites = manager.config.get_type_sites(scraping_type)
    setattr(manager.config, SCRAPING_TYPE_SITE_FIELDS[scraping_type], sites)
    for field in ManualConfig.REDUCED_FIELDS:
        current = manager.config.type_field_configs.setdefault(scraping_type, {}).setdefault(
            field, FieldPriorityConfig()
        )
        current.site_prority = _sync_field_sites_after_type_sites_changed(
            current.site_prority,
            previous_sites,
            sites,
        )
    manager.config.fill_missing_type_field_configs()
    manager.save()
    refresh_site_priority_ui(window)


def _open_priority_editor(window: "MyMAinWindow", scraping_type: FixedScrapingType) -> None:
    info = window._type_website_ui[scraping_type]
    type_sites = _parse_sites(info.line_edit.text())
    if not type_sites:
        QMessageBox.warning(window, "没有可用网站", f"请先为{info.title}配置至少一个网站。")
        return

    from mdcx.config.manager import manager

    setattr(manager.config, SCRAPING_TYPE_SITE_FIELDS[scraping_type], type_sites)
    manager.config.fill_missing_type_field_configs()
    dialog = FieldPriorityDialog(
        f"{info.title}字段优先级",
        scraping_type,
        type_sites,
        manager.config.type_field_configs.get(scraping_type, {}),
        window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    manager.config.type_field_configs[scraping_type] = dialog.field_configs()
    manager.config.fill_missing_type_field_configs()
    manager.save()
    refresh_site_priority_ui(window)


def _hide_legacy_field_website_group(window: "MyMAinWindow") -> None:
    window.Ui.groupBox_35.hide()
    window.Ui.layoutWidget2.hide()
    window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.setMinimumHeight(1330)
    window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.resize(
        window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.width(),
        1330,
    )
