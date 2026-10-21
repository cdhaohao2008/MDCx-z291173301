"""窗口居中：把顶层窗口放到屏幕「可用区域」的正中央（排除任务栏等系统区域）。

项目里先后长出过好几份几乎一样的 ``_center_on_screen``，拷贝粘贴之下逐渐分裂成
「有的按客户区居中、有的按窗口外框居中」，在 Windows 上差出半个标题栏的高度。
本模块把它收敛成唯一实现，下面的关键约束都来自真机 Windows 实测，不是推断：

1. **一律以 ``frameGeometry()`` 为准**，不是 ``geometry()``。后者只是客户区，
   比外框少一个标题栏（真机实测 30~33px），按它居中窗口会整体偏上半个标题栏。
2. **原生窗口尚未创建时 ``frameGeometry()`` 会退化成客户区**。此时若在 ``__init__``
   里直接居中，第一次就会偏半个标题栏；必须靠 ``allow_defer`` 延后一拍，等窗口真正
   创建后再定位。``CenterOnFirstShowMixin`` 在 ``showEvent`` 里调用，此时原生窗口已经
   存在，天然规避了这个坑。
3. **只居中一次**。用户手动挪过窗口之后重新打开，不该被拽回正中——否则每开关一次
   位置都被重置。这个语义由 :class:`CenterOnFirstShowMixin` 固化。
4. **最大化/全屏时不介入**，位置交给系统接管。
5. **窗口比可用区域还大时贴到左上角**，保证整个窗口都留在屏幕内，不会挪出可视区域。

不适用（故意不居中）的窗口：

- ``NfoPreviewWindow``：设计上要精确覆盖主窗口（``setGeometry(parent.geometry())``），
  跟着主窗口的最大化/最小化状态联动。
- ``_TipBubble`` 之类的气泡提示：锚定在触发它的行上，不是独立窗口。
- ``QMessageBox``：用户明确要求保持 Qt 默认的「居中于父窗口」，改了反而突兀。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QGuiApplication

# 目标窗口用 Any 注解：QDialog/QWidget/QMainWindow 都接受，避免调用方到处转型


def available_geometry(widget: Any) -> QRect | None:
    """取窗口所在屏幕的可用区域；取不到或无效时返回 None。"""
    try:
        screen = widget.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        avail = screen.availableGeometry()
    except RuntimeError, AttributeError:
        # 窗口已被 C++ 侧销毁，或根本不是 QWidget
        return None
    except Exception:
        return None
    return avail if avail.isValid() else None


def center_on_screen(widget: Any, avail: QRect | None = None, *, allow_defer: bool = True) -> bool:
    """把窗口整体（外框）移到 ``avail`` 的正中央，尺寸不变。

    Args:
        widget: 目标顶层窗口。
        avail: 目标区域。None 或无效时自动取窗口所在屏幕的可用区域。
        allow_defer: 原生窗口还没建好（``windowHandle() is None``）时，是否排队到
            事件循环下一拍再定位。真机 Windows 上首个事件循环内就能拿到稳定外框，
            但延后一拍更保险，且不会改变最终结果。

    Returns:
        True 表示本次调用已经完成定位；False 表示跳过（已最大化/全屏、取不到屏幕、
        或已排队延后定位）。
    """
    try:
        if widget is None:
            return False
        if widget.isMaximized() or widget.isFullScreen():
            return False  # 最大化/全屏时位置由系统接管
        if avail is None or not hasattr(avail, "isValid") or not avail.isValid():
            avail = available_geometry(widget)
            if avail is None:
                return False
        if allow_defer and widget.windowHandle() is None:
            # 原生窗口未创建，frameGeometry 此刻退化为客户区；延后一拍再定位。
            # avail 已在上面解析成具体区域，这里捕获的是解析后的值。
            QTimer.singleShot(0, lambda: center_on_screen(widget, avail, allow_defer=False))
            return False
        frame = widget.frameGeometry()
        x = avail.x() + (avail.width() - frame.width()) // 2
        y = avail.y() + (avail.height() - frame.height()) // 2
        # 比可用区域还大时贴左上角，保证整个窗口都留在屏幕里
        widget.move(max(x, avail.x()), max(y, avail.y()))
        return True
    except RuntimeError, AttributeError:
        return False
    except Exception:
        # 居中属于锦上添花，绝不能因为它把调用方的业务流程带崩
        return False


class CenterOnFirstShowMixin:
    """混入到 QDialog/QWidget：首次显示时把窗口居中到屏幕可用区域正中央。

    语义是「只首次居中」——用户手动挪过之后重新 show 不会被拽回正中，
    否则每开关一次窗口位置都被重置。同理，最大化/全屏、显示中的窗口不动。

    用法::

        class MyDialog(CenterOnFirstShowMixin, QDialog):
            ...
    """

    # 类属性兜底，避免混入方在 __init__ 之前就被 show 的极端情况
    _window_centered_once: bool = False

    def showEvent(self, event: Any) -> None:  # noqa: N802 - Qt 事件命名
        super().showEvent(event)  # type: ignore[misc]
        if self._window_centered_once:
            return
        self._window_centered_once = True
        center_on_screen(self)
