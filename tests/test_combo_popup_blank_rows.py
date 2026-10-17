"""下拉弹窗上下空白带回归（软件设置→刮削网站「指定网站」、网络→网站设置「当前网站」）。

用户截图：这两个站点下拉展开后，列表上方与下方各有一条与行高相当的空白控件，
点不中、选不了，看着像多出来的两项。

根因（`mdcx/controllers/main_window/init.py` 的 `_setup_combo_boxes`）：view 上写死了
`setMaximumHeight(322)`，而弹窗外框（`QComboBoxPrivateContainer`）的高度是
`maxVisibleItems × 行高` 算出来的、**与 view 的 maximumHeight 无关**。站点下拉行高约
40px 时 10 行要 400px，外框留够 400 而 view 被钉在 322，于是外框那套 QVBoxLayout 把
撑不满的 view 垂直居中，空出来的 78px 就成了上下两条空白带。

现修法是**不设上限**：外框多高 view 就多高，正好贴满，空白带消失（弹窗外框尺寸与改前
完全一致，那 322 从来只裁 view、不参与外框高度计算；变的只是同一块地方从
「8 行 + 上下空白」变成「10 行」）。

离屏平台下弹窗不渲染（既有已知局限，见 docs/Changelog.md），但**几何照常**，所以直接
量 view 在外框里的位置与高度。断言分两类、都不吃平台差异：
- 结构性：`maximumHeight` 未被写死（错位就是这么来的，且不依赖任何几何）；
- 几何性：无滚动条时外框高度恰为行数×行高，view 必须与外框严丝合缝（`y==0`、
  底也不留）；有滚动条时 view 必须至少够放下 `maxVisibleItems` 行，不被截半。

`_OLD_MAX_HEIGHT` 那条负向对照把改前那行装回去，空白带必须复现，否则以上断言恒真。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

from mdcx.controllers.main_window.init import _setup_combo_boxes

# 与生产全局 QSS（`style.py` 的 `QComboBox QAbstractItemView::item`）同口径的下拉项样式，
# 只把 min-height 抬到 32px：离屏字体度量下 24px 那档行高只有 32px、10 行 320px 塞得进
# 322 的旧上限，测不出错位；32px 档行高 40px、10 行 400px > 322，正中用户截图那一档。
_ITEM_QSS = """
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D8DEE9;
    selection-background-color: #4C6EFF;
    selection-color: white;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 32px;
    padding: 4px 8px;
    color: #111827;
}
"""

# 改前写死的上限，仅用于「负向对照」，证明本文件那些断言不是恒真
_OLD_MAX_HEIGHT = 322

# 可见行数（生产 `_setup_combo_boxes` 统一写死的 maxVisibleItems）
_VISIBLE_ITEMS = 10

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _open_popup(item_count, max_height=None):
    """按生产口径装好的下拉框并展开弹窗，返回 (host, combo, view, 弹窗外框)。

    host 必须一并返回：它是 combo 的父控件，调用方不持有引用时会被 Python 回收，
    连带 combo 的 C++ 对象一起析构，后续取几何就报「wrapped C/C++ object has been deleted」。
    """
    app = _ensure_app()
    host = QWidget()
    combo = QComboBox(host)
    combo.setStyleSheet(_ITEM_QSS)
    for i in range(item_count):
        combo.addItem(f"Site{i} 定位说明：有码+无码+素人+FC2", f"value{i}")
    host.resize(320, 40)
    host.show()
    app.processEvents()
    _setup_combo_boxes(host)
    if max_height is not None:  # 负向对照专用：把改前那行代码原样装回去
        combo.view().setMaximumHeight(max_height)
    combo.showPopup()
    app.processEvents()
    view = combo.view()
    assert view is not None
    return host, combo, view, view.window()


@pytest.fixture()
def open_popup():
    opened = []

    def _open(item_count, max_height=None):
        host, combo, view, popup = _open_popup(item_count, max_height)
        opened.append((host, combo))
        return combo, view, popup

    try:
        yield _open
    finally:
        for host, combo in opened:
            combo.hidePopup()
            host.deleteLater()
        _ensure_app().processEvents()


def _row_height(view, combo) -> int:
    model = combo.model()
    assert model is not None
    return view.visualRect(model.index(1, 0)).height()


def test_old_cap_actually_would_bind(open_popup):
    """前置条件：本档行高下改前那 322 确实装不下 10 行（否则测的是另一种情况）。"""
    combo, view, _ = open_popup(_VISIBLE_ITEMS + 5)
    assert _row_height(view, combo) * combo.maxVisibleItems() > _OLD_MAX_HEIGHT


def test_popup_view_not_capped_to_a_stale_height(open_popup):
    """结构性回归本体：view 不再被钉在某个写死的高度上限上。"""
    combo, view, popup = open_popup(_VISIBLE_ITEMS + 5)
    assert view.maximumHeight() >= popup.height(), (
        f"view 上限 {view.maximumHeight()} 小于弹窗外框 {popup.height()}，必然又被居中出上下空白带"
    )


def test_popup_without_scrollbar_view_fills_frame_exactly(open_popup):
    """无滚动条时外框高度 = 行数 × 行高，view 必须与外框严丝合缝：首尾都不留白。"""
    _, view, popup = open_popup(_VISIBLE_ITEMS - 5)  # 5 行 < 可见 10 行，不出滚动条
    assert view.geometry() == popup.rect(), f"view={view.geometry().getRect()} 未贴满外框={popup.rect().getRect()}"


def test_scrolled_popup_view_tall_enough_for_visible_rows(open_popup):
    """有滚动条时 view 必须至少够放下 10 行，不被截半（截半即被居中留白）。"""
    combo, view, _ = open_popup(_VISIBLE_ITEMS + 5)
    assert view.height() >= _row_height(view, combo) * combo.maxVisibleItems(), (
        f"view 高 {view.height()} 放不满 {combo.maxVisibleItems()} 行"
    )


def test_blank_band_reappears_when_old_cap_reintroduced(open_popup):
    """负向对照：把改前那 322 装回去，空白带必须原样复现。"""
    combo, view, popup = open_popup(_VISIBLE_ITEMS + 5, max_height=_OLD_MAX_HEIGHT)
    top_blank = view.geometry().y()
    bottom_blank = popup.height() - view.geometry().y() - view.height()
    assert top_blank > 0, "封顶后 view 未被居中，负向对照失效"
    assert bottom_blank > 0, "封顶后 view 未留出底部空白，负向对照失效"
