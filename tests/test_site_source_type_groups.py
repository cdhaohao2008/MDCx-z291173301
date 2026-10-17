"""「编辑网站」对话框：可用网站（网址源）按有码/无码/素人/FC2/欧美/国产分组展示。

用户需求原文（三轮累积）：
    1.「在所有网站前加上有码、无码、素人、FC2、欧美、国产这几个选项」
       ——逐组给出的站点清单，组内顺序即优先级递减，不得改动排序；
    2.「点击有码、无码、素人、FC2、欧美、国产要将包含的网站加入到启用网站列表里，
        没有【其他】，别加戏OK？按钮高度和其他网站一致，删掉【】，宽度按照字体宽度设定」
    3.「有码、无码、素人、FC2、欧美、国产这样默认排在DMM左边」

所以这里逐条锁住：
    1. 六个分组标题按用户给的次序出现，且每组内是用户给的名单与顺序；
    2. 标题行就是类型名本身（无装饰符号）、与站点 chip 同高，横向排在所属组第一个站点
       的左边（即「有码 DMM DMM_API …」同一行顺排）；
    3. 单击标题行 = 整组加入启用列表；标题只有这六个，不存在「其他」；
    4. 标题行不带 UserRole，不会被当成站点混进启用列表或复制结果；
    5. 启用列表的顺序仍旧完全由用户决定（分组只作用于候选区的展示）。

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
    PALETTE_GROUP_TYPES,
    SITE_GROUP_ROLE,
    SiteListEditorDialog,
    _group_sites_at,
    _list_sites,
    grouped_palette_groups,
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
        # FC2 自己家的站排在第三方聚合站前面（提交 e30bdbb 定的序）
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
# 反查表：按标题取回它对应的类型，用来在断言里点名要比较的那份需求名单
USER_TITLES_INV = {title: key for key, title in USER_TITLES.items()}

# MyWife 不属于任何类型组：它是「人妻・熟女・3P」独立系列，走「指定网站」或路径含
# mywife 单独指定。用户明确不要「其他」分组，所以它作为无标题的末组接在国产后面。
UNTITLED_GROUP = ""
EXPECTED_GROUPS = {
    **{title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()},
    UNTITLED_GROUP: ["MyWife"],
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


def _groups_of(sites) -> dict[str, list[str]]:
    """把 grouped_palette_groups 的结果压成 {分组标题: 组内站点名}。"""
    groups: dict[str, list[str]] = {}
    for title, group in grouped_palette_groups(sites):
        assert title not in groups, f"分组「{title}」重复出现"
        groups[title] = [site.value for site in group]
    return groups


def _groups_from_widget(dialog) -> dict[str, list[str]]:
    """直接读对话框里已铺好的候选区，确保 UI 用的就是上面那套装序逻辑。

    每组的成员先按标题行携带的名单定位，再逐行核对行序——组内行序与分组数据不一致
    （比如点击加入时会按错误的次序追加）要当场暴露，不能等到断言整张表时才发现。
    """
    palette = dialog.available_list
    groups: dict[str, list[str]] = {}
    covered: set[int] = set()
    for row in range(palette.count()):
        if palette.item(row).data(SITE_GROUP_ROLE) is None:
            continue
        title = palette.item(row).data(SITE_GROUP_ROLE)
        assert title not in groups, f"分组「{title}」重复出现"
        members = [site.value for site in _group_sites_at(palette, row)]
        member_rows = [
            palette.item(row + offset).data(Qt.ItemDataRole.UserRole) for offset in range(1, len(members) + 1)
        ]
        assert member_rows == members, f"{title} 组内的行序与该组名单不一致"
        groups[title] = members
        covered.update(range(row, row + len(members) + 1))
    leftover = [
        palette.item(row).data(Qt.ItemDataRole.UserRole) for row in range(palette.count()) if row not in covered
    ]
    if leftover:
        groups[UNTITLED_GROUP] = leftover
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


def _title_row_of(dialog, title: str) -> int:
    return next(row for row in _title_rows(dialog) if dialog.available_list.item(row).data(SITE_GROUP_ROLE) == title)


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
    titles = [title for title, group in grouped_palette_groups(ALL_SITES) if title]
    assert titles == EXPECTED_GROUP_ORDER


def test_there_is_no_other_group_title():
    """用户明确不要「其他」分组：标题只有那六个类型名。"""
    titles = [title for title, _ in grouped_palette_groups(ALL_SITES) if title]
    assert set(titles) == set(EXPECTED_GROUP_ORDER)
    assert "其他" not in titles


def test_each_group_lists_exactly_the_requested_sites_in_order():
    """每组内的站点与顺序，逐项等于用户给的清单。"""
    assert _groups_of(ALL_SITES) == EXPECTED_GROUPS


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
    grouped_sites = [site for _, group in grouped_palette_groups(ALL_SITES) for site in group]
    # 允许重复（一个站点可同属多组），但必须完整覆盖传入集合
    assert set(grouped_sites) == set(ALL_SITES)


def test_empty_candidate_list_produces_no_groups():
    assert grouped_palette_groups([]) == []


def test_group_without_available_sites_leaves_no_empty_title():
    """某一组在本机没有候选站点时不留空标题，否则会多出五个点开没内容的分组。"""
    assert _groups_of([Website.FALENO]) == {"有码": ["Faleno"]}


def test_sites_outside_every_group_are_appended_without_a_title():
    """落在六组之外的站点（如 MyWife）按传入次序接在末尾，但不另起「其他」标题。"""
    groups = grouped_palette_groups([Website.MYWIFE, Website.DMM, Website.AVSOX])
    assert [title for title, _ in groups] == ["有码", "无码", "素人", "FC2", ""]
    assert [site.value for site in groups[-1][1]] == ["MyWife"]


def test_does_not_mutate_input():
    source = list(UNGROUPED_ORDER)
    grouped_palette_groups(source)
    assert source == UNGROUPED_ORDER


# --------------------------------------------------------------------------- 对话框运行期


def test_palette_shows_the_requested_groups(dialog):
    """候选区 = 六个分组（+ 末尾无标题的 MyWife），组内站点与顺序逐项等于需求清单。"""
    assert _groups_from_widget(dialog) == EXPECTED_GROUPS


def test_group_title_rows_are_inert(dialog):
    """标题行不可选中、不可拖拽、不带 UserRole——不会被当成站点加进启用列表。"""
    rows = _title_rows(dialog)
    assert len(rows) == len(EXPECTED_GROUP_ORDER)
    for row in rows:
        item = dialog.available_list.item(row)
        assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
        assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled
        assert item.data(Qt.ItemDataRole.UserRole) is None

    site_rows = sum(1 for row in range(dialog.available_list.count()) if row not in rows)
    # 站点行总数 = 六组之和 + MyWife；标题行不计入，去重后的站点数则少于行数
    assert site_rows == sum(len(v) for v in USER_SITE_LISTS.values()) + 1
    assert len(_list_sites(dialog.available_list)) == len(ALL_SITES) < site_rows


def test_group_title_text_is_the_plain_type_name(dialog):
    """标题文案就是类型名本身：删掉【】，也不要别的装饰。"""
    for row in _title_rows(dialog):
        item = dialog.available_list.item(row)
        assert item.text() == item.data(SITE_GROUP_ROLE)
        assert "【" not in item.text() and "】" not in item.text()


def _laid_out(dlg, qt_app):
    """把对话框摆到固定尺寸并完成布局，拿到可用的 visualItemRect。"""
    dlg.resize(860, 640)
    dlg.show()
    qt_app.processEvents()
    return dlg.available_list


def test_first_group_title_sits_left_of_dmm(qt_app):
    """需求里点名的那个例子：「有码」就横排在 DMM 左边、同一行。

    首组一定从行首开始，所以这一条在任何窗口宽度下都成立。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        title_rect = palette.visualItemRect(palette.item(_title_row_of(dlg, "有码")))
        dmm_rect = palette.visualItemRect(palette.item(_row_of(dlg, "DMM")))
        assert title_rect.top() == dmm_rect.top(), "「有码」与 DMM 不在同一行"
        assert title_rect.right() <= dmm_rect.left(), "「有码」不在 DMM 左边"
    finally:
        dlg.deleteLater()


