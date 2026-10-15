"""
刮削过程所需图片操作
"""

import asyncio
import os
import time
import traceback
from pathlib import Path
from typing import cast

from PIL import Image

from ..base.image import add_mark_thread
from ..config.enums import DownloadableFile, FixedScrapingType, MarkType
from ..config.manager import manager
from ..log_console import log_console
from ..models.log_buffer import LogBuffer
from ..models.model_types import CrawlersResult, FileInfo, OtherInfo
from ..models.mosaic import has_leak_mark, has_umr_mark, has_uncensored_mark, is_censored_mosaic
from ..utils import executor, get_used_time
from ..utils.file import check_pic_async, copy_file_async, copy_file_sync, delete_file_sync

YOUMA_RIGHT_CROP_TYPES = {FixedScrapingType.YOUMA}
FACE_FALLBACK_CROP_TYPES = {
    FixedScrapingType.WUMA,
    FixedScrapingType.FC2,
    FixedScrapingType.OUMEI,
    FixedScrapingType.GUOCHAN,
    FixedScrapingType.SUREN,
    FixedScrapingType.AUTO,
}


def get_face_crop_left(image, crop_width, log_fn=None) -> int | None:
    from .face_crop import get_face_crop_left as detect_face_crop_left

    return detect_face_crop_left(image, crop_width, log_fn=log_fn)


async def add_mark(json_data: OtherInfo, file_info: FileInfo, mosaic: str):
    poster_marked = json_data.poster_marked
    thumb_marked = json_data.thumb_marked
    fanart_marked = json_data.fanart_marked
    download_files = manager.config.download_files
    mark_type = manager.config.mark_type
    has_sub = file_info.has_sub
    definition = file_info.definition
    mark_list = []
    if ("K" in definition or "UHD" in definition) and MarkType.HD in mark_type:
        if "8" in definition:
            mark_list.append("8K")
        else:
            mark_list.append("4K")
    if has_sub and MarkType.SUB in mark_type:
        mark_list.append("字幕")

    if is_censored_mosaic(mosaic):
        if MarkType.YOUMA in mark_type:
            mark_list.append("有码")
    elif has_umr_mark(mosaic):
        if MarkType.UMR in mark_type:
            mark_list.append("破解")
        elif MarkType.UNCENSORED in mark_type:
            mark_list.append("无码")
    elif has_leak_mark(mosaic):
        if MarkType.LEAK in mark_type:
            mark_list.append("流出")
        elif has_uncensored_mark(mosaic) and MarkType.UNCENSORED in mark_type:
            mark_list.append("无码")
    elif has_uncensored_mark(mosaic) and MarkType.UNCENSORED in mark_type:
        mark_list.append("无码")

    if mark_list:
        download_files = manager.config.download_files
        mark_show_type = ",".join(mark_list)
        poster_path = json_data.poster_path
        thumb_path = json_data.thumb_path
        fanart_path = json_data.fanart_path

        if (
            manager.config.thumb_mark == 1
            and DownloadableFile.THUMB in download_files
            and thumb_path
            and not thumb_marked
        ):
            await add_mark_thread(thumb_path, mark_list)
            LogBuffer.log().write(f"\n 🍀 Thumb add watermark: {mark_show_type}!")
        if (
            manager.config.poster_mark == 1
            and DownloadableFile.POSTER in download_files
            and poster_path
            and not poster_marked
        ):
            await add_mark_thread(poster_path, mark_list)
            LogBuffer.log().write(f"\n 🍀 Poster add watermark: {mark_show_type}!")
        if (
            manager.config.fanart_mark == 1
            and DownloadableFile.FANART in download_files
            and fanart_path
            and not fanart_marked
        ):
            await add_mark_thread(fanart_path, mark_list)
            LogBuffer.log().write(f"\n 🍀 Fanart add watermark: {mark_show_type}!")


def _image_size_blocking(pic_path: str | Path) -> tuple[int, int] | None:
    """同步读取图片像素尺寸，失败时返回 None（只读、不删文件）。"""
    try:
        with Image.open(pic_path) as img:  # 损坏/非图片文件在此抛异常
            width, height = img.size
        return int(width), int(height)
    except Exception:
        return None


