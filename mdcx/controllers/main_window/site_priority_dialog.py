# mypy: ignore-errors
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QAction
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
from mdcx.utils.window_center import CenterOnFirstShowMixin, center_on_screen

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
    FixedScrapingType.YOUMA: "有码番号",
    FixedScrapingType.WUMA: "无码番号",
    FixedScrapingType.SUREN: "素人番号",
    FixedScrapingType.FC2: "个摄番号",
    FixedScrapingType.OUMEI: "欧美番号",
    FixedScrapingType.GUOCHAN: "国产番号",
    FixedScrapingType.DONGMAN: "动漫里番",
}


# 「编辑网站」弹窗顶部「可用网站（按类型分组）」里那七个分组标题的**短名**，与设置页
# 各行标签 / 两个弹窗标题（编辑XX网站源、XX字段优先级）用的 TYPE_TITLES 分开。
# 七个 chip 必须挤在同一行里，带「番号」三字会顶到框宽、换行后标题与站点就分不清了，
# 故这里只保留「有码」「个摄」这类一眼能认出来的短名（用户指定）。
PALETTE_GROUP_TITLES = {
    FixedScrapingType.YOUMA: "有码",
    FixedScrapingType.WUMA: "无码",
    FixedScrapingType.SUREN: "素人",
    FixedScrapingType.FC2: "个摄",
    FixedScrapingType.OUMEI: "欧美",
    FixedScrapingType.GUOCHAN: "国产",
    FixedScrapingType.DONGMAN: "动漫",
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

# 「字段优先级」里每个字段那一行的高度（一行网站 chip）。对话框的总高度按它乘行数算，
# 所以改动这里就能让字段区跟着变。
FIELD_ROW_HEIGHT = 58

# 默认一次露全的行数：字段共十九行，整屏放不下，但「标题 … 全部演员」这六行是天天要改的
FIELD_PRIORITY_VISIBLE_ROWS = 6

# 「编辑网站」两个显示框的默认行数：上方候选区五行、下方启用区四行。
# 定死而不是跟着内容伸缩：同一个对话框在六种类型下高矮、宽窄、样式要完全一样。
SITE_EDITOR_PALETTE_ROWS = 6
SITE_EDITOR_SELECTED_ROWS = 4

# 「字段优先级」上方「可用网站」框默认露全的行数。
FIELD_PALETTE_VISIBLE_ROWS = 4

# 「编辑网站」与「字段优先级」两个对话框共用的高度：两边都是网站源相关的弹窗，
# 挨着开的时候高度一致才不显得其中一个「高耸入云」；也别超过常见的 800 高的屏幕。
DIALOG_HEIGHT = 680

# 实际用的共用高度。字体或界面缩放一大，「字段优先级」那六行字段加四行候选区就比 680 高，
# Qt 会把这个窗口撑大（这在测试进程里才暴露出来：那边加载了主题字体，窗口被顶到 720）。
# 与其让两个窗口就此高矮不一，不如把「字段优先级」真正需要的高度量出来给两边一起用——
# 用户要的是两个窗口一样高、而且与打开顺序无关。
_FIELD_PRIORITY_HEIGHT: int | None = None


def shared_dialog_height() -> int:
    """两个弹窗共用的高度：以「字段优先级」在这个字体/缩放下真正需要的高度为准。

    以前这里是「见过「字段优先级」之后记下它的高度」，于是先开哪个窗口决定了两个窗口
    一样高还是差一截——用户看到的正是「先开字段优先级、再开编辑网站，后者更高」。现在
    改成现场量一次：把「字段优先级」的控件摆出来（不显示、不联网，只是问它 sizeHint 要
    多高），量完缓存下来。两个窗口都按它来，先开哪个都一样。
    """
    global _FIELD_PRIORITY_HEIGHT
    if _FIELD_PRIORITY_HEIGHT is None:
        # 先占位再摆探针：探针自己构造时也会调到这里，占了位才不会自己套自己
        _FIELD_PRIORITY_HEIGHT = DIALOG_HEIGHT
        probe = FieldPriorityDialog("高度测量", FixedScrapingType.YOUMA, list(Website)[:8], {}, None)
        try:
            _FIELD_PRIORITY_HEIGHT = max(DIALOG_HEIGHT, probe.sizeHint().height())
        finally:
            probe.deleteLater()
    return _FIELD_PRIORITY_HEIGHT


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


# 候选区的分组顺序：与 TYPE_TITLES / PALETTE_GROUP_TITLES 的声明序一致（含动漫里番——
# 它同样是「类型刮削网站」下的一个类型，用户要在这里也能一眼看到它默认配了哪几个站）
PALETTE_GROUP_TYPES: tuple[FixedScrapingType, ...] = (
    FixedScrapingType.YOUMA,
    FixedScrapingType.WUMA,
    FixedScrapingType.SUREN,
    FixedScrapingType.FC2,
    FixedScrapingType.OUMEI,
    FixedScrapingType.GUOCHAN,
    FixedScrapingType.DONGMAN,
)


def grouped_palette_groups(sites: Iterable[Website]) -> list[tuple[str, list[Website]]]:
    """把候选站点按有码/无码/素人/个摄/欧美/国产/动漫分成 [(标题, 组内站点)]。

    组内顺序 = TYPE_DEFAULT_SITES 里该组的默认名单顺序（优先级从高到低），不重排。
    一个站点可同属多组，会在每个组里各出现一次——它确实是这几个类型的可用来源，
    而「全部添加」用的是 self._all_sites 原序，不会因此重复添加。

    没有「其他」分组标题：落在这些组之外的站点（如 MyWife、AVSEX、Getchu）按传入次序接在
    最后一组后面，但仍要出现在候选区里——它们也是能选的网站源，只是不属于任何一个类型组。
    这类分组标题为空串，_make_group_item 不会把它当成一个可见标题，但它的站点仍会出现在
    标题下方的站点区里。
    """
    available = list(dict.fromkeys(sites))
    available_set = set(available)
    groups: list[tuple[str, list[Website]]] = []
    placed: set[Website] = set()
    for scraping_type in PALETTE_GROUP_TYPES:
        group = [site for site in TYPE_DEFAULT_SITES.get(scraping_type, ()) if site in available_set]
        if not group:
            # 该类型在本机没有已注册爬虫的站点时不留空标题，否则会出现一个没有内容的分组
            continue
        groups.append((PALETTE_GROUP_TITLES[scraping_type], group))
        placed.update(group)
    rest = [site for site in available if site not in placed]
    if rest:
        groups.append(("", rest))
    return groups


# 少数几站不在字母序上该出现的位置，按用户要求单独给一个排序键：
# AVEntertainments 归到 AVheat / AVMOO / AVSEX / AVSOX 之后（键尾的 ~ 排在所有字母之后，
# 于是它紧跟在 AVSOX 后面），Madouqu 归到 Madou.club 之前（键就是 "madou"，前缀更短排前面）。
PALETTE_SORT_KEYS: dict[Website, str] = {
    Website.AVENTERTAINMENTS: "avsox~",
    Website.MADOUQU: "madou",
}


def palette_site_order(sites: Iterable[Website]) -> list[Website]:
    """候选区里站点的铺放次序：标题之下是一份去重后的 A-Z 名单。

    分组只留在开头那几个标题上（单击整组加入、右键复制本组），站点本身不再按组分段，
    也不再按各组默认名单的优先级排——用户要的就是一路 A-Z 看下去，找站靠字母而不是靠
    记忆分组；同一个站也只出现一次。少数几站的位置由 PALETTE_SORT_KEYS 单独指定。
    """
    return sorted(dict.fromkeys(sites), key=lambda site: PALETTE_SORT_KEYS.get(site, site.value).casefold())


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


# 分组标题与站点同样占一个条目、同样走默认委托（纯白背景、与站点 chip 同高、宽度按
# 字体走），只是不带 UserRole、不可选中不可拖动——_list_sites / _selected_sites 靠
# UserRole 过滤站点行，自然把标题排除在外。双击某个标题即加入该组全部网站、右键
# 「加入列表：启用网站」同样可整组加入、右键复制该组名单，都直接读这两个角色，不必按行
# 范围去猜（换行位置、组数增减都不影响）。
SITE_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1
SITE_GROUP_SITES_ROLE = Qt.ItemDataRole.UserRole + 2


def _make_group_item(title: str, sites: Sequence[Website]) -> QListWidgetItem:
    """候选区里的一个分组标题：文案就是类型名，成员名单挂在标题自己身上。

    标题排在所有站点之前（用户要求「有码、无码、素人、个摄、欧美、国产这样默认排在 DMM
    左边」），后面紧跟着站点、与站点共用同一个换行流——所以第一行看起来就是
    「有码 无码 素人 个摄 欧美 国产 DMM DMM_API LibreDMM …」，右边不留空。
    标题只用加粗与站点区分，**不再另刷深色底**（用户明确要「和其他站点一样纯白背景」）。
    """
    item = QListWidgetItem(title)
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setData(SITE_GROUP_ROLE, title)
    item.setData(SITE_GROUP_SITES_ROLE, [site.value for site in sites])
    item.setToolTip(
        f"类型分组标题：双击即加入该组全部网站（{len(sites)} 个），右键可复制该组名单或整组加入「启用网站」"
    )
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return item


def _group_sites_at(list_widget: QListWidget, row: int) -> list[Website]:
    """第 row 行若是分组标题，返回它自己带的成员名单；否则空列表。"""
    item = list_widget.item(row)
    values = item.data(SITE_GROUP_SITES_ROLE) if item is not None else None
    return [Website(value) for value in values] if values else []


def _is_group_item(item: QListWidgetItem | None) -> bool:
    return item is not None and item.data(SITE_GROUP_SITES_ROLE) is not None


def _is_site_item(item: QListWidgetItem | None) -> bool:
    """是否站点行。标题行没有 UserRole，靠它把两者分开。"""
    return item is not None and item.data(Qt.ItemDataRole.UserRole) in Website


def _site_tooltip_lines(site: Website) -> list[str]:
    """站点项的悬停提示：定位说明 + 类型 + 联动组成员（说明加入一个会带上哪些）。

    「类型」这一行是候选区去重铺放后必须补上的：站点只在列表里出现一次，标题又都
    提到了顶部，不写这一条就看不出它同时是有码站、也是无码站。用的是候选区那套短名
    （PALETTE_GROUP_TITLES），与标题对得上。两行的标签只写「类型：」与「联动：」，
    不再缀上「适用」「（加入其一即默认加入全组）」那半句解释——悬停框宽度有限，长标签
    会把站点名单挤成两行还容易被截断，而这三个字本身已经说清了是什么。
    """
    lines: list[str] = []
    if description := _site_description(site):
        lines.append(description)
    if types := [PALETTE_GROUP_TITLES[key] for key in PALETTE_GROUP_TYPES if site in TYPE_DEFAULT_SITES.get(key, ())]:
        lines.append("类型：" + "、".join(types))
    if group := site_group_of(site):
        lines.append("联动：" + "、".join(member.value for member in group))
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
    """把 sites 铺进列表。grouped=True 时先放七个分组标题，紧跟着才是站点。

    标题与站点在同一个换行流里顺排，所以第一行就是「有码 无码 素人 个摄 欧美 国产
    DMM DMM_API LibreDMM …」，右边不留空白（用户要求「不要空着，继续排列站点」），同时又满足「七个标题排在 DMM 之前」。

    默认（grouped=False）保持传入的原序——「启用网站」和各字段名单的原序就是用户的
    优先级序列，任何排序都不能掺进来；候选区才用 grouped=True。
    """
    list_widget.clear()
    if not grouped:
        for site in sites:
            list_widget.addItem(_make_site_item(site))
        return
    for title, group in grouped_palette_groups(sites):
        if title:  # 无标题的末组（MyWife 等）不另起标题，站点照样铺出来
            list_widget.addItem(_make_group_item(title, group))
    for site in palette_site_order(sites):
        list_widget.addItem(_make_site_item(site))
    # 填完清掉当前项：Qt 会把第一行设成当前项，于是第一个标题被套上聚焦框、比别的
    # 站点多一圈边框（用户不要「标题被圈起来」）。清掉之后所有格子长得一模一样。
    list_widget.setCurrentRow(-1)


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


def _event_pos(event) -> QPoint:
    """鼠标事件的落点（Qt6 给 QPointF，旧式 API 给 QPoint）。"""
    try:
        return event.position().toPoint()
    except AttributeError:
        return event.pos()


def _site_list_context_menu(list_widget: QListWidget, pos) -> None:
    """站点列表的右键菜单。

    复制的是「点到的那个东西」：点在站点上复制该站点，点在某个分组标题上复制该组
    自己的名单（不是整张列表——六个类型就是六份不同的名单，复制整张等于把分类白做了），
    点在空白处才复制整张列表。

    最下方另有「加入列表：启用网站」：只有「编辑网站」对话框的候选区挂了
    `on_add_to_enabled` 回调才出现（启用列表与字段优先级那几行没有「启用网站列表」可言），
    它把「点的哪一格就加入哪一格」这条规则交给回调去做：点标题加入整组、点站点加入那一个、
    点空白处加入当前选中的那些。排在最下方是为了不和上面两条「复制」混作一谈——用户
    右键多半是为了复制，加入得是刻意选的那一项。
    """
    item = list_widget.itemAt(pos)
    site_value = item.data(Qt.ItemDataRole.UserRole) if _is_site_item(item) else None
    sites = _list_sites(list_widget)
    group_title = item.data(SITE_GROUP_ROLE) if _is_group_item(item) else None
    group_sites = _group_sites_at(list_widget, list_widget.row(item)) if group_title else []
    if site_value is None and not sites:
        return

    menu = QMenu(list_widget)
    primary: QAction | None = None
    primary_text = ""
    primary_message = ""
    if site_value is not None:
        primary_text = f"复制站点：{site_value}"
        primary_message = f"站点「{site_value}」"
    elif group_sites:
        primary_text = f"复制本组：{len(group_sites)}个站点"
        primary_message = f"「{group_title}」组的{len(group_sites)}个站点"
    if primary_text:
        primary = menu.addAction(primary_text)
        menu.addSeparator()
    list_action = menu.addAction(f"复制列表：{len(sites)}个站点")
    on_add_to_enabled = getattr(list_widget, "on_add_to_enabled", None)
    add_action: QAction | None = None
    if on_add_to_enabled is not None:
        menu.addSeparator()
        add_action = menu.addAction("加入列表：启用网站")
        # 点在空白处又没选中任何站点时无站可加（`_selected_sites` 无选中项可读），
        # 摆个灰项让人一眼看出点它没用，而不是点了之后列表纹丝不动
        if item is None and not _selected_sites(list_widget):
            add_action.setEnabled(False)

    if (chosen := menu.exec(list_widget.viewport().mapToGlobal(pos))) is None:
        return
    if add_action is not None and chosen is add_action:
        on_add_to_enabled(item)
        return
    if primary is not None and chosen is primary:
        text = site_value if site_value is not None else _sites_text(group_sites)
        _copy_to_clipboard(text, primary_message)
        return
    if chosen is list_action:
        _copy_to_clipboard(_sites_text(sites), f"{len(sites)}个站点的列表")


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


def _list_row_pitch(list_widget: QListWidget) -> int:
    """量出列表当前的行距（像素）：相邻两个「视觉行」顶边之差。

    流式换行的列表里同一行的站顶边相同，所以取所有相邻顶边之间的最小正差。量不出来
    （内容全在一行、或者还没排版）时返回 0。
    """
    if list_widget.count() == 0:
        return 0
    if hint := list_widget.sizeHintForRow(0):
        return int(hint)
    tops = sorted({list_widget.visualItemRect(list_widget.item(row)).top() for row in range(list_widget.count())})
    deltas = [b - a for a, b in zip(tops, tops[1:], strict=False) if b - a > 0]
    return min(deltas) if deltas else 0


def _fit_list_rows(list_widget: QListWidget, rows: int) -> None:
    """把一个流式换行的列表框调到「正好 rows 行」的框高。

    「正好」是说第 rows 行整行露得出来、下一行一像素都不露——只露半行的效果更糟，
    看着像「有 bug 的半截」。框高变了换行位置会重排，所以这里从当前排布量出真实行距
    再直接换算：视口要 rows 行那么高，框高再加上边框与内边距。
    """
    if list_widget.count() == 0:
        return
    # 内容装不满 rows 行也照样定成 rows 行：框的高度是这个对话框的规格的一部分，
    # 「启用网站」只勾了三五个站时窗口也得跟勾满时一样高，否则六种类型下高矮不一。
    tops = sorted({list_widget.visualItemRect(list_widget.item(row)).top() for row in range(list_widget.count())})
    # 行距优先问 Qt 自己要（sizeHintForRow 就是换行流式布局用的行高，含样式表给的边距），
    # 字体/界面缩放变了它跟着变；量 visualItemRect 只作兜底，那是在「此刻的排布」上量的，
    # 字体还没落定时会量到旧行距，算出来的框高就只够露三行半。
    pitch = list_widget.sizeHintForRow(0)
    if pitch <= 0:
        pitch = tops[1] - tops[0] if len(tops) > 1 else list_widget.visualItemRect(list_widget.item(0)).height()
    chrome = list_widget.height() - list_widget.viewport().height()  # 边框 + 样式表给的内边距
    # 这里明确要「几行就几行」，样式表给的默认最小高度（150 ≈ 5 行）得让位，
    # 否则算出来的行数永远比样式表那个下限小、调不动
    list_widget.setMinimumHeight(0)
    list_widget.setFixedHeight(rows * pitch + chrome)
    list_widget.updateGeometry()
    parent = list_widget.parentWidget()
    if parent is not None and parent.layout() is not None:
        parent.layout().activate()


def _localize_dialog_buttons(buttons: QDialogButtonBox) -> None:
    if ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok):
        ok_button.setText("保存")
    if cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel):
        cancel_button.setText("取消")


