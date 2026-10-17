"""封面图片裁剪窗（CutWindow）最大化/最小化 + Esc 关闭回归测试。

背景（用户诉求）：裁剪窗原先是死板的 1000x600 固定窗口，标题栏只有「关闭」，
想放大看细节只能拖边角，且拖小之后右侧面板与底栏直接被裁掉。诉求三条：

1. 标题栏补上**最小化 + 最大化**按钮（.ui 是纯绝对几何、没有布局管理器，
   窗口变大后控件不会自己跟位，必须由 `_relayout()` 按当前尺寸重排）；
2. **最大化时窗口组件与图片同步放大**：右侧面板固定宽贴右缘、底栏两个滑块等分
   富余并加长、图片按新显示区重新等比缩放，且**用户已选好的裁剪框跟着图片一起
   放大**（指向原图同一块区域，不许因为放大而漂移）；
3. **Esc 关闭**裁剪窗。

同时锁死「设计尺寸 1000x600 下与 .ui 逐像素一致」——本文件所有重排逻辑都以
.ui 的原始坐标为基准，任何改动不得让普通态窗口发生位移。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget

_app: QApplication | None = None

# posterCutTool.ui 的设计尺寸：左图区 800 + 右侧面板 200，底栏 60 高
DESIGN_W, DESIGN_H = 1000, 600
DESIGN_SIDE_X, DESIGN_SIDE_W = 800, 200
DESIGN_IMG_W, DESIGN_IMG_H = 800, 540
DESIGN_BAR_Y, DESIGN_BAR_H = 540, 60


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


class _StubMain(QWidget):
    """裁剪窗只用到这几个属性，给个最小替身，避免为测试拉起整个主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.dark_mode = False
        self.options = QFileDialog.Option.DontUseNativeDialog  # 仅 open_image 用得上
        self.img_path = None
        self.emitted: list[tuple[str, object]] = []
        self.change_to_mainpage = SimpleNamespace(emit=lambda *a: self.emitted.append(("main", a)))
        self.request_preview_images = SimpleNamespace(emit=lambda *a: self.emitted.append(("prev", a)))
        self.nfo_lib_images_changed = SimpleNamespace(emit=lambda *a: self.emitted.append(("nfo", a)))

    def show_log_text(self, _text: str) -> None:
        pass


@pytest.fixture()
def cut(app, tmp_path):
    """打开一个 1000x600 的裁剪窗（未加载图片）。"""
    from mdcx.controllers.cut_window import CutWindow

    parent = _StubMain()
    window = CutWindow(parent)
    window.resize(DESIGN_W, DESIGN_H)
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    parent.deleteLater()
    app.processEvents()


@pytest.fixture()
def cut_with_poster(app, tmp_path):
    """打开裁剪窗并载入一张 1000x1500 的竖版封面（2:3，典型海报）。"""
    from mdcx.controllers.cut_window import CutWindow

    poster = tmp_path / "ABC-001-poster.jpg"
    Image.new("RGB", (1000, 1500), (40, 80, 120)).save(poster, quality=95)

    parent = _StubMain()
    window = CutWindow(parent)
    window.resize(DESIGN_W, DESIGN_H)
    window.showimage(poster, SimpleNamespace(number="ABC-001", has_sub=False, mosaic="", definition=""))
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    parent.deleteLater()
    app.processEvents()


@pytest.fixture()
def cut_with_landscape(app, tmp_path):
    """打开裁剪窗并载入一张 1500x1000 的横版图片（3:2）。"""
    from mdcx.controllers.cut_window import CutWindow

    poster = tmp_path / "ABC-002-poster.jpg"
    Image.new("RGB", (1500, 1000), (40, 80, 120)).save(poster, quality=95)

    parent = _StubMain()
    window = CutWindow(parent)
    window.resize(DESIGN_W, DESIGN_H)
    window.showimage(poster, SimpleNamespace(number="ABC-002", has_sub=False, mosaic="", definition=""))
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    parent.deleteLater()
    app.processEvents()


def _centering_error(win):
    """居中偏差（像素）：图片两侧留白之差。整数除法最多差半像素，允许 1px。"""
    area = win.Ui.widget_cutimage
    img = win.Ui.label_backgroud_pic
    return max(
        abs(img.x() * 2 - (area.width() - img.width())),
        abs(img.y() * 2 - (area.height() - img.height())),
    )


