"""「编辑网站」对话框：可用网站（网址源）按有码/无码/素人/FC2/欧美/国产分组展示。

用户需求原文：
    「在所有网站前加上有码、无码、素人、FC2、欧美、国产这几个选项」
    ——逐组给出的站点清单，组内顺序即优先级递减，不得改动排序。

三条约束必须同时成立，所以这里逐条锁住：
    1. 六个分组标题按用户给的次序出现，且每组内是用户给的名单与顺序；
    2. 分组标题行不参与「加入启用列表」——不可选中、不可拖拽、不带 UserRole；
    3. 启用列表的顺序仍旧完全由用户决定（分组只作用于候选区的展示）。

另外还锁了一条「候选区分组 == 配置默认名单」的不变量：两者同源于
models.TYPE_DEFAULT_SITES，一旦各改各的，用户看到的分组就会和实际默认行为对不上，
而且没有任何报错提示。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import TYPE_DEFAULT_SITES, Config  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    OTHER_PALETTE_GROUP_TITLE,
    PALETTE_GROUP_TYPES,
    SITE_GROUP_ROLE,
    SiteListEditorDialog,
    _list_sites,
    grouped_palette_entries,
)

# 用注册表全量真实站点，才能覆盖到 Airav.cc / 7mmtv / MyWife 这类边界值
ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]

# 用户需求里逐组给出的名单（组内顺序 = 优先级递减，不得重排）。这里原样抄一遍当期望值，
# 免得「实现和常量表一起被改错」时测试还照样绿。
USER_SITE_LISTS = {
    FixedScrapingType.YOUMA: [
        "DMM",
        "DMM_API",
        "LibreDMM",
        "AVEntertainments",
        "Dahlia",
        "Faleno",
        "MGStage",
        "Prestige",
        "Official",
        "AVBase",
        "AVMOO",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "Airav.cc",
        "FreeJavBT",
        "IQQTV",
        "Lulubar",
        "MissAV",
        "MissAV_API",
        "R18.dev",
        "Xcity",
        "TheJavDB_API",
        "JavLibrary",
        "AVSEX",
        "Getchu",
    ],
    FixedScrapingType.WUMA: [
        "AVEntertainments",
        "AVSOX",
        "Official",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "Airav.cc",
        "FreeJavBT",
        "IQQTV",
        "Lulubar",
        "MissAV",
        "MissAV_API",
        "AVSEX",
        "Getchu",
    ],
    FixedScrapingType.SUREN: [
        "DMM",
        "DMM_API",
        "LibreDMM",
        "AVEntertainments",
        "MGStage",
        "Prestige",
        "Official",
        "AVBase",
        "AVMOO",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "Airav.cc",
        "FreeJavBT",
        "IQQTV",
        "Lulubar",
        "MissAV",
        "MissAV_API",
        "R18.dev",
        "Xcity",
        "TheJavDB_API",
        "JavLibrary",
        "AVSEX",
        "Getchu",
    ],
    FixedScrapingType.FC2: [
        "FC2",
        "FC2PPVDB",
"AVSOX",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "IQQTV",
        "MissAV",
        "MissAV_API",
        "AVSEX",
        "Getchu",
    ],
    FixedScrapingType.OUMEI: [
        "ThepornDB",
        "AVheat",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "7mmtv",
        "MissAV",
        "MissAV_API",
        "IQQTV",
        "JavFree",
        "AVSEX",
        "Getchu",
    ],
    FixedScrapingType.GUOCHAN: [
        "Madouqu",
        "Madou.club",
        "AVSEX",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "IQQTV",
        "MissAV",
        "MissAV_API",
        "Getchu",
    ],
}

# 需求标题里给出的分组次序：有码、无码、素人、FC2、欧美、国产
EXPECTED_GROUP_ORDER = ["有码", "无码", "素人", "FC2", "欧美", "国产"]

# 候选区各组的标题（取自 TYPE_TITLES，六组之外的 DONGMAN 不参与分组）
USER_TITLES = dict(zip(PALETTE_GROUP_TYPES, EXPECTED_GROUP_ORDER, strict=True))

# MyWife 不属于任何类型组：它是「人妻・熟女・3P」独立系列，走「指定网站」或路径含
# mywife 单独指定，不进任何类型组名单，因此候选区里单独收在「其他」下。
EXPECTED_GROUPS = {
    **{title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()},
    OTHER_PALETTE_GROUP_TITLE: ["MyWife"],
}

# 非分组的原始顺序：按此断言「全部添加」未被分组展示污染
UNGROUPED_ORDER = [Website.DMM, Website.AVBASE, Website.XCITY, Website.GETCHU]

# 六组各自的 Config 字段名，用于锁「候选区分组 == 配置默认名单」
TYPE_CONFIG_FIELDS = {
    FixedScrapingType.YOUMA: "website_youma",
    FixedScrapingType.WUMA: "website_wuma",
    FixedScrapingType.SUREN: "website_suren",
    FixedScrapingType.FC2: "website_fc2",
    FixedScrapingType.OUMEI: "website_oumei",
    FixedScrapingType.GUOCHAN: "website_guochan",
}


def _groups_of(entries) -> dict[str, list[str]]:
    """把 PaletteEntry 序列压成 {分组标题: 组内站点名}，顺便验证每组都以标题行开头。"""
    groups: dict[str, list[str]] = {}
    current = None
    for entry in entries:
        if entry.site is None:
            current = entry.title
            assert current not in groups, f"分组「{current}」重复出现"
            groups[current] = []
        else:
            assert current is not None, "站点出现在任何分组标题之前"
            groups[current].append(entry.site.value)
    return groups


def _groups_from_widget(dialog) -> dict[str, list[str]]:
    """直接读对话框里已铺好的候选区，确保 UI 用的就是上面那套装序逻辑。"""
    groups: dict[str, list[str]] = {}
    current = None
    for row in range(dialog.available_list.count()):
        item = dialog.available_list.item(row)
        if item.data(SITE_GROUP_ROLE) is not None:
            current = item.data(SITE_GROUP_ROLE)
            assert current not in groups, f"分组「{current}」重复出现"
            groups[current] = []
        else:
            assert current is not None, "站点出现在任何分组标题之前"
            groups[current].append(item.data(Qt.ItemDataRole.UserRole))
    return groups


def _title_rows(dialog) -> list[int]:
    return [
        row
        for row in range(dialog.available_list.count())
        if dialog.available_list.item(row).data(SITE_GROUP_ROLE) is not None
    ]


def _row_of(dialog, site_value: str) -> int:
    return next(
        row
        for row in range(dialog.available_list.count())
        if dialog.available_list.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dialog(qt_app):
    dlg = SiteListEditorDialog("编辑测试网站源", [Website.DMM, Website.AVBASE], ALL_SITES, None)
    try:
        yield dlg
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- 纯函数层


def test_group_titles_follow_the_requested_order():
    """分组标题按需求给的次序：先有码，最后国产。"""
    entries = grouped_palette_entries(ALL_SITES)
    titles = [entry.title for entry in entries if entry.site is None]
    assert titles == [*EXPECTED_GROUP_ORDER, OTHER_PALETTE_GROUP_TITLE]


def test_each_group_lists_exactly_the_requested_sites_in_order():
    """每组内的站点与顺序，逐项等于用户给的清单。"""
    assert _groups_of(grouped_palette_entries(ALL_SITES)) == EXPECTED_GROUPS


def test_groups_match_config_defaults():
    """候选区的分组与 Config 默认名单同源同序。

    两者一旦漂移，用户看到的分组是一套、装好程序实际用的默认名单是另一套，
    且没有任何报错，只是「选了没生效」。
    """
    config = Config()
    for scraping_type, field in TYPE_CONFIG_FIELDS.items():
        assert [site.value for site in getattr(config, field)] == [
            site.value for site in TYPE_DEFAULT_SITES[scraping_type]
        ], f"{scraping_type.name} 的默认名单与常量表不一致"


def test_every_grouped_site_has_a_registered_crawler():
    """分组里的站点必须都已注册爬虫——否则用户在该组里根本加不上它。"""
    registered = set(ALL_SITES)
    for sites in TYPE_DEFAULT_SITES.values():
        assert set(sites) <= registered, f"含未注册站点：{sorted(set(sites) - registered)}"


def test_grouped_palette_keeps_every_available_site():
    """分组只是排版手段：一个候选站点都不能因此消失。"""
    grouped_sites = [entry.site for entry in grouped_palette_entries(ALL_SITES) if entry.site is not None]
    # 允许重复（一个站点可同属多组），但必须完整覆盖传入集合
    assert set(grouped_sites) == set(ALL_SITES)


def test_empty_candidate_list_produces_no_groups():
    assert grouped_palette_entries([]) == []


def test_group_without_available_sites_leaves_no_empty_title():
    """某一组在本机没有候选站点时不留空标题，否则会多出五个点开没内容的分组。"""
    entries = grouped_palette_entries([Website.FALENO])
    assert _groups_of(entries) == {"有码": ["Faleno"]}


def test_sites_outside_every_group_collect_into_other():
    """落在六组之外的站点（如 MyWife）按传入次序收进「其他」，不丢。

    DMM/AVSOX 本身就同属多个组，会在每个组里各出现一次——它确实是这些类型的可用来源。
    """
    entries = grouped_palette_entries([Website.MYWIFE, Website.DMM, Website.AVSOX])
    assert _groups_of(entries) == {
        "有码": ["DMM"],
        "无码": ["AVSOX"],
        "素人": ["DMM"],
        "FC2": ["AVSOX"],
        "其他": ["MyWife"],
    }


def test_does_not_mutate_input():
    source = list(UNGROUPED_ORDER)
    grouped_palette_entries(source)
    assert source == UNGROUPED_ORDER


# --------------------------------------------------------------------------- 对话框运行期


def test_palette_shows_the_requested_groups(dialog):
    """候选区 = 六个分组 + 「其他」，组内站点与顺序逐项等于需求清单。"""
    assert _groups_from_widget(dialog) == EXPECTED_GROUPS


def test_group_title_rows_are_inert(dialog):
    """标题行不可选中、不可拖拽、不带 UserRole——不会被当成站点加进启用列表。"""
    rows = _title_rows(dialog)
    assert len(rows) == len(EXPECTED_GROUPS)
    for row in rows:
        item = dialog.available_list.item(row)
        assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
        assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled
        assert item.data(Qt.ItemDataRole.UserRole) is None

    site_rows = sum(1 for row in range(dialog.available_list.count()) if row not in rows)
    # 站点行总数 = 六组之和 + 其他；标题行不计入，去重后的站点数则少于行数
    assert site_rows == sum(len(v) for v in USER_SITE_LISTS.values()) + 1
    assert len(_list_sites(dialog.available_list)) == len(ALL_SITES) < site_rows


def test_double_clicking_a_group_title_adds_nothing(qt_app):
    """双击标题不能把上次选中的残留站点顺带加进去；双击站点仍然正常加入。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        dlg._on_available_double_clicked(dlg.available_list.item(_title_rows(dlg)[0]))
        assert dlg.selected_sites() == []

        row = _row_of(dlg, "7mmtv")
        dlg.available_list.item(row).setSelected(True)
        dlg._on_available_double_clicked(dlg.available_list.item(row))
        assert dlg.selected_sites() == [Website.MMTV]
    finally:
        dlg.deleteLater()


