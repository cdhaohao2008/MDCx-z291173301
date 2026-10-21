"""全项目「窗口打开即居中于屏幕可用区正中央」的统一约定与回归测试。

需求：MDCx 主窗口、演员管理器、选择媒体库、数据清洗、数据源测试、应用管理器设置、
封面图片裁剪等窗口，打开时都落在**屏幕可用区域**（排除任务栏）的正中央。

为什么要有这个文件：项目里先后长出过六七份各自复制的 ``_center_on_screen``，
拷贝之下逐渐分裂（有的按客户区居中、有的按外框居中；有的只居中一次、有的每次都居中），
在 Windows 上差出半个标题栏的高度。这里把行为收敛到
:mod:`mdcx.utils.window_center` 一个实现，并用下面三类测试把它钉死：

1. 工具函数本身的边界（超屏贴左上角、最大化不介入、原生窗口没建好要延后、异常不外泄）
2. ``CenterOnFirstShowMixin`` 的「只首次居中」语义
3. 每个顶层窗口类逐个打开，验证真的落在正中央；再加一条「新增窗口必须自己居中」的
   清单守卫，避免以后再长出一个不居中的窗口。
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from mdcx.utils.window_center import (  # noqa: E402
    CenterOnFirstShowMixin,
    available_geometry,
    center_on_screen,
)

_app: QApplication | None = None

# offscreen 平台有两处已知偏差，都不是被测逻辑的问题：
#   1. 它给窗口加了 2px 的假边框；
#   2. frameGeometry() 比 move() 晚一个事件循环才更新。
# 真机 Windows 上实测偏差是 0，这里留 4px 容差既能盖住上面两点，
# 又远小于「真的没居中」的量级（那种情况是几百 px）。
_TOL = 4

# 故意不居中的顶层窗口，及不居中的理由（新增豁免必须写清理由）
_ALLOWED_NOT_CENTERED = {
    "NfoPreviewWindow": "设计上要精确覆盖主窗口，并跟随主窗口最大化/最小化",
}


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _pump(app: QApplication, times: int = 4) -> None:
    for _ in range(times):
        app.processEvents()


def _avail() -> QRect:
    return QGuiApplication.primaryScreen().availableGeometry()


def _assert_centered(widget: QWidget, msg: str) -> None:
    """逐轴校验：某轴超出可用区时贴到该轴起点，否则要求中心偏差在容差内。

    逐轴而非整体判断，是因为「窗口比屏幕宽但比屏幕矮」时，宽轴贴左、矮轴照常垂直居中，
    这正是 center_on_screen 里 max(x, avail.x()) / max(y, avail.y()) 的行为。
    """
    avail = _avail()
    frame = widget.frameGeometry()
    if frame.width() > avail.width():
        assert frame.x() == avail.x(), f"{msg}: 宽于可用区时未贴左边缘, frame={frame.getRect()} avail={avail.getRect()}"
    else:
        dx = frame.center().x() - avail.center().x()
        assert abs(dx) <= _TOL, f"{msg}: 水平未居中, 偏差 {dx}px, frame={frame.getRect()}"
    if frame.height() > avail.height():
        assert frame.y() == avail.y(), f"{msg}: 高于可用区时未贴上边缘, frame={frame.getRect()} avail={avail.getRect()}"
    else:
        dy = frame.center().y() - avail.center().y()
        assert abs(dy) <= _TOL, f"{msg}: 垂直未居中, 偏差 {dy}px, frame={frame.getRect()}"


# ==================================================================
# 1. 工具函数本身的边界
# ==================================================================


def test_center_on_screen_uses_frame_not_client():
    """以 frameGeometry（外框）为准：差一个标题栏高度，按客户区居中会偏上半个标题栏。"""
    app = _ensure_app()
    w = QWidget()
    w.resize(400, 300)
    w.show()
    _pump(app)
    try:
        assert center_on_screen(w) is True
        _pump(app)
        _assert_centered(w, "普通窗口")
    finally:
        w.close()
        w.deleteLater()


def test_center_on_screen_keeps_size():
    """居中只改位置，不动尺寸。"""
    app = _ensure_app()
    w = QWidget()
    w.resize(432, 321)
    w.show()
    _pump(app)
    try:
        center_on_screen(w)
        _pump(app)
        assert (w.width(), w.height()) == (432, 321)
    finally:
        w.close()
        w.deleteLater()


def test_center_on_screen_clamps_oversized_window_to_topleft():
    """窗口比可用区还大时贴左上角，保证整个窗口留在屏幕内。"""
    app = _ensure_app()
    avail = _avail()
    w = QWidget()
    w.resize(avail.width() + 400, avail.height() + 300)
    w.show()
    _pump(app)
    try:
        center_on_screen(w)
        _pump(app)
        assert w.frameGeometry().topLeft() == avail.topLeft()
    finally:
        w.close()
        w.deleteLater()


def test_center_on_screen_skips_maximized_and_fullscreen():
    """最大化/全屏时位置由系统接管，不能去抢。

    注意不能在断言前对窗口 move()：offscreen 平台上对已最大化窗口 move() 会把状态
    打回 Normal（真机 Windows 不会），那样测的就不是「最大化时被跳过」了。
    """
    app = _ensure_app()
    w = QWidget()
    w.resize(300, 200)
    w.show()
    _pump(app)
    try:
        w.showMaximized()
        _pump(app)
        assert w.isMaximized(), "offscreen 平台应能进入最大化态"
        before = w.frameGeometry()
        assert center_on_screen(w) is False, "最大化时不应介入"
        assert w.frameGeometry() == before, "最大化时不应改动位置"

        w.showFullScreen()
        _pump(app)
        assert w.isFullScreen(), "offscreen 平台应能进入全屏态"
        before = w.frameGeometry()
        assert center_on_screen(w) is False, "全屏时不应介入"
        assert w.frameGeometry() == before, "全屏时不应改动位置"
    finally:
        w.showNormal()
        w.close()
        w.deleteLater()


def test_center_on_screen_defers_until_native_window_exists():
    """windowHandle() 为 None 时不能直接定位，否则外框会退化成客户区。"""
    app = _ensure_app()
    w = QWidget()
    w.resize(300, 200)
    w.move(11, 13)
    try:
        # 未 show 的顶层窗口没有原生窗口，函数应排队而不是就地（错误地）定位
        assert w.windowHandle() is None
        assert center_on_screen(w) is False
        assert (w.x(), w.y()) == (11, 13), "不应在原生窗口建好前改动位置"
        # 延后的一拍在 show() 之后触发，此时原生窗口已存在，定位才会生效
        w.show()
        _pump(app)
        _assert_centered(w, "延后定位")
    finally:
        w.close()
        w.deleteLater()


def test_center_on_screen_accepts_explicit_avail():
    """显式传入可用区时按传入值定位，不看窗口实际所在屏幕。"""
    app = _ensure_app()
    avail = QRect(100, 200, 900, 700)
    w = QWidget()
    w.resize(300, 200)
    w.show()
    _pump(app)
    try:
        assert center_on_screen(w, avail) is True
        _pump(app)
        frame = w.frameGeometry()
        assert frame.x() == avail.x() + (avail.width() - frame.width()) // 2
        assert frame.y() == avail.y() + (avail.height() - frame.height()) // 2
    finally:
        w.close()
        w.deleteLater()


def test_available_geometry_rejects_non_widget():
    assert available_geometry(object()) is None


def test_center_on_screen_swallows_errors():
    """居中是锦上添花，绝不能把调用方的业务流程带崩。"""
    from PyQt6 import sip

    app = _ensure_app()
    assert center_on_screen(None) is False
    assert center_on_screen(object()) is False

    w = QWidget()
    w.show()
    _pump(app)
    w.close()
    # deleteLater 只排队，真正析构要靠 sip.delete（PyQt6 里没有独立 sip 包）
    sip.delete(w)
    _pump(app)
    # C++ 对象已销毁，再调一次只会被 RuntimeError 吞掉返回 False
    assert center_on_screen(w) is False


# ==================================================================
# 2. CenterOnFirstShowMixin 的「只首次居中」语义
# ==================================================================


class _DemoDialog(CenterOnFirstShowMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.resize(360, 240)


def test_mixin_centers_on_first_show():
    app = _ensure_app()
    dlg = _DemoDialog()
    try:
        dlg.show()
        _pump(app)
        _assert_centered(dlg, "混入式窗口首次打开")
    finally:
        dlg.close()
        dlg.deleteLater()


def test_mixin_does_not_recenter_after_user_move():
    """用户手动挪过之后重新打开，不该被拽回正中——否则每开关一次位置都被重置。"""
    app = _ensure_app()
    dlg = _DemoDialog()
    try:
        dlg.show()
        _pump(app)
        dlg.move(10, 10)
        _pump(app)
        dlg.hide()
        _pump(app)
        dlg.show()
        _pump(app)
        assert dlg.frameGeometry().x() == 10, "重新 show 时把用户挪的位置拽回了正中"
    finally:
        dlg.close()
        dlg.deleteLater()


def test_mixin_flag_is_per_instance():
    """_window_centered_once 是实例状态，不能串到别的窗口上。"""
    app = _ensure_app()
    a = _DemoDialog()
    b = _DemoDialog()
    try:
        a.show()
        _pump(app)
        assert a._window_centered_once is True
        assert b._window_centered_once is False, "一个窗口居中过不应影响另一个"
        b.show()
        _pump(app)
        _assert_centered(b, "第二个窗口首次打开")
    finally:
        for dlg in (a, b):
            dlg.close()
            dlg.deleteLater()


# ==================================================================
# 3. 逐个窗口验证真的居中
# ==================================================================


def _make_actor():
    from mdcx.tools.emby_actor_manager import ActorInfo

    return ActorInfo(name="测试演员", actor_id="id1", server_id="srv1")


def _lib_dialog():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    return LibrarySelectDialog([{"Name": "L1"}, {"Name": "L2"}])


def _clean_rules_dialog():
    from mdcx.tools.emby_actor_manager_ui import ActorCleanRulesDialog

    return ActorCleanRulesDialog([])


def _manager_dialog():
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    return EmbyActorManagerDialog()


def _settings_dialog():
    from mdcx.tools.emby_actor_manager_ui import EmbyActorSettingsDialog

    return EmbyActorSettingsDialog()


def _source_test_dialog():
    from mdcx.tools.emby_actor_manager_ui import ActorSourceTestDialog

    return ActorSourceTestDialog()


def _detail_dialog():
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    return ActorDetailDialog(_make_actor())


def _donate_dialog():
    from mdcx.views.donate_window import DonateDialog

    return DonateDialog()


def _similar_dialog():
    from mdcx.views.similar_window import SimilarDialog

    corpus = [{"Title": "A", "Year": "2020"}, {"Title": "B", "Year": "2021"}]
    return SimilarDialog(corpus, {"Title": "A", "Year": "2020"}, top_n=5)


def _site_list_dialog():
    from mdcx.controllers.main_window.site_priority_dialog import SiteListEditorDialog

    return SiteListEditorDialog("站点顺序", [], [])


def _field_priority_dialog():
    from mdcx.controllers.main_window.site_priority_dialog import FieldPriorityDialog

    return FieldPriorityDialog("字段优先级", "movie", [], {})


_WINDOW_FACTORIES = [
    ("LibrarySelectDialog", _lib_dialog),
    ("ActorCleanRulesDialog", _clean_rules_dialog),
    ("EmbyActorManagerDialog", _manager_dialog),
    ("EmbyActorSettingsDialog", _settings_dialog),
    ("ActorSourceTestDialog", _source_test_dialog),
    ("ActorDetailDialog", _detail_dialog),
    ("DonateDialog", _donate_dialog),
    ("SimilarDialog", _similar_dialog),
    ("SiteListEditorDialog", _site_list_dialog),
    ("FieldPriorityDialog", _field_priority_dialog),
]


@pytest.mark.parametrize(("name", "factory"), _WINDOW_FACTORIES, ids=[n for n, _ in _WINDOW_FACTORIES])
def test_dialog_opens_centered_in_available_area(name, factory):
    """每个弹窗首次打开都要落在屏幕可用区正中央（真机 Windows 实测偏差为 0）。"""
    app = _ensure_app()
    dlg = factory()
    try:
        dlg.show()
        _pump(app)
        _assert_centered(dlg, name)
    finally:
        try:
            dlg.close()
            dlg.deleteLater()
        except RuntimeError:
            pass
        _pump(app)


def test_named_windows_from_the_requirement_are_all_covered():
    """需求点名的窗口必须都在上面的清单里，新增窗口别忘了补测试。"""
    named = {
        "EmbyActorManagerDialog",  # 演员管理器
        "LibrarySelectDialog",  # 选择媒体库
        "ActorCleanRulesDialog",  # 数据清洗规则
        "ActorSourceTestDialog",  # 数据源测试
        "EmbyActorSettingsDialog",  # 应用管理器设置
        "ActorDetailDialog",  # 演员详情
    }
    covered = {n for n, _ in _WINDOW_FACTORIES}
    assert named <= covered, f"需求点名的窗口没被测试覆盖: {sorted(named - covered)}"


# ==================================================================
# 4. 清单守卫：以后新加的顶层窗口不能偷偷不居中
# ==================================================================

_MDCX_ROOT = pathlib.Path(__file__).resolve().parents[1] / "mdcx"
_QT_WINDOW_BASES = {"QDialog", "QMainWindow"}


def _top_level_window_classes() -> dict[str, str]:
    """静态扫出 mdcx 下所有直接继承 QDialog/QMainWindow 的顶层窗口类。

    返回 {类名: 相对文件路径}。只做语法分析，不 import，避免把整个项目拖进来。
    """
    found: dict[str, str] = {}
    for path in sorted(_MDCX_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name in _QT_WINDOW_BASES:
                    rel = str(path.relative_to(_MDCX_ROOT.parent)).replace("\\", "/")
                    found.setdefault(node.name, rel)
                    break
    return found


def _class_index() -> dict[str, str]:
    """扫出 mdcx 下所有类 -> 所在文件（解耦后窗口类由多个 mixin 拼装）。"""
    index: dict[str, str] = {}
    for path in sorted(_MDCX_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        rel = str(path.relative_to(_MDCX_ROOT.parent)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index.setdefault(node.name, rel)
    return index


def _class_source_files(class_name: str, index: dict[str, str]) -> list[str]:
    """收集该类本身与它全部 mixin 基类所在的源文件。"""
    files: set[str] = set()
    queue = [class_name]
    while queue:
        name = queue.pop()
        rel = index.get(name)
        if rel is None or rel in files:
            continue
        files.add(rel)
        try:
            tree = ast.parse((_MDCX_ROOT.parent / rel).read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                for base in node.bases:
                    base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    if base_name:
                        queue.append(base_name)
                break
    return sorted(files)


def test_every_top_level_window_can_center_itself():
    """每个顶层窗口要么自带 _center_on_screen，要么混入 CenterOnFirstShowMixin。

    豁免必须写进 _ALLOWED_NOT_CENTERED 并附上理由。
    """
    index = _class_index()
    missing: list[str] = []
    for class_name, rel in _top_level_window_classes().items():
        if class_name in _ALLOWED_NOT_CENTERED:
            continue
        # 窗口类已拆成多个 mixin，逐个 mixin 宿主文件一起判定
        source = "".join(
            (_MDCX_ROOT.parent / item).read_text(encoding="utf-8") for item in _class_source_files(class_name, index)
        )
        has_own = "_center_on_screen" in source
        has_mixin = "CenterOnFirstShowMixin" in source
        if not (has_own or has_mixin):
            missing.append(f"{class_name} ({rel})")
    assert not missing, (
        "以下顶层窗口打开时不会居中，也没有豁免理由，请混入 CenterOnFirstShowMixin "
        f"或实现 _center_on_screen(): {missing}"
    )


def test_allowed_not_centered_entries_still_exist():
    """豁免清单别留着早已不存在的类名，那会让守卫名存实亡。"""
    existing = set(_top_level_window_classes())
    stale = set(_ALLOWED_NOT_CENTERED) - existing
    assert not stale, f"豁免清单里的类已不存在: {sorted(stale)}"
    for class_name in _ALLOWED_NOT_CENTERED:
        assert _ALLOWED_NOT_CENTERED[class_name].strip(), f"{class_name} 的豁免必须写明理由"