async def _image_size_async(pic_path: str | Path) -> tuple[int, int] | None:
    """异步读取图片像素尺寸：仅取尺寸，区别于 check_pic_async 的「损坏即删除」。"""
    try:
        if not await asyncio.to_thread(os.path.exists, pic_path):
            return None
    except (OSError, TypeError, ValueError):
        return None
    return await asyncio.to_thread(_image_size_blocking, pic_path)


async def _replace_if_poster_bigger(
    poster_path: Path | None,
    target_path: Path | None,
    label: str,
) -> bool:
    """poster **宽和高都严格大于** target 时用 poster 覆盖 target，成功返回 True。

    判据刻意不用像素面积：面积大 ≠ 每一维都大。例如 poster 1000x2000（面积 200 万）
    大于 thumb 1500x1000（面积 150 万），但 poster 的宽度反而更窄 —— 这种「竖图覆盖
    横图」并不是真正的「更大的缩略图」，用它替换会让 thumb 变小。按面积判会误替换，
    故必须是 poster_w > target_w **且** poster_h > target_h 两个条件同时成立。

    target 缺失或读不出尺寸（损坏）时无从比较，直接用 poster 补上/修复。
    """
    if not poster_path or not target_path:
        return False
    try:
        if await asyncio.to_thread(os.path.samefile, poster_path, target_path):
            return False  # 同一个文件，无需替换
    except OSError:
        pass
    poster_size = await _image_size_async(poster_path)
    if not poster_size:
        return False
    target_size = await _image_size_async(target_path)
    if target_size and not (poster_size[0] > target_size[0] and poster_size[1] > target_size[1]):
        LogBuffer.log().write(
            f"\n 🍀 封面替换{label}跳过: poster {poster_size[0]}x{poster_size[1]}"
            f" 未同时大于 {target_path.name} {target_size[0]}x{target_size[1]}"
        )
        return False
    ok, err = await copy_file_async(poster_path, target_path)
    if not ok:
        LogBuffer.log().write(f"\n 🍀 封面替换{label}失败: {err}")
        return False
    LogBuffer.log().write(
        f"\n 🍀 封面替换{label}: poster {poster_size[0]}x{poster_size[1]} → {label} {target_path.name}"
        + (f" {target_size[0]}x{target_size[1]}" if target_size else "")
    )
    return True


async def replace_thumb_fanart_with_poster(
    json_data: OtherInfo,
    thumb_path: Path | None,
    fanart_path: Path | None,
    poster_path: Path | None,
):
    """「封面替换缩略图」：勾选后，若 poster **宽和高都严格大于** thumb/fanart，则用 poster 覆盖之。

    仅当对应文件类型本身也勾选了「下载」时才替换，否则 replace 出来的文件会被
    pic_some_deal 之类的清理逻辑当成「不下载的中间产物」删掉。替换放在加水印之前，
    这样替换后的 thumb/fanart 仍能正常打上水印。
    """
    download_files = manager.config.download_files
    if DownloadableFile.POSTER_REPLACE_THUMB not in download_files:
        return
    if DownloadableFile.POSTER not in download_files:
        return
    if not poster_path:
        return

    thumb_done = False
    fanart_done = False
    if DownloadableFile.THUMB in download_files:
        thumb_done = await _replace_if_poster_bigger(poster_path, thumb_path, "缩略图")
    if DownloadableFile.FANART in download_files:
        fanart_done = await _replace_if_poster_bigger(poster_path, fanart_path, "背景图")

    # 替换后文件内容已变，需复位 marked 标记，否则 add_mark 会跳过加水印
    if thumb_done:
        json_data.thumb_marked = False
        if thumb_path:
            json_data.thumb_path = thumb_path
    if fanart_done:
        json_data.fanart_marked = False
        if fanart_path:
            json_data.fanart_path = fanart_path


