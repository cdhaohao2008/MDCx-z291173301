"""图片后缀与主图路径工具（整理模式、普通/更新模式共用）。

poster / thumb / fanart 三张主图不再局限于 .jpg：本地已有的 jpg / jpeg / jfif /
png / gif / webp / bmp / tif / tiff / tga / ico / pcx / avif / heic / jxr 等格式
同样能被识别为主图，搬走时保留源文件的真实扩展名
（poster.png → poster.png，fanart.gif → fanart.gif），避免"改扩展名"造成的
格式伪装与动图变静图。

本模块统一维护受支持的后缀集合、主图候选路径以及"实际落位路径"的解析，
供整理模式（core/organize.py）、普通/更新模式（core/file.py、core/web.py）
与刮削收尾记账（core/scraper.py）共用，避免各处各写一份导致行为漂移。
"""

from __future__ import annotations

from pathlib import Path

import aiofiles.os

from .file import delete_file_async

# 受支持的图片后缀（按查找优先级排列，.jpg 在前，保证既有行为完全不变）
# 覆盖 jpg / jpeg / jfif / png / gif / webp / bmp / tif / tiff / tga / ico / pcx /
# avif / heic / jxr 等常见格式：主图不局限于 jpg，读取模式与整理模式都能识别并展示。
IMAGE_SUFFIX_ORDER: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".jfif",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".tga",
    ".ico",
    ".pcx",
    ".avif",
    ".heic",
    ".jxr",
)
IMAGE_SUFFIXES: frozenset[str] = frozenset(IMAGE_SUFFIX_ORDER)


def image_path_candidates(base: Path) -> list[Path]:
    """同一张图在各种受支持后缀下的候选路径（base 一般以 .jpg 结尾）。"""
    return [base.with_suffix(suffix) for suffix in IMAGE_SUFFIX_ORDER]


def image_path_with_suffix(base: Path, suffix: str) -> Path:
    """按源文件的真实后缀生成目标路径（保留原扩展名）。"""
    text = str(suffix or "").lower()
    if not text or text not in IMAGE_SUFFIXES:
        return base
    return base.with_suffix(text if text.startswith(".") else f".{text}")


def is_supported_image_suffix(suffix: str) -> bool:
    """后缀是否属于受支持的图片格式。"""
    return str(suffix or "").lower() in IMAGE_SUFFIXES


async def resolve_existing_image(base: Path) -> Path | None:
    """返回实际存在的图片路径（按 IMAGE_SUFFIX_ORDER 优先级），都不存在则返回 None。"""
    for candidate in image_path_candidates(base):
        if await aiofiles.os.path.exists(candidate):
            return candidate
    return None


def resolve_existing_image_sync(base: Path) -> Path | None:
    """同步版本：在磁盘上查找实际存在的图片路径（GUI 线程里用）。"""
    for candidate in image_path_candidates(base):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


async def remove_other_image_variants(base: Path, keep: Path | None = None) -> None:
    """删除同一张图的其它后缀副本，避免 poster.png 与 poster.jpg 并存。"""
    for candidate in image_path_candidates(base):
        if keep is not None and str(candidate).lower() == str(keep).lower():
            continue
        if await aiofiles.os.path.exists(candidate):
            await delete_file_async(candidate)


async def resolve_main_image(base: Path, *, drop_other_variants: bool = False) -> Path | None:
    """解析主图实际落位路径。

    - base 一般是 poster.jpg 这类规范名
    - 优先返回规范名本身，其次按受支持后缀依次查找
    - drop_other_variants=True 时删除同名的其它后缀副本（下载覆盖后的残留清理）
    """
    existing = await resolve_existing_image(base)
    if existing is None:
        return None
    if drop_other_variants:
        await remove_other_image_variants(base, keep=existing)
    return existing
