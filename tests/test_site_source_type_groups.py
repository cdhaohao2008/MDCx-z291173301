"""「编辑网站」对话框：可用网站（网址源）开头的七个加粗分组标题，其后紧接全部可用站点。

用户需求原文（六轮累积）：
    1.「在所有网站前加上有码、无码、素人、FC2、欧美、国产这几个选项」
       ——逐组给出的站点清单，组内顺序即优先级递减，不得改动排序；
    2.「点击有码、无码、素人、FC2、欧美、国产要将包含的网站加入到启用网站列表里，
        没有【其他】，别加戏OK？按钮高度和其他网站一致，删掉【】，宽度按照字体宽度设定」
    3.「有码、无码、素人、FC2、欧美、国产这样默认排在DMM左边」
    4.「有码、无码、素人、FC2、欧美、国产、DMM、DMM_API按照这样排序」
    5.「有码、无码、素人、FC2、欧美、国产后面不要标深色，和其他站点一样纯白背景就行，
        不要空着啊，继续排列DMM、DMM_API、LibreDMM等站点」
    6.「有码：仅能有码（镜像站，无 CF 墙，默认中文页）改成 有码：仅能有码」「有码又圈起来了」
        「DMM到MyWife从A-Z排序啊」
    7.「有码、无码、素人、个摄、欧美、国产、动漫由鼠标单击加入启用网站列表改成由鼠标
        双击时才加入启用网站列表，右键菜单里加上加入启用网站列表，排在在最下方」
       ——第 2 条那句「点击…要加入」后来细化成**双击**：七个标题挤在候选区第一行，
        顺着扫一眼必然挨个碰过去，单击就整组塞进启用列表（且无从撤销）不是用户要的。

第 3、4 条曾被实现成「六个标题占满候选区最上面一整行」（accent 底色 + 边框 + 自绘 chip，
站点从第二行才开始），第 5 条把这条路否掉了：标题就是普通的一格，与其它站点同底色、
只有文字加粗，且**后面不留空白**。第 6 条再修三处：镜像站的说明不得夹带额外措辞；
第一个标题**不能被聚焦框圈起来**；标题之下的站点是一份去重后的 **A-Z** 名单。
所以这里逐条锁住：
    1. 七个分组标题按用户给的次序排在候选区最前面，且每组是用户给的名单与顺序；
    2. 标题不可选中、不可拖、不带 UserRole，不会被当成站点混进启用列表或复制结果；
    3. 标题与站点同一个流式排布，**标题右边立刻接着站点**（没有单独一行，也没有空隙），
       标题只加粗、底色仍是普通站点那一套（没有自定义 delegate 绘制深色块）；
    4. 站点按名称 A-Z 去重铺放、每个站只出现一次（7mmtv … Xcity）；
    5. 候选区任何时刻都没有当前项——Qt 默认会把第一行设成当前项并给它套聚焦框，
       于是第一个标题「被圈起来」；
    6. **双击**某个标题 = 把这一组整组加入启用列表（单击什么也不加）；标题只有这七个，
       不存在「其他」；
    7. 站点行的单击仍旧只是选中（加入靠双击或「添加选中」）；双击标题不会把「上一次
       选中残留」顺带加进去；
    8. 启用列表的顺序仍旧完全由用户决定（分组只作用于候选区的展示）。

另外还锁了一条「候选区分组 == 配置默认名单」的不变量：两者同源于
models.TYPE_DEFAULT_SITES，一旦各改各的，用户看到的分组就会和实际默认行为对不上，
而且没有任何报错提示。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
)

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import TYPE_DEFAULT_SITES, Config  # noqa: E402
from mdcx.controllers.main_window import site_priority_dialog as spd  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    DIALOG_HEIGHT,
    FIELD_PALETTE_VISIBLE_ROWS,
    FIELD_PRIORITY_FIELDS,
    FIELD_PRIORITY_VISIBLE_ROWS,
    PALETTE_GROUP_TYPES,
    PALETTE_SORT_KEYS,
    SITE_EDITOR_PALETTE_ROWS,
    SITE_EDITOR_SELECTED_ROWS,
    FieldPriorityDialog,
    SiteListEditorDialog,
    SitePaletteList,
    _group_sites_at,
    _is_group_item,
    _list_sites,
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
        "Missav",
        "Missav_API",
        "R18.dev",
        "Xcity",
        "TheJavDB",
        "JavLibrary",
        "Javlibrary\u00b7\u955c\u50cf",
    ],
    FixedScrapingType.WUMA: [
        "AVSOX",
        "AVEntertainments",
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
        "Missav",
        "Missav_API",
    ],
    FixedScrapingType.SUREN: [
        "DMM",
        "DMM_API",
        "LibreDMM",
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
        "Missav",
        "Missav_API",
        "R18.dev",
        "Xcity",
        "TheJavDB",
        "JavLibrary",
        "Javlibrary\u00b7\u955c\u50cf",
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
        "Missav",
        "Missav_API",
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
        "Missav",
        "Missav_API",
        "IQQTV",
        "JavFree",
    ],
    FixedScrapingType.GUOCHAN: [
        "Madouqu",
        "Madou.club",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
        "JavBus",
        "JavDay",
        "JavFree",
        "7mmtv",
        "IQQTV",
        "Missav",
        "Missav_API",
    ],
    FixedScrapingType.DONGMAN: [
        "Getchu",
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
    ],
}

# 分组次序：有码、无码、素人、个摄、欧美、国产、动漫
EXPECTED_GROUP_ORDER = ["有码", "无码", "素人", "个摄", "欧美", "国产", "动漫"]

# 候选区各组的标题（取自 PALETTE_GROUP_TITLES，即那七个短名 chip；
# 设置页各行标签与两个弹窗标题用的是带「番号」的 TYPE_TITLES，两边不同源、也不同名）
USER_TITLES = dict(zip(PALETTE_GROUP_TYPES, EXPECTED_GROUP_ORDER, strict=True))
# 反查表：按标题取回它对应的类型，用来在断言里点名要比较的那份需求名单
USER_TITLES_INV = {title: key for key, title in USER_TITLES.items()}

# MyWife 不属于任何类型组：它是「人妻・熟女・3P」独立系列，走「指定网站」或路径含
# mywife 单独指定。用户明确不要「其他」分组，所以它作为无标题的末组接在国产后面。
UNTITLED_GROUP = ""
EXPECTED_GROUPS = {
    **{title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()},
    # AVSEX 与 Getchu 已从六组默认名单移除（对大陆 IP 过不了 CF 墙，2.5.6 起），
    # 其中 Getchu 后来进了动漫组：
    # 两者现在和 MyWife 一起落到这个无标题的末组里，仍然出现在候选区里可选，
    # 只是没有任何一组会默认勾选它们。
    UNTITLED_GROUP: ["AVSEX", "MyWife"],
}

# 非分组的原始顺序：按此断言「全部添加」未被候选区排序污染
UNGROUPED_ORDER = [
    Website.DMM,
    Website.AVBASE,
    Website.XCITY,
    Website.AVSOX,
    Website.MADOUQU,
    Website.THEPORNDB,
    Website.GETCHU,
]

# 七组各自的 Config 字段名，用于锁「候选区分组 == 配置默认名单」
TYPE_CONFIG_FIELDS = {
    FixedScrapingType.YOUMA: "website_youma",
    FixedScrapingType.WUMA: "website_wuma",
    FixedScrapingType.SUREN: "website_suren",
    FixedScrapingType.FC2: "website_fc2",
    FixedScrapingType.OUMEI: "website_oumei",
    FixedScrapingType.GUOCHAN: "website_guochan",
    FixedScrapingType.DONGMAN: "website_dongman",
}


def _groups_of(sites) -> dict[str, list[str]]:
    """把 grouped_palette_groups 的结果压成 {分组标题: 组内站点名}。"""
    groups: dict[str, list[str]] = {}
    for title, group in grouped_palette_groups(sites):
        assert title not in groups, f"分组「{title}」重复出现"
        groups[title] = [site.value for site in group]
    return groups


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


def _laid_out(dlg, qt_app):
    """把「编辑网站」摆到固定尺寸并完成布局，拿到可用的 visualItemRect。"""
    dlg.resize(860, 640)
    dlg.show()
    qt_app.processEvents()
    return dlg.available_list


def _shown(dlg, qt_app):
    """把「字段优先级」摆开并跑完布局（它没有 available_list，只有 _field_lists）。"""
    dlg.resize(860, DIALOG_HEIGHT)
    dlg.show()
    qt_app.processEvents()
    return dlg


def _title_rows(dialog) -> dict[str, int]:
    """{分组标题: 所在行号}；候选区应当恰好七个标题（六类 + 动漫）。"""
    rows = {
        str(dialog.available_list.item(row).text()): row
        for row in range(dialog.available_list.count())
        if _is_group_item(dialog.available_list.item(row))
    }
    assert list(rows) == EXPECTED_GROUP_ORDER, f"标题不是 {EXPECTED_GROUP_ORDER}：{list(rows)}"
    return rows


def _groups_from_widget(dialog) -> dict[str, list[str]]:
    """读候选区里每个标题自带的组内名单（单击整组加入与右键复制都靠它）。"""
    return {
        title: [site.value for site in _group_sites_at(dialog.available_list, row)]
        for title, row in _title_rows(dialog).items()
    }


def _site_row_values(dialog) -> list[str]:
    """候选区里站点行的行序（标题不带 UserRole，天然被排除在外）。"""
    palette = dialog.available_list
    return [
        palette.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(palette.count())
        if palette.item(row).data(Qt.ItemDataRole.UserRole) is not None
    ]


def _row_of(dialog, site_value: str) -> int:
    return next(
        row
        for row in range(dialog.available_list.count())
        if dialog.available_list.item(row).data(Qt.ItemDataRole.UserRole) == site_value
    )


def _label_of(item) -> str:
    """项目在界面上的名字：站点用 UserRole，标题用它的文案。"""
    return item.data(Qt.ItemDataRole.UserRole) or str(item.text())


def _visual_order(palette) -> list[str]:
    """按「先上后下、同行先左后右」的视觉次序读出候选区的项目顺序。

    候选区是流式换行布局，行号 ≠ 看到的顺序（「六个标题排在最前面」说的是眼睛看到的
    位置），所以断言必须走视觉矩形而不是行号。
    """
    pairs = [(palette.visualItemRect(palette.item(row)), palette.item(row)) for row in range(palette.count())]
    pairs.sort(key=lambda pair: (pair[0].top(), pair[0].left()))
    return [_label_of(item) for _, item in pairs]


def _visible_center(palette, row: int):
    """某一行在视口里的中心点——先滚到可见处。

    候选区只露得下前几行，直接拿 visualItemRect 的中心会点到视口外面去，
    于是「点标题不加」这类断言会因为根本没点着而假绿。
    """
    palette.scrollToItem(palette.item(row))
    QApplication.processEvents()
    return palette.visualItemRect(palette.item(row)).center()


def _click_title(dialog, title: str) -> None:
    """真的点一下某个标题（走鼠标事件那条链路，而不是直接调内部方法）。"""
    point = _visible_center(dialog.available_list, _title_rows(dialog)[title])
    QTest.mouseClick(dialog.available_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def _double_click(list_widget, point) -> None:
    """真的双击一下某一点（走 `QAbstractItemView` 的按下→双击那条链路）。

    **不能用 `QTest.mouseDClick`**：离屏平台下它发出的双击不会被 Qt 认成
    `mouseDoubleClickEvent`，实测 `itemDoubleClicked` 一次都不触发，拿它做断言只会假绿。
    照 Qt 的真实顺序手工发四个事件即可（`mouseDoubleClickEvent` 要求
    `d->pressedIndex == index`，少了第一步「按下」它会退化成一次普通按下）。
    """
    for event_type, state in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        (QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            list_widget.viewport(),
            QMouseEvent(
                event_type,
                QPointF(point),
                QPointF(point),
                Qt.MouseButton.LeftButton,
                state,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
    QApplication.processEvents()


def _double_click_title(dialog, title: str) -> None:
    _double_click(dialog.available_list, _visible_center(dialog.available_list, _title_rows(dialog)[title]))


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
    """某一组在本机没有候选站点时不留空标题，否则会多出几个点开没内容的标题。"""
    assert _groups_of([Website.FALENO]) == {"有码": ["Faleno"]}


def test_sites_outside_every_group_are_appended_without_a_title():
    """落在七组之外的站点（如 MyWife）按传入次序接在末尾，但不另起「其他」标题。"""
    groups = grouped_palette_groups([Website.MYWIFE, Website.DMM, Website.AVSOX])
    assert [title for title, _ in groups] == ["有码", "无码", "素人", "个摄", ""]
    assert [site.value for site in groups[-1][1]] == ["MyWife"]


def test_does_not_mutate_input():
    source = list(UNGROUPED_ORDER)
    grouped_palette_groups(source)
    palette_site_order(source)
    assert source == UNGROUPED_ORDER


def test_palette_site_order_is_alphabetical_without_duplicates():
    """候选区的站点是一份去重后的 A-Z 名单（用户要「一路 A-Z 看下去」）。

    分组只留在开头那几个标题上；站点本身既不按组分段、也不按各组默认名单的优先级排。
    少数几站有单独的排序键（PALETTE_SORT_KEYS），所以比对时用同一把尺子。
    """
    order = palette_site_order(ALL_SITES)
    values = [site.value for site in order]
    keys = [PALETTE_SORT_KEYS.get(site, site.value).casefold() for site in order]
    assert order == list(dict.fromkeys(order)), "候选区里同一个站出现了多次"
    assert keys == sorted(keys), "候选区没有按排序键排列"
    assert set(order) == set(ALL_SITES), "有站点在铺放时丢了"
    assert values[0] == "7mmtv" and values[-1] == "Xcity", "A-Z 的首尾应当是 7mmtv、Xcity"


def test_palette_sort_keys_put_the_two_sites_where_the_user_wanted():
    """用户单独点名过两站的位置：AVEntertainments 排在 AVheat/AVMOO/AVSEX/AVSOX 之后、
    Madouqu 排在 Madou.club 之前。"""
    values = [site.value for site in palette_site_order(ALL_SITES)]
    assert values.index("AVEntertainments") == values.index("AVSOX") + 1
    assert values.index("AVEntertainments") > values.index("AVheat") > values.index("AVBase")
    assert values.index("Madouqu") + 1 == values.index("Madou.club")


def test_palette_site_order_ignores_input_order():
    """传入次序不影响 A-Z 结果（候选区只是展示，默认名单的原序在启用列表里另行保存）。"""
    assert [site.value for site in palette_site_order([Website.MYWIFE, Website.DMM, Website.AVSOX])] == [
        "AVSOX",
        "DMM",
        "MyWife",
    ]


# --------------------------------------------------------------------------- 对话框运行期


def test_palette_shows_the_requested_groups(dialog):
    """候选区七个标题，各带需求里那一份名单（组内顺序逐项一致）。"""
    assert _groups_from_widget(dialog) == {title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()}


def test_sites_lie_after_the_titles_once_each(dialog):
    """标题之下铺全部站点：每个站只出现一次，且是一份 A-Z 名单。"""
    assert _site_row_values(dialog) == [site.value for site in palette_site_order(ALL_SITES)]
    assert _site_row_values(dialog)[:2] == ["7mmtv", "Airav.cc"]
    assert _site_row_values(dialog)[-1] == "Xcity"
    assert len(_list_sites(dialog.available_list)) == len(ALL_SITES)


def test_titles_come_first_and_sites_continue_right_after(qt_app):
    """第 5 条需求的正面：标题排最前面，**后面立刻接着站点，不留空隙**。

    此前六个标题曾被做成占满整行的一行（accent 底色 + 自绘 chip），站点从第二行才
    开始；用户要的是「和别的站点一样纯白背景，标题右边直接排站点」。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        order = _visual_order(palette)
        assert order[: len(EXPECTED_GROUP_ORDER)] == EXPECTED_GROUP_ORDER, f"标题不在最前面：{order[:8]}"
        first_site = order[len(EXPECTED_GROUP_ORDER)]
        assert first_site == "7mmtv", f"标题后面没有紧接站点：{order[: len(EXPECTED_GROUP_ORDER) + 3]}"
        # 「不留空」= 同一行：第一个标题与第一个站点行的行矩形 top 相同
        title_rect = palette.visualItemRect(palette.item(_title_rows(dlg)["有码"]))
        site_rect = palette.visualItemRect(palette.item(_row_of(dlg, "7mmtv")))
        assert site_rect.top() == title_rect.top(), "站点被挤到了下一行，标题右边空了一块"
    finally:
        dlg.deleteLater()


