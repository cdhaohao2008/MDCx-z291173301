"""「编辑网站」对话框的联动站点组：加入补齐、移动整组同行、移除只删被选中的那个。

用户需求分两条，本文件分别锁死：
    一、「当加入组内任意一个站点即默认加入组内另外的站点，加入后可以手动移除」
    二、「移动联动组内任一网站时同步移动联动组内其他网站，
        移除网站按旧规则执行不受影响」

第二条的关键在于**移动要整组、移除要单个**——两条需求字面上都涉及「组」，但语义相反，
所以每条路径都必须单独断言，只测其中一条会漏掉把移除也改成连带删除的回归。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import SITE_GROUPS, expand_site_groups, site_group_of  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    FieldPriorityDialog,
    PrioritySiteList,
    SiteListEditorDialog,
    _list_sites,
    _setup_site_list,
)

ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]
DMM_GROUP = (Website.DMM, Website.DMM_API, Website.LIBREDMM)
JAVBUS, GETCHU, AVSOX, PRESTIGE, XCITY = (
    Website.JAVBUS,
    Website.GETCHU,
    Website.AVSOX,
    Website.PRESTIGE,
    Website.XCITY,
)
# DMM 组夹在杂站中间，用来验证整组被拆散的情况
SPLIT = [JAVBUS, Website.DMM, GETCHU, Website.LIBREDMM, AVSOX]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _editor(qt_app, selected):
    dlg = SiteListEditorDialog("t", list(selected), ALL_SITES, None)
    return dlg, dlg.selected_list


def _values(list_widget) -> list[str]:
    return [site.value for site in _list_sites(list_widget)]


def _move(list_widget, site, row):
    """模拟一次内部拖拽重排：选中 → mimeData 记录 drag_sites → 落到 row 行之前。"""
    for r in range(list_widget.count()):
        item = list_widget.item(r)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) == site.value)
    list_widget.mimeData([list_widget.currentItem()])
    list_widget._move_sites(row)
    return _values(list_widget)


def _drop_back(dialog, site):
    """模拟把站点从「启用网站」拖回「可用网站」= 移除。

    不构造合成 QDropEvent：那玩意儿的 source() 恒为 None（真实拖拽由 Qt 的拖拽
    管理器填），走不到 SitePaletteList 的移除分支。直接调它抽出来的 remove_sites_from，
    覆盖的正是 dropEvent 里那段移除逻辑。
    """
    selected_list = dialog.selected_list
    row = next(
        r for r in range(selected_list.count()) if selected_list.item(r).data(Qt.ItemDataRole.UserRole) == site.value
    )
    item = selected_list.item(row)
    item.setSelected(True)
    selected_list.mimeData([item])  # 触发 drag_sites 快照，与真实拖拽起点一致
    dialog.available_list.remove_sites_from(selected_list, set(selected_list.drag_sites))


# --------------------------------------------------------------------- 组定义本身


def test_site_groups_are_exactly_the_requested_seven():
    assert [tuple(s.value for s in group) for group in SITE_GROUPS] == [
        ("DMM", "DMM_API", "LibreDMM"),
        ("Missav", "Missav_API"),
        ("FC2", "FC2PPVDB"),
        ("ThepornDB", "AVheat"),
        ("JavDB", "JavDB_API", "JavDB_APP"),
        ("Madouqu", "Madou.club"),
        # 原站与镜像站是同一份数据的两条通道，只勾一条不如两条都留（用户要求）
        ("JavLibrary", "Javlibrary\u00b7\u955c\u50cf"),
    ]


def test_every_grouped_site_resolves_to_its_group():
    for group in SITE_GROUPS:
        for member in group:
            assert site_group_of(member) == group


def test_expand_is_noop_for_ungrouped_sites():
    assert expand_site_groups([GETCHU, JAVBUS]) == [GETCHU, JAVBUS]


# ------------------------------------------------------------------------ 加入联动


def test_adding_one_member_pulls_in_the_whole_group(qt_app):
    for trigger in DMM_GROUP:
        dlg, _ = _editor(qt_app, [])
        row = next(
            r
            for r in range(dlg.available_list.count())
            if dlg.available_list.item(r).data(Qt.ItemDataRole.UserRole) == trigger.value
        )
        dlg.available_list.item(row).setSelected(True)
        dlg._add_selected()
        assert set(dlg.selected_sites()) == set(DMM_GROUP), trigger


def test_reselecting_an_enabled_site_does_not_pull_the_group(qt_app):
    """已启用的站点不构成「本次新加入」，故不会触发补齐——与「移除后不复活」同一条原则。"""
    dlg, _ = _editor(qt_app, [Website.DMM])
    row = next(
        r
        for r in range(dlg.available_list.count())
        if dlg.available_list.item(r).data(Qt.ItemDataRole.UserRole) == "DMM"
    )
    dlg.available_list.item(row).setSelected(True)
    dlg._add_selected()
    values = _values(dlg.selected_list)
    assert values == ["DMM"]
    assert values.count("DMM") == 1


@pytest.mark.parametrize(
    "trigger", [Website.JAVLIBRARY, Website.JAVLIBRARY_MIRROR], ids=["JavLibrary", "Javlibrary-mirror"]
)
def test_javlibrary_and_its_mirror_pull_in_each_other(qt_app, trigger):
    """原站与镜像站互为联动：加入其一时自动带上另一条（用户要求）。

    两条通道指向同一份数据，只勾一条等于把另一条可达的路堵上；且原站对大陆 IP 有
    CF 墙、镜像没有，两条都留着刮削时哪条通走哪条。
    """
    dlg, _ = _editor(qt_app, [])
    row = next(
        r
        for r in range(dlg.available_list.count())
        if dlg.available_list.item(r).data(Qt.ItemDataRole.UserRole) == trigger.value
    )
    dlg.available_list.item(row).setSelected(True)
    dlg._add_selected()
    assert set(dlg.selected_sites()) == {Website.JAVLIBRARY, Website.JAVLIBRARY_MIRROR}
    # 反向：只留原站时，加镜像不会把已启用的原站再加一遍
    dlg2, _ = _editor(qt_app, [Website.JAVLIBRARY])
    row2 = next(
        r
        for r in range(dlg2.available_list.count())
        if dlg2.available_list.item(r).data(Qt.ItemDataRole.UserRole) == Website.JAVLIBRARY_MIRROR.value
    )
    dlg2.available_list.item(row2).setSelected(True)
    dlg2._add_selected()
    values = _values(dlg2.selected_list)
    assert values.count("JavLibrary") == 1 and Website.JAVLIBRARY_MIRROR.value in values


# -------------------------------------------------------------------- 移动整组同行


def test_moving_a_member_takes_the_whole_group_to_the_end(qt_app):
    _, lst = _editor(qt_app, SPLIT)
    assert _move(lst, Website.DMM, 5) == ["JavBus", "Getchu", "AVSOX", "DMM", "LibreDMM"]


def test_moving_a_member_takes_the_whole_group_to_the_front(qt_app):
    _, lst = _editor(qt_app, SPLIT)
    # 整块挪到最前，但块内仍按原相对次序 DMM → LibreDMM（拖 LibreDMM 不会把它插到 DMM 之上）
    assert _move(lst, Website.LIBREDMM, 0) == ["DMM", "LibreDMM", "JavBus", "Getchu", "AVSOX"]


def test_moving_a_member_mid_list_keeps_group_adjacent(qt_app):
    _, lst = _editor(qt_app, SPLIT)
    # 拖到第 2 行：落点取自移除前坐标系，须扣掉已越过的 DMM 本身，整组正好停在 Getchu 前
    assert _move(lst, Website.DMM, 2) == ["JavBus", "DMM", "LibreDMM", "Getchu", "AVSOX"]


def test_move_preserves_relative_order_inside_the_group(qt_app):
    _, lst = _editor(qt_app, [Website.LIBREDMM, Website.DMM, GETCHU])
    # 块内顺序沿用原相对次序，不因拖动而翻转
    assert _move(lst, Website.DMM, 3) == [GETCHU.value, "LibreDMM", "DMM"]


def test_moving_ungrouped_site_carries_nothing(qt_app):
    _, lst = _editor(qt_app, [JAVBUS, GETCHU, AVSOX, PRESTIGE])
    assert _move(lst, GETCHU, 4) == ["JavBus", "AVSOX", "Prestige", "Getchu"]


def test_move_is_a_noop_for_unknown_site(qt_app):
    _, lst = _editor(qt_app, [JAVBUS, GETCHU])
    before = _values(lst)
    assert _move(lst, XCITY, 0) == before  # XCITY 不在列表里


def test_move_ignores_stale_drag_sites(qt_app):
    """drag_sites 是上次拖拽的快照；与当前列表取交集，避免陈旧值把站点复制一份。"""
    _, lst = _editor(qt_app, [JAVBUS, Website.DMM, GETCHU])
    lst.drag_sites = [Website.DMM, XCITY]  # XCITY 已不在列表里
    lst._move_sites(3)
    values = _values(lst)
    assert values.count("DMM") == 1
    assert "Xcity" not in values


def test_move_does_not_resurrect_manually_removed_members(qt_app):
    """移动是重排不是加入：被用户移除过的同组站点不该在移动时冒出来。"""
    _, lst = _editor(qt_app, [JAVBUS, Website.DMM, GETCHU])  # LibreDMM 已手动移除
    values = _move(lst, Website.DMM, 3)
    assert "LibreDMM" not in values
    assert values == ["JavBus", "Getchu", "DMM"]


def test_move_leaves_nothing_selected_so_qt_cannot_delete_them(qt_app):
    """挪完之后**不能**留着选中态，否则 Qt 的收尾会把刚挪好的站点删掉。

    `QAbstractItemView::startDrag` 收尾时是
        if (drag->exec(...) == Qt::MoveAction && !d->dropEventMoved) d->clearOrRemove();
    `dropEventMoved` 全 Qt 只有 startDrag 自己置 false，没有任何一处置 true，而 clearOrRemove()
    删的正是「当前选中着的整行」。所以挪完必须自己把选中态清干净。
    （早前这里断言的是「保留选中态便于连着拖下一次」——那条恰好就是站点凭空消失的成因。）
    """
    _, lst = _editor(qt_app, SPLIT)
    for r in range(lst.count()):
        lst.item(r).setSelected(lst.item(r).data(Qt.ItemDataRole.UserRole) == "DMM")
    lst.mimeData([lst.currentItem()])
    lst._move_sites(5)
    assert lst.selectedItems() == [], "留了选中态，Qt 收尾时会把这些站点删掉"
    assert _values(lst) == ["JavBus", "Getchu", "AVSOX", "DMM", "LibreDMM"]


def test_moving_is_grouped_only_when_auto_group_enabled(qt_app):
    """「字段优先级」对话框的名单列表不启用联动，仍走 Qt 默认移动。"""
    lst = PrioritySiteList(ALL_SITES, 74, None, False)
    _setup_site_list(lst, ALL_SITES)  # 构造函数不填充条目，由调用方 _setup_site_list 铺
    try:
        assert lst._auto_group is False
        calls: list[int] = []
        lst._move_sites = lambda row: calls.append(row)  # type: ignore[method-assign]
        row = next(r for r in range(lst.count()) if lst.item(r).data(Qt.ItemDataRole.UserRole) == "DMM")
        lst.item(row).setSelected(True)
        mime = lst.mimeData([lst.item(row)])
        lst.dropEvent(
            QDropEvent(
                QPointF(5, 5),
                Qt.DropAction.MoveAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert calls == []  # 没有走联动分支
    finally:
        lst.deleteLater()


def test_field_priority_dialog_lists_are_not_grouped(qt_app):
    dlg = FieldPriorityDialog("t", FixedScrapingType.YOUMA, list(DMM_GROUP), {}, None)
    try:
        palette = dlg.findChildren(PrioritySiteList)
        assert palette, "应至少找到一个名单列表"
        for lst in palette:
            assert lst._auto_group is False
    finally:
        dlg.deleteLater()


# ----------------------------------------------------------------- 移除不受影响


def test_remove_button_only_drops_the_selected_site(qt_app):
    """「移除选中」按旧规则：只删选中的那一个，同组其余站点留在启用列表里。"""
    dlg, lst = _editor(qt_app, [Website.DMM, Website.LIBREDMM, AVSOX])
    lst.item(0).setSelected(True)
    dlg._remove_selected()
    assert _values(lst) == ["LibreDMM", "AVSOX"]


def test_dragging_back_to_palette_only_removes_that_site(qt_app):
    """拖回「可用网站」= 移除，同样不连带同组站点。"""
    dlg, lst = _editor(qt_app, [Website.DMM, Website.LIBREDMM, AVSOX])
    _drop_back(dlg, Website.DMM)
    assert _values(lst) == ["LibreDMM", "AVSOX"]


def test_removing_a_site_is_persisted_not_re_added_by_later_edits(qt_app):
    """移除 LibreDMM 后再加无关站点，LibreDMM 不复活（联动只由本次新加入的站点触发）。"""
    dlg, _ = _editor(qt_app, [Website.DMM, Website.DMM_API, AVSOX])
    row = next(
        r
        for r in range(dlg.available_list.count())
        if dlg.available_list.item(r).data(Qt.ItemDataRole.UserRole) == "Prestige"
    )
    dlg.available_list.item(row).setSelected(True)
    dlg._add_selected()
    values = _values(dlg.selected_list)
    assert "LibreDMM" not in values
    assert set(values) == {"DMM", "DMM_API", "AVSOX", "Prestige"}