class _SiteListBase(QListWidget):
    """站点列表的共用行为：右键只弹菜单不改选中态；滚轮只滚自己，不外传。

    右键那条：Qt 默认在右键按下时会顺手选中那一格，于是被右键的格子套上 `:selected`
    的深色底，看着像「多了一个内部方框」，菜单关掉后那格还留着高亮。右键的动作只是
    复制，不该改变选中状态：按下前后把「选中的行 + 当前行」原样保留，菜单读的是按下的
    位置，不依赖选中态，所以恢复不影响复制。

    滚轮那条（「字段优先级」窗口）：十九行字段挤在一个 QScrollArea 里，每行是一个
    固定 58 高、左到右换行的站点列表。Qt 的滚轮是**自发事件**——派发方式为「从鼠标
    底下的控件起，沿父控件一路往上递，直到某一层既处理了（event() 返回 true）又接受
    了事件才停」（见 `QApplication::notify` 里 `case QEvent::Wheel` 那段 do-while）。
    实测（离屏探针，同一版 PyQt6 6.11）：
        - 本行还能滚  → wheelEvent 滚了滚动条并 accept，视口层 res=True → 传递在此终止；
        - 本行已到底 / 这一行站点太少装得下 → Qt 把事件 ignore 掉 → 继续往上递 →
          被外层 QScrollArea 接住 → **上下行与最右侧滚动条一起动**（用户实机截图标注
          的正是这一处）。
    所以「鼠标在标题里滚只影响标题」要靠两处收口：wheelEvent 里滚不动也照样 accept
    （截住最常见的那条路径），以及 WA_NoMousePropagation（在列表这一层就把传递掐断，
    兜住没走到 wheelEvent 的路径，例如鼠标正好停在行内那条滚动条上）。

    聚焦框那条：左键点中任意一个站点 chip，Qt 都会把它设成**当前项**，而
    `QListView::paintEvent` 里 `option.state.setFlag(QStyle::State_HasFocus, focus &&
    current == index)`（focus = 视图有焦点 && current 有效），于是 `QStyleSheetStyle`
    在 chip 内部再套一个圆角框——肉眼就是 chip 里嵌了个小方框（与 `:selected` 那层填充
    是两回事）。三个列表（候选区、「启用网站」、「字段优先级」的十九行字段）此前都留着
    它，现在统一在左键按下后清掉当前项（见 `_release_current_item`）：这三处要的都是
    「选中」不是「当前位置」，留着当前项只会多出一圈框。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # 兜底：滚轮在列表这一层就把传递掐断。它管的是「没走到 wheelEvent 的那条路」——
        # 鼠标正好停在行内那条滚动条上时，滚轮由滚动条接手，它滚不动时同样 ignore 事件，
        # 递上来的第一站就是本控件，加了这个属性就不会再越过本控件去带动上层滚动区。
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        # on_add_to_enabled：右键菜单最下方「加入列表：启用网站」的回调，签名是
        # (item) -> None，item 是右键按下的那一格（点在空白处时为 None）。留空则菜单里
        # 不出现这一项——「启用网站」列表和「字段优先级」那几行都没有「启用列表」可言，
        # 只有「编辑网站」对话框的候选区会挂上它（见 SiteListEditorDialog._add_from_palette）。
        self.on_add_to_enabled = None

    def wheelEvent(self, event) -> None:
        """滚轮只滚本列表；本行滚不动时也照样吃掉，不往上递给外层滚动区。"""
        super().wheelEvent(event)
        if not event.isAccepted():
            event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            selected = [self.row(item) for item in self.selectedItems()]
            current = self.currentRow()
            super().mousePressEvent(event)
            if self.selectedItems() or self.currentRow() >= 0:
                self.clearSelection()
                for row in selected:
                    self.item(row).setSelected(True)
                self.setCurrentRow(current)
            # 右键点在一个分组标题上也要清：那一格带 ItemIsEnabled 而不带
            # ItemIsSelectable，Qt 却照样会把它设成当前项，于是它被套上聚焦框
            if _is_group_item(self.itemAt(_event_pos(event))):
                self._release_current_item()
            return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._release_current_item()

    def _release_current_item(self) -> None:
        """清掉当前项，但保住按下时已经选中的那几格。

        为什么非得保住：`QAbstractItemView::setCurrentIndex` 对无效索引并不只清当前项——
        它照样先问一句 `selectionCommand(无效索引, nullptr)`（无事件时是 ClearAndSelect），
        再交给 `QItemSelectionModel::setCurrentIndex` → `select(无效索引, ClearAndSelect)`，
        整个选中集跟着一起没了（实测：选中一行后 setCurrentRow(-1)，selectedItems 变空）。
        「添加选中」「移除」按钮、以及拖拽加入与重排全都读的是选中集，清空了就是废的。
        所以先记下选中的行、清完再逐个还回去；`setSelected` 不碰当前项（实测），还回去之后
        当前项仍是 -1、聚焦框也就没有了。右键那条（上面的 mousePressEvent）用的也是同一
        套路。

        **只管鼠标**：键盘方向键仍由 Qt 走 `moveCursor` 设置当前项，于是键盘用户仍能看见
        自己在哪儿——全靠视觉定位的键盘操作不该被这条一起抹掉。
        """
        selected = [self.row(item) for item in self.selectedItems()]
        self.setCurrentRow(-1)
        for row in selected:
            if (item := self.item(row)) is not None:
                item.setSelected(True)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        # 光标进入时若当前项为空，Qt 会把当前项设成第一行，于是那一格一被聚焦就被圈起来。
        # 这三个列表要的都是「选中」不是「当前位置」（点站点照样选中、拖拽照样拖），所以
        # 这里清掉，让开窗后的观感与别的格子一致。
        self.setCurrentRow(-1)


class SitePaletteList(_SiteListBase):
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
        # grouped：是否把七个分组标题排在站点之前。_setup_site_list 之后每次重建都要带着这个
        # 标志，否则刷新一次分组就没了，故存成公开属性给调用方原样传回去。
        self.grouped = grouped
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


class PrioritySiteList(_SiteListBase):
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
        # 挪完之后**不能**把被移动的站点重新选中，否则它们会被 Qt 当场删掉：
        # QAbstractItemView::startDrag 的收尾是
        #     if (drag->exec(...) == Qt::MoveAction && !d->dropEventMoved) d->clearOrRemove();
        # 而 dropEventMoved 除了 startDrag 自己置 false 之外，全 Qt 没有任何一处置 true
        # （基类 dropEvent 也没置，自实现的 dropEvent 自然更不会），所以只要这次拖拽以
        # Move 收场（本列表的 defaultDropAction 正是 Move，我们又 acceptProposedAction），
        # clearOrRemove() 必被调用——它删的是「当前选中着的那些整行」。顺序我们已经改好了，
        # Qt 再删一次，表现就是「拖一下调顺序，站点直接消失」（用户实机反馈的正是这条）。
        # 字段优先级那几行走的是基类 dropEvent（Qt 自己 moveRows），Qt 搬动时已经先把选中态
        # 带走了，所以那边不受这条收尾影响；只有这条自实现路径要自己把选中态清干净。
        self.clearSelection()

    def mimeData(self, items: list[QListWidgetItem]):
        self.drag_sites = _selected_sites(self)
        return super().mimeData(items)

    def normalize(self) -> None:
        allowed_set = set(self._allowed_sites)
        _setup_site_list(self, [site for site in _list_sites(self) if site in allowed_set])

    def _drop_row(self, event) -> int:
        row = self.indexAt(_event_pos(event)).row()
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
        # 可用网站（网址源）的候选区：先排六个类型分组标题，紧跟着按组铺全部站点
        # （见 grouped_palette_groups / palette_site_order）。_all_sites 的原序仍然保留着：
        # 它是「全部添加」写入启用列表的顺序，也是拖拽插入时的落点参照，都属于用户
        # 自定的优先级序列，不受这里的分组影响。
        self._palette_sites = self._all_sites

        layout = QVBoxLayout(self)

        self.selected_list = PrioritySiteList(self._all_sites, 168, self, self._dark, auto_group=True)
        self.available_list = SitePaletteList(
            self._palette_sites, self, removable_source=self.selected_list, dark=self._dark, grouped=True
        )
        self.available_list.on_removed = self._sync_selected_from_list

        top_panel = self._build_panel("可用网站（按类型分组）", self.available_list)
        bottom_panel = self._build_panel("", self.selected_list)
        # 上方那行说明拿来给下面那行对齐用（见 _place_caption）：面板里的第一个 QLabel 就是它
        self.top_title = top_panel.findChild(QLabel)
        # 「启用网站」这行说明摆在两个显示框的正中间。它不进布局：布局只会把这行放在两个框
        # 之间某个位置（富余高度给谁由 stretch 说话，字体一大就偏），而我们要在布局定下来
        # 之后按两个框的实际边沿自己摆——见 _place_caption。
        self.middle_title = self._panel_title("启用网站（从左到右优先级递减）")
        self.middle_title.setParent(self)  # 不进布局，自行摆放（见 _place_caption）
        # 两个框各分一半富余高度：否则富余高度全堆在两框之间，「启用网站」那行说明
        # 周围就空出一大片（用户要求缩小这个间距）
        layout.addWidget(top_panel, 1)
        layout.addWidget(bottom_panel, 1)

        group_hint = QLabel("联动组：加入组内任意一个站点即自动加入组内其余站点，加入后可在「启用网站」中手动移除")
        group_hint.setWordWrap(True)
        group_hint.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text_muted']};")
        layout.addWidget(group_hint)

        copy_hint = QLabel(
            "开头的七个加粗标题是有码、无码、素人、个摄、欧美、国产、动漫，"
            "双击一个标题即加入该组全部网站，"
            "后面紧跟全部可用网站（按名称 A-Z 排序、每个站只出现一次）。"
            "右键：站点上复制该站点、标题上复制本组名单、空白处复制整张列表，"
            "最下方另有「加入列表：启用网站」"
        )
        copy_hint.setWordWrap(True)
        copy_hint.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text_muted']};")
        layout.addWidget(copy_hint)

        actions = QHBoxLayout()
        add_button = QPushButton("添加选中")
        remove_button = QPushButton("移除选中")
        add_all_button = QPushButton("全部添加")
        clear_button = QPushButton("清空站点")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _localize_dialog_buttons(buttons)
        # 保存 / 取消 与「添加选中 / 移除选中」同排，不必沉到对话框最底下去够鼠标
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addWidget(add_all_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(buttons)
        layout.addLayout(actions)
        for button in (*buttons.buttons(), add_button, remove_button, add_all_button, clear_button):
            _style_inline_button(button, self._dark)

        add_button.clicked.connect(self._add_selected)
        remove_button.clicked.connect(self._remove_selected)
        add_all_button.clicked.connect(self._add_all)
        clear_button.clicked.connect(self._clear_selected)
        self.available_list.itemDoubleClicked.connect(self._on_available_double_clicked)
        self.available_list.on_add_to_enabled = self._add_from_palette
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected())

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._refresh_lists()
        # 两个列表贴紧内容后，对话框也收到刚好装下它们的高度（不留在底部当空白）
        self.resize(self.width(), shared_dialog_height())

    def _place_caption(self) -> None:
        """把「启用网站」那行说明摆到两个显示框的正中间。

        布局只保证「两个框上下排着」，富余高度给谁由 stretch 说话，说不清会落在哪一格；
        而说明行的意思就是「下面是启用网站」，用户要它稳稳待在两个框的中间。布局定下来
        之后按两个框的实际边沿算一次，比跟 stretch 较劲可靠。
        """
        top_bottom = self.available_list.mapTo(self, QPoint(0, self.available_list.height())).y()
        bottom_top = self.selected_list.mapTo(self, QPoint(0, 0)).y()
        size = self.middle_title.sizeHint()
        # 空带够高就摆在正中间；空带已经压到一行以内（两个框各分一半富余高度之后就是
        # 这种情况），就紧跟在上面那个框底下，别让它骑到框上去
        band = bottom_top - top_bottom
        target = top_bottom + band // 2 if band >= size.height() else top_bottom + size.height() // 2 + 2
        # 左边跟「可用网站」那行严格对齐（用户要求两行的字一个像素都不错开），只占文字那么大：
        # 否则这块看不见的控件会盖在两个框上，把它们的点击吃掉
        left = self.top_title.mapTo(self, QPoint(0, 0)).x()
        self.middle_title.setGeometry(left, target - size.height() // 2, size.width(), size.height())
        self.middle_title.show()

    def selected_sites(self) -> list[Website]:
        return _list_sites(self.selected_list)

    def _sync_selected_from_list(self) -> None:
        self._selected_sites = self.selected_sites()

    def _panel_title(self, text: str) -> QLabel:
        """显示框上方的粗体说明行（两个显示框共用同一种样子）。"""
        label = QLabel(text)
        label.setStyleSheet(f"font-weight: bold; color: {get_theme_tokens(self._dark)['text']};")
        return label

    def _build_panel(self, title: str, list_widget: QListWidget) -> QWidget:
        # title 传空串时不带说明行：那种情况下说明行单独摆在两个显示框之间
        panel = QWidget()
        layout = QVBoxLayout(panel)
        if title:
            layout.addWidget(self._panel_title(title))
        layout.addWidget(list_widget)
        return panel

    def _on_available_double_clicked(self, item) -> None:
        """双击分组标题 = 整组加入；双击站点行 = 加入该站（与「添加选中」同一套）。

        分组标题原来是**单击**整组加入的，本轮按用户口径改成**双击**：单击那一格
        用户只是想看看它是哪一组，顺手扫过列表时不该一路把整组站点都塞进启用列表。
        标题不可选中，所以双击它不会带上「上次选中的残留」——单击标题什么也没选中，
        这里直接按标题自带的名单加入即可（`_add_sites` 里已启用的保持原位，重复双击幂等）。
        """
        if _is_group_item(item):
            self._add_sites(_group_sites_at(self.available_list, self.available_list.row(item)))
            return
        if _is_site_item(item):
            self._add_selected()

    def _add_from_palette(self, item) -> None:
        """右键「加入列表：启用网站」：点的哪一格就加入哪一格。

        点标题 = 整组加入（同双击）、点站点 = 只加那一个（右键不改选中态，所以不能靠
        `_add_selected`）、点空白处 = 加当前选中的那些（等价于「添加选中」按钮）。
        无论哪一种，最终都走 `_add_sites`：已启用的保持原位、联动组自动补齐。
        """
        if _is_group_item(item):
            self._add_sites(_group_sites_at(self.available_list, self.available_list.row(item)))
            return
        sites = [Website(item.data(Qt.ItemDataRole.UserRole))] if _is_site_item(item) else []
        self._add_sites(sites or _selected_sites(self.available_list))

    def _refresh_lists(self) -> None:
        _setup_site_list(self.available_list, self._palette_sites, grouped=self.available_list.grouped)
        _setup_site_list(self.selected_list, self._selected_sites)
        self._fit_lists_to_content()

    def _fit_lists_to_content(self) -> None:
        """把两个显示框定到「上方五行、下方四行」。

        两边都用同一个固定档位，不再跟着内容伸缩：六种类型的候选站数量差很多，跟着内容
        伸缩会让同一个对话框在不同类型下时高时矮；固定行数之后窗口的高、宽、样式在六种
        类型下一模一样，区别只在于框里能滚动多少行。
        """
        for list_widget, rows in (
            (self.available_list, SITE_EDITOR_PALETTE_ROWS),
            (self.selected_list, SITE_EDITOR_SELECTED_ROWS),
        ):
            # 视口还没成型（构造期、未显示）时算不出行距，等 showEvent 再定
            if list_widget.viewport().width() < 200:
                continue
            # 行距在字体/主题定下来之前量是不准的（先量后变），所以按「当前行距」记一次：
            # 行距变了才重新调，没变就不再动它，免得反复触发布局
            pitch = _list_row_pitch(list_widget)
            if pitch and getattr(list_widget, "fit_pitch", None) == pitch:
                continue
            _fit_list_rows(list_widget, rows)
            list_widget.fit_pitch = pitch
            self.layout().activate()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 显示出来后视口宽度才是真的，此时贴一次内容高度，并把对话框收到刚好装下它
        self._fit_lists_to_content()
        # 主题字体与布局在这一拍之后才最终定下来，行距会变；补一次，行距没变就自动跳过
        QTimer.singleShot(0, self._fit_lists_to_content)
        self.resize(self.width(), shared_dialog_height())
        # 高度定下来之后再摆位置：否则先居中再改高度，窗口又会掉到屏幕偏下
        center_on_screen(self)
        self._place_caption()
        # center_on_screen 在原生窗口还没建好时会把定位延后一拍（见 mdcx.utils.window_center），
        # 那一拍之后两个框的边沿会变，所以再排一次：说明行按最终位置摆，不抢在定位前面
        QTimer.singleShot(0, self._place_caption)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 宽度变了，chip 的换行位置与行数也跟着变，高度要重新贴一次
        self._fit_lists_to_content()
        self._place_caption()

    def _add_selected(self) -> None:
        self._add_sites(_selected_sites(self.available_list))

    def _add_sites(self, sites: list[Website]) -> None:
        """按给定次序把 sites 追加进启用列表（已启用的保持原位，不重排）。"""
        current = self.selected_sites()
        self._selected_sites = current
        added = [site for site in sites if site not in current]
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
        self.resize(860, DIALOG_HEIGHT)
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
            list_widget = PrioritySiteList(self._type_sites, FIELD_ROW_HEIGHT, self, self._dark)
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
        self._fit_field_rows()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 视口宽度这时才是真的（构造期那一遍是按还没排版完的宽度量的），重新定一次：
        # 上方「可用网站」正好四行、下方字段正好六行
        self._fit_field_rows()
        # 与「编辑网站」同一个高度、也同一个摆法：默认居中
        center_on_screen(self)

    def _fit_field_rows(self) -> None:
        """把两个显示框都定到「整行」的排布：上方四行、下方六行。

        下方字段一共十九行，默认高度下第六行（全部演员）被对话框底边切掉一半，保存/取消
        又正好压在它上面，所以按 58 高 + 6 行距把滚动区定高，六行整行露全、第七行一
        像素都不露。上方「可用网站」原来是 3.3 行（第四行只露一条缝），按用户要求补成
        整四行——框高变了每一行的换行位置都会重排，所以由 _fit_list_rows 反复量到
        「完全露出的视觉行数 == 4」为止。剩下的字段行仍可在滚动区里滚。
        """
        scroll = self.findChild(QScrollArea)
        if scroll is None:
            return
        visible = FIELD_PRIORITY_FIELDS[:FIELD_PRIORITY_VISIBLE_ROWS]
        # 实测每行的排布是 58 高 + 6 行距：六行整好占到 387 像素，第七行从 393 开始。
        # 按这个把滚动区定高，六行整行露全、第七行一像素都不露，对话框也不会高过主窗口。
        scroll.setFixedHeight(len(visible) * (FIELD_ROW_HEIGHT + 6) + 4)
        palette = next(iter(self.findChildren(SitePaletteList)), None)
        if palette is not None:
            _fit_list_rows(palette, FIELD_PALETTE_VISIBLE_ROWS)
        self.resize(self.width(), shared_dialog_height())

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
        # title 取 TYPE_TITLES（带「番号」的正式组名），与设置页各行标签、
        # 「编辑网站」对话框标题「编辑{type}网站源」三处保持同一个组名。
        FixedScrapingType.YOUMA: TypeWebsiteUi(
            FixedScrapingType.YOUMA, TYPE_TITLES[FixedScrapingType.YOUMA], ui.lineEdit_website_youma, 0
        ),
        FixedScrapingType.WUMA: TypeWebsiteUi(
            FixedScrapingType.WUMA, TYPE_TITLES[FixedScrapingType.WUMA], ui.lineEdit_website_wuma, 2
        ),
        FixedScrapingType.SUREN: TypeWebsiteUi(
            FixedScrapingType.SUREN, TYPE_TITLES[FixedScrapingType.SUREN], ui.lineEdit_website_suren, 4
        ),
        FixedScrapingType.FC2: TypeWebsiteUi(
            FixedScrapingType.FC2, TYPE_TITLES[FixedScrapingType.FC2], ui.lineEdit_website_fc2, 6
        ),
        FixedScrapingType.OUMEI: TypeWebsiteUi(
            FixedScrapingType.OUMEI, TYPE_TITLES[FixedScrapingType.OUMEI], ui.lineEdit_website_oumei, 8
        ),
        FixedScrapingType.GUOCHAN: TypeWebsiteUi(
            FixedScrapingType.GUOCHAN, TYPE_TITLES[FixedScrapingType.GUOCHAN], ui.lineEdit_website_guochan, 10
        ),
        # 动漫里番同样是「类型刮削网站」下的一类，排在国产番号下面一行（对应 layoutWidget_6 的 row 16）；
        # 两个按钮靠下面的 f"pushButton_edit_website_{key}" 按类型名拼出来，正好对得上 .ui 里的名字
        FixedScrapingType.DONGMAN: TypeWebsiteUi(
            FixedScrapingType.DONGMAN, TYPE_TITLES[FixedScrapingType.DONGMAN], ui.lineEdit_website_dongman, 16
        ),
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
