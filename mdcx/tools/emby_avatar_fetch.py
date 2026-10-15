"""头像图源取数的唯一分派实现。

同一段「按图源分派」的阶梯此前在 UI 层被复制了三份，彼此会慢慢漂移：

- ``PreparePreviewThread._fetch_avatar_from``
- ``_actor_source_test_execute``（演员源自检）
- ``ActorDetailDialog._fetch_image``

三份的差别只在**调用点上下文**（缓存目录、本地头像目录/预扫描索引、是否需要背景图、
是否吞异常、是否记录日志），分派本身完全一样。这里把分派收敛到
:func:`fetch_avatar_from_source`，差异全部由参数表达。

注意 ``graphis`` 的返回值是 ``(头像, 背景)`` 元组；只有 ``PreparePreviewThread``
需要额外消费其中的背景图，因此它仍在自己的循环里特判 ``graphis``，
本模块对它提供的能力对那条路径是不可达的（保持原有行为）。

本模块刻意只依赖 ``emby_actor_manager``（数据层），不含任何 Qt 代码，
UI 层通过传入上下文参数复用它。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .emby_actor_manager import (
    ActorInfo,
    from_gfriends,
    from_graphis,
    from_local_avatar,
    from_minnano_image,
    get_gfriends_index,
)

__all__ = [
    "GFRIENDS",
    "GRAPHIS",
    "MINNANO",
    "LOCAL",
    "IMAGE_SOURCE_KEYS",
    "is_known_source",
    "load_gfriends_index",
    "fetch_avatar_from_source",
]

GFRIENDS = "gfriends"
GRAPHIS = "graphis"
MINNANO = "minnano"
LOCAL = "local"

#: 全部受支持的图源标识。顺序仅供展示用，实际取数顺序由调用方传入的列表决定。
IMAGE_SOURCE_KEYS = (GFRIENDS, GRAPHIS, MINNANO, LOCAL)


def is_known_source(src: str) -> bool:
    """该标识是否是受支持的图源（用于区分「未知数据源」与「未命中」）。"""
    return src in IMAGE_SOURCE_KEYS


async def load_gfriends_index() -> dict[str, str] | None:
    """加载 gfriends 索引；任何异常都按「不可用」处理，由调用方跳过该源。"""
    try:
        return await get_gfriends_index()
    except Exception:
        return None


async def fetch_avatar_from_source(
    actor: ActorInfo,
    src: str,
    *,
    gfriends_index: dict[str, str] | None,
    cache_dir: Path,
    local_avatar_dir: str,
    local_avatar_index: dict[str, str] | None = None,
) -> Any:
    """按单个图源尝试取头像，返回该源的原始结果。

    返回值形态随源而异：``graphis`` 返回 ``(头像, 背景)`` 元组或 ``None``，
    其余返回路径字符串或 ``None``。未知源、索引缺失一律返回 ``None``；
    需要区分这两种「空」时请先用 :func:`is_known_source` 判定。
    """
    if src == GFRIENDS:
        if not gfriends_index:
            return None
        return await from_gfriends(actor, gfriends_index, cache_dir)
    if src == GRAPHIS:
        return await from_graphis(actor, cache_dir)
    if src == MINNANO:
        return await from_minnano_image(actor, cache_dir)
    if src == LOCAL:
        return from_local_avatar(actor, local_avatar_dir, local_avatar_index)
    return None
