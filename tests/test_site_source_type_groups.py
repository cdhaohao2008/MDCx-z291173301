"""「编辑网站」对话框：可用网站（网址源）顶部横排分组标题，其下按组铺开全部站点。

用户需求原文（四轮累积）：
    1.「在所有网站前加上有码、无码、素人、FC2、欧美、国产这几个选项」
       ——逐组给出的站点清单，组内顺序即优先级递减，不得改动排序；
    2.「点击有码、无码、素人、FC2、欧美、国产要将包含的网站加入到启用网站列表里，
        没有【其他】，别加戏OK？按钮高度和其他网站一致，删掉【】，宽度按照字体宽度设定」
    3.「有码、无码、素人、FC2、欧美、国产这样默认排在DMM左边」
    4.「有码、无码、素人、FC2、欧美、国产、DMM、DMM_API按照这样排序」

第 3 条此前是「顺带」成立的：流式换行下标题 chip 恰好横排在所属组第一个站的左边，
但另外五个标题仍散落在各自的段落里。第 4 条把它钉死成显式规则——六个标题整体排到
候选区最上面一行、从左到右横排，第一个站点才是 DMM、第二个是 DMM_API。所以这里逐条锁住：
    1. 六个分组标题按用户给的次序横排在最上面一行，且每组是用户给的名单与顺序；
    2. 标题行不可选中、不可拖、不带 UserRole，不会被当成站点混进启用列表或复制结果；
    3. 标题下方是全部可用站点：按组序去重铺放、每个站只出现一次，DMM、DMM_API 排在最前，
       六组之外的 MyWife 接在末尾；
    4. 单击某个标题 chip = 把这一组整组加入启用列表；标题只有这六个，不存在「其他」；
    5. 站点行的单击仍旧只是选中（加入靠双击或「添加选中」），双击标题行无副作用；
    6. 启用列表的顺序仍旧完全由用户决定（分组只作用于候选区的展示）。

另外还锁了一条「候选区分组 == 配置默认名单」的不变量：两者同源于
models.TYPE_DEFAULT_SITES，一旦各改各的，用户看到的分组就会和实际默认行为对不上，
而且没有任何报错提示。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import TYPE_DEFAULT_SITES, Config  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    PALETTE_GROUP_TYPES,
    SITE_GROUP_ROLE,
    SiteListEditorDialog,
    _is_group_item,
    _list_sites,
    _palette_groups,
    _site_tooltip_lines,
    grouped_palette_groups,
    palette_site_order,
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

# 非分组的原始顺序：按此断言「全部添加」未被候选区排序污染
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


def _chip_groups_of(dialog) -> dict[str, list[str]]:
    """读候选区顶部标题行里的各组名单（单击整组加入与右键复制都靠它）。"""
    return {title: [site.value for site in sites] for title, sites in _palette_groups(dialog.available_list)}


def _site_row_values(dialog) -> list[str]:
    """候选区里站点行的行序（标题行不带 UserRole，天然被排除在外）。"""
    palette = dialog.available_list
    return [
        palette.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(palette.count())
        if palette.item(row).data(Qt.ItemDataRole.UserRole) is not None
    ]


def _header_row(dialog) -> int:
    """顶部那一行标题的行号：候选区只允许有一个标题行。"""
    rows = [row for row in range(dialog.available_list.count()) if _is_group_item(dialog.available_list.item(row))]
    assert len(rows) == 1, f"候选区应当只有一个标题行，实际 {len(rows)} 个"
    return rows[0]


def _chip_index(dialog, title: str) -> int:
    """标题 chip 在顶部那一行里是第几个（从 0 起）。"""
    titles = list(dialog.available_list.item(_header_row(dialog)).data(SITE_GROUP_ROLE))
    assert title in titles, f"候选区没有「{title}」这个标题，只有 {titles}"
    return titles.index(title)


def _row_of(dialog, site_value: str) -> int:
    return next(
        row
        for row in range(dialog.available_list.count())
        if dialog.available_list.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


def _click_chip(dialog, title: str) -> None:
    """真的点一下某个标题 chip（走鼠标事件那条链路，而不是直接调内部方法）。"""
    point = dialog.available_list.chip_point(_chip_index(dialog, title))
    assert point is not None, f"标题「{title}」拿不到 chip 位置"
    QTest.mouseClick(dialog.available_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def _visible_site_center(dialog, value: str) -> QPoint:
    """某个站点行在视口里的中心点——先滚到可见处。

    候选区只露得下前几行，直接拿 visualItemRect 的中心会点到视口外面去，
    于是「点站点不加」这类断言会因为根本没点着而假绿。
    """
    palette = dialog.available_list
    row = _row_of(dialog, value)
    palette.scrollToItem(palette.item(row))
    QApplication.processEvents()
    return palette.visualItemRect(palette.item(row)).center()


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
    assert palette_site_order([]) == []


def test_group_without_available_sites_leaves_no_empty_title():
    """某一组在本机没有候选站点时不留空标题，否则会多出五个点开没内容的标题 chip。"""
    assert _groups_of([Website.FALENO]) == {"有码": ["Faleno"]}


def test_sites_outside_every_group_are_appended_without_a_title():
    """落在六组之外的站点（如 MyWife）按传入次序接在末尾，但不另起「其他」标题。"""
    groups = grouped_palette_groups([Website.MYWIFE, Website.DMM, Website.AVSOX])
    assert [title for title, _ in groups] == ["有码", "无码", "素人", "FC2", ""]
    assert [site.value for site in groups[-1][1]] == ["MyWife"]


def test_does_not_mutate_input():
    source = list(UNGROUPED_ORDER)
    grouped_palette_groups(source)
    palette_site_order(source)
    assert source == UNGROUPED_ORDER


def test_palette_site_order_dedupes_by_first_group():
    """标题移到顶部之后，组与组的界线没了，同一个站不能因此铺两三次。

    取它第一次出现的组的位置：有码组最全，DMM、DMM_API、LibreDMM 都先落在有码，
    无码/素人/FC2/欧美/国产再依次补上各自独有的站，六组之外的 MyWife 收尾。
    """
    order = palette_site_order(ALL_SITES)
    assert order == list(dict.fromkeys(order)), "候选区里同一个站出现了多次"
    assert set(order) == set(ALL_SITES), "有站点在铺放时丢了"
    assert [site.value for site in order[:2]] == ["DMM", "DMM_API"], "前两个站必须是 DMM、DMM_API"
    assert order[-1] == Website.MYWIFE, "六组之外的 MyWife 应接在最后"


def test_palette_site_order_is_group_order_then_leftovers():
    """铺放次序 = 六个组依次铺、组内即默认名单序，未分组的按传入次序收尾。"""
    order = palette_site_order([Website.MYWIFE, Website.DMM, Website.AVSOX])
    assert [site.value for site in order] == ["DMM", "AVSOX", "MyWife"]


# --------------------------------------------------------------------------- 对话框运行期


def test_palette_shows_the_requested_groups(dialog):
    """候选区顶部六个标题 chip，各带需求里那一份名单（组内顺序逐项一致）。"""
    assert _chip_groups_of(dialog) == {title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()}


def test_sites_lie_under_the_titles_once_each(dialog):
    """标题之下铺全部站点：每个站只出现一次，行序即 palette_site_order。"""
    assert _site_row_values(dialog) == [site.value for site in palette_site_order(ALL_SITES)]
    assert _site_row_values(dialog)[:2] == ["DMM", "DMM_API"]
    assert _site_row_values(dialog)[-1] == "MyWife"
    assert len(_list_sites(dialog.available_list)) == len(ALL_SITES)


def test_header_row_sits_above_every_site(dialog):
    """第 4 条需求的正面：标题行在最上面一行，站点从第二行开始。

    这是本轮改动的核心——此前标题是「顺带」落在 DMM 左边，另外五个标题散在各段里，
    现在必须是候选区唯一一行标题，且排在所有站点之前。
    """
    palette = dialog.available_list
    header_row = _header_row(dialog)
    assert header_row == 0, "标题行不是候选区第一行"
    header_rect = palette.visualItemRect(palette.item(header_row))
    for value in ("DMM", "DMM_API", "MyWife"):
        assert header_rect.top() < palette.visualItemRect(palette.item(_row_of(dialog, value))).top()


def test_group_title_row_is_inert(dialog):
    """标题行不可选中、不可拖拽、不带 UserRole——不会被当成站点加进启用列表。"""
    row = _header_row(dialog)
    item = dialog.available_list.item(row)
    assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
    assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert item.data(Qt.ItemDataRole.UserRole) is None
    # 文案是空的（文字由 delegate 自绘），标题存在额外的 ItemDataRole 里
    assert item.text() == ""


def test_group_title_text_is_the_plain_type_name(dialog):
    """标题文案就是类型名本身：删掉【】，也不要别的装饰。"""
    titles = [str(title) for title in dialog.available_list.item(_header_row(dialog)).data(SITE_GROUP_ROLE)]
    assert titles == EXPECTED_GROUP_ORDER
    assert all("【" not in title and "】" not in title for title in titles)


def _laid_out(dlg, qt_app):
    """把对话框摆到固定尺寸并完成布局，拿到可用的 visualItemRect。"""
    dlg.resize(860, 640)
    dlg.show()
    qt_app.processEvents()
    return dlg.available_list


def test_group_titles_are_laid_out_like_site_chips(qt_app):
    """标题 chip 与网站 chip 同高、宽度随文字走，几个 chip 横排一行互不重叠。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        header_rect = palette.visualItemRect(palette.item(_header_row(dlg)))
        site_rect = palette.visualItemRect(palette.item(_row_of(dlg, "DMM")))
        assert header_rect.height() == site_rect.height(), "标题行与站点不同高"
        rects = [palette.chip_point(index) for index in range(len(EXPECTED_GROUP_ORDER))]
        assert all(point is not None for point in rects), "有 chip 拿不到位置"
        xs = [point.x() for point in rects]
        assert xs == sorted(xs) and len(set(xs)) == len(xs), f"chip 没有从左到右排开：{xs}"
        for index, point in enumerate(rects):
            assert header_rect.left() <= point.x() <= header_rect.right(), f"chip {index} 越出了标题行"
            assert header_rect.top() <= point.y() <= header_rect.bottom(), f"chip {index} 越出了标题行"
        # 宽度按字体来：不会拉成整行宽
        assert header_rect.width() == palette.viewport().width()
    finally:
        dlg.deleteLater()