# ============================== 1. 窗口按钮 ==============================


def test_cut_window_has_minimize_maximize_buttons(cut):
    """标题栏必须有最小化 + 最大化按钮（关闭按钮 QDialog 自带），且不是无边框窗。"""
    flags = cut.windowFlags()
    assert flags & Qt.WindowType.WindowMinimizeButtonHint, "缺少最小化按钮"
    assert flags & Qt.WindowType.WindowMaximizeButtonHint, "缺少最大化按钮"
    assert not flags & Qt.WindowType.FramelessWindowHint, "应保留系统标题栏"


def test_cut_window_minimize_button_minimizes(cut, app):
    """最小化按钮真的能把窗口收起来（原生语义，不是只加了个图标）。"""
    cut.show()
    app.processEvents()
    cut.showMinimized()
    app.processEvents()
    assert cut.isMinimized(), "最小化没有生效"
    cut.showNormal()
    app.processEvents()
    assert not cut.isMinimized(), "最小化后还原不回来"


def test_minimize_from_maximized_drops_maximized_bit(cut, app):
    """最大化状态下最小化：Qt 只会 OR 上 Minimized 位，必须由我们摘掉残留的 Maximized 位。

    否则窗口停在 Minimized|Maximized 这种自相矛盾的状态，Windows 还原不了，
    表现就是"最小化按钮点了没反应"。
    """
    cut.show()
    app.processEvents()
    cut.showMaximized()
    app.processEvents()

    cut.showMinimized()  # 走 Qt 的最小化路径
    app.processEvents()

    assert cut.isMinimized(), "没有进入最小化"
    assert not cut.windowState() & Qt.WindowState.WindowMaximized, "最小化后仍带最大化位，窗口状态自相矛盾"


def test_minimize_from_maximized_restores_normal_size(cut, app):
    """最大化后最小化、再还原，应该回到最大化前的常规尺寸，而不是卡在屏幕大小。"""
    cut.resize(DESIGN_W, DESIGN_H)
    cut.show()
    app.processEvents()
    assert (cut.width(), cut.height()) == (DESIGN_W, DESIGN_H)

    cut.showMaximized()
    app.processEvents()
    assert (cut.width(), cut.height()) != (DESIGN_W, DESIGN_H), "本用例需要窗口确实被放大了"

    cut.showMinimized()
    app.processEvents()
    cut.showNormal()
    app.processEvents()

    assert not cut.isMinimized(), "最小化后还原不回来"
    assert (cut.width(), cut.height()) == (DESIGN_W, DESIGN_H), "还原后没有回到常规尺寸"


def test_window_does_not_reopen_maximized(cut, app):
    """裁剪窗是常驻对象：关闭再打开必须回到常规状态，不能把上次的最大化带进来。

    main_window 启动时只创建一次 CutWindow，之后只反复 show()，
    不清状态的话用户最大化过一次，之后每次打开都是最大化。
    """
    cut.show()
    app.processEvents()
    cut.showMaximized()
    app.processEvents()
    assert cut.isMaximized()

    cut.close()
    app.processEvents()
    cut.show()
    app.processEvents()

    assert not cut.isMaximized(), "重新打开时仍是最大化状态"
    assert not cut.isMinimized(), "重新打开时是最小化状态"
    assert (cut.width(), cut.height()) == (DESIGN_W, DESIGN_H)


def test_reopen_after_minimize_comes_back(cut, app):
    """被最小化后再次打开裁剪窗要能真正回到台面。

    最小化的窗口在 Qt 眼里仍是「可见」的，show() 会直接跳过，必须走 present()。
    """
    cut.show()
    app.processEvents()
    cut.showMinimized()
    app.processEvents()
    assert cut.isMinimized()

    cut.present()
    app.processEvents()

    assert not cut.isMinimized(), "再次打开时窗口还缩在任务栏里"


# ====================== 1.4 打开时居中、尺寸不变 ======================


def _pump(app: QApplication, times: int = 3) -> None:
    """多转几圈事件循环。

    居中是 showEvent 里排了个 singleShot，之后的 move 还要再过一圈才反映到
    frameGeometry 上（offscreen 平台尤其明显，真机 Windows 一次就到位）。
    """
    for _ in range(times):
        app.processEvents()