def test_group_titles_are_laid_out_like_site_chips(qt_app):
    """标题 chip 与网站 chip 同高、宽度随文字走，且排在组内第一个站点之前。

    标题可能正好落在某一行末尾、它的站点换到下一行（流式换行的正常结果），
    所以这里只要求「排在前面」；同排时进一步要求在左侧。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        viewport_width = palette.viewport().width()
        for title in EXPECTED_GROUP_ORDER:
            title_row = _title_row_of(dlg, title)
            title_rect = palette.visualItemRect(palette.item(title_row))
            site_rect = palette.visualItemRect(palette.item(title_row + 1))
            assert title_rect.height() == site_rect.height(), f"{title} 标题与站点不同高"
            # 宽度按字体来：不会拉成整行宽
            assert title_rect.width() < viewport_width // 2, f"{title} 标题被拉宽了"
            if title_rect.top() == site_rect.top():
                assert title_rect.right() <= site_rect.left(), f"{title} 标题不在首个站点左边"
            else:
                assert title_rect.top() < site_rect.top(), f"{title} 标题排到了组内站点之后"
    finally:
        dlg.deleteLater()


def test_group_sites_read_back_from_the_widget(dialog):
    """_group_sites_at 读出的组内名单与需求逐项一致（单击整组加入与右键复制都靠它）。"""
    for title in EXPECTED_GROUP_ORDER:
        sites = _group_sites_at(dialog.available_list, _title_row_of(dialog, title))
        assert [site.value for site in sites] == USER_SITE_LISTS[USER_TITLES_INV[title]]


@pytest.mark.parametrize("title", EXPECTED_GROUP_ORDER)
def test_clicking_group_title_adds_that_whole_group(qt_app, title):
    """单击分组标题 = 把该组全部网站按组内优先级次序加入启用列表。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        dlg._on_available_clicked(dlg.available_list.item(_title_row_of(dlg, title)))
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[USER_TITLES_INV[title]]
    finally:
        dlg.deleteLater()


