"""议题 #146 回归: 选择媒体库对话框按库数自适应初始尺寸。

默认最小 480x320, 20 行时约 618x412(宽按 3:2), 双向钳制到屏幕可用区 85%，打开居中。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _make_libs(n: int) -> list[dict]:
    return [{"Id": f"lib-{i}", "Name": f"媒体库{i}", "CollectionType": "movies"} for i in range(n)]


def test_initial_size_20_rows_and_3_by_2():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=1920, avail_h=1080)
    # 高度预算 = chrome_h(120，除列表可视区外的窗口内容) + 20 行 × 行高 30 + slack 12(列表边框/横向滚动条)
    # = 732，再按 initial_size 里「整体向上缩进一行汉字高度」的 -20 收成 712（712 同时高于 320 下限、
    # 低于 int(1080*0.85)=918 的屏幕上限，两个钳制都不生效）。
    assert h == 120 + 20 * 30 + 12 - 20
    assert abs(w - round(h * 3 / 2)) <= 1


def test_initial_size_clamps_to_small_screen():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=800, avail_h=450)
    assert w <= int(800 * 0.85)
    assert h <= int(450 * 0.85)
    assert w >= 480 and h >= 320


def test_initial_size_floors_to_minimum():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=10, visible_rows=1, chrome_h=40, avail_w=1920, avail_h=1080)
    # 高度预算 40 + 1*10 + 12 - 20 = 42 低于 320 下限 → 高被钉在最小值 320；
    # 宽是拿「已钳到下限的 320」按 3:2 反推出来的 round(320*3/2)=480（再经
    # max(480, min(480, int(1920*0.85)=1632)) 仍是 480），故宽正好是最小宽 480。
    assert (w, h) == (480, 320)


def test_initial_size_fewer_rows_shrinks_height():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    _, h_big = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=1920, avail_h=1080)
    _, h_small = LibrarySelectDialog.initial_size(row_h=30, visible_rows=5, chrome_h=120, avail_w=1920, avail_h=1080)
    assert h_small < h_big


def test_dialog_resizes_beyond_minimum_on_large_screen(monkeypatch):
    """集成: 25 库 + 1920x1080 屏 → 明显大于 480x320 最小尺寸。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    assert dlg.width() > 480, "宽应随 3:2 放宽"
    assert dlg.height() > 320
    # 全库上限场景: 不低于 20 行按实际行高(议题 #156 起取真实行高, 不再用 26px 估算下限)的高度
    assert dlg.height() >= 20 * dlg.list_widget.sizeHintForRow(0)


def test_dialog_clamps_on_small_screen(monkeypatch):
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 800, 450))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    assert dlg.width() <= int(800 * 0.85)
    assert dlg.height() <= int(450 * 0.85)
    assert dlg.width() >= 480 and dlg.height() >= 320


def test_dialog_few_libraries_not_taller(monkeypatch):
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    big = LibrarySelectDialog(_make_libs(24))
    small = LibrarySelectDialog(_make_libs(2))
    assert small.height() < big.height()


def _make_libs_mixed(n: int, boxsets: int) -> list[dict]:
    libs = _make_libs(n)
    libs += [{"Id": f"box-{i}", "Name": f"合集{i}", "CollectionType": "boxsets"} for i in range(boxsets)]
    return libs


def test_boxsets_hidden_by_default():
    """议题 #156: 合集(boxsets)是 Emby 自动创建的空壳库(无演员/标签), 默认不展示。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs_mixed(24, 1))
    assert dlg._hidden_boxsets == 1
    assert dlg.list_widget.count() == 24
    assert len(dlg.get_selected_ids()) == 24
    assert all(not lid.startswith("box-") for lid in dlg.get_selected_ids())


def test_boxsets_only_falls_back_to_original_list():
    """议题 #156: 极端情况——全部库都是合集时回退展示原始列表, 避免空对话框。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs_mixed(0, 3))
    assert dlg.list_widget.count() == 3


def test_row_height_pinned_to_checkbox():
    """议题 #156: 行高由 item 显式 sizeHint 钉死为复选框高度——此前从未设置 sizeHint,
    行高由默认代理字号决定、与预算行高无确定关系, Windows 上 20 行预算只容得下 19 行。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs(25))
    cb_h = dlg._checkboxes[0].sizeHint().height()
    assert dlg.list_widget.item(0).sizeHint().height() == cb_h
    assert dlg.list_widget.sizeHintForRow(0) == cb_h


def test_twenty_rows_fully_visible_on_large_screen(monkeypatch):
    """议题 #156 集成回归: 25 库 + 1920x1080 → 视口至少完整容纳 20 行。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    dlg.show()
    row_h = dlg.list_widget.sizeHintForRow(0)
    assert row_h > 0
    assert dlg.list_widget.viewport().height() // row_h >= 20


def test_default_minimum_is_480x320(monkeypatch):
    """默认最小尺寸 480x320：库少时窗口收敛到该下限。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    assert (LibrarySelectDialog.MIN_WIDTH, LibrarySelectDialog.MIN_HEIGHT) == (480, 320)
    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(1))
    assert dlg.minimumWidth() == 480 and dlg.minimumHeight() == 320
    assert (dlg.width(), dlg.height()) == (480, 320)


def test_twenty_libraries_default_size_618x412(monkeypatch):
    """20 个库时默认 618x412（offscreen 默认字号下的行高/边框预算）。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(20))
    assert (dlg.width(), dlg.height()) == (618, 412)


def test_dialog_opens_centered_on_screen(monkeypatch):
    """打开默认居于屏幕正中央（以外框 frameGeometry 为准）。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    avail = QRect(0, 0, 1920, 1080)
    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(20))
    dlg.show()
    _ensure_app().processEvents()
    frame = dlg.frameGeometry()
    assert dlg.x() == avail.x() + (avail.width() - frame.width()) // 2
    assert dlg.y() == avail.y() + (avail.height() - frame.height()) // 2