def _screen_center() -> QPoint:
    screen = QApplication.primaryScreen()
    assert screen is not None, "取不到主屏幕"
    return screen.availableGeometry().center()


# offscreen 平台给的是假的 2px 边框，且 frameGeometry 的落点比真机滞后一整轮事件循环，
# 没法在同步断言里做到逐像素相等；真机 Windows 实测偏差为 (0, 0)、四边留白完全对称。
# 这里只留几个像素的容差，仍足以拦住"根本没居中"（那种会差上百像素）。
_CENTER_TOL = 4


def _center_error(cut) -> int:
    delta = cut.frameGeometry().center() - _screen_center()
    return abs(delta.x()) + abs(delta.y())


def test_cut_window_opens_centered(cut, app):
    """打开时整扇窗居中于屏幕可用区域正中。"""
    cut.present()
    _pump(app)
    assert _center_error(cut) <= _CENTER_TOL, (
        f"窗口没有居中：frame 中心 {cut.frameGeometry().center()} != 屏幕中心 {_screen_center()}"
    )


def test_centering_keeps_window_size(cut, app):
    """居中只挪位置，不许顺带改尺寸。"""
    cut.resize(1000, 600)
    cut.present()
    _pump(app)
    assert (cut.width(), cut.height()) == (1000, 600)


def test_reopen_recenters_without_resizing(cut, app):
    """手动挪走后再打开：位置回到正中，尺寸仍保持用户自己调的那个。"""
    cut.resize(900, 560)
    cut.present()
    _pump(app)
    cut.move(10, 10)
    _pump(app)

    cut.close()
    _pump(app)
    cut.present()
    _pump(app)

    assert _center_error(cut) <= _CENTER_TOL, "重新打开没有回到屏幕正中"
    assert (cut.width(), cut.height()) == (900, 560), "居中把用户调过的尺寸改回去了"


def test_centering_skipped_when_maximized(cut, app):
    """最大化时位置归系统管，不能再去 move。"""
    cut.present()
    _pump(app)
    cut.showMaximized()
    _pump(app)
    before = cut.frameGeometry().center()

    cut._center_on_screen()
    _pump(app)
    assert cut.frameGeometry().center() == before, "最大化状态下不该再自行移动窗口"


# ====================== 1.5 与主窗口相互独立 ======================


def test_cut_window_has_no_qt_parent(cut):
    """裁剪窗必须是独立顶层窗口，不能挂在主窗口底下。"""
    assert cut.parent() is None, "裁剪窗仍以主窗口为 QObject 父级，会被连带收起"
    assert cut.isWindow(), "裁剪窗不是顶层窗口"
    assert int(cut.windowFlags()) & 0xF == int(Qt.WindowType.Window), (
        "窗口类型应为 Window(1)，Dialog(3) 会成为主窗口的附属窗"
    )
    assert not cut.isModal(), "裁剪窗不应是模态窗口，会阻塞主窗口"


def test_cut_window_is_not_tool_window(cut):
    """工具窗在任务栏/Alt+Tab 里不独立，容易被主窗口的状态影响。"""
    flags = int(cut.windowFlags())
    assert flags & int(Qt.WindowType.Tool) != int(Qt.WindowType.Tool), "仍是工具窗"


def test_cut_window_does_not_quit_app_on_close(cut):
    """关掉裁剪窗不得退出整个应用（独立窗口后它就是最后一扇可见窗口）。"""
    assert not cut.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose), (
        "WA_QuitOnClose 仍为 True，关掉裁剪窗会直接退出应用"
    )


def test_main_window_minimize_keeps_cut_window(cut, app):
    """主窗口最小化时，裁剪窗不能被连带收走。"""
    cut.present()
    app.processEvents()
    assert cut.isVisible()

    cut.main_window.showMinimized()
    app.processEvents()
    try:
        assert cut.isVisible(), "主窗口最小化把裁剪窗一起收走了"
        assert not cut.isMinimized(), "裁剪窗被连带最小化"
    finally:
        cut.main_window.showNormal()
        app.processEvents()


def test_main_window_hide_keeps_cut_window(cut, app):
    """主窗口收进托盘（hide）时，裁剪窗不能跟着消失。"""
    cut.present()
    app.processEvents()

    cut.main_window.hide()
    app.processEvents()
    try:
        assert cut.isVisible(), "主窗口隐藏把裁剪窗一起收走了"
    finally:
        cut.main_window.show()
        app.processEvents()


