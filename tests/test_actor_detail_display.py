"""议题 #180 回归：演员详情「现有数据」简介把 `<br>` 还原为换行展示。

Emby 服务器上的简介以 `<br>` 分行（服务器端渲染需要，数据本身正确），
MDCx 详情对话框此前按纯文本直出，用户看到满屏 `<br>` 标签。
修复仅在展示层替换，数据对象与同步 payload 不受影响。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
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

        mgr._open_actor_detail(_row_of("甲"))
        _pump()
        assert set(mgr._detail_dialogs) == {"da1"}
        d1 = mgr._detail_dialogs["da1"]
        assert d1.parent() is None, "详情应是无父级独立窗口"
        assert not d1.isModal(), "详情应非模态，管理器可并存操作"
        assert d1.isVisible()
        assert d1.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # 同演员再次打开：复用，不多开
        mgr._open_actor_detail(_row_of("甲"))
        _pump()
        assert set(mgr._detail_dialogs) == {"da1"}
        assert mgr._detail_dialogs["da1"] is d1
        # 不同演员：多开，互不干扰
        mgr._open_actor_detail(_row_of("乙"))
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
    from PyQt6.QtWidgets import QLabel, QSizePolicy

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
        # 本地头像目录行已移到中列按钮行上方（面板内不再有），此处只钉住它不再属于面板
        assert not hasattr(panel, "folder_edit")
        assert not [lbl for lbl in panel.findChildren(QLabel) if lbl.text() == "本地头像目录:"]
    finally:
        dlg.deleteLater()


def _flatten_widgets(layout):
    """按布局顺序展开直接子控件（子布局内的控件紧跟该子布局，深度不限）。"""
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget()
        if widget is not None:
            out.append(widget)
            continue
        sub = item.layout()
        if sub is not None:
            out.extend(_flatten_widgets(sub))
    return out


def _detail_buttons(dlg):
    """需求点名的六枚按钮：获取头像/获取信息/同步头像+简介/只同步头像/只同步简介/浏览。"""
    return [
        dlg.btn_fetch_image,
        dlg.btn_fetch_info,
        dlg.btn_sync_both,
        dlg.btn_sync_image,
        dlg.btn_sync_info,
        dlg.folder_browse_btn,
    ]


def test_detail_dialog_font_bumped_title_untouched():
    """演员详情窗口内所有控件比应用默认字号大一号；窗口标题（系统窗口框绘制）保持原样。"""
    _ensure_app()
    from PyQt6.QtWidgets import QLabel

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog, _ui_font_pt

    dlg = ActorDetailDialog(_make_actor(name="青山知可子"))
    try:
        dlg.show()
        for _ in range(5):
            _ensure_app().processEvents()
        expected = float(_ui_font_pt().removesuffix("pt"))
        assert expected > QApplication.font().pointSizeF(), "详情窗应比应用默认字号大一号"
        labels = [lbl for lbl in dlg.findChildren(QLabel) if lbl.text()]
        assert labels, "详情窗内应有可见文字"
        for lbl in labels:
            assert lbl.font().pointSizeF() == pytest.approx(expected), f"[{lbl.text()[:12]}] 字号未放大"
        # 标题栏文字由系统窗口框绘制、不受 QSS 影响：文案不变（钉住「标题除外」这条）
        assert dlg.windowTitle() == "演员详情 - 青山知可子"
    finally:
        dlg.deleteLater()


def test_detail_dialog_primary_buttons_and_max_height_stretch():
    """六枚按钮蓝色底 + 最大化时高度按对话框高度比例等比拉升，宽度不动，还原即恢复。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        dlg.resize(1600, 1000)
        for _ in range(10):
            _ensure_app().processEvents()

        for btn in _detail_buttons(dlg):
            assert btn.objectName() == "btnPrimary", f"[{btn.text()}] 缺主按钮样式标记"
        qss = dlg.styleSheet()
        assert "QPushButton#btnPrimary" in qss and "#1565c0" in qss, "详情窗须自带蓝色主按钮样式"

        # 离屏平台没有真正的最大化窗口，强制 isMaximized 为真驱动 _sync_button_stretch
        # 注意：宽度不变只对五个「功能按钮」成立；【浏览】按用户要求随窗口状态改宽
        # （最小化/还原 = 【只同步简介】宽，最大化 = 其一半），由下一个用例单独锁。
        normal = {b.text(): (b.width(), b.height(), b.minimumHeight()) for b in _detail_buttons(dlg)}
        dlg.isMaximized = lambda: True
        try:
            dlg.resize(1600, 1200)
            for _ in range(10):
                _ensure_app().processEvents()
            ratio = dlg.height() / dlg._dialog_base_h
            assert ratio > 1.0, "最大化态高度应大于默认高度"
            for btn, base in dlg._stretch_base_h:
                want = max(1, int(round(base * ratio)))
                assert btn.minimumHeight() == want, f"[{btn.text()}] 高度未按比例 {ratio:.2f} 拉升"
                assert btn.height() >= want, f"[{btn.text()}] 实际高度未跟上"
                if btn is dlg.folder_browse_btn:
                    continue
                assert btn.width() == normal[btn.text()][0], f"[{btn.text()}] 宽度不应被改动"
        finally:
            dlg.isMaximized = lambda: False
        dlg.resize(1600, 1000)
        for _ in range(10):
            _ensure_app().processEvents()
        restored = {b.text(): (b.width(), b.height(), b.minimumHeight()) for b in _detail_buttons(dlg)}
        for btn in _detail_buttons(dlg):
            if btn is dlg.folder_browse_btn:
                continue
            assert restored[btn.text()] == normal[btn.text()], f"[{btn.text()}] 还原后应回到普通态几何"
        assert restored[dlg.folder_browse_btn.text()][1:] == normal[dlg.folder_browse_btn.text()][1:], (
            "【浏览】还原后高度应复原"
        )
    finally:
        dlg.deleteLater()


