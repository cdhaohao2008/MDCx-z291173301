"""「编辑网站」对话框：右键启用/禁用站点。

用户需求：
    「鼠标右键单击加上启用站点：***，禁用站点：*** 功能，启用站点/禁用站点在复制站点
    之上展示，被禁用的站点在有码、无码、个摄、欧美、传媒、短剧、动漫组内同步禁用，
    被禁用的站点在启用网站内也同步变成灰色，默认启用全部站点，禁用站点后站点变成灰色，
    被禁用的站点网络检测、刮削字段、下载图片等等全部跳过」

本文件锁 UI 侧的四件事：
    1. 两条动作永远排在「复制站点」之前，按当前状态互斥置灰；
    2. 默认没有禁用站点，点「禁用站点」后候选区与启用列表同时灰显；
    3. 再点「启用站点」恢复；
    4. 灰显只影响绘制，项目仍可选中、拖拽、右键（只是不参与检测/刮削）。
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QStyleOptionViewItem  # noqa: E402

from mdcx.config.enums import Website  # noqa: E402
from mdcx.config.models import Config  # noqa: E402
from mdcx.controllers.main_window.site_priority_dialog import (  # noqa: E402
    SITE_DISABLED_ROLE,
    SiteListEditorDialog,
    _SiteItemDelegate,
)

SITES = [Website.DMM, Website.MGSTAGE, Website.JAVDB]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _shown(dlg) -> None:
    dlg.resize(860, 640)
    dlg.show()
    QApplication.processEvents()


def _item_of(list_widget, site: Website):
    return next(
        list_widget.item(row)
        for row in range(list_widget.count())
        if list_widget.item(row).data(Qt.ItemDataRole.UserRole) == site.value
    )


def _center(list_widget, item) -> QPoint:
    return list_widget.visualItemRect(item).center()


def _menu_actions(list_widget, point, monkeypatch) -> list:
    captured: list[QMenu] = []

    def fake_exec(self, *args, **kwargs):
        captured.append(self)
        return None

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    list_widget.customContextMenuRequested.emit(point)
    return captured[-1].actions()


def _choose(list_widget, point, text: str, monkeypatch) -> None:
    def fake_exec(self, *args, **kwargs):
        return next(action for action in self.actions() if action.text() == text and action.isEnabled())

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    list_widget.customContextMenuRequested.emit(point)


def _toggle(dlg, list_widget, site: Website, action_text: str, monkeypatch) -> None:
    item = _item_of(list_widget, site)
    _choose(list_widget, _center(list_widget, item), action_text, monkeypatch)


def test_default_config_has_no_disabled_sites():
    assert Config().website_disabled == []


def test_disabled_actions_are_above_copy_and_follow_state(qt_app, monkeypatch):
    dlg = SiteListEditorDialog("t", [Website.DMM], SITES, None)
    try:
        _shown(dlg)
        point = _center(dlg.selected_list, _item_of(dlg.selected_list, Website.DMM))
        actions = _menu_actions(dlg.selected_list, point, monkeypatch)
        texts = [action.text() for action in actions]
        assert texts[:4] == ["启用站点：DMM", "禁用站点：DMM", "", "复制站点：DMM"]
        assert texts.index("禁用站点：DMM") < texts.index("复制站点：DMM")

        enable_action = next(action for action in actions if action.text() == "启用站点：DMM")
        disable_action = next(action for action in actions if action.text() == "禁用站点：DMM")
        assert not enable_action.isEnabled()
        assert disable_action.isEnabled()
    finally:
        dlg.deleteLater()


def test_disable_and_enable_site_keeps_palette_and_enabled_list_in_sync(qt_app, monkeypatch):
    dlg = SiteListEditorDialog("t", [Website.DMM, Website.MGSTAGE], SITES, None)
    try:
        _shown(dlg)

        _toggle(dlg, dlg.available_list, Website.DMM, "禁用站点：DMM", monkeypatch)

        assert dlg.disabled_sites() == [Website.DMM]
        for list_widget in (dlg.available_list, dlg.selected_list):
            item = _item_of(list_widget, Website.DMM)
            assert item.data(SITE_DISABLED_ROLE) is True
            assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)

        _toggle(dlg, dlg.selected_list, Website.DMM, "启用站点：DMM", monkeypatch)

        assert dlg.disabled_sites() == []
        for list_widget in (dlg.available_list, dlg.selected_list):
            assert _item_of(list_widget, Website.DMM).data(SITE_DISABLED_ROLE) is False
    finally:
        dlg.deleteLater()


def test_disabled_item_is_drawn_grey_but_stays_interactive(qt_app):
    dlg = SiteListEditorDialog("t", [Website.DMM, Website.MGSTAGE], SITES, None, disabled_sites=[Website.DMM])
    try:
        _shown(dlg)
        item = _item_of(dlg.selected_list, Website.DMM)
        delegate = dlg.selected_list.itemDelegate()
        assert isinstance(delegate, _SiteItemDelegate)

        option = QStyleOptionViewItem()
        delegate.initStyleOption(option, dlg.selected_list.indexFromItem(item))
        assert not (option.state & QStyle.StateFlag.State_Enabled)

        # 只改绘制状态，不摘 flags：禁用站仍能被选中、拖拽与右键操作。
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled
        assert item.flags() & Qt.ItemFlag.ItemIsSelectable
        assert item.flags() & Qt.ItemFlag.ItemIsDragEnabled
    finally:
        dlg.deleteLater()
