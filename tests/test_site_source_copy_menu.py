"""「编辑网站」对话框：右键复制单个站点 / 单个分组 / 整张站点列表，以及「加入列表：启用网站」。

用户需求原文（四轮）：
    1.「鼠标右键点击时可以复制站点列表，单个站点鼠标右键点击也可以复制」
    2.「有码、无码、素人、FC2、欧美、国产右键复制不是复制全部39个站点，
        是复制它们各自包含的站点」
    3.「有码、无码、素人、FC2、欧美、国产后面不要标深色，和其他站点一样纯白背景就行，
        不要空着啊，继续排列DMM、DMM_API、LibreDMM等站点」
    4.「有码、无码、素人、个摄、欧美、国产、动漫由鼠标单击加入启用网站列表改成由鼠标
        双击时才加入启用网站列表，右键菜单里加上加入启用网站列表，排在在最下方」

六个分组标题后来从「六个标题各占一行」改成「开头六个加粗标题、后面紧接站点」的普通
流式排布（见 test_site_source_type_groups.py），「点在某个标题上复制它自己那一份」
这条语义不变，只是命中判定回到「那一行项目的矩形」。整组加入原先是**单击**，第 4 条
改成**双击**（那条一并锁在 test_site_source_type_groups.py），右键菜单则多出最下方一项
「加入列表：启用网站」（第 4 条原文写作「加入启用网站列表」，随后按用户要求改成
「加入列表：启用网站」，与同菜单里的「复制列表：N个站点」对齐）——本文件锁的正是它的
位置、出现范围与三种落点的语义。

复制出的文本必须是逗号分隔的站点名序列，且与设置页输入框里的格式一致——
这是「复制」这件事真正有用的前提：粘回输入框（或粘给同事）能被 _parse_sites
原样认出来。用分号、换行或带方括号都会让复制结果粘不回去。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QListWidget, QMenu  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.config.models import FieldPriorityConfig  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    PALETTE_SORT_KEYS,
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

# 顶部七个短名 chip 的次序（与 PALETTE_GROUP_TITLES / PALETTE_GROUP_TYPES 的组序一致）
CHIP_ORDER = ["有码", "无码", "个摄", "欧美", "传媒", "短剧", "动漫"]


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


def _menu_actions(list_widget, point, monkeypatch) -> list[QAction]:
    """只把菜单弹出来看一眼（选第一项即可），返回菜单里那一串 QAction。"""
    captured: list[QMenu] = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.append(self) or self.actions()[0])
    list_widget.customContextMenuRequested.emit(point)
    return captured[-1].actions()


def _row_of(list_widget, site_value: str) -> int:
    return next(
        row for row in range(list_widget.count()) if list_widget.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


def _right_press(list_widget, point) -> None:
    """真的按一次右键（按下+松开），而不是手工发 contextMenuRequested 信号。

    信号那一条路跳过了 `QAbstractItemView` 的按下处理——正是它会在右键时顺手选中
    被点的格子，于是格子被套上 `:selected` 的内部方框（用户截图里那个）。
    """
    QTest.mousePress(list_widget.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseRelease(list_widget.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
    QApplication.processEvents()


def _fill_at(list_widget, point) -> str:
    """某一点所在格子的填充色（选中态与常态差得很明显，用它验证有没有被选中）。"""
    color = list_widget.viewport().grab().toImage().pixelColor(point)
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def _title_rows(palette) -> dict[str, int]:
    """{标题: 行号}；候选区应当恰好七个标题（六类 + 动漫）。"""
    rows = {str(palette.item(row).text()): row for row in range(palette.count()) if _is_group_item(palette.item(row))}
    assert list(rows) == CHIP_ORDER, f"标题不是 {CHIP_ORDER}：{list(rows)}"
    return rows


def _title_center(palette, title: str) -> QPoint:
    """标题那一格的中点：点它等于右键点在这个标题上。"""
    rect = palette.visualItemRect(palette.item(_title_rows(palette)[title]))
    assert rect.isValid() and rect.width() > 0, f"标题「{title}」没有可见矩形"
    return rect.center()


def _group_at(palette, title: str) -> list[Website]:
    """标题自带的成员名单（双击加入与右键复制都以它为唯一依据）。"""
    sites = _group_sites_at(palette, _title_rows(palette)[title])
    assert sites, f"标题「{title}」没有带成员名单"
    return list(sites)


def _values(sites) -> list[str]:
    return [site.value for site in sites]


def _site_center(palette, site_value: str) -> QPoint:
    return _center(palette, palette.item(_row_of(palette, site_value)))


ADD_ACTION = "加入列表：启用网站"


def test_add_action_sits_at_the_bottom_of_the_palette_menu(qt_app, monkeypatch):
    """「加入列表：启用网站」排在菜单最下方（用户指定），且与两条「复制」隔开。

    菜单顺序是有讲究的：右键绝大多数时候是为了复制，加入得是刻意滚到最后去点的那一项，
    所以它既不在最上面、也不夹在两条复制项中间。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        texts = _right_click(palette, _title_center(palette, "有码"), monkeypatch, "复制本组")
        assert texts == ["复制本组：28个站点", "", "复制列表：39个站点", "", ADD_ACTION]
        assert texts[-1] == ADD_ACTION, ADD_ACTION
    finally:
        dlg.deleteLater()