def test_chip_hit_test_picks_only_its_own_chip(qt_app):
    """命中判定与绘制用同一份矩形：点 chip 中心得到它自己，点站点/别处没有 chip。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        for index in range(len(EXPECTED_GROUP_ORDER)):
            assert palette.chip_index_at(palette.chip_point(index)) == index
        # 第一个站点行的中心不该命中任何 chip
        site_point = palette.visualItemRect(palette.item(_row_of(dlg, "DMM"))).center()
        assert palette.chip_index_at(site_point) is None
        # 标题行下方一行（第一个站点行）也不该命中任何 chip
        assert palette.chip_index_at(QPoint(palette.chip_point(0).x(), palette.chip_point(0).y() + 40)) is None
    finally:
        dlg.deleteLater()


def test_group_sites_read_back_from_the_widget(dialog):
    """标题行回读出的组内名单与需求逐项一致（单击整组加入与右键复制都靠它）。"""
    for title in EXPECTED_GROUP_ORDER:
        assert _chip_groups_of(dialog)[title] == USER_SITE_LISTS[USER_TITLES_INV[title]]


def test_site_tooltip_says_which_types_it_serves():
    """候选区里每个站只出现一次，「它同时属于哪些类型」得靠悬停提示补上。"""
    dmm_lines = " ".join(_site_tooltip_lines(Website.DMM))
    assert "适用类型：有码、素人" in dmm_lines
    # 不属于六组的站点不该编出一个类型来
    assert "适用类型" not in " ".join(_site_tooltip_lines(Website.MYWIFE))


@pytest.mark.parametrize("title", EXPECTED_GROUP_ORDER)
def test_clicking_group_title_adds_that_whole_group(qt_app, title):
    """单击分组标题 chip = 把该组全部网站按组内优先级次序加入启用列表。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _click_chip(dlg, title)
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[USER_TITLES_INV[title]]
    finally:
        dlg.deleteLater()