def test_detail_dialog_browse_width_follows_sync_info():
    """【浏览】宽度跟着【只同步简介】走：还原/最小化时等宽，最大化时为其一半。

    基准取兄弟按钮的当前宽而非写死数值 —— 五个功能按钮本身会随栏宽伸缩，
    写死会在别的分辨率/窗口尺寸下对不齐。
    """
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        for size in ((1080, 720), (1600, 1000), (1920, 1200)):
            dlg.resize(*size)
            _pump()
            ref = dlg.btn_sync_info.width()
            assert dlg.folder_browse_btn.width() == ref, f"{size} 下【浏览】应与【只同步简介】等宽"

        dlg.isMaximized = lambda: True
        try:
            dlg.resize(1920, 1000)  # 必须换尺寸，否则不发出 Resize、驱动不到 _sync_browse_width
            _pump()
            ref = dlg.btn_sync_info.width()
            # 产品侧取 round（奇数宽四舍五入到最近的一半），不是截断
            half = max(1, int(round(ref / 2.0)))
            assert dlg.folder_browse_btn.width() == half, f"最大化时【浏览】应为【只同步简介】的一半 ({half})"
        finally:
            dlg.isMaximized = lambda: False
        dlg.resize(1920, 1200)
        _pump()
        assert dlg.folder_browse_btn.width() == dlg.btn_sync_info.width(), "还原后【浏览】应回到等宽"
    finally:
        dlg.deleteLater()


