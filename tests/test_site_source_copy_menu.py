"""「编辑网站」对话框：右键复制单个站点 / 单个分组 / 整张站点列表。

用户需求原文（三轮）：
    1.「鼠标右键点击时可以复制站点列表，单个站点鼠标右键点击也可以复制」
    2.「有码、无码、素人、FC2、欧美、国产右键复制不是复制全部39个站点，
        是复制它们各自包含的站点」
    3.「有码、无码、素人、FC2、欧美、国产后面不要标深色，和其他站点一样纯白背景就行，
        不要空着啊，继续排列DMM、DMM_API、LibreDMM等站点」

六个分组标题后来从「六个标题各占一行」改成「开头六个加粗标题、后面紧接站点」的普通
流式排布（见 test_site_source_type_groups.py），「点在某个标题上复制它自己那一份」
这条语义不变，只是命中判定回到「那一行项目的矩形」。

复制出的文本必须是逗号分隔的站点名序列，且与设置页输入框里的格式一致——
这是「复制」这件事真正有用的前提：粘回输入框（或粘给同事）能被 _parse_sites
原样认出来。用分号、换行或带方括号都会让复制结果粘不回去。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QListWidget, QMenu  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.config.models import FieldPriorityConfig  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    FieldPriorityDialog,
    SiteListEditorDialog,
    SitePaletteList,
    _group_sites_at,
    _is_group_item,
    _list_sites,
    _parse_sites,
    _sites_text,
)
from mdcx.gen.field_enums import CrawlerResultFields  # noqa: E402

ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]

# 选中顺序即优先级，复制出来必须原样保持，不能被 A-Z 或分组重排
CUSTOM_ORDER = [Website.XCITY, Website.MGSTAGE, Website.GETCHU, Website.DMM]

# 顶部六个标题的次序（与需求给的次序一致）
CHIP_ORDER = ["有码", "无码", "素人", "FC2", "欧美", "国产"]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _shown(dlg) -> None:
    """摆出来并跑一遍布局：`visualItemRect` 要布局完成后才有意义。"""
    dlg.resize(860, 640)
    dlg.show()
    QApplication.processEvents()


def _center(list_widget, item) -> QPoint:
    return list_widget.visualItemRect(item).center()


def _blank_corner(list_widget) -> QPoint:
    """视口右下角：两个列表都是换行流式排布，最后一行之后必然是空白。"""
    viewport = list_widget.viewport()
    return QPoint(max(1, viewport.width() - 2), max(1, viewport.height() - 2))


def _right_click(list_widget, point, monkeypatch, pick: str) -> list[str]:
    """弹出右键菜单并选中文字以 pick 开头的那一项；返回菜单项文案列表。"""
    captured: list[QMenu] = []

    def fake_exec(self, *args, **kwargs):
        captured.append(self)
        for action in self.actions():
            if action.text().startswith(pick):
                return action
        raise AssertionError(f"菜单里没有「{pick}」开头的项：{[a.text() for a in self.actions()]}")

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    list_widget.customContextMenuRequested.emit(point)
    return [action.text() for action in captured[-1].actions()]


def _row_of(list_widget, site_value: str) -> int:
    return next(
        row for row in range(list_widget.count()) if list_widget.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


def _title_rows(palette) -> dict[str, int]:
    """{标题: 行号}；候选区应当恰好六个标题。"""
    rows = {str(palette.item(row).text()): row for row in range(palette.count()) if _is_group_item(palette.item(row))}
    assert list(rows) == CHIP_ORDER, f"标题不是 {CHIP_ORDER}：{list(rows)}"
    return rows


def _title_center(palette, title: str) -> QPoint:
    """标题那一格的中点：点它等于右键点在这个标题上。"""
    rect = palette.visualItemRect(palette.item(_title_rows(palette)[title]))
    assert rect.isValid() and rect.width() > 0, f"标题「{title}」没有可见矩形"
    return rect.center()


def _group_at(palette, title: str) -> list[Website]:
    """标题自带的成员名单（单击加入与右键复制都以它为唯一依据）。"""
    sites = _group_sites_at(palette, _title_rows(palette)[title])
    assert sites, f"标题「{title}」没有带成员名单"
    return list(sites)


def test_right_click_site_copies_only_that_site(qt_app, monkeypatch):
    """点在单个站点上：剪贴板里只应是这个站点的名字。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        item = dlg.selected_list.item(1)  # CUSTOM_ORDER[1] = MGStage
        texts = _right_click(dlg.selected_list, _center(dlg.selected_list, item), monkeypatch, "复制站点")
        assert texts == ["复制站点：MGStage", "", "复制列表（4 个站点）"]
        assert app.clipboard().text() == "MGStage"
    finally:
        dlg.deleteLater()