def test_add_action_is_absent_from_the_other_lists(qt_app, monkeypatch):
    """只有候选区有这一项：「启用网站」列表与「字段优先级」那几行没有「启用列表」可言。

    没有「启用网站列表」的地方却摆一项同名动作，用户点了只会不知道加到哪儿去。
    """
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    priority = FieldPriorityDialog(
        "t",
        CUSTOM_ORDER,
        CUSTOM_ORDER,
        {CrawlerResultFields.TITLE: FieldPriorityConfig(site_prority=CUSTOM_ORDER)},
        None,
    )
    try:
        _shown(dlg)
        assert dlg.selected_list.on_add_to_enabled is None
        enabled = _right_click(dlg.selected_list, _site_center(dlg.selected_list, "MGStage"), monkeypatch, "复制站点")
        assert ADD_ACTION not in enabled, enabled

        palette = next(w for w in priority.findChildren(QListWidget) if isinstance(w, SitePaletteList))
        assert palette.on_add_to_enabled is None
        field_list = next(iter(priority._field_lists.values()))
        fields = _right_click(field_list, _center(field_list, field_list.item(0)), monkeypatch, "复制站点")
        assert ADD_ACTION not in fields, fields
    finally:
        dlg.deleteLater()
        priority.deleteLater()


def test_add_action_on_a_group_title_adds_the_whole_group(qt_app, monkeypatch):
    """右键点标题 → 整组加入（与双击同一套名单、同一套次序）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        _right_click(palette, _title_center(palette, "有码"), monkeypatch, ADD_ACTION)
        assert _values(dlg.selected_sites()) == _values(_group_at(palette, "有码"))
    finally:
        dlg.deleteLater()


def test_add_action_on_a_site_adds_only_that_site(qt_app, monkeypatch):
    """右键点站点 → 只加那一个：右键不改选中态，不能顺手把选中的那批一起加进来。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        palette.item(_row_of(palette, "IQQTV")).setSelected(True)
        _right_click(palette, _site_center(palette, "Dahlia"), monkeypatch, ADD_ACTION)
        assert dlg.selected_sites() == [Website.DAHLIA]
    finally:
        dlg.deleteLater()


