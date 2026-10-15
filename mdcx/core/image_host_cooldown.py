"""图床级失败冷却的兼容再导出（保留旧导入路径）。

实现已下沉到 `mdcx/base/image_host_cooldown.py`——调用方 `mdcx/base/web.py`
与 `mdcx/core/media_resource.py` 此前从 core 取用属于层级倒置。

新代码请直接 `from mdcx.base.image_host_cooldown import ...`；此处的转出
仅为兼容既有导入。下方的模块级 `__getattr__` 保证任何名字（含测试用到的私有名
`_reset_for_test` / `_FAIL_THRESHOLD`）都能照旧取到。
"""

from __future__ import annotations

from ..base import image_host_cooldown as _impl
from ..base.image_host_cooldown import (
    record_failure,
    record_success,
    remaining_seconds,
)

__all__ = [
    "record_failure",
    "record_success",
    "remaining_seconds",
]


def __getattr__(name: str):
    """把其余名字（含私有名）原样转发到实现模块。"""
    return getattr(_impl, name)