def test_cut_window_minimize_keeps_main_window(cut, app):
    """反方向：裁剪窗最小化/最大化都不应改变主窗口的状态与可见性。"""
    cut.main_window.show()
    app.processEvents()
    before = cut.main_window.windowState()

    cut.present()
    app.processEvents()
    cut.showMinimized()
    app.processEvents()
    cut.showMaximized()
    app.processEvents()
    cut.showNormal()
    app.processEvents()

    assert cut.main_window.windowState() == before, "裁剪窗改动了主窗口的窗口状态"
    assert cut.main_window.isVisible(), "裁剪窗把主窗口弄没了"


# ============================== 2. Esc 关闭 ==============================


def test_cut_window_esc_closes(cut, app):
    """Esc 关闭裁剪窗。"""
    cut.show()
    app.processEvents()
    assert cut.isVisible()
    QTest.keyClick(cut, Qt.Key.Key_Escape)
    app.processEvents()
    assert not cut.isVisible(), "Esc 没有关闭裁剪窗"


def test_cut_window_esc_closes_with_focus_on_child(cut, app):
    """焦点落在子控件上时 Esc 也要能关（按键事件冒泡到窗口）。"""
    cut.show()
    app.processEvents()
    cut.Ui.radioButton_add_censored.setFocus()  # 焦点在水印单选钮上
    app.processEvents()
    assert cut.Ui.radioButton_add_censored.hasFocus()
    QTest.keyClick(cut.Ui.radioButton_add_censored, Qt.Key.Key_Escape)
    app.processEvents()
    assert not cut.isVisible(), "焦点在子控件上时 Esc 没有关闭裁剪窗"


# ============================== 3. 设计尺寸逐像素不变 ==============================


def test_design_size_keeps_ui_geometry(cut):
    """1000x600 下三个区域与 .ui 设计坐标逐像素一致（重排不得让普通态窗口位移）。"""
    assert cut.Ui.widget.geometry().getRect() == (DESIGN_SIDE_X, 0, DESIGN_SIDE_W, DESIGN_H)
    assert cut.Ui.widget_cutimage.geometry().getRect() == (0, 0, DESIGN_IMG_W, DESIGN_IMG_H)
    assert cut.Ui.widget_2.geometry().getRect() == (0, DESIGN_BAR_Y, DESIGN_IMG_W, DESIGN_BAR_H)
    # 右侧面板三个动作按钮贴底，坐标照搬 .ui
    assert cut.Ui.pushButton_close.geometry().getRect() == (30, 550, 141, 40)
    assert cut.Ui.pushButton_cut.geometry().getRect() == (30, 500, 141, 40)
    assert cut.Ui.pushButton_cut_close.geometry().getRect() == (30, 440, 141, 50)
    # 底栏两个滑块保持设计长度
    assert cut.Ui.horizontalSlider_left.geometry().getRect() == (50, 31, 311, 20)
    assert cut.Ui.horizontalSlider_right.geometry().getRect() == (480, 30, 311, 21)


def test_relayout_is_idempotent(cut, app):
    """重复重排不能自己漂移。"""
    before = cut.Ui.widget_2.geometry().getRect(), cut.Ui.horizontalSlider_left.geometry().getRect()
    cut._relayout()
    cut._relayout(force=True)
    app.processEvents()
    assert (cut.Ui.widget_2.geometry().getRect(), cut.Ui.horizontalSlider_left.geometry().getRect()) == before


# ============================== 4. 放大时同步放大 ==============================