def test_add_action_on_blank_area_adds_the_selected_sites(qt_app, monkeypatch):
    """右键点空白处 → 加当前选中的那些（等价于「添加选中」按钮）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        for value in ("Xcity", "IQQTV"):
            palette.item(_row_of(palette, value)).setSelected(True)
        _right_click(palette, _blank_corner(palette), monkeypatch, ADD_ACTION)
        assert _values(dlg.selected_sites()) == ["Xcity", "IQQTV"]
    finally:
        dlg.deleteLater()


def test_add_action_appends_and_keeps_existing_order(qt_app, monkeypatch):
    """右键加入与双击同一套规矩：已启用的留在原位，新加的接在后面。"""
    dlg = SiteListEditorDialog("t", [Website.XCITY], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        _right_click(palette, _title_center(palette, "传媒"), monkeypatch, ADD_ACTION)
        values = _values(dlg.selected_sites())
        assert values[0] == "Xcity"
        assert values[1:] == _values(_group_at(palette, "传媒"))
    finally:
        dlg.deleteLater()


def test_add_action_leaves_the_clipboard_alone(qt_app, monkeypatch):
    """选「加入」不写剪贴板——它不是复制，别把用户的剪贴板内容顺手换掉。"""
    app = qt_app
    app.clipboard().setText("原有内容")
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        _right_click(dlg.available_list, _site_center(dlg.available_list, "Dahlia"), monkeypatch, ADD_ACTION)
        assert app.clipboard().text() == "原有内容"
        assert dlg.selected_sites() == [Website.DAHLIA]
    finally:
        dlg.deleteLater()


def test_add_action_is_disabled_only_when_there_is_nothing_to_add(qt_app, monkeypatch):
    """点在空白处又没选中任何站点时它是灰的——否则点了列表纹丝不动，像坏了。

    点了站点或点了标题都无站不可加，只有「空白处 + 无选中」这一种落点是空转。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list

        def add_enabled_at(point) -> bool:
            return next(a.isEnabled() for a in _menu_actions(palette, point, monkeypatch) if a.text() == ADD_ACTION)

        assert add_enabled_at(_blank_corner(palette)) is False
        assert add_enabled_at(_site_center(palette, "Dahlia")) is True
        assert add_enabled_at(_title_center(palette, "有码")) is True
        palette.item(_row_of(palette, "Dahlia")).setSelected(True)
        assert add_enabled_at(_blank_corner(palette)) is True
    finally:
        dlg.deleteLater()


def test_right_click_site_copies_only_that_site(qt_app, monkeypatch):
    """点在单个站点上：剪贴板里只应是这个站点的名字。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        item = dlg.selected_list.item(1)  # CUSTOM_ORDER[1] = MGStage
        texts = _right_click(dlg.selected_list, _center(dlg.selected_list, item), monkeypatch, "复制站点")
        assert texts == ["复制站点：MGStage", "", "复制列表：4个站点"]
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
        assert texts == ["复制列表：4个站点"]
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
        assert texts == ["复制本组：28个站点", "", "复制列表：39个站点", "", "加入列表：启用网站"]
        copied = app.clipboard().text().split(",")
        assert copied[:3] == ["DMM", "DMM_API", "LibreDMM"]
        assert len(copied) == 28 == len(set(copied))
        # 别的组才有的站点不能混进来（MyWife 不属于任何一组）
        assert "MyWife" not in copied and "Madouqu" not in copied
        assert _parse_sites(app.clipboard().text()) == _group_at(palette, "有码")
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("title", "count"),
    [
        ("有码", 28),
        ("无码", 15),
        ("个摄", 12),
        ("欧美", 10),
        ("传媒", 10),
        ("短剧", 1),
        ("动漫", 4),
    ],
)
def test_each_group_title_copies_its_own_list(qt_app, monkeypatch, title, count):
    """七个标题各自复制各自那份名单，互不相等，也不会复制成 39 站。"""
    app = qt_app
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg)
        palette = dlg.available_list
        texts = _right_click(palette, _title_center(palette, title), monkeypatch, "复制本组")
        assert texts[0] == f"复制本组：{count}个站点"
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
        _right_click(palette, _title_center(palette, "个摄"), monkeypatch, "复制本组")
        assert _parse_sites(app.clipboard().text()) == _group_at(palette, "个摄")
        assert app.clipboard().text() == _sites_text(_group_at(palette, "个摄"))
    finally:
        dlg.deleteLater()


def test_right_click_gap_between_titles_copies_the_whole_list(qt_app, monkeypatch):
    """点在首行的空白处不该复制某一组，退回「复制整张列表」。

    首行是 `有码 无码 … 传媒 DMM …` 流式排布的一行，chip 之间与行尾的空白同样可能
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
        assert texts == ["复制列表：39个站点", "", "加入列表：启用网站"]
    finally:
        dlg.deleteLater()


