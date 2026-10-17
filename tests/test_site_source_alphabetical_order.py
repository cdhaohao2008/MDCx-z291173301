"""「编辑网站」对话框：可用网站（网址源）默认按 A-Z 排序，启用网站顺序仍由用户自定义。

用户需求原文：
    「将软件设置-刮削网站-类型刮削网站-编辑网站里的网址源按A-Z的顺序默认排序，
      注意启用网站的顺序还是要由用户自定义」

两条约束必须同时成立，所以这里既断言「可用列表已排序」，也断言「启用列表原样不动」——
只测前者会漏掉把排序误施加到启用列表上的回归。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    SiteListEditorDialog,
    _list_sites,
    _sorted_sites,
)

# 用注册表全量真实站点，才能覆盖到 Airav.cc / 7mmtv 这类大小写与数字开头的边界值
ALL_SITES = [Website(site) for site in __import__("mdcx.crawlers", fromlist=["c"]).get_registered_crawler_site_values()]

# 非 A-Z 的原始顺序：按此断言「全部添加」未被排序污染
UNSORTED_ORDER = [Website.DMM, Website.AVBASE, Website.XCITY, Website.GETCHU]


def _palette_values(dialog) -> list[str]:
    return [
        dialog.available_list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(dialog.available_list.count())
    ]


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


def test_sorted_sites_is_case_insensitive_az():
    # 大小写混排时按折叠名排：Airav.cc 排在 AVBase 之前（airav < avbase）
    assert [s.value for s in _sorted_sites([Website.AVBASE, Website.AIRAV_CC, Website.DMM])] == [
        "Airav.cc",
        "AVBase",
        "DMM",
    ]


def test_sorted_sites_prefix_orders_shorter_first():
    # 同前缀：JavDB < JavDB_API < JavDB_APP（折叠名逐字符比较）
    assert [s.value for s in _sorted_sites([Website.JAVDB_APP, Website.JAVDB, Website.JAVDB_API])] == [
        "JavDB",
        "JavDB_API",
        "JavDB_APP",
    ]


def test_sorted_sites_does_not_mutate_input():
    source = list(UNSORTED_ORDER)
    _sorted_sites(source)
    assert source == UNSORTED_ORDER


def test_sorted_sites_empty():
    assert _sorted_sites([]) == []


# --------------------------------------------------------------------------- 对话框运行期


def test_available_palette_is_sorted_az(dialog):
    values = _palette_values(dialog)
    assert values == sorted(values, key=lambda v: (v.casefold(), v))
    # 数字开头与含点/下划线的品牌值都应就位，而不是被排到末尾或挤掉
    assert values[0] == "7mmtv"
    for expected in ("Airav.cc", "JavDB_APP", "Madou.club", "R18.dev"):
        assert expected in values


def test_enabled_list_keeps_user_order(dialog):
    """排序只作用于可用列表；进来时是什么顺序，启用列表就保持什么顺序。"""
    assert [site.value for site in dialog.selected_sites()] == ["DMM", "AVBase"]
    assert [site.value for site in _list_sites(dialog.selected_list)] == ["DMM", "AVBase"]


def test_enabled_order_survives_refresh(dialog):
    """_refresh_lists 会按 _palette_sites 重画可用列表，不能连带重排启用列表。"""
    dialog._refresh_lists()
    assert [site.value for site in dialog.selected_sites()] == ["DMM", "AVBase"]
    assert _palette_values(dialog) == sorted(_palette_values(dialog), key=lambda v: (v.casefold(), v))


def test_add_selected_keeps_existing_priority_and_appends_new(qt_app):
    """添加新站点时，老站点的相对优先级不变，新站点追加在后（不被 A-Z 打乱）。"""
    dlg = SiteListEditorDialog("t", [Website.XCITY, Website.DMM], ALL_SITES, None)
    try:
        dlg.available_list.item(0).setSelected(True)  # 7mmtv，与已有站点无关
        dlg._add_selected()
        values = [site.value for site in dlg.selected_sites()]
        assert values[:2] == ["Xcity", "DMM"]
        assert values[2] == "7mmtv"
    finally:
        dlg.deleteLater()


def test_add_all_uses_original_registration_order(qt_app):
    """「全部添加」写进启用列表的是用户自定的优先级序列，沿用传入原序、不做 A-Z 排序。"""
    dlg = SiteListEditorDialog("t", [], UNSORTED_ORDER, None)
    try:
        dlg._add_all()
        assert [site.value for site in dlg.selected_sites()] == [
            "DMM",
            "AVBase",
            "Xcity",
            "Getchu",
        ]
        # 但可用列表仍然按 A-Z 展示
        assert _palette_values(dlg) == ["AVBase", "DMM", "Getchu", "Xcity"]
    finally:
        dlg.deleteLater()


def test_group_expansion_still_works_alongside_sorting(qt_app):
    """上一轮的联动组不因排序而失效：从按 A-Z 排列的可用列表里加入 DMM 仍补齐全组。"""
    dlg = SiteListEditorDialog("t", [], ALL_SITES, None)
    try:
        row = next(
            r
            for r in range(dlg.available_list.count())
            if dlg.available_list.item(r).data(Qt.ItemDataRole.UserRole) == "DMM"
        )
        dlg.available_list.item(row).setSelected(True)
        dlg._add_selected()
        assert set(dlg.selected_sites()) == {Website.DMM, Website.DMM_API, Website.LIBREDMM}
    finally:
        dlg.deleteLater()