def test_right_click_blank_area_copies_the_whole_list(qt_app, monkeypatch):
    """点在空白处：复制整张列表，按列表里的顺序、逗号分隔。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        texts = _right_click(dlg.selected_list, _blank_corner(dlg.selected_list), monkeypatch, "复制列表")
        assert texts == ["复制列表（4 个站点）"]
        assert app.clipboard().text() == "Xcity,MGStage,Getchu,DMM"
    finally:
        dlg.deleteLater()


def test_copied_list_is_readable_back_by_the_parser(qt_app, monkeypatch):
    """复制出的文本粘回输入框能被原样解析回来——否则「复制」没有意义。"""
    app = qt_app
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        _right_click(dlg.selected_list, _blank_corner(dlg.selected_list), monkeypatch, "复制列表")
        assert _parse_sites(app.clipboard().text()) == CUSTOM_ORDER
        assert app.clipboard().text() == _sites_text(CUSTOM_ORDER)
    finally:
        dlg.deleteLater()


def test_right_click_group_title_copies_that_group_only(qt_app, monkeypatch):
    """点在分组标题上：复制的是这一组自己的名单，不是整张 39 站列表。

    这是「辛辛苦苦分类」的意义所在——六个类型是六份不同的名单，复制整张等于分类白做。
    """
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        texts = _right_click(palette, _title_center(palette, "有码"), monkeypatch, "复制本组")
        assert texts == ["复制本组「有码」（31 个站点）", "", "复制列表（39 个站点）"]
        copied = app.clipboard().text().split(",")
        assert copied[:3] == ["DMM", "DMM_API", "LibreDMM"]
        assert len(copied) == 31 == len(set(copied))
        # 别的组才有的站点不能混进来（MyWife 不属于任何一组）
        assert "MyWife" not in copied and "Madouqu" not in copied
        assert _parse_sites(app.clipboard().text()) == _group_at(palette, "有码")
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("title", "count"),
    [("有码", 31), ("无码", 18), ("素人", 29), ("FC2", 15), ("欧美", 14), ("国产", 14)],
)
def test_each_group_title_copies_its_own_list(qt_app, monkeypatch, title, count):
    """六个标题各自复制各自那份名单，互不相等，也不会复制成 39 站。"""
    app = qt_app
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        texts = _right_click(palette, _title_center(palette, title), monkeypatch, "复制本组")
        assert texts[0] == f"复制本组「{title}」（{count} 个站点）"
        copied = app.clipboard().text().split(",")
        assert len(copied) == count
        assert len(copied) < len(_list_sites(palette))
    finally:
        dlg.deleteLater()


def test_group_copy_is_readable_back_by_the_parser(qt_app, monkeypatch):
    """复制某一组的名单同样要能粘回输入框。"""
    app = qt_app
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        _right_click(palette, _title_center(palette, "FC2"), monkeypatch, "复制本组")
        assert _parse_sites(app.clipboard().text()) == _group_at(palette, "FC2")
        assert app.clipboard().text() == _sites_text(_group_at(palette, "FC2"))
    finally:
        dlg.deleteLater()


def test_right_click_gap_between_titles_copies_the_whole_list(qt_app, monkeypatch):
    """点在首行的空白处不该复制某一组，退回「复制整张列表」。

    首行是 `有码 无码 … 国产 DMM …` 流式排布的一行，chip 之间与行尾的空白同样可能
    误判成「点中标题」——误判就会给用户一份他根本没点的名单。
    """
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        top = palette.visualItemRect(palette.item(_title_rows(palette)["有码"])).top()
        blank = next(
            (x for x in range(1, palette.viewport().width() - 1) if palette.itemAt(QPoint(x, top)) is None), None
        )
        assert blank is not None, "首行末尾没有空白处可测"
        texts = _right_click(palette, QPoint(blank, top), monkeypatch, "复制列表")
        assert texts == ["复制列表（39 个站点）"]
    finally:
        dlg.deleteLater()


def test_palette_copy_covers_every_site_once(qt_app, monkeypatch):
    """候选区每个站只出现一行，复制出的列表既不重复也不漏（含 MyWife）。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _right_click(dlg.available_list, _blank_corner(dlg.available_list), monkeypatch, "复制列表")
        copied = app.clipboard().text().split(",")
        assert len(copied) == len(set(copied)) == len(_list_sites(dlg.available_list))
        assert copied[:2] == ["DMM", "DMM_API"]
        # 唯一没进任何一组的 MyWife 也得在（它接在站点区末尾，不另起「其他」标题）
        assert copied[-1] == "MyWife"
    finally:
        dlg.deleteLater()


def test_no_menu_when_list_is_empty(qt_app, monkeypatch):
    """空列表上右键不该弹一个只能复制空串的菜单。"""
    shown: list[QMenu] = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: shown.append(self))
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        dlg._clear_selected()
        dlg.selected_list.customContextMenuRequested.emit(_blank_corner(dlg.selected_list))
        assert shown == []
    finally:
        dlg.deleteLater()


def test_context_menu_policy_is_custom_on_both_lists(qt_app):
    """两个列表都得自己处理右键，否则菜单不弹（Qt 默认策略在部分样式下会直接吞掉）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        for list_widget in (dlg.available_list, dlg.selected_list):
            assert list_widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    finally:
        dlg.deleteLater()


def test_field_priority_palette_also_copies(qt_app, monkeypatch):
    """「字段优先级」对话框顶部的可用网站同样支持右键复制（它不分组，故没有标题）。"""
    app = qt_app
    app.clipboard().clear()
    dlg = FieldPriorityDialog("t", CUSTOM_ORDER, CUSTOM_ORDER, {CrawlerResultFields.TITLE: FieldPriorityConfig()}, None)
    try:
        palette = next(w for w in dlg.findChildren(QListWidget) if isinstance(w, SitePaletteList))
        assert [row for row in range(palette.count()) if _is_group_item(palette.item(row))] == []
        _right_click(palette, _blank_corner(palette), monkeypatch, "复制列表")
        assert app.clipboard().text() == "Xcity,MGStage,Getchu,DMM"
    finally:
        dlg.deleteLater()