def test_palette_copy_covers_every_site_once(qt_app, monkeypatch):
    """候选区每个站只出现一行、且是 A-Z 序，复制出的列表既不重复也不漏。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _right_click(dlg.available_list, _blank_corner(dlg.available_list), monkeypatch, "复制列表")
        copied = app.clipboard().text().split(",")
        assert len(copied) == len(set(copied)) == len(_list_sites(dlg.available_list))
        # 少数几站有单独的排序键（PALETTE_SORT_KEYS），比对时用同一把尺子
        keys = [PALETTE_SORT_KEYS.get(Website(value), value).casefold() for value in copied]
        assert keys == sorted(keys), "候选区复制出来的不是排序键顺序"
        assert copied[:2] == ["7mmtv", "Airav.cc"]
        # 不属任何一组的 MyWife 也在里面（它只是没有自己的标题，不是不能选）
        assert "MyWife" in copied and copied[-1] == "Xcity"
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


def _right_click_leaves_the_lists_untouched(qt_app, which: str) -> None:
    """右键只弹菜单：选中态与当前项都保持原样，被点的那格也不该多出内部方框。

    QAbstractItemView 默认会在右键按下时顺手「选中」被点的格子，于是那一格被套上
    QSS 的 `:selected`（比常态深一档、还带边框）——用户截图里就是这个内部方框。
    右键是「看一眼/复制一下」，不该改变列表的选中状态；单击选中仍然是原样行为。
    """
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        _shown(dlg)
        list_widget = dlg.available_list if which == "palette" else dlg.selected_list
        # Getchu / DMM 两个候选区与「启用网站」列表里都有，才能两边共用同一组断言
        point = _center(list_widget, list_widget.item(_row_of(list_widget, "DMM")))
        # 基准是「鼠标悬停但没选中」的填充色：悬停本来就会浅一档，跟选中态不是一回事，
        # 直接拿没悬停的格子当基准会把悬停误判成选中。
        QTest.mouseMove(list_widget.viewport(), point)
        QApplication.processEvents()
        hover_fill = _fill_at(list_widget, point)
        before = sorted(list_widget.row(item) for item in list_widget.selectedItems())
        current_before = list_widget.currentRow()

        _right_press(list_widget, point)

        after = sorted(list_widget.row(item) for item in list_widget.selectedItems())
        assert after == before, f"右键把选中项改了：{before} → {after}"
        assert list_widget.currentRow() == current_before, "右键把当前项改了"
        assert _fill_at(list_widget, point) == hover_fill, "被右键的那格多了内部方框（被当成选中了）"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("which", ["palette", "enabled"])
def test_right_click_does_not_select_the_pressed_cell(qt_app, which):
    _right_click_leaves_the_lists_untouched(qt_app, which)


@pytest.mark.parametrize("which", ["palette", "enabled"])
def test_left_click_still_selects(qt_app, which):
    """别把右键那套「恢复现场」误伤到左键：单击选中是这两个列表的基本操作。"""
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        _shown(dlg)
        list_widget = dlg.available_list if which == "palette" else dlg.selected_list
        row = _row_of(list_widget, "DMM")
        QTest.mouseClick(
            list_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            _center(list_widget, list_widget.item(row)),
        )
        QApplication.processEvents()
        assert [list_widget.row(item) for item in list_widget.selectedItems()] == [row]
    finally:
        dlg.deleteLater()


def test_right_click_still_copies_the_pressed_site(qt_app, monkeypatch):
    """不选中 ≠ 不能复制：菜单读的是按下的那一格（`itemAt(pos)`），不是选中项。"""
    app = qt_app
    app.clipboard().clear()
    dlg = SiteListEditorDialog("t", CUSTOM_ORDER, ALL_SITES, None)
    try:
        _shown(dlg)
        point = _center(dlg.selected_list, dlg.selected_list.item(_row_of(dlg.selected_list, "MGStage")))
        _right_press(dlg.selected_list, point)
        assert dlg.selected_list.item(_row_of(dlg.selected_list, "MGStage")).isSelected() is False, "右键选中了"
        texts = _right_click(dlg.selected_list, point, monkeypatch, "复制站点")
        assert texts[0] == "复制站点：MGStage"
        assert app.clipboard().text() == "MGStage"
    finally:
        dlg.deleteLater()