def test_clicking_the_last_group_does_not_swallow_untitled_sites(qt_app):
    """六组之外零星站点（MyWife）没有标题、就接在末尾，点「国产」不该顺带加上它。

    这正是「没有其他分组」带来的坑：成员必须取自标题 chip 自带的名单，不能按行范围读，
    否则末尾这批零散站点会被算进上一组。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _click_chip(dlg, "国产")
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[FixedScrapingType.GUOCHAN]
        assert Website.MYWIFE not in dlg.selected_sites()
        # 它仍然出现在候选区里，只是不再有自己的标题 chip
        assert Website.MYWIFE in _list_sites(dlg.available_list)
    finally:
        dlg.deleteLater()


def test_clicking_group_title_appends_and_keeps_existing_order(qt_app):
    """已启用的站点留在原位不动，新组接在后面。"""
    dlg = SiteListEditorDialog("t", [Website.GETCHU], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _click_chip(dlg, "FC2")
        values = [site.value for site in dlg.selected_sites()]
        assert values[0] == "Getchu"
        assert values[1:] == [v for v in USER_SITE_LISTS[FixedScrapingType.FC2] if v != "Getchu"]
    finally:
        dlg.deleteLater()


def test_clicking_group_title_twice_does_not_duplicate(qt_app):
    """重复单击同一标题是幂等的，不会把同一批站点塞两遍。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _click_chip(dlg, "国产")
        first = [site.value for site in dlg.selected_sites()]
        _click_chip(dlg, "国产")
        assert [site.value for site in dlg.selected_sites()] == first
    finally:
        dlg.deleteLater()