def test_detail_dialog_existing_info_has_no_focus_frame():
    """左栏只读简介框不占焦点，开窗即无强调色（蓝）边框。

    根因：Qt 的 windows11 风格会给「有焦点的文本框」描一圈强调色边框，而详情窗
    的第一个可聚焦控件恰是这个**只读**框，用户在左栏最底部看到一条蓝线，既不能
    点进去改、又像多出来的装饰。故令其 NoFocus（顺带移出 Tab 链），并把初始焦点
    留给窗口本身，免得蓝框只是挪到中间的「简介」框上去。
    """
    _ensure_app()
    from PyQt6.QtCore import Qt

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor(existing_overview="旧简介<br>line2"))
    try:
        assert dlg.existing_info.isReadOnly(), "本用例针对只读展示框"
        assert dlg.existing_info.focusPolicy() == Qt.FocusPolicy.NoFocus, "只读框不应占焦点"
        assert dlg.focusPolicy() == Qt.FocusPolicy.StrongFocus, "窗口须能接住初始焦点"

        dlg.show()
        _pump()
        focused = _ensure_app().focusWidget()
        assert focused is dlg, f"开窗后焦点应留在窗口上，实则落在 {type(focused).__name__}"
        assert focused is not dlg.existing_info and focused is not dlg.overview_edit, "不应有输入框被描上焦点框"
        # NoFocus 的控件既不在 Tab 链里、点击也不会聚焦它，焦点只能由程序 setFocus()
        # 直接塞进来 —— 正常交互路径下这个只读框拿不到焦点，蓝框也就无从产生。
    finally:
        dlg.deleteLater()


def test_detail_dialog_is_strictly_centered_on_screen():
    """窗口外框严格居于屏幕可用区正中央（且不随管理器位置漂移）。

    两处旧毛病：①按「管理器窗口中心」定位，管理器一被拖动详情窗就跟着偏；
    ②用客户区尺寸配 move()（move 收的是外框左上角），整体偏下偏右一个标题栏。
    故断言的是 **frameGeometry**（含标题栏/边框）与可用区中心的偏差，允许 1px 取整余量。
    """
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    avail = _ensure_app().primaryScreen().availableGeometry()

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        _pump()
        frame = dlg.frameGeometry()
        dx = frame.center().x() - avail.center().x()
        dy = frame.center().y() - avail.center().y()
        if frame.width() <= avail.width() and frame.height() <= avail.height():
            # 客户区尺寸 ≠ 外框尺寸：断言外框居中才是「视觉上居中」
            assert abs(dx) <= 1 and abs(dy) <= 1, f"外框中心应落在可用区正中央，实则偏 ({dx}, {dy})"
        else:
            # 某一维比可用区还大（离屏平台固定 800 宽，而详情窗最小 1080 宽）：
            # 该维按设计钳到可用区左上/上缘，保证标题栏留在屏内抓得到。
            if frame.width() > avail.width():
                assert frame.x() == avail.x(), f"宽度放不下时应贴可用区左缘，实则 x={frame.x()}"
            if frame.height() > avail.height():
                assert frame.y() == avail.y(), f"高度放不下时应贴可用区上缘，实则 y={frame.y()}"

        # 只居中一次：用户挪过之后重新 show 不该被拽回正中（否则每次开关都被重置位置）
        dlg.move(10, 10)
        dlg.hide()
        _pump()
        dlg.show()
        _pump()
        assert dlg.frameGeometry().x() == 10, "复用已有窗口时应保留用户挪动的位置"

        # 最大化/还原走系统原生几何，不该被居中逻辑改写
        dlg.showMaximized()
        _pump()
        dlg.showNormal()
        _pump()
        assert dlg.frameGeometry().x() == 10, "最大化往返后仍应保留原位置"
    finally:
        dlg.deleteLater()


