"""议题 #180 回归：演员详情「现有数据」简介把 `<br>` 还原为换行展示。

Emby 服务器上的简介以 `<br>` 分行（服务器端渲染需要，数据本身正确），
MDCx 详情对话框此前按纯文本直出，用户看到满屏 `<br>` 标签。
修复仅在展示层替换，数据对象与同步 payload 不受影响。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _make_actor(**kw):
    from mdcx.tools.emby_actor_manager import ActorInfo

    base = {"name": "高桥惠子", "actor_id": "id1", "server_id": "srv1"}
    base.update(kw)
    return ActorInfo(**base)


def test_detail_dialog_renders_br_as_newline():
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    actor = _make_actor(existing_overview="简介文本<br>===== 个人资料 =====<br>出生: 1955年1月22日<br/>生日")
    dlg = ActorDetailDialog(actor)
    text = dlg.existing_info.toPlainText()
    assert "<br" not in text.lower()
    assert "简介文本\n===== 个人资料 =====\n出生: 1955年1月22日\n生日" in text
    # 数据本体不变：同步 payload 仍带 <br>（服务器渲染依赖原样）
    assert actor.existing_overview == "简介文本<br>===== 个人资料 =====<br>出生: 1955年1月22日<br/>生日"
    dlg.deleteLater()


def test_detail_dialog_max_min_buttons_and_layout():
    """演员详情：有最大化/最小化按钮，三栏 1:2:1，默认 1080x720（数据源测试窗同款）。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        flags = dlg.windowFlags()
        assert flags & Qt.WindowType.WindowMaximizeButtonHint, "应有最大化按钮"
        assert flags & Qt.WindowType.WindowMinimizeButtonHint, "应有最小化按钮"
        assert dlg.minimumWidth() == 1080 and dlg.minimumHeight() == 720
        layout = dlg.layout()
        assert [layout.stretch(i) for i in range(layout.count())] == [1, 2, 1]
        panel = layout.itemAt(2).widget()
        assert panel.maximumWidth() > 1000, "快速设置面板不限定宽，stretch 才分得到"
    finally:
        dlg.deleteLater()


def test_detail_dialog_br_case_and_space_variants():
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    actor = _make_actor(existing_overview="a<BR>b<Br/>c<br />d")
    dlg = ActorDetailDialog(actor)
    assert dlg.existing_info.toPlainText().startswith("简介: a\nb\nc\nd\n")
    dlg.deleteLater()


def test_detail_dialog_independent_from_manager():
    """详情与管理器互不干扰：无父级、非模态；同演员复用、异演员多开；关窗摘除。"""
    _ensure_app()
    from PyQt6.QtCore import Qt

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    def _pump(n=10):
        for _ in range(n):
            _ensure_app().processEvents()

    mgr = EmbyActorManagerDialog()
    try:
        mgr.show()
        _pump()
        a1 = _make_actor(name="甲", actor_id="da1")
        a2 = _make_actor(name="乙", actor_id="da2")
        mgr._actors = [a1, a2]
        mgr._populate_table([a1, a2])
        _pump()

        def _row_of(name):
            for r in range(mgr.table.rowCount()):
                item = mgr.table.item(r, 1)
                if item is not None and item.text() == name:
                    return r
            raise AssertionError(f"表格缺 {name} 行")

        mgr._on_table_double_clicked(_row_of("甲"), 1)
        _pump()
        assert set(mgr._detail_dialogs) == {"da1"}
        d1 = mgr._detail_dialogs["da1"]
        assert d1.parent() is None, "详情应是无父级独立窗口"
        assert not d1.isModal(), "详情应非模态，管理器可并存操作"
        assert d1.isVisible()
        assert d1.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # 同演员再次双击：复用，不多开
        mgr._on_table_double_clicked(_row_of("甲"), 1)
        _pump()
        assert set(mgr._detail_dialogs) == {"da1"}
        assert mgr._detail_dialogs["da1"] is d1
        # 不同演员：多开，互不干扰
        mgr._on_table_double_clicked(_row_of("乙"), 1)
        _pump()
        assert set(mgr._detail_dialogs) == {"da1", "da2"}
        # 关一个：摘除，另一个与管理器都不受影响
        d1.close()
        _pump()
        assert set(mgr._detail_dialogs) == {"da2"}
        assert mgr.isVisible()
        # 本地 log 可用（此前详情无 log 方法，失败路径直接 AttributeError）
        rest = mgr._detail_dialogs["da2"]
        rest.log("smoke")
        assert rest._log_lines == ["smoke"]
        for d in list(mgr._detail_dialogs.values()):
            d.close()
        _pump()
        assert mgr._detail_dialogs == {}
    finally:
        for d in list(getattr(mgr, "_detail_dialogs", {}).values()):
            try:
                d.close()
            except RuntimeError:
                pass
        mgr.close()
        _pump()

    # 管理器先关：详情回写静默丢弃，不炸
    mgr2 = EmbyActorManagerDialog()
    try:
        cb = mgr2._make_detail_synced()
    finally:
        mgr2.close()
        _pump()
        mgr2.deleteLater()
        _pump()
    cb(_make_actor(name="丙", actor_id="da3"))


def test_detail_dialog_columns_exact_ratio_and_lists_half():
    """三栏按总宽精确 1:2:1（左栏不再比快速设置窄），两列表 1:1 平分面板高度。"""
    _ensure_app()
    from PyQt6.QtWidgets import QSizePolicy

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        for _ in range(15):
            _ensure_app().processEvents()
        layout = dlg.layout()
        cols = [layout.itemAt(i).widget() for i in range(3)]
        for w in cols:
            assert w.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
        ws = [w.width() for w in cols]
        assert abs(ws[1] - 2 * ws[0]) <= 2, f"新数据应为现有数据 2 倍: {ws}"
        assert abs(ws[2] - ws[0]) <= 2, f"快速设置应与现有数据等宽: {ws}"
        panel = cols[2]
        assert abs(panel.image_list.height() - panel.info_list.height()) <= 1
        assert panel._lists_expanded is True
        assert panel.folder_edit.width() > 0
    finally:
        dlg.deleteLater()