def test_maximize_scales_image_and_widgets(cut_with_poster, app):
    """最大化（等效放大窗口）时：图片放大、控件铺满、右侧面板仍贴右缘。"""
    win = cut_with_poster
    old_pic = (win.pic_new_w, win.pic_new_h)
    old_slider = win.Ui.horizontalSlider_left.width()
    old_side_x = win.Ui.widget.x()

    win.resize(1920, 1080)  # 与 showMaximized 走同一条 resizeEvent → _relayout 路径
    app.processEvents()

    # 图片按新显示区等比放大（1000x1500 竖图撑满高度，宽随高度走）
    assert win.pic_new_h > old_pic[1], "图片没有随窗口放大"
    assert win.pic_new_w > old_pic[0], "图片宽度没有随窗口放大"
    assert win.Ui.label_backgroud_pic.height() == win.pic_new_h, "图片标签未跟上缩放尺寸"
    assert not win.Ui.label_backgroud_pic.pixmap().isNull(), "放大后图片丢了"
    assert abs(win.pic_new_w / win.pic_new_h - 1000 / 1500) < 0.01, "放大后图片比例被破坏"

    # 左侧图片区吃掉全部富余，右侧面板固定宽且仍贴右缘
    assert win.Ui.widget.width() == DESIGN_SIDE_W, "右侧面板宽度不该变"
    assert win.Ui.widget.x() + win.Ui.widget.width() == 1920, "右侧面板没有贴住右缘"
    assert win.Ui.widget.x() > old_side_x, "右侧面板没有右移"
    assert win.Ui.widget_cutimage.height() == 1080 - DESIGN_BAR_H, "图片区没有铺满剩余高度"
    assert win.Ui.widget_2.height() == DESIGN_BAR_H, "底栏高度不该变"
    assert win.Ui.widget_2.width() == 1920 - DESIGN_SIDE_W, "底栏宽度没有跟上"

    # 底栏两个滑块等分加长，右组同步右移但右缘保持设计边距
    slider_w = win.Ui.horizontalSlider_left.width()
    assert slider_w > old_slider, "滑块没有随窗口加长"
    assert win.Ui.horizontalSlider_right.width() == slider_w, "两个滑块应等长"
    right_geo = win.Ui.horizontalSlider_right.geometry()
    assert 1920 - DESIGN_SIDE_W - (right_geo.x() + right_geo.width()) == 9, "右组没有保持设计的右边距"
    assert win.Ui.label_6.x() == right_geo.x() - 40, "右组标签没有跟着滑块走"

    # 右侧面板动作按钮始终贴底
    assert win.Ui.pushButton_close.geometry().getRect() == (30, 1080 - 10 - 40, 141, 40)
    assert win.Ui.pushButton_cut_close.y() + 50 == 1080 - 10 - 40 - 10 - 40 - 10, "动作按钮没有贴底对齐"


def test_crop_rect_scales_with_image(cut_with_poster, app):
    """用户已选好的裁剪框跟着图片一起放大（按相对位置还原，不是原地不动或重置）。"""
    win = cut_with_poster
    before = win.pushButton_select_cutrange.geometry().getRect()
    old_w, old_h = win.pic_new_w, win.pic_new_h

    win.resize(1600, 1200)
    app.processEvents()

    after = win.pushButton_select_cutrange.geometry().getRect()
    assert after[2] > before[2] and after[3] > before[3], "裁剪框没有跟着图片放大"
    # 相对位置与相对大小都不变
    assert abs(after[0] / win.pic_new_w - before[0] / old_w) < 0.01
    assert abs(after[2] / win.pic_new_w - before[2] / old_w) < 0.01
    assert abs(after[3] / win.pic_new_h - before[3] / old_h) < 0.01
    # 仍被限制在图片显示区内
    assert after[0] >= 0 and after[1] >= 0
    assert after[0] + after[2] <= win.pic_new_w and after[1] + after[3] <= win.pic_new_h


def test_crop_region_in_source_image_survives_resize(cut_with_poster, app):
    """放大/还原不改变裁剪范围在**原图**中的位置（放大只为看得更清楚，不能改选区）。"""
    win = cut_with_poster
    # 先把裁剪框挪到中间并缩窄，确保不是「整图选中」这种退化用例
    win._apply_crop_rect(
        win.pushButton_select_cutrange.geometry().__class__(120, 200, 150, 225),
        sync_sliders=True,
    )
    win.getRealPos()
    before = win.getRealPos()

    win.resize(1920, 1080)
    app.processEvents()
    assert _close_rect(win.getRealPos(), before), "最大化后原图裁剪区域漂移了"

    win.resize(DESIGN_W, DESIGN_H)
    app.processEvents()
    assert _close_rect(win.getRealPos(), before), "还原后原图裁剪区域漂移了"


def _close_rect(got, want, tol: int = 3) -> bool:
    return len(got) == len(want) and all(abs(a - b) <= tol for a, b in zip(got, want, strict=True))