def test_detail_dialog_folder_row_above_buttons():
    """本地头像目录（标签/输入框/浏览）移到中列，置于获取头像、获取信息按钮行上方。"""
    _ensure_app()
    from PyQt6.QtWidgets import QLabel, QLineEdit

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        for _ in range(5):
            _ensure_app().processEvents()
        root = dlg.layout()
        middle = root.itemAt(1).widget()  # 新数据（同步前可编辑）中列
        order = _flatten_widgets(middle.layout())
        idx = {id(w): i for i, w in enumerate(order)}

        assert dlg.folder_edit.parentWidget() is middle, "目录输入框应在中列而非快速设置面板"
        assert dlg.folder_browse_btn.parentWidget() is middle, "浏览按钮应在中列"
        label = [lbl for lbl in middle.findChildren(QLabel) if lbl.text() == "本地头像目录:"]
        assert label, "中列内应有「本地头像目录:」标签"

        i_folder = idx[id(dlg.folder_edit)]
        i_browse = idx[id(dlg.folder_browse_btn)]
        i_fetch_img = idx[id(dlg.btn_fetch_image)]
        i_fetch_info = idx[id(dlg.btn_fetch_info)]
        assert max(i_folder, i_browse) < i_fetch_img < i_fetch_info, (
            f"目录行应整体在按钮行上方，实测 目录输入框={i_folder} 浏览={i_browse} "
            f"获取头像={i_fetch_img} 获取信息={i_fetch_info}"
        )
        # 与快速设置面板同列的旧位置已清空
        panel = root.itemAt(2).widget()
        assert not hasattr(panel, "folder_edit")
        assert not panel.findChildren(QLineEdit), "面板内不应再有目录输入框"
    finally:
        dlg.deleteLater()


def test_detail_dialog_folder_edit_autosaves(monkeypatch):
    """目录输入框改动即自动保存；面板改数据源顺序时不得把目录值覆盖回旧值。

    测试桩 manager 刻意不实现 `_replace_config` / `save`（防止用例真写盘），
    这里按真实 manager 的调用形状打桩，只校验「配置流向」。
    """
    _ensure_app()
    from mdcx.config.manager import manager
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    seen: dict = {}

    def _replace_config(cfg):
        # 真实 manager 的语义：替换内存配置（下面面板的「带回当前值」才成立）
        seen["cfg"] = cfg
        manager.config = cfg

    monkeypatch.setattr(manager, "_replace_config", _replace_config, raising=False)
    monkeypatch.setattr(manager, "save", lambda: seen.update(saved=True), raising=False)

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.folder_edit.setText("D:/测试头像目录")
        assert seen.get("saved") is True, "目录改动未触发自动保存"
        assert seen["cfg"].actor_photo_folder == "D:/测试头像目录", "目录值未写入待存配置"
        # 面板拖拽排序触发 _save：目录值应原样带回当前值，不被面板的旧兜底覆盖
        seen.clear()
        dlg.layout().itemAt(2).widget()._save()
        assert seen["cfg"].actor_photo_folder == dlg.folder_edit.text().strip(), "面板保存覆盖了目录值"
    finally:
        dlg.deleteLater()


def _preview_pairs(dlg):
    """（预览框, 所在栏）两对：现有数据 / 新数据（同步前可编辑）。"""
    root = dlg.layout()
    return (
        ("现有数据", dlg.existing_avatar_label, root.itemAt(0).widget()),
        ("新数据", dlg.new_avatar_label, root.itemAt(1).widget()),
    )


def _pump(n=10):
    for _ in range(n):
        _ensure_app().processEvents()


