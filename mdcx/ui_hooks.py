"""Qt 无关的界面回调登记表：底层模块只管调，真正的控件动作交给界面层绑定。

背景
----
`mdcx/base/file.py` 这类基础设施模块需要"把按钮切成忙/闲""在路径标签上打一行字"
这类界面动作，但它们不该为了这点需求把 PyQt6 拖进来。这里用与
`mdcx/log_console.py` 完全相同的做法解决：

- 本模块 = **Qt 无关侧**，只有四个纯函数式的界面回调槽位，默认全是空实现。
- `mdcx/signals.py` = **Qt 侧**，`Signals` 构造时把自己的 pyqtSignal `emit`
  注册进来，于是 `ui_hooks.change_buttons_status()` 与
  `signal.change_buttons_status.emit()` 触发的是同一批槽位。

未绑定（无界面、单测、命令行）时全部静默丢弃，行为与"信号没有连接"完全一致。
"""

from __future__ import annotations

from collections.abc import Callable

from .utils import singleton


def _do_nothing(*_args, **_kwargs) -> None:
    """默认回调：没有界面时静默丢弃。"""


@singleton
class UiHooks:
    """底层模块可安全调用的界面回调集合（不依赖 Qt）。"""

    def __init__(self) -> None:
        self._change_buttons_status: Callable[[], None] = _do_nothing
        self._reset_buttons_status: Callable[[], None] = _do_nothing
        self._set_label_file_path: Callable[[str], None] = _do_nothing
        self._view_success_file_settext: Callable[[str], None] = _do_nothing

    # region 绑定（只有 Qt 侧调用）
    def bind(
        self,
        *,
        change_buttons_status: Callable[[], None],
        reset_buttons_status: Callable[[], None],
        set_label_file_path: Callable[[str], None],
        view_success_file_settext: Callable[[str], None],
    ) -> None:
        """界面层在启动时登记真实实现，之后 `signal.*.emit` 与 `ui_hooks.*` 等价。"""
        self._change_buttons_status = change_buttons_status
        self._reset_buttons_status = reset_buttons_status
        self._set_label_file_path = set_label_file_path
        self._view_success_file_settext = view_success_file_settext

    # endregion

    # region 调用（底层模块用这些）
    def change_buttons_status(self) -> None:
        self._change_buttons_status()

    def reset_buttons_status(self) -> None:
        self._reset_buttons_status()

    def set_label_file_path(self, text: str) -> None:
        self._set_label_file_path(text)

    def view_success_file_settext(self, text: str) -> None:
        self._view_success_file_settext(text)

    # endregion


ui_hooks = UiHooks()