def test_enabled_list_keeps_user_order(dialog):
    """分组只作用于候选区；启用列表进来是什么顺序就保持什么顺序。"""
    assert [site.value for site in dialog.selected_sites()] == ["DMM", "AVBase"]
    assert [site.value for site in _list_sites(dialog.selected_list)] == ["DMM", "AVBase"]


def test_enabled_order_and_groups_survive_refresh(dialog):
    """_refresh_lists 会重画候选区，分组不能刷没、启用列表也不能被重排。"""
    dialog._refresh_lists()
    assert [site.value for site in dialog.selected_sites()] == ["DMM", "AVBase"]
    assert _groups_from_widget(dialog) == EXPECTED_GROUPS


def test_add_selected_appends_in_palette_order(qt_app):
    """一次多选时，新站点按候选区里的行序追加，老站点的相对优先级不动。

    行序 = 分组序，同一站点取它第一次出现的那一行：DMM、7mmtv、Getchu 里，
    7mmtv 在有码组、Getchu 也在有码组且排最后，所以 Getchu 反而先加。
    """
    dlg = SiteListEditorDialog("t", [Website.XCITY, Website.DMM], ALL_SITES, None)
    try:
        for value in ("Getchu", "7mmtv"):
            dlg.available_list.item(_row_of(dlg, value)).setSelected(True)
        dlg._add_selected()
        values = [site.value for site in dlg.selected_sites()]
        assert values[:2] == ["Xcity", "DMM"]
        assert values[2:] == ["Getchu", "7mmtv"]
    finally:
        dlg.deleteLater()