def test_detail_dialog_preview_takes_third_of_column_height():
    """两个头像预览框各占所在栏三分之一高度、横向铺满整栏，头像水平居中。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import (
        _AVATAR_PREVIEW_COL_RATIO,
        ActorDetailDialog,
    )

    assert _AVATAR_PREVIEW_COL_RATIO == 3, "预览框占栏高的比例应为三分之一"
    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        for size in ((1080, 720), (1400, 900), (1600, 1000)):
            dlg.resize(*size)
            _pump()
            for name, label, box in _preview_pairs(dlg):
                assert label.parentWidget() is box, f"[{name}] 预览框应挂在该栏内"
                assert label.height() == box.height() // 3, (
                    f"[{name}] 预览框应占该栏三分之一高度，实测 框={label.height()} 栏={box.height()}"
                )
                # 横向铺满整栏（原 setFixedSize(130,180) 会卡在 130 不铺栏）
                assert label.width() >= box.width() - 32, (
                    f"[{name}] 预览框应铺满栏宽，实测 框={label.width()} 栏={box.width()}"
                )
                assert label.alignment() & Qt.AlignmentFlag.AlignHCenter, f"[{name}] 头像应水平居中"
                assert label.alignment() & Qt.AlignmentFlag.AlignVCenter, f"[{name}] 头像应垂直居中"
        # 左栏只有「预览框 + 简介」两个控件：预览框按外框高取一半后，
        # 简介应吃满栏内剩余高度——用实际几何核算，两个控件 + 边距 + 间隙之外
        # 只该剩组标题那点占位（约 22px），不该有整块空白留给简介。
        _, label, left = _preview_pairs(dlg)[0]
        lay = left.layout()
        m = lay.contentsMargins()
        used = m.top() + m.bottom() + lay.spacing() + label.height() + dlg.existing_info.height()
        assert left.height() - used <= 40, f"左栏简介未吃满剩余高度，栏内空出 {left.height() - used}px"
    finally:
        dlg.deleteLater()


def test_detail_dialog_preview_height_taken_from_overview():
    """中栏多出来的高度由下方内容让出，简介让得比信息表格多（stretch 2 : 1）。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor(new_overview="简介" * 80))
    try:
        dlg.show()
        dlg.resize(1600, 1000)
        _pump()
        middle = dlg.layout().itemAt(1).widget()
        lay = middle.layout()
        stretch = {}
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None:
                stretch[id(w)] = lay.stretch(i)
        assert stretch[id(dlg.overview_edit)] == 2, "简介应占更大的伸缩比（多占的空间从简介获取）"
        assert stretch[id(dlg.info_table)] == 1
        # 让出的是高度不是可见性：简介仍要装得下内容
        assert dlg.overview_edit.height() > dlg.overview_edit.minimumHeight()
    finally:
        dlg.deleteLater()


def test_detail_dialog_preview_rescales_pixmap(tmp_path):
    """预览框随窗口变高变矮，头像按新框尺寸等比重绘；文字态（无头像）不被重绘覆盖。"""
    _ensure_app()
    from PyQt6.QtGui import QPixmap

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor())
    try:
        dlg.show()
        dlg.resize(1600, 1000)
        _pump()
        src = tmp_path / "face.png"
        QPixmap(400, 640).fill()  # 竖版 5:8
        QPixmap(400, 640).save(str(src))

        dlg._show_pixmap(dlg.existing_avatar_label, str(src))
        _pump()
        label = dlg.existing_avatar_label
        big_h = label.pixmap().height()
        # 框比原图更「瘦」（框宽高比 < 图宽高比），KeepAspectRatio 下按框高铺满
        assert big_h == label.height(), "头像应按框高等比铺满"
        assert abs(label.pixmap().width() / big_h - 400 / 640) < 0.02, "重绘后宽高比应保持不变"

        dlg.resize(1080, 720)
        _pump()
        small_h = label.pixmap().height()
        assert small_h == label.height(), "框变矮后头像应跟着重绘"
        assert small_h < big_h, "窗口变小后头像应变小"

        # 文字态：setText 清掉了 pixmap，resize 时不能被原图重绘盖掉
        label.setText("无头像")
        dlg.resize(1400, 900)
        _pump()
        assert label.pixmap().isNull(), "文字态不应被原图覆盖"
        assert label.text() == "无头像"
    finally:
        dlg.deleteLater()


def _info_table_need_h(table):
    """表格「全部行完整显示」所需高度：表头 + 各行高 + 上下边框 + 2px 取整余量。

    与产品侧 _sync_info_table_min_h 同一口径——测试里独立复算一遍，
    免得只断言「等于 minimumHeight」变成自证。
    """
    header = table.horizontalHeader()
    head = header.height() if header is not None and not header.isHidden() else 0
    rows = sum(max(0, table.rowHeight(i)) for i in range(table.rowCount()))
    return head + rows + 2 * table.frameWidth() + 2


def _five_row_actor():
    """凑齐信息表五行（标签/年份/生日/出生地/外部ID）。"""
    return _make_actor(
        new_overview="简介" * 80,
        new_taglines=["日本女演员"],
        new_production_year=1966,
        new_premiere_date="1966-07-07",
        new_production_locations=["Osaka, Japan"],
        new_provider_ids={"维基百科": "x"},
    )