def test_clicking_a_site_row_does_not_add_it(qt_app):
    """只有标题 chip 是「一点就整组进」；站点行的单击仍旧只是选中。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        point = _visible_site_center(dlg, "Dahlia")
        QTest.mouseClick(palette.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        # 先确认这一下真落在站点行上（否则「没加进去」是因为根本没点着）
        assert [palette.row(item) for item in palette.selectedItems()] == [_row_of(dlg, "Dahlia")]
        assert dlg.selected_sites() == [], "单击站点行就加进了启用列表"
    finally:
        dlg.deleteLater()


def test_double_clicking_the_header_row_adds_nothing_extra(qt_app):
    """双击标题行不能把上次选中的残留站点顺带加进去；双击站点仍然正常加入。

    这里直接走 `itemDoubleClicked` 的处理函数而不是合成双击事件：离屏环境下
    QTest.mouseDClick 发出的双击不会被 QListWidget 认成 `mouseDoubleClickEvent`
    （实测 itemDoubleClicked 一次都不触发），拿它做断言只会假绿。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        dlg._on_available_double_clicked(dlg.available_list.item(_header_row(dlg)))
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
    assert _chip_groups_of(dialog) == {title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()}


def test_add_selected_appends_in_selection_order(qt_app):
    """一次多选时，新站点按选中次序追加，老站点的相对优先级不动。

    追加次序取 `selectedItems()` 的给出次序（即用户点选的先后），不是候选区的行序——
    这一点原测试的注释写反了（说是「行序＝分组序」），断言值其实一直是选中次序。
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
    """「全部添加」写进启用列表的是传入原序，候选区展示仍按分组铺。"""
    dlg = SiteListEditorDialog("t", [], UNGROUPED_ORDER, None)
    try:
        dlg._add_all()
        assert [site.value for site in dlg.selected_sites()] == ["DMM", "AVBase", "Xcity", "Getchu"]
        # 候选区仍按各组自己的优先级序铺：四个站都属有码，故有码 chip 就是这四个的原序
        assert _chip_groups_of(dlg) == {
            "有码": ["DMM", "AVBase", "Xcity", "Getchu"],
            "无码": ["Getchu"],
            "素人": ["DMM", "AVBase", "Xcity", "Getchu"],
            "FC2": ["Getchu"],
            "欧美": ["Getchu"],
            "国产": ["Getchu"],
        }
        assert _site_row_values(dlg) == ["DMM", "AVBase", "Xcity", "Getchu"]
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