def test_add_all_uses_original_order_while_palette_stays_grouped(qt_app):
    """「全部添加」写进启用列表的是传入原序，候选区展示仍是分组的。"""
    dlg = SiteListEditorDialog("t", [], UNGROUPED_ORDER, None)
    try:
        dlg._add_all()
        assert [site.value for site in dlg.selected_sites()] == ["DMM", "AVBase", "Xcity", "Getchu"]
        # 候选区仍按各组自己的优先级序排：Getchu 在有码/素人组里排最后、无码组里排最前
        assert _groups_from_widget(dlg) == {
            "有码": ["DMM", "AVBase", "Xcity", "Getchu"],
            "无码": ["Getchu"],
            "素人": ["DMM", "AVBase", "Xcity", "Getchu"],
            "FC2": ["Getchu"],
            "欧美": ["Getchu"],
            "国产": ["Getchu"],
        }
    finally:
        dlg.deleteLater()


def test_group_expansion_still_works_from_grouped_palette(qt_app):
    """联动组不因分组而失效：从按类型铺开的候选区里加入 DMM 仍补齐全组。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        dlg.available_list.item(_row_of(dlg, "DMM")).setSelected(True)
        dlg._add_selected()
        assert set(dlg.selected_sites()) == {Website.DMM, Website.DMM_API, Website.LIBREDMM}
    finally:
        dlg.deleteLater()