def test_detail_dialog_info_table_all_rows_visible_on_maximize_and_restore():
    """最大化/还原（及任意缩放）后信息表要完整显示全部行，让出的高度由简介承担。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_five_row_actor())
    try:
        dlg.show()
        _pump()
        table = dlg.info_table
        assert table.rowCount() == 5, "本用例按五行锁定"
        need = _info_table_need_h(table)
        assert table.minimumHeight() == need, "表格下限应等于完整显示五行所需高度"

        for size in ((1080, 720), (1600, 1000), (1920, 1200)):
            dlg.resize(*size)
            _pump()
            assert table.height() >= need, f"{size} 下表格高 {table.height()} < 完整显示所需 {need}"
            assert table.verticalScrollBar().maximum() == 0, f"{size} 下表格仍要滚动才看得全"

        dlg.showMaximized()
        _pump()
        assert table.height() >= need and table.verticalScrollBar().maximum() == 0, "最大化后仍要滚动"
        dlg.showNormal()
        _pump()
        assert table.height() >= need and table.verticalScrollBar().maximum() == 0, "还原后仍要滚动"

        # 让高的是简介：它得留在自己的最小高之上，且预览框取高不受牵连
        assert dlg.overview_edit.height() > dlg.overview_edit.minimumHeight(), "简介被挤到最小高以下"
        _, _, middle = _preview_pairs(dlg)[1]
        assert dlg.new_avatar_label.height() == middle.height() // 3, "表格下限不应把预览框挤变形"
    finally:
        dlg.deleteLater()


def test_detail_dialog_info_table_min_h_follows_row_count():
    """行数随「右键增删行」变化后，完整显示所需的下限要跟着重算（不等下次缩放才生效）。"""
    _ensure_app()
    from PyQt6.QtWidgets import QTableWidgetItem

    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_five_row_actor())
    try:
        dlg.show()
        dlg.resize(1080, 720)
        _pump()
        table = dlg.info_table
        before = table.minimumHeight()

        for _ in range(3):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(""))
            table.setItem(row, 1, QTableWidgetItem(""))
        dlg._sync_column_heights()
        _pump()
        assert table.rowCount() == 8
        assert table.minimumHeight() == _info_table_need_h(table) > before, "增行后下限应按新行数抬高"

        for _ in range(3):
            table.removeRow(0)
        dlg._sync_column_heights()
        _pump()
        assert table.minimumHeight() == _info_table_need_h(table) == before, "删回五行后下限应复原"
    finally:
        dlg.deleteLater()


def test_detail_dialog_preview_never_starves_other_controls():
    """预览框按「栏高一半」取高，但不得挤瘪同栏其余控件、也不得把窗口顶大形成死循环。

    反死循环的不变式：预览框写死高度会计进所在栏的最小高，若它 + 其余控件最小高之和
    超过栏高，栏会被顶大 → 栏高变 → 预览框目标高再变 → 窗口继续被顶大。故此处钉住
    「栏的 minimumSizeHint 不超过它实际拿到的高度」。
    """
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    dlg = ActorDetailDialog(_make_actor(new_overview="简介" * 200))
    try:
        dlg.show()
        for size in ((1080, 720), (1920, 1200), (1080, 720)):
            dlg.resize(*size)
            _pump()
            for name, label, box in _preview_pairs(dlg):
                assert box.minimumSizeHint().height() <= box.height() + 1, (
                    f"[{name}] 预览框把栏的最小高顶破了（min={box.minimumSizeHint().height()} "
                    f"实际={box.height()}），窗口会被无限顶大"
                )
                assert label.height() >= 1
        middle = dlg.layout().itemAt(1).widget()
        for w in (dlg.overview_edit, dlg.info_table, dlg.folder_edit, dlg.btn_fetch_image):
            assert w.height() >= w.minimumHeight(), f"[{w.text() or type(w).__name__}] 被挤到最小高以下"
            assert w.height() > 0
        assert middle.height() <= dlg.height(), "栏不应高过对话框"
    finally:
        dlg.deleteLater()