def test_clicking_the_last_group_does_not_swallow_untitled_sites(qt_app):
    """六组之外零星站点（MyWife）没有标题行、就接在最后一组后面，点「国产」不该顺带加上它。

    这正是「没有其他分组」带来的坑：成员必须取自标题行自带的名单，不能按行范围读到
    下一个标题为止，否则最后一段零散站点会被算进上一组。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        dlg._on_available_clicked(dlg.available_list.item(_title_row_of(dlg, "国产")))
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[FixedScrapingType.GUOCHAN]
        assert Website.MYWIFE not in dlg.selected_sites()
        # 它仍然出现在候选区里，只是不再有自己的标题行
        assert Website.MYWIFE in _list_sites(dlg.available_list)
    finally:
        dlg.deleteLater()


def test_clicking_group_title_appends_and_keeps_existing_order(qt_app):
    """已启用的站点留在原位不动，新组接在后面。"""
    dlg = SiteListEditorDialog("t", [Website.GETCHU], ALL_SITES, None)
    try:
        dlg._on_available_clicked(dlg.available_list.item(_title_row_of(dlg, "FC2")))
        values = [site.value for site in dlg.selected_sites()]
        assert values[0] == "Getchu"
        assert values[1:] == [v for v in USER_SITE_LISTS[FixedScrapingType.FC2] if v != "Getchu"]
    finally:
        dlg.deleteLater()


def test_clicking_group_title_twice_does_not_duplicate(qt_app):
    """重复单击同一标题是幂等的，不会把同一批站点塞两遍。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        row = _title_row_of(dlg, "国产")
        dlg._on_available_clicked(dlg.available_list.item(row))
        first = [site.value for site in dlg.selected_sites()]
        dlg._on_available_clicked(dlg.available_list.item(_title_row_of(dlg, "国产")))
        assert [site.value for site in dlg.selected_sites()] == first
    finally:
        dlg.deleteLater()


def test_clicking_a_site_row_does_not_add_it(qt_app):
    """只有标题是「一点就整组进」；站点行的单击仍旧只是选中。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        item = dlg.available_list.item(_row_of(dlg, "Dahlia"))
        dlg._on_available_clicked(item)
        assert dlg.selected_sites() == []
    finally:
        dlg.deleteLater()


def test_double_clicking_a_group_title_adds_nothing_extra(qt_app):
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