def _right_crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    ax, ay, bx, by = width / 1.9, 0, width, height
    if width == 800:
        if height == 439:
            ax, ay, bx, by = 420, 0, width, height
        elif 499 <= height <= 503:
            ax, ay, bx, by = 437, 0, width, height
        else:
            ax, ay, bx, by = 421, 0, width, height
    elif width == 840 and height == 472:
        ax, ay, bx, by = 473, 0, 788, height
    return int(ax), int(ay), int(bx), int(by)


def _center_crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    crop_width = int(height / 1.5)
    ax = max(int((width - crop_width) / 2), 0)
    ay = 0
    bx = min(ax + crop_width, width)
    by = height
    return ax, ay, bx, by


def cut_thumb_to_poster(
    json_data: CrawlersResult,
    thumb_path: Path,
    poster_path: Path,
    scraping_type: FixedScrapingType,
    log_fn=None,
):
    start_time = time.time()
    log = log_fn or LogBuffer.web().write
    if os.path.exists(poster_path):
        delete_file_sync(poster_path)

    img: Image.Image | None = None
    img_new = None
    img_new_png = None
    # 打开图片, 获取图片尺寸
    try:
        img = Image.open(thumb_path)  # 返回一个Image对象
        img = cast("Image.Image", img)

        w, h = img.size
        prop = h / w

        # 优先按图片比例决定基础裁剪方式，保持旧版自动裁剪行为。
        if prop >= 1.4:
            copy_file_sync(thumb_path, poster_path)
            log(f"\n 🍀 Poster done! (copy thumb)({get_used_time(start_time)}s)")
            json_data.poster_from = "copy thumb"
            img.close()
            return True
        if prop >= 1:
            json_data.poster_from = "thumb center"
            ax, ay, bx, by = _center_crop_box(w, h)
            log(f"\n 🖼 Poster裁剪: {scraping_type.value} {w}x{h}，竖图居中裁剪")

        # 横图有码作品固定走右裁剪；其余已枚举类型优先做人脸识别，失败后回退居中裁剪。
        elif scraping_type in YOUMA_RIGHT_CROP_TYPES:
            json_data.poster_from = "thumb right"
            ax, ay, bx, by = _right_crop_box(w, h)
            log(f"\n 🖼 Poster裁剪: {scraping_type.value} {w}x{h}，有码右裁策略")
        elif scraping_type in FACE_FALLBACK_CROP_TYPES:
            crop_width = int(h / 1.5)
            face_left = get_face_crop_left(img, crop_width, log_fn=log)
            if face_left is None:
                json_data.poster_from = "thumb center"
                ax, ay, bx, by = _center_crop_box(w, h)
                log(f"\n 🖼 Poster裁剪: {scraping_type.value} {w}x{h}，人脸未识别到，居中裁剪")
            else:
                json_data.poster_from = "thumb face"
                ax, ay, bx, by = face_left, 0, face_left + crop_width, h
                if bx > w:
                    bx = w
                    ax = max(bx - crop_width, 0)
                log(f"\n 🖼 Poster裁剪: {scraping_type.value} {w}x{h}，人脸识别裁剪")
        else:
            json_data.poster_from = "thumb center"
            ax, ay, bx, by = _center_crop_box(w, h)
            log(f"\n 🖼 Poster裁剪: {scraping_type.value} {w}x{h}，默认居中裁剪")

        # 裁剪并保存
        img_new = img.convert("RGB")
        img_new = cast("Image.Image", img_new)
        img_new_png = img_new.crop((ax, ay, bx, by))
        img_new_png.save(poster_path, quality=95, subsampling=0)
        if executor.run(check_pic_async(poster_path)):
            log(f"\n 🍀 Poster done! ({json_data.poster_from})({get_used_time(start_time)}s)")
            return True
        log(f"\n 🥺 Poster cut failed! ({json_data.poster_from})({get_used_time(start_time)}s)")
    except Exception as e:
        log(f"\n 🥺 Poster failed! ({json_data.poster_from})({get_used_time(start_time)}s)\n    {e!s}")
        log_console.show_traceback_log(traceback.format_exc())
        log_console.log_text(f"{traceback.format_exc()}\n Pic: {thumb_path}")
        return False
    finally:
        if img_new_png:
            img_new_png.close()
        if img_new:
            img_new.close()
        if img:
            img.close()
    return False
