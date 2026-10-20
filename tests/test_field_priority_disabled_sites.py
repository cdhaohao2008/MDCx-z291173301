"""「字段优先级」窗口同步「编辑网站」的禁用灰显。

用户要求（2026-10-20）：在「编辑网站」禁用某站后，字段优先级窗口上方「可用网站」以及
标题、原标题、简介、原简介、演员、全部演员等每个字段右侧的站点 chip 都要同步变灰；
重新启用后恢复正常。字段窗口本身不提供启用/禁用右键菜单，只负责把状态显示出来。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import FieldPriorityConfig  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    SITE_DISABLED_ROLE,
    FieldPriorityDialog,
    SitePaletteList,
)
from mdcx.gen.field_enums import CrawlerResultFields  # noqa: E402

_SITES = [
    Website.OFFICIAL_10MUSUME,
    Website.OFFICIAL_1PONDO,
    Website.OFFICIAL_CARIBBEANCOM,
    Website.OFFICIAL_HEYZO,
    Website.OFFICIAL_PACOPACOMAMA,
]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _item_disabled(list_widget, site: Website) -> bool:
    for row in range(list_widget.count()):
        item = list_widget.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == site.value:
            return bool(item.data(SITE_DISABLED_ROLE))
    raise AssertionError(f"{site.value} 不在列表里")


def _make_dialog(disabled: list[Website]) -> FieldPriorityDialog:
    configs = {
        CrawlerResultFields.TITLE: FieldPriorityConfig(site_prority=[Website.OFFICIAL_HEYZO, Website.OFFICIAL_10MUSUME])
    }
    return FieldPriorityDialog(
        "字段优先级",
        FixedScrapingType.WUMA,
        _SITES,
        configs,
        None,
        disabled_sites=disabled,
    )


def test_palette_and_every_field_row_gray_disabled_site(qt_app):
    dlg = _make_dialog([Website.OFFICIAL_HEYZO])
    try:
        palette = dlg.findChild(SitePaletteList)
        assert palette is not None
        assert _item_disabled(palette, Website.OFFICIAL_HEYZO) is True
        assert _item_disabled(palette, Website.OFFICIAL_10MUSUME) is False

        # 不只是标题字段：所有字段行都拿到同一份禁用集合
        for field, list_widget in dlg._field_lists.items():
            if field == CrawlerResultFields.TITLE:
                assert _item_disabled(list_widget, Website.OFFICIAL_HEYZO) is True
                assert _item_disabled(list_widget, Website.OFFICIAL_10MUSUME) is False
            assert list_widget.disabled_sites == {Website.OFFICIAL_HEYZO}, field
    finally:
        dlg.deleteLater()


def test_reenabled_site_is_not_gray(qt_app):
    dlg = _make_dialog([])
    try:
        palette = dlg.findChild(SitePaletteList)
        assert palette is not None
        assert _item_disabled(palette, Website.OFFICIAL_HEYZO) is False
        assert _item_disabled(dlg._field_lists[CrawlerResultFields.TITLE], Website.OFFICIAL_HEYZO) is False
    finally:
        dlg.deleteLater()


def test_reset_rebuild_keeps_disabled_state(qt_app):
    dlg = _make_dialog([Website.OFFICIAL_HEYZO])
    try:
        dlg._reset_field(CrawlerResultFields.TITLE)
        assert _item_disabled(dlg._field_lists[CrawlerResultFields.TITLE], Website.OFFICIAL_HEYZO) is True
    finally:
        dlg.deleteLater()