def test_sliders_stay_in_sync_after_resize(cut_with_poster, app):
    """放大后两个滑块仍正确反映当前裁剪框尺寸。"""
    win = cut_with_poster
    win.resize(1920, 1080)
    app.processEvents()
    px, py, pw, ph = win.pushButton_select_cutrange.geometry().getRect()
    assert win.Ui.horizontalSlider_left.value() == win._size_to_slider(ph, win.pic_new_h)
    assert win.Ui.horizontalSlider_right.value() == win._size_to_slider(pw, win.pic_new_w)


def test_restore_roundtrip_is_stable(cut_with_poster, app):
    """放大 → 还原后与全新打开完全一致（不残留放大态的几何或裁剪框）。"""
    win = cut_with_poster
    win.resize(1920, 1080)
    app.processEvents()
    win.resize(DESIGN_W, DESIGN_H)
    app.processEvents()
    snap = (
        win.Ui.widget.geometry().getRect(),
        win.Ui.widget_cutimage.geometry().getRect(),
        win.Ui.widget_2.geometry().getRect(),
        win.Ui.horizontalSlider_left.geometry().getRect(),
        win.Ui.horizontalSlider_right.geometry().getRect(),
        win.pushButton_select_cutrange.geometry().getRect(),
    )
    win._relayout(force=True)
    app.processEvents()
    assert (
        win.Ui.widget.geometry().getRect(),
        win.Ui.widget_cutimage.geometry().getRect(),
        win.Ui.widget_2.geometry().getRect(),
        win.Ui.horizontalSlider_left.geometry().getRect(),
        win.Ui.horizontalSlider_right.geometry().getRect(),
        win.pushButton_select_cutrange.geometry().getRect(),
    ) == snap


def test_crop_output_unchanged_by_resize(cut_with_poster, app, tmp_path):
    """放大状态下点「裁剪」，落盘结果必须与普通尺寸下一致（放大只是看得更清楚）。"""
    from mdcx.utils import executor

    win = cut_with_poster
    win._apply_crop_rect(win.pushButton_select_cutrange.geometry().__class__(120, 200, 150, 225))
    win.getRealPos()
    want = win.getRealPos()

    win.resize(1920, 1080)
    app.processEvents()
    assert executor.run(win.to_cut([])) is True, "放大状态下裁剪失败"
    poster = win.cut_poster_path
    assert poster.exists(), "没有产出 poster"
    with Image.open(poster) as img:
        # 缩放取整带来的 ±1px 容差
        assert abs(img.size[0] - (want[2] - want[0])) <= 1, f"裁剪宽 {img.size[0]} 与选区 {want} 不符"
        assert abs(img.size[1] - (want[3] - want[1])) <= 1, f"裁剪高 {img.size[1]} 与选区 {want} 不符"


# ============================== 5. 最小尺寸不塌 ==============================


def test_minimum_size_keeps_widgets_usable(cut, app):
    """窗口缩到最小也不能塌：滑块不重叠、动作按钮不压到水印选项上。"""
    win = cut
    win.resize(win.minimumWidth(), win.minimumHeight())
    app.processEvents()
    bar = win.Ui.widget_2
    left = win.Ui.horizontalSlider_left.geometry()
    right = win.Ui.horizontalSlider_right.geometry()
    assert left.right() < right.left(), "两个滑块重叠了"
    assert right.right() <= bar.width(), "右组滑块超出底栏被裁掉"
    assert win.Ui.label_6.x() + win.Ui.label_6.width() <= bar.width(), "右组标签超出底栏被裁掉"
    # 水印选项组底部不能被动作按钮压住
    assert win.Ui.gridLayoutWidget.y() + win.Ui.gridLayoutWidget.height() <= win.Ui.pushButton_cut_close.y()


def test_image_fits_after_maximize(cut_with_poster, app):
    """最大化后重新打开别的图，也按当前（放大后的）窗口尺寸显示，不会退回 800x540。"""
    win = cut_with_poster
    win.resize(1920, 1080)
    app.processEvents()
    win.showimage(win.show_image_path, SimpleNamespace(number="ABC-001", has_sub=False, mosaic="", definition=""))
    app.processEvents()
    assert win.pic_new_h == win.Ui.widget_cutimage.height(), "重新打开图片时没有按放大后的显示区铺满"
    assert win.pic_new_h > 900
    assert Path(win.show_image_path).exists(), "原图路径丢了"


