"""手动停止（Stop）判定的唯一实现。

各业务模块此前各自复制了一份 ``log_console.stop or Flags.stop_requested``
（``emby_actor_manager`` / ``emby_actor_info`` / ``emby_actor_image``
各一份模块级函数，``actor_db_tool`` 里还有四份函数内副本），
标志一变就要改多处，极易漂移。这里收敛成单一实现：

- :func:`stop_requested` 是唯一的判定入口；
- 各模块仍保留自己的 ``_is_stop_requested()`` 一行委托，
  因为测试（如 ``tests/test_emby_actor_role_filter_158.py``、
  ``tests/test_emby_actor_manager.py``）monkeypatch 的正是模块级这个名字，
  委托层可以保证 patch 依然生效。

关于 ``log_console.stop`` 与历史写法 ``signal.stop``：
``mdcx/signals.py`` 的 ``Signals.stop`` 已是代理到 ``log_console.stop`` 的属性，
两者是同一个变量，此处统一使用不依赖 Qt 的 ``log_console.stop``。

本模块刻意不依赖 PyQt6 —— 它位于 utils 层，供 tools/base/core 等业务层共用。
"""

from ..log_console import log_console
from ..models.flags import Flags

__all__ = ["stop_requested"]


def stop_requested() -> bool:
    """全局停止标记或任务级停止标记任一置位即视为已请求停止。"""
    return log_console.stop or Flags.stop_requested