def test_no_item_carries_a_focus_ring(qt_app):
    """第一个分组标题不能被圈起来（用户截图里就是它多了��圈边框）。

    根因是 Qt 的两条默认行为：填列表时第一行会被设成当前项；且光标进入列表时若当前项
    为空又会重新选中第一行。当前项带着聚焦框，于是第一个标题总比旁边的站点多一圈。
    候选区不需要「当前项」，所以填完、聚焦后、点标题后都要保持没有当前项。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        assert palette.currentRow() == -1, f"开窗就有当前项：{palette.currentItem().text()}"
        palette.setFocus()
        qt_app.processEvents()
        assert palette.currentRow() == -1, "一聚焦 Qt 就把当前项设成了第一行（那是第一个标题）"
        _double_click_title(dlg, "有码")
        assert palette.currentRow() == -1, "双击标题后它成了当前项，被套上聚焦框"
        assert dlg.selected_sites(), "双击标题本该整组加入（清当前项不该把功能一起清掉）"
    finally:
        dlg.deleteLater()


def test_site_click_still_selects_while_no_current_item(qt_app):
    """清掉当前项之后，站点行的单击照样能选中（用的是「选中」而不是「当前项」）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        point = _visible_center(palette, _row_of(dlg, "7mmtv"))
        QTest.mouseClick(palette.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        assert [palette.row(item) for item in palette.selectedItems()] == [_row_of(dlg, "7mmtv")]
        dlg._add_selected()
        assert dlg.selected_sites() == [Website.MMTV]
    finally:
        dlg.deleteLater()


def test_group_titles_are_not_painted_as_dark_chips(qt_app):
    """第 5 条需求的另一半：标题不再有自定义深色底。

    「不要标深色，和其他站点一样纯白背景」的实现方式就是**不给标题单独的绘制**——
    没有专门的 delegate、没有 accent 底色/边框，标题只靠 `setFont` 加粗区分。
    """
    assert not hasattr(spd, "SiteGroupDelegate"), "又冒出给标题自绘深色块的 delegate 了"
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        delegate = palette.itemDelegate()
        assert type(delegate).__name__ == "QStyledItemDelegate", f"候选区装了自定义 delegate：{type(delegate).__name__}"
        for title, row in _title_rows(dlg).items():
            item = palette.item(row)
            assert item.background().style() == Qt.BrushStyle.NoBrush, f"「{title}」带了自定义底色"
            assert item.data(Qt.ItemDataRole.DecorationRole) is None, f"「{title}」带了自定义图标"
    finally:
        dlg.deleteLater()


def test_group_title_font_is_bold(qt_app):
    """标题只靠加粗区分（用户只否掉了深色，没否掉加粗）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        for title, row in _title_rows(dlg).items():
            assert palette.item(row).font().bold(), f"「{title}」没加粗"
        assert not palette.item(_row_of(dlg, "DMM")).font().bold(), "站点不该加粗"
    finally:
        dlg.deleteLater()


def test_group_title_item_is_inert(dialog):
    """标题不可选中、不可拖动、不带 UserRole——不会被当成站点加进启用列表。"""
    for title, row in _title_rows(dialog).items():
        item = dialog.available_list.item(row)
        assert not item.flags() & Qt.ItemFlag.ItemIsSelectable, f"「{title}」可选中"
        assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled, f"「{title}」可拖动"
        assert item.data(Qt.ItemDataRole.UserRole) is None, f"「{title}」带了 UserRole"


def test_group_title_text_is_the_plain_type_name(dialog):
    """标题文案就是类型名本身：删掉【】，也不要别的装饰。"""
    assert list(_title_rows(dialog)) == EXPECTED_GROUP_ORDER
    for title in _title_rows(dialog):
        assert "【" not in title and "】" not in title


def test_group_sites_read_back_from_the_widget(dialog):
    """标题行回读出的组内名单与需求逐项一致（单击整组加入与右键复制都靠它）。"""
    for title in EXPECTED_GROUP_ORDER:
        assert _groups_from_widget(dialog)[title] == USER_SITE_LISTS[USER_TITLES_INV[title]]


def test_site_tooltip_says_which_types_it_serves():
    """候选区里每个站只出现一次，「它同时属于哪些类型」得靠悬停提示补上。

    两行标签按用户要求只写「类型：」与「联动：」——原本是「适用类型：」和
    「联动组（加入其一即默认加入全组）：」，后半句把悬停框挤到换行还容易被截断。
    """
    dmm_lines = " ".join(_site_tooltip_lines(Website.DMM))
    assert "类型：有码、素人" in dmm_lines
    # 不属于任何类型组的站点不该编出一个类型来
    assert "类型：" not in " ".join(_site_tooltip_lines(Website.MYWIFE))


def test_site_tooltip_says_which_sites_link_together():
    """联动组那行按用户要求只写「联动：」，成员名单照旧列全。"""
    dmm_lines = " ".join(_site_tooltip_lines(Website.DMM))
    assert "联动：DMM、DMM_API、LibreDMM" in dmm_lines
    # 「加入其一即默认加入全组」这半句解释已从标签里去掉
    assert "联动组" not in dmm_lines
    assert "加入其一" not in dmm_lines
    # 不属于任何联动组的站点不该编出一个来
    assert "联动：" not in " ".join(_site_tooltip_lines(Website.MYWIFE))


@pytest.mark.parametrize("title", EXPECTED_GROUP_ORDER)
def test_double_clicking_group_title_adds_that_whole_group(qt_app, title):
    """双击分组标题 = 把该组全部网站按组内优先级次序加入启用列表。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _double_click_title(dlg, title)
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[USER_TITLES_INV[title]]
    finally:
        dlg.deleteLater()


def test_single_clicking_group_title_adds_nothing(qt_app):
    """单击标题什么也不加——它是「看一眼这是哪一组」，不是「加入这一组」。

    七组标题就挤在列表第一行，顺着扫一眼必然挨个碰过去；单击就整组塞进启用列表的话，
    用户只是碰了一下就把三十来个站加进去了（且没有撤销），所以整组加入必须落在双击上。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _click_title(dlg, "有码")
        assert dlg.selected_sites() == [], "单击标题就整组加进了启用列表"
    finally:
        dlg.deleteLater()


def test_double_clicking_the_last_group_does_not_swallow_untitled_sites(qt_app):
    """七组之外零星站点（MyWife）没有标题、就接在末尾，双击「国产」不该顺带加上它。

    这正是「没有其他分组」带来的坑：成员必须取自标题自带的名单，不能按行范围读，
    否则末尾这批零散站点会被算进上一组。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _double_click_title(dlg, "国产")
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[FixedScrapingType.GUOCHAN]
        assert Website.MYWIFE not in dlg.selected_sites()
        # 它仍然出现在候选区里，只是不再有自己的标题
        assert Website.MYWIFE in _list_sites(dlg.available_list)
    finally:
        dlg.deleteLater()


def test_double_clicking_group_title_appends_and_keeps_existing_order(qt_app):
    """已启用的站点留在原位不动，新组接在后面。"""
    dlg = SiteListEditorDialog("t", [Website.XCITY], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _double_click_title(dlg, "个摄")
        values = [site.value for site in dlg.selected_sites()]
        assert values[0] == "Xcity"
        assert values[1:] == USER_SITE_LISTS[FixedScrapingType.FC2]
    finally:
        dlg.deleteLater()


def test_double_clicking_group_title_twice_does_not_duplicate(qt_app):
    """重复双击同一标题是幂等的，不会把同一批站点塞两遍。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        _double_click_title(dlg, "国产")
        first = [site.value for site in dlg.selected_sites()]
        _double_click_title(dlg, "国产")
        assert [site.value for site in dlg.selected_sites()] == first
    finally:
        dlg.deleteLater()


def test_clicking_a_site_row_does_not_add_it(qt_app):
    """站点行的单击仍旧只是选中（双击才加入）。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        point = _visible_center(palette, _row_of(dlg, "Dahlia"))
        QTest.mouseClick(palette.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        # 先确认这一下真落在站点行上（否则「没加进去」是因为根本没点着）
        assert [palette.row(item) for item in palette.selectedItems()] == [_row_of(dlg, "Dahlia")]
        assert dlg.selected_sites() == [], "单击站点行就加进了启用列表"
    finally:
        dlg.deleteLater()


def test_double_clicking_a_site_row_adds_only_that_site(qt_app):
    """双击站点行 = 加入该站，与双击标题一样走鼠标那条链路。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        _double_click(palette, _visible_center(palette, _row_of(dlg, "7mmtv")))
        assert dlg.selected_sites() == [Website.MMTV]
    finally:
        dlg.deleteLater()


def test_double_clicking_a_group_title_ignores_leftover_selection(qt_app):
    """双击标题只加它自己那一组，不把「上一次选中残留」顺带加进去。

    标题不可选中，双击它不会改变选中集——这正是「按标题自带的名单加入」而不是复用
    `_add_selected` 的原因（后者读的是当前选中项）。这里先故意选中一个站再双击标题。
    """
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        palette = _laid_out(dlg, qt_app)
        palette.item(_row_of(dlg, "7mmtv")).setSelected(True)
        _double_click(palette, _visible_center(palette, _title_rows(dlg)["无码"]))
        assert [site.value for site in dlg.selected_sites()] == USER_SITE_LISTS[FixedScrapingType.WUMA]
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
    assert _groups_from_widget(dialog) == {title: USER_SITE_LISTS[key] for key, title in USER_TITLES.items()}


def test_add_selected_appends_in_selection_order(qt_app):
    """一次多选时，新站点按选中次序追加，老站点的相对优先级不动。

    追加次序取 `selectedItems()` 的给出次序（即用户点选的先后），不是候选区的行序——
    这一点早前那个用例的注释写反了（断言值其实一直是选中次序）。
    """
    dlg = SiteListEditorDialog("t", [Website.XCITY, Website.DMM], ALL_SITES, None)
    try:
        for value in ("IQQTV", "7mmtv"):
            dlg.available_list.item(_row_of(dlg, value)).setSelected(True)
        dlg._add_selected()
        values = [site.value for site in dlg.selected_sites()]
        assert values[:2] == ["Xcity", "DMM"]
        assert values[2:] == ["IQQTV", "7mmtv"]
    finally:
        dlg.deleteLater()


def test_add_all_uses_original_order_while_palette_stays_grouped(qt_app):
    """「全部添加」写进启用列表的是传入原序，候选区展示仍按分组铺。"""
    dlg = SiteListEditorDialog("t", [], UNGROUPED_ORDER, None)
    try:
        dlg._add_all()
        assert [site.value for site in dlg.selected_sites()] == [
            "DMM",
            "AVBase",
            "Xcity",
            "AVSOX",
            "Madouqu",
            "ThepornDB",
            "Getchu",
        ]
        # 候选区仍按各组自己的优先级序铺：四个站都属有码，故该标题带的就是这四个的原序
        assert _groups_from_widget(dlg) == {
            "有码": ["DMM", "AVBase", "Xcity"],
            "无码": ["AVSOX"],
            "素人": ["DMM", "AVBase", "Xcity"],
            "个摄": ["AVSOX"],
            "欧美": ["ThepornDB"],
            "国产": ["Madouqu"],
            "动漫": ["Getchu"],
        }
        assert _site_row_values(dlg) == ["AVBase", "AVSOX", "DMM", "Getchu", "Madouqu", "ThepornDB", "Xcity"]
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


# --------------------------------------------------------------------------- 两个弹窗的观感


def test_clear_button_is_named_clearing_sites(dialog):
    """清空按钮写「清空站点」——它清的是右侧那份列表，不是「清空当前选中」之类。"""
    texts = [btn.text() for btn in dialog.findChildren(QPushButton)]
    assert "清空站点" in texts, texts
    assert "清空" not in texts


def test_save_and_cancel_sit_on_the_same_row_as_the_add_buttons(qt_app):
    """保存 / 取消与「添加选中」「移除选中」同排，不必沉到对话框最底下去够鼠标。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        buttons = {b.text(): b for b in dlg.findChildren(QPushButton)}
        assert {"添加选中", "移除选中", "全部添加", "清空站点", "保存", "取消"} <= set(buttons)
        tops = {name: buttons[name].mapTo(dlg, buttons[name].rect().topLeft()).y() for name in buttons}
        reference = tops["添加选中"]
        for name in ("移除选中", "全部添加", "清空站点", "保存", "取消"):
            assert abs(tops[name] - reference) <= 2, f"「{name}」不在同一行：{tops}"
    finally:
        dlg.deleteLater()


def test_both_dialogs_use_the_same_height(qt_app):
    """「编辑网站」与「字段优先级」一样高，且都不超过屏幕。

    高度跟着「字段优先级」的实际排布走：字体/界面缩放一大它就得高一点，
    这时另一个窗口也跟着高，不会一个 680 一个 720。
    """
    priority = FieldPriorityDialog("t", FixedScrapingType.YOUMA, ALL_SITES, {}, None)
    editor = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(priority, qt_app)
        _laid_out(editor, qt_app)
        assert editor.height() == priority.height()
        assert priority.height() >= DIALOG_HEIGHT
        screen = priority.screen() or QApplication.primaryScreen()
        assert priority.height() <= screen.availableGeometry().height()
    finally:
        priority.deleteLater()
        editor.deleteLater()


def test_editing_caption_sits_between_the_two_lists(qt_app):
    """「启用网站」那行说明垂直居中在两个显示框之间，而不是贴着下面那个框。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        _shown(dlg, qt_app)
        palette = dlg.available_list
        caption = next(label for label in dlg.findChildren(QLabel) if label.text().startswith("启用网站（"))
        top_box_bottom = palette.mapTo(dlg, QPoint(0, palette.height())).y()
        bottom_box_top = dlg.selected_list.mapTo(dlg, QPoint(0, 0)).y()
        caption_center = caption.mapTo(dlg, QPoint(0, caption.height() // 2)).y()
        assert bottom_box_top > top_box_bottom, "两个显示框没有上下分开"
        caption_center = caption.mapTo(dlg, QPoint(0, caption.height() // 2)).y()
        size = caption.sizeHint().height()
        # 空带够高时说明行在正中间；空带压到一行以内（两个框各分一半富余高度）时，
        # 它紧跟在上面那个框底下——两种都算「在两个框之间」
        assert top_box_bottom < caption_center <= bottom_box_top + 2, (
            f"说明行没待在两个框之间：{caption_center} / {top_box_bottom} / {bottom_box_top}"
        )
        if bottom_box_top - top_box_bottom >= size:
            gap_center = (top_box_bottom + bottom_box_top) // 2
            assert abs(caption_center - gap_center) <= 2, f"说明行偏离两框中点：{caption_center} vs {gap_center}"
        # 左边也要跟「可用网站（按类型分组）」那行严格对齐：两行字一个像素都不得错开
        top_caption_x = dlg.top_title.mapTo(dlg, QPoint(0, 0)).x()
        caption_x = caption.mapTo(dlg, QPoint(0, 0)).x()
        assert caption_x == top_caption_x, f"说明行没有与上方那行左对齐：{caption_x} vs {top_caption_x}"
    finally:
        dlg.deleteLater()


def test_field_priority_shows_exactly_four_and_six_rows(qt_app):
    """「字段优先级」上方正好四行、下方正好六行——半截行看着像渲染坏了。"""
    dlg = FieldPriorityDialog("t", FixedScrapingType.YOUMA, ALL_SITES, {}, None)
    try:
        _shown(dlg, qt_app)
        palette = next(iter(dlg.findChildren(SitePaletteList)))
        tops = sorted({palette.visualItemRect(palette.item(r)).top() for r in range(palette.count())})
        assert len(tops) > FIELD_PALETTE_VISIBLE_ROWS
        assert tops[FIELD_PALETTE_VISIBLE_ROWS] >= palette.viewport().height(), "上方露出了半截第五行"

        scroll = next(w for w in dlg.findChildren(QScrollArea))
        viewport_height = scroll.viewport().height()
        fields = FIELD_PRIORITY_FIELDS[:FIELD_PRIORITY_VISIBLE_ROWS]
        starts = [dlg._field_lists[f].mapTo(scroll.viewport(), QPoint(0, 0)).y() for f in fields]
        bottoms = [
            dlg._field_lists[f].mapTo(scroll.viewport(), QPoint(0, dlg._field_lists[f].height())).y() for f in fields
        ]
        assert starts == sorted(starts), f"字段行顺序乱了：{starts}"
        assert max(bottoms) <= viewport_height, f"下方第六行被切了：{max(bottoms)} > {viewport_height}"
    finally:
        dlg.deleteLater()


def test_both_dialogs_open_centered_on_screen(qt_app):
    """两个弹窗都摆在屏幕正中央——Qt 默认只保证「在父控件中央」，父控件偏下时窗口就掉下去了。

    判定沿用项目自己的约定（`tests/test_window_centering.py` / `mdcx.utils.window_center`）：
    比可用区还宽/高时贴左上角，其余情况居中（误差 4 像素内）。两个弹窗都宽 860，
    在窄屏上就是「贴左」那一支。
    """
    editor = SiteListEditorDialog("t", [], ALL_SITES, None)
    priority = FieldPriorityDialog("t", FixedScrapingType.YOUMA, ALL_SITES, {}, None)
    try:
        for dlg in (editor, priority):
            _shown(dlg, qt_app)
            screen = dlg.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry()
            frame = dlg.frameGeometry()
            if frame.width() > avail.width():
                assert frame.x() == avail.x(), f"比屏幕宽时应当贴左边缘：{frame} vs {avail}"
            else:
                assert abs(frame.center().x() - avail.center().x()) <= 4, f"没有水平居中：{frame}"
            if frame.height() > avail.height():
                assert frame.y() == avail.y(), f"比屏幕高时应当贴上边缘：{frame} vs {avail}"
            else:
                assert abs(frame.center().y() - avail.center().y()) <= 4, f"没有垂直居中：{frame}"
    finally:
        editor.deleteLater()
        priority.deleteLater()


def test_site_editor_boxes_show_six_and_four_rows(qt_app):
    """「编辑网站」两个框定死为上方五行、下方四行。

    跟着内容伸缩会让同一个对话框在不同类型下时高时矮（六种类型的候选站数量差很多），
    固定行数之后窗口的高、宽、样式在六种类型下一模一样，区别只在框里能滚动多少行。
    """
    dlg = SiteListEditorDialog("t", ALL_SITES[:12], ALL_SITES, None)
    try:
        _laid_out(dlg, qt_app)
        dlg._fit_lists_to_content()  # 显式跑一次，别让断言取决于 showEvent 的时序

        def row_pitch(widget) -> int:
            """行距 = 相邻两「视觉行」顶边之差（同一行里的站顶边相同，取最小正差）。"""
            tops = sorted({widget.visualItemRect(widget.item(r)).top() for r in range(widget.count())})
            deltas = [b - a for a, b in zip(tops, tops[1:], strict=False) if b - a > 0]
            assert deltas, "内容还没排开"
            return min(deltas)

        for widget, rows in (
            (dlg.available_list, SITE_EDITOR_PALETTE_ROWS),
            (dlg.selected_list, SITE_EDITOR_SELECTED_ROWS),
        ):
            # 两个框的行距未必一样（启用区的行更矮），各自量各自的
            pitch = row_pitch(widget)
            height = widget.viewport().height()
            # 至多 rows 行（露半截行是最难看的）、至少 rows-1 行（不能塌成一两行）
            assert (rows - 1) * pitch <= height <= rows * pitch, f"框高不是 {rows} 行档位：{height} / {pitch}"
    finally:
        dlg.deleteLater()