def test_no_image_keeps_crop_box_draggable(cut, app):
    """没打开图片时（灰底）裁剪框依然受显示区约束，不会停在旧尺寸上。"""
    win = cut
    win.resize(1400, 900)
    win.show()  # 隐藏态被改的尺寸 Qt 不发 resize，靠 showEvent 补重排
    app.processEvents()
    assert (win.pic_new_w, win.pic_new_h) == (1400 - DESIGN_SIDE_W, 900 - DESIGN_BAR_H)
    px, py, pw, ph = win.pushButton_select_cutrange.geometry().getRect()
    assert 0 <= px and 0 <= py and px + pw <= win.pic_new_w and py + ph <= win.pic_new_h


# ============================== 4. 横图居中显示 ==============================


def test_landscape_image_centered_vertically_when_horizontally_full(cut_with_landscape, app):
    """显示区比图片"更方"（1200x840 → 显示区 1000x780，1.28 < 1.5）时横图水平撑满，上下留白应均分。"""
    win = cut_with_landscape
    win.resize(1200, 840)
    win.show()
    app.processEvents()

    area = win.Ui.widget_cutimage
    img = win.Ui.label_backgroud_pic
    assert img.width() == area.width(), "本用例需要横图水平撑满"
    assert img.height() < area.height(), "本用例需要上下确实留白"
    assert _centering_error(win) <= 1, "上下留白没有均分（垂直未居中）"


def test_landscape_image_centered_horizontally_when_vertically_full(cut_with_landscape, app):
    """窗口压扁（1400x520 → 显示区 1200x460，2.61 > 1.5）时横图垂直撑满，左右留白应均分。"""
    win = cut_with_landscape
    win.resize(1400, 520)
    win.show()
    app.processEvents()

    area = win.Ui.widget_cutimage
    img = win.Ui.label_backgroud_pic
    assert img.height() == area.height(), "本用例需要横图垂直撑满"
    assert img.width() < area.width(), "本用例需要左右确实留白"
    assert _centering_error(win) <= 1, "左右留白没有均分（水平未居中）"


def test_landscape_image_centered_after_maximize(cut_with_landscape, app):
    """最大化后重排，横图依旧居中，且宽高比不变。"""
    win = cut_with_landscape
    win.resize(DESIGN_W, DESIGN_H)
    win.show()
    app.processEvents()
    before_ratio = win.pic_new_w / win.pic_new_h

    win.showMaximized()
    app.processEvents()

    assert _centering_error(win) <= 1, "最大化后横图没有居中"
    # 居中只是挪位置，等比缩放的宽高比必须保持
    assert abs(win.pic_new_w / win.pic_new_h - before_ratio) < 0.01
    assert abs(win.pic_new_w / win.pic_new_h - 1500 / 1000) < 0.01, "原始宽高比被破坏"


def test_portrait_image_stays_top_left_aligned(cut_with_poster, app):
    """竖图维持原来的左上角对齐（本次只调整横图）。"""
    win = cut_with_poster
    win.resize(1600, 900)
    win.show()
    app.processEvents()

    img = win.Ui.label_backgroud_pic
    assert img.width() < win.Ui.widget_cutimage.width(), "本用例需要右侧确实留白"
    assert (img.x(), img.y()) == (0, 0), "竖图不应被居中"


def test_centering_does_not_break_cropping(cut_with_landscape, app):
    """居中只改显示位置：选中区域与裁剪坐标仍以图片为基准，to_cut 结果不受影响。"""
    win = cut_with_landscape
    win.resize(1400, 520)  # 横图水平撑满 + 上下居中
    win.show()
    app.processEvents()

    rect = QRect(int(win.pic_new_w * 0.3), int(win.pic_new_h * 0.2), 300, 150)
    win._apply_crop_rect(rect, sync_sliders=True)
    before = win.getRealPos()
    assert win.pushButton_select_cutrange.geometry() == rect

    win.resize(DESIGN_W, DESIGN_H)
    win.show()
    app.processEvents()
    # 图片缩放 + 居中偏移都不应改变"选中的原图区域"
    assert _close_rect(win.getRealPos(), before), "居中后选中的原图区域漂移了"
