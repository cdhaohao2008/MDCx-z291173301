import asyncio
import contextlib
import os
import re
import shutil
import stat
import threading
import time
import traceback
from pathlib import Path
from typing import cast
from uuid import uuid4

import aiofiles
import aiofiles.os

from ..config.enums import DownloadableFile, KeepableFile, NoEscape, Switch
from ..config.extend import (
    READ_MAIN_MODE,
    SEPARATE_MAIN_MODE,
    SEPARATE_META_EXTS,
    eff_del_empty_folder,
    eff_failed_file_move,
    eff_success_file_move,
    eff_success_file_rename,
    get_movie_path_setting,
    get_runtime_main_mode,
    get_separate_meta_root,
    is_organize_selected,
    need_clean,
)
from ..config.manager import manager
from ..config.models import CleanAction
from ..config.resource_policy import resource_policy
from ..config.resources import resources
from ..log_console import log_console
from ..models.enums import FileMode
from ..models.flags import FileDoneDict, Flags
from ..models.log_buffer import LogBuffer
from ..ui_hooks import ui_hooks
from ..utils import executor, get_current_time, get_used_time
from ..utils.file import copy_file_async, copy_file_sync, delete_file_async, delete_file_sync, move_file_async
from ..utils.picture import resolve_existing_image

LARGE_LIST_SORT_THRESHOLD = 50000
_large_list_warned: set[str] = set()
_success_list_save_lock = asyncio.Lock()
_SUCCESS_REPLACE_RETRY_MAX = 8
_SUCCESS_REPLACE_RETRY_BASE_SLEEP = 0.15
_remain_save_lock = threading.Lock()


def _path_lines_for_write(paths: list[Path] | set[Path], list_name: str):
    if len(paths) > LARGE_LIST_SORT_THRESHOLD:
        if list_name not in _large_list_warned:
            log_console.log_text(f" ⚠ {list_name} 数量较大（{len(paths)}），保存时将跳过排序以降低内存占用。")
            _large_list_warned.add(list_name)
        for path in paths:
            yield str(path) + "\n"
        return
    for path_str in sorted(str(path) for path in paths):
        yield path_str + "\n"


def _build_success_tmp_path(success_path: Path) -> Path:
    return success_path.with_name(f"{success_path.name}.{os.getpid()}.{uuid4().hex}.tmp")


def _ensure_file_writable(path: Path) -> None:
    if not path.exists():
        return
    current_mode = path.stat().st_mode
    if not (current_mode & stat.S_IWRITE):
        path.chmod(current_mode | stat.S_IWRITE)


async def _replace_success_file_with_retry(success_tmp_path: Path, success_path: Path) -> None:
    try:
        await asyncio.to_thread(_ensure_file_writable, success_path)
    except Exception:
        log_console.log_text(" ⚠ success.txt 文件属性检查失败，将继续尝试保存。")

    for attempt in range(1, _SUCCESS_REPLACE_RETRY_MAX + 1):
        try:
            await asyncio.to_thread(os.replace, success_tmp_path, success_path)
            return
        except PermissionError:
            if attempt == 1:
                log_console.log_text(" ⚠ success.txt 正在被占用，正在重试保存...")
            if attempt >= _SUCCESS_REPLACE_RETRY_MAX:
                raise
            await asyncio.sleep(_SUCCESS_REPLACE_RETRY_BASE_SLEEP * attempt)


async def _cleanup_success_tmp_file(success_tmp_path: Path) -> None:
    try:
        if await aiofiles.os.path.exists(success_tmp_path):
            await aiofiles.os.remove(success_tmp_path)
    except Exception:
        pass


async def move_other_file(
    number: str,
    folder_old_path: Path,
    folder_new_path: Path,
    file_name: str,
    naming_rule: str,
    meta_folder_new_path: Path | None = None,
):
    # 软硬链接模式不移动
    if manager.config.soft_link != 0:
        return

    # 分离模式：元数据与其他文件分开存放
    separate_meta = meta_folder_new_path is not None and meta_folder_new_path != folder_old_path

    # 目录相同不移动
    if folder_new_path == folder_old_path and not separate_meta:
        return

    # 更新模式 或 读取模式
    if get_runtime_main_mode() in (4, READ_MAIN_MODE):
        if manager.config.update_mode == "c" and not eff_success_file_rename():
            return

    elif not eff_success_file_move() and not eff_success_file_rename():
        return

    files = await aiofiles.os.listdir(folder_old_path)
    for old_file in files:
        if os.path.splitext(old_file)[1].lower() in manager.config.media_type:
            continue
        if (
            number in old_file or file_name in old_file or naming_rule in old_file
        ) and "-cd" not in old_file.lower():  # 避免多分集时，其他分级的内容被移走
            old_file_old_path = folder_old_path / old_file
            if separate_meta and os.path.splitext(old_file)[1].lower() in SEPARATE_META_EXTS:
                old_file_new_path = meta_folder_new_path / old_file
            else:
                old_file_new_path = folder_new_path / old_file
            if (
                old_file_old_path != old_file_new_path
                and await aiofiles.os.path.exists(old_file_old_path)
                and not await aiofiles.os.path.exists(old_file_new_path)
            ):
                await move_file_async(old_file_old_path, old_file_new_path)
                LogBuffer.log().write(f"\n 🍀 Move {old_file} done!")


async def move_mediainfo(
    folder_old_path: Path,
    folder_new_path: Path,
    file_name: str,
    naming_rule: str,
) -> None:
    """随视频同步移动同名 ``-mediainfo.json``，并按新文件名重命名。

    整理模式不下载、不刮削，只整理已有文件；``move_other_file`` 在同目录时
    会直接返回，且移动其他文件时不会改名，因此 Mediainfo 需要单独处理。
    """
    if manager.config.soft_link != 0:
        return
    if not (eff_success_file_move() or eff_success_file_rename()):
        return

    old_stem = Path(file_name).stem.lower()
    target = folder_new_path / f"{naming_rule}-mediainfo.json"
    search_dirs = [folder_old_path]
    if folder_new_path != folder_old_path:
        search_dirs.append(folder_new_path)

    for search_dir in search_dirs:
        if not await aiofiles.os.path.isdir(search_dir):
            continue
        try:
            names = await aiofiles.os.listdir(search_dir)
        except OSError:
            continue
        exact = f"{old_stem}-mediainfo.json"
        candidates = [name for name in names if name.lower() == exact]
        if not candidates:
            candidates = [
                name for name in names if name.lower().startswith(old_stem) and name.lower().endswith("-mediainfo.json")
            ]
        for name in candidates:
            source = search_dir / name
            if source == target:
                return
            if await aiofiles.os.path.exists(target):
                LogBuffer.log().write(f"\n 🍀 Mediainfo 已存在，跳过: {target.name}")
                return
            try:
                await move_file_async(source, target)
                LogBuffer.log().write(f"\n 🍀 Move {name} -> {target.name} done!")
            except Exception as e:
                LogBuffer.error().write(f"移动 Mediainfo 失败: {source} ({e!s})")
            return


async def copy_trailer_to_theme_videos(folder_new_path: Path, naming_rule: str) -> None:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    theme_videos_policy = resource_policy(
        DownloadableFile.THEME_VIDEOS,
        KeepableFile.THEME_VIDEOS,
        download_files=download_files,
        keep_files=keep_files,
    )
    theme_videos_folder_path = folder_new_path / "backdrops"
    theme_videos_new_path = theme_videos_folder_path / "theme_video.mp4"

    # 不保留不下载主题视频时，删除
    if theme_videos_policy.should_remove_existing:
        if await aiofiles.os.path.exists(theme_videos_folder_path):
            await asyncio.to_thread(shutil.rmtree, theme_videos_folder_path, ignore_errors=True)
        return

    # 保留主题视频并存在时返回
    if theme_videos_policy.should_keep and await aiofiles.os.path.exists(theme_videos_folder_path):
        LogBuffer.log().write(f"\n 🍀 Theme video done! (old)({get_used_time(start_time)}s) ")
        return

    # 不下载主题视频时返回
    if not theme_videos_policy.should_download:
        return

    # 不存在预告片时返回
    trailer_name = manager.config.trailer_simple_name
    trailer_folder = None
    if trailer_name:
        trailer_folder = folder_new_path / "trailers"
        trailer_file_path = trailer_folder / "trailer.mp4"
    else:
        trailer_file_path = folder_new_path / (naming_rule + "-trailer.mp4")
    if not await aiofiles.os.path.exists(trailer_file_path):
        return

    # 存在预告片时复制
    await aiofiles.os.makedirs(theme_videos_folder_path, exist_ok=True)
    if await aiofiles.os.path.exists(theme_videos_new_path):
        await delete_file_async(theme_videos_new_path)
    await copy_file_async(trailer_file_path, theme_videos_new_path)
    LogBuffer.log().write("\n 🍀 Theme video done! (copy trailer)")

    # 不下载并且不保留预告片时，删除预告片
    trailer_policy = resource_policy(
        DownloadableFile.TRAILER,
        KeepableFile.TRAILER,
        download_files=download_files,
        keep_files=manager.config.keep_files,
    )
    if trailer_policy.should_remove_existing:
        await delete_file_async(trailer_file_path)
        if trailer_name and trailer_folder:
            await asyncio.to_thread(shutil.rmtree, trailer_folder, ignore_errors=True)
        LogBuffer.log().write("\n 🍀 Trailer delete done!")


async def pic_some_deal(number: str, thumb_final_path: Path, fanart_final_path: Path) -> None:
    """
    thumb、poster、fanart 删除冗余的图片
    """
    # 不保存thumb时，清理 thumb
    thumb_policy = resource_policy(
        DownloadableFile.THUMB,
        KeepableFile.THUMB,
        download_files=manager.config.download_files,
        keep_files=manager.config.keep_files,
    )
    if thumb_policy.should_remove_existing:
        # 主图可能是 png/webp/gif 等其它格式，按实际落位路径判断与清理
        existing_fanart = await resolve_existing_image(fanart_final_path)
        existing_thumb = await resolve_existing_image(thumb_final_path)
        if existing_fanart is not None:
            Flags.file_done_dic[number]["thumb"] = existing_fanart
        else:
            Flags.file_done_dic[number]["thumb"] = None
        if existing_thumb is not None:
            await delete_file_async(existing_thumb)
            LogBuffer.log().write("\n 🍀 Thumb delete done!")
    elif not thumb_policy.should_download:
        # thumb 未勾选下载、但 poster/fanart 需要中间源时，thumb_download 会下载
        # 中间 thumb 供裁剪/复制使用。若本地原本就没有 thumb（local_thumb 为空，
        # 即 deal_old_files 未迁移到旧文件），该文件属于中间产物，用完即删，
        # 否则“不下载+保留”会在无旧文件时意外落盘 thumb.jpg。
        try:
            local_thumb = Flags.file_done_dic.get(number, cast(FileDoneDict, {})).get("local_thumb")
        except Exception:
            local_thumb = None
        existing_thumb = await resolve_existing_image(thumb_final_path)
        if not local_thumb and existing_thumb is not None:
            existing_fanart = await resolve_existing_image(fanart_final_path)
            if existing_fanart is not None:
                Flags.file_done_dic[number]["thumb"] = existing_fanart
            else:
                Flags.file_done_dic[number]["thumb"] = None
            await delete_file_async(existing_thumb)
            LogBuffer.log().write("\n 🍀 Thumb delete done! (temp)")


async def save_success_list(old_path: Path | None = None, new_path: Path | None = None) -> None:
    if old_path and NoEscape.RECORD_SUCCESS_FILE in manager.config.no_escape:
        # 软硬链接时，保存原路径；否则保存新路径
        # （UI 线程可并发改 success_list，add 包锁；await 不可放锁内，
        # 先判链再进锁，避免跨挂起点持锁冻住 UI）
        if manager.config.soft_link != 0:
            with Flags.guarded():
                Flags.success_list.add(old_path)
        elif new_path:
            is_link = await aiofiles.os.path.islink(new_path)
            with Flags.guarded():
                Flags.success_list.add(new_path)
                if is_link:
                    Flags.success_list.add(old_path)
                    Flags.success_list.add(new_path.resolve())
    if get_used_time(Flags.success_save_time) > 5 or not old_path:
        Flags.success_save_time = time.time()
        success_tmp_path = Path()
        try:
            async with _success_list_save_lock:
                success_path = resources.u("success.txt")
                success_tmp_path = _build_success_tmp_path(success_path)
                with Flags.guarded():
                    success_list_snapshot = list(Flags.success_list)
                async with aiofiles.open(success_tmp_path, "w", encoding="utf-8", errors="ignore") as f:
                    await f.writelines(_path_lines_for_write(success_list_snapshot, "成功列表"))
                await _replace_success_file_with_retry(success_tmp_path, success_path)
        except Exception as e:
            log_console.log_text(f"  Save success list Error {e!s}\n {traceback.format_exc()}")
        finally:
            if success_tmp_path:
                await _cleanup_success_tmp_file(success_tmp_path)
        with Flags.guarded():
            success_count = len(Flags.success_list)
        ui_hooks.view_success_file_settext(f"查看 ({success_count})")


def save_remain_list() -> None:
    """Save remain list to disk in a background thread to avoid blocking the UI.

    Called by a 1.5s QTimer in the main thread. Snapshot ``Flags.remain_list``
    here (main thread) so the background thread iterates a stable list. A lock
    prevents duplicate writes while preserving retry-on-error behavior.
    """
    if not (Flags.can_save_remain and Switch.REMAIN_TASK in manager.config.switch_on):
        return
    if not _remain_save_lock.acquire(blocking=False):
        return
    with Flags.guarded():
        remain_snapshot = list(Flags.remain_list)
    threading.Thread(target=_save_remain_list_sync, args=(remain_snapshot,), daemon=True).start()


def save_remain_list_now() -> None:
    """立即把当前剩余任务落盘（停止刮削 / 刮削协程退出时调用，议题 #98）。

    不看 dirty 标志——调用方要的就是"此刻"的最新快照。仍走后台线程 +
    同一把锁，避免与定时保存并发写坏文件；锁被占时说明已有一轮保存在途，
    下一轮定时保存会兜底。
    """
    if Switch.REMAIN_TASK not in manager.config.switch_on:
        return
    if not _remain_save_lock.acquire(blocking=False):
        return
    with Flags.guarded():
        remain_snapshot = list(Flags.remain_list)
    threading.Thread(target=_save_remain_list_sync, args=(remain_snapshot,), daemon=True).start()


def _build_remain_tmp_path(remain_path: Path) -> Path:
    return remain_path.with_name(f"{remain_path.name}.{os.getpid()}.{uuid4().hex}.tmp")


def _save_remain_list_sync(paths: list[Path]) -> None:
    """原子写 remain.txt（tmp + os.replace，读取端只见完整版本，议题 #98）。

    落盘后按快照比对清 dirty：保存期间 remain_list 又变化（旧线程的快照
    已过期）时保持 can_save_remain=True，交由下一轮定时保存收尾——
    旧实现无条件清标志，会吞掉新变化的落盘机会。
    """
    remain_path = resources.u("remain.txt")
    tmp_path = _build_remain_tmp_path(remain_path)
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="ignore") as f:
            f.writelines(_path_lines_for_write(paths, "剩余任务列表"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, remain_path)
        # 检查-清标志须原子：比对期间 remain_list 又被改则不清，交下一轮收尾
        with Flags.guarded():
            if list(Flags.remain_list) == paths:
                Flags.can_save_remain = False
    except Exception as e:
        log_console.log_text(f"save remain list error: {e!s}\n {traceback.format_exc()}")
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
    finally:
        _remain_save_lock.release()


async def _clean_empty_folders(path: Path, file_mode: FileMode, allow_empty: bool | None = None) -> None:
    start_time = time.time()
    if allow_empty is None:
        allow_empty = manager.config.del_empty_folder
    if not allow_empty or file_mode == FileMode.Again:
        return
    ui_hooks.set_label_file_path("🗑 正在清理空文件夹，请等待...")
    log_console.log_text(" ⏳ Cleaning empty folders...")

    if NoEscape.FOLDER in manager.config.no_escape:
        ignore_dirs = []
    else:
        ignore_dirs = get_movie_path_setting(movie_path_override=path).ignore_dirs

    if not await aiofiles.os.path.exists(path):
        log_console.log_text(f" 🍀 Clean done!({get_used_time(start_time)}s)")
        log_console.log_text("=" * 80)
        return

    def task():
        folders: list[Path] = []
        for root, dirs, _files in path.walk(top_down=True):
            if (root / "skip").exists():  # 是否有skip文件
                dirs[:] = []  # 忽略当前文件夹子目录
                continue
            if root in ignore_dirs:
                dirs[:] = []  # 忽略当前文件夹子目录
                continue
            dirs_list = [root / d for d in dirs]
            folders.extend(dirs_list)
        folders.sort(reverse=True)
        for folder in folders:
            hidden_file_mac = folder / ".DS_Store"
            hidden_file_windows = folder / "Thumbs.db"
            if os.path.exists(hidden_file_mac):
                delete_file_sync(hidden_file_mac)  # 删除隐藏文件
            if os.path.exists(hidden_file_windows):
                delete_file_sync(hidden_file_windows)  # 删除隐藏文件
            try:
                if not os.listdir(folder):
                    os.rmdir(folder)
                    log_console.log_text(f" 🗑 Clean empty folder: {folder}")
            except Exception as e:
                log_console.show_traceback_log(traceback.format_exc())
                log_console.log_text(f" 🔴 Delete empty folder error: {e!s}")

    await asyncio.to_thread(task)
    log_console.log_text(f" 🍀 Clean done!({get_used_time(start_time)}s)")
    log_console.log_text("=" * 80)


async def check_and_clean_files() -> None:
    ui_hooks.change_buttons_status()
    start_time = time.time()
    movie_paths = get_movie_path_setting().movie_paths
    log_console.log_text("🍯 🍯 🍯 NOTE: START CHECKING AND CLEAN FILE NOW!!!")
    log_console.log_text(f"\n ⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
    log_console.log_text(
        f" 🖥 Movie path: {';'.join(str(path) for path in movie_paths)} \n ⏳ Checking all videos and cleaning, Please wait..."
    )
    total = 0
    succ = 0
    fail = 0
    # 只有主界面点击会运行此函数, 因此此 walk 无需后台执行
    for movie_path in movie_paths:
        if not Path(movie_path).exists():
            log_console.log_text(f" 🔴 Movie folder does not exist: {movie_path}")
            continue
        for root, _dirs, files in Path(movie_path).walk(top_down=True):
            for f in files:
                # 判断清理文件
                path = root / f
                file_type_current = os.path.splitext(f)[1]
                if need_clean(path, f, file_type_current):
                    total += 1
                    result, error_info = delete_file_sync(path)
                    if result:
                        succ += 1
                        log_console.log_text(f" 🗑 Clean: {path!s} ")
                    else:
                        fail += 1
                        log_console.log_text(f" 🗑 Clean error: {error_info} ")
    log_console.log_text(f" 🍀 Clean done!({get_used_time(start_time)}s)")
    log_console.log_text("================================================================================")
    for movie_path in movie_paths:
        # 视频刮削目录下的空目录：永远走左侧正常模式开关（两种模式都一样）
        await _clean_empty_folders(movie_path, FileMode.Default, allow_empty=manager.config.del_empty_folder)
        if get_runtime_main_mode() == SEPARATE_MAIN_MODE:
            meta_root = get_separate_meta_root(
                movie_path, get_movie_path_setting(movie_path_override=movie_path).success_folder
            )
            if meta_root is not None:
                # 数据存放目录下的空目录：走右侧分离模式开关
                await _clean_empty_folders(meta_root, FileMode.Default, allow_empty=eff_del_empty_folder())
    ui_hooks.set_label_file_path("🗑 清理完成！")
    log_console.log_text(
        f" 🎉🎉🎉 All finished!!!({get_used_time(start_time)}s) Total {total} , Success {succ} , Failed {fail} "
    )
    log_console.log_text("================================================================================")
    ui_hooks.reset_buttons_status()


def get_success_list() -> None:
    """This function is intended to be sync"""
    Flags.success_save_time = time.time()
    success_path = resources.u("success.txt")
    if os.path.isfile(success_path):
        with open(success_path, encoding="utf-8", errors="ignore") as f:
            loaded_success = {p for path in f if (line := path.strip()) and (p := Path(line)).suffix}
        with Flags.guarded():
            Flags.success_list = loaded_success
        executor.run(save_success_list())
    with Flags.guarded():
        success_total = len(Flags.success_list)
    ui_hooks.view_success_file_settext(f"查看 ({success_total})")


async def movie_lists(
    ignore_dirs: list[Path],
    media_type: list[str],
    movie_path: Path,
    include_success: bool = False,
) -> list[Path]:
    start_time = time.time()
    total = []
    skip_list = ["skip", ".skip", ".ignore"]
    not_skip_success = include_success or NoEscape.SKIP_SUCCESS_FILE not in manager.config.no_escape

    log_console.show_traceback_log("🔎 遍历待刮削目录....")

    def task():
        i = 100
        skip = 0
        skip_repeat_softlink = 0
        seen_link_targets: set[Path] = set()
        for root, dirs, files in movie_path.walk(top_down=True):
            for d in dirs.copy():
                if root / d in ignore_dirs or "behind the scenes" in d:
                    dirs.remove(d)

            # 文件夹是否存在跳过文件
            for skip_key in skip_list:
                if skip_key in files:
                    dirs.clear()
                    break
            else:
                # 处理文件列表
                for f in files:
                    file_name, file_ext = os.path.splitext(f)

                    # 跳过隐藏文件、预告片、主题视频
                    if re.search(r"^\..+", file_name):
                        continue
                    if "trailer." in f or "trailers." in f:
                        continue
                    if "theme_video." in f:
                        continue

                    # 判断清理文件
                    path = root / f
                    if CleanAction.AUTO_CLEAN in manager.config.clean_enable and need_clean(path, f, file_ext):
                        result, error_info = delete_file_sync(path)
                        if result:
                            log_console.log_text(f" 🗑 Clean: {path} ")
                        else:
                            log_console.log_text(f" 🗑 Clean error: {error_info} ")
                        continue

                    # 添加文件
                    if file_ext.lower() in media_type:
                        if os.path.islink(path):
                            real_path = Path(os.path.realpath(path))
                            # 清理失效的软链接文件
                            if NoEscape.CHECK_SYMLINK in manager.config.no_escape and not real_path.exists():
                                result, error_info = delete_file_sync(path)
                                if result:
                                    log_console.log_text(f" 🗑 Clean dead link: {path} ")
                                else:
                                    log_console.log_text(f" 🗑 Clean dead link error: {error_info} ")
                                continue
                            if real_path in seen_link_targets:
                                skip_repeat_softlink += 1
                                continue
                            seen_link_targets.add(real_path)
                        if not_skip_success:
                            total.append(path)
                        else:
                            # task() 跑在 to_thread 工作线程，success_list 正被协程/UI 并发改：包锁判
                            with Flags.guarded():
                                already_done = path in Flags.success_list
                            if already_done:
                                skip += 1
                            else:
                                total.append(path)

        found_count = len(total)
        if found_count >= i:
            i = found_count + 100
            log_console.show_traceback_log(
                f"✅ Found ({found_count})! "
                f"Skip successfully scraped ({skip}) repeat softlink ({skip_repeat_softlink})! "
                f"({get_used_time(start_time)}s)... Still searching, please wait... \u3000"
            )
            log_console.log_text(
                f"    {get_current_time()} Found ({found_count})! "
                f"Skip successfully scraped ({skip}) repeat softlink ({skip_repeat_softlink})! "
                f"({get_used_time(start_time)}s)... Still searching, please wait... \u3000"
            )
        return total, skip, skip_repeat_softlink

    total, skip, skip_repeat_softlink = await asyncio.to_thread(task)

    total.sort()
    log_console.show_traceback_log(
        f"🎉 Done!!! Found ({len(total)})! "
        f"Skip successfully scraped ({skip}) repeat softlink ({skip_repeat_softlink})! "
        f"({get_used_time(start_time)}s) \u3000"
    )
    log_console.log_text(
        f"    Done!!! Found ({len(total)})! "
        f"Skip successfully scraped ({skip}) repeat softlink ({skip_repeat_softlink})! "
        f"({get_used_time(start_time)}s) \u3000"
    )
    return total


async def get_movie_list(file_mode: FileMode, movie_path: Path, ignore_dirs: list[Path]) -> list[Path]:
    movie_list = []
    if file_mode == FileMode.Default:  # 刮削默认视频目录的文件
        if not await aiofiles.os.path.exists(movie_path):
            log_console.log_text("\n 🔴 Movie folder does not exist!")
        else:
            log_console.log_text(f" 🖥 Movie path: {movie_path}")
            log_console.log_text(" 🔎 Searching all videos, Please wait...")
            ui_hooks.set_label_file_path(f"正在遍历待刮削视频目录中的所有视频，请等待...\n {movie_path}")
            if NoEscape.FOLDER in manager.config.no_escape or get_runtime_main_mode() in (4, READ_MAIN_MODE):
                ignore_dirs = []
            media_type = list(manager.config.media_type)
            # 整理模式需要扫描已刮削成功的文件，并处理 STRM 链接文件
            # （扫描规则跟着用户在「软件设置」里选择的模式走：整理模式自动
            #  切换成读取模式发生在扫描之后，扫描时仍需看到成功输出目录内的文件）
            organize_mode = is_organize_selected()
            # 整理模式需要扫描已刮削成功的文件，并处理 STRM 链接文件
            normalized_media_type = {str(ext).lower().lstrip(".") for ext in media_type}
            if organize_mode and "strm" not in normalized_media_type:
                media_type.append(".strm")
            try:
                # 获取所有需要刮削的影片列表
                movie_list = await movie_lists(
                    ignore_dirs,
                    media_type,
                    movie_path,
                    include_success=organize_mode,
                )
            except Exception:
                log_console.show_traceback_log(traceback.format_exc())
                log_console.log_text(traceback.format_exc())
            count_all = len(movie_list)
            log_console.log_text(" 📺 Find " + str(count_all) + " movies")

    elif file_mode == FileMode.Single:  # 刮削单文件（工具页面）
        file_path = Flags.single_file_path
        if not await aiofiles.os.path.exists(file_path):
            log_console.log_text(" 🔴 Movie file does not exist!")
        else:
            movie_list.append(file_path)  # 把文件路径添加到movie_list
            log_console.log_text(f" 🖥 File path: {file_path}")
            if Flags.appoint_url:
                log_console.log_text(" 🌐 File url: " + Flags.appoint_url)

    return movie_list


async def newtdisk_creat_symlink(
    copy_flag: bool,
    netdisk_path: Path | None = None,
    local_path: Path | None = None,
) -> None:
    from_tool = False
    if not netdisk_path:
        from_tool = True
        ui_hooks.change_buttons_status()
    start_time = time.time()
    if not netdisk_path:
        netdisk_path = Path(manager.config.netdisk_path)
    if not local_path:
        local_path = Path(manager.config.localdisk_path)
    log_console.log_text("🍯 🍯 🍯 开始创建符号链接")
    log_console.log_text(f" 📁 源路径: {netdisk_path} \n 📁 目标路径：{local_path} \n")
    try:
        if not netdisk_path or not local_path:
            log_console.log_text(f" 🔴 网盘目录和本地目录不能为空！请重新设置！({get_used_time(start_time)}s)")
            log_console.log_text("================================================================================")
            if from_tool:
                ui_hooks.reset_buttons_status()
            return
        copy_exts = [".nfo", ".jpg", ".png"] + manager.config.sub_type
        file_exts = "|".join(manager.config.media_type).lower().split("|") + copy_exts + manager.config.sub_type

        def task():
            total = 0
            copy_num = 0
            link_num = 0
            fail_num = 0
            skip_num = 0
            done = set()
            for root, _, files in netdisk_path.walk(top_down=True):
                if root == local_path:
                    continue

                local_dir = local_path / root.relative_to(netdisk_path)
                os.makedirs(local_dir, exist_ok=True)
                for f in files:
                    # 跳过隐藏文件、预告片、主题视频
                    if f.startswith("."):
                        continue
                    if "trailer." in f or "trailers." in f:
                        continue
                    if "theme_video." in f:
                        continue
                    # 跳过未知扩展名
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in file_exts:
                        continue

                    total += 1
                    net_file = root / f
                    local_file = local_dir / f
                    if local_file.is_file():
                        log_console.log_text(f" {total} 🟠 跳过: 已存在文件或有效的符号链接\n {net_file} ")
                        skip_num += 1
                        continue
                    if local_file.is_symlink():
                        log_console.log_text(f" {total} 🔴 删除: 无效的符号链接\n {net_file} ")
                        local_file.unlink()

                    if ext in copy_exts:  # 直接复制的文件
                        if not copy_flag:
                            continue
                        copy_file_sync(net_file, local_file)
                        log_console.log_text(f" {total} 🍀 Copy done!\n {net_file} ")
                        copy_num += 1
                        continue
                    # 不对原文件进行有效性检查以减小可能的网络 IO 开销
                    if net_file in done:
                        log_console.log_text(
                            f" {total} 🟠 Link skip! Source file already linked, this file is duplicate!\n {net_file} "
                        )
                        skip_num += 1
                        continue
                    done.add(net_file)

                    try:
                        os.symlink(net_file, local_file)
                        log_console.log_text(f" {total} 🍀 Link done!\n {net_file} ")
                        link_num += 1
                    except Exception as e:
                        error_info = ""
                        if "symbolic link privilege not held" in str(e):
                            error_info = "   \n没有创建权限，请尝试管理员权限！或按照教程开启用户权限： https://www.jianshu.com/p/0e307bfe8770"
                        log_console.log_text(f" {total} 🔴 Link failed!{error_info} \n {net_file} ")
                        log_console.log_text(traceback.format_exc())
                        fail_num += 1
            return total, copy_num, link_num, skip_num, fail_num

        total, copy_num, link_num, skip_num, fail_num = await asyncio.to_thread(task)
        log_console.log_text(
            f"\n 🎉🎉🎉 All finished!!!({get_used_time(start_time)}s) Total {total} , "
            f"Linked {link_num} , Copied {copy_num} , Skiped {skip_num} , Failed {fail_num} "
        )
    except Exception:
        log_console.log_text(traceback.format_exc())

    log_console.log_text("================================================================================")
    if from_tool:
        ui_hooks.reset_buttons_status()


async def move_file_to_failed_folder(failed_folder: Path, file_path: Path, folder_old_path: Path) -> Path:
    # 更新模式、读取模式，不移动失败文件；生效开关-关时，不移动； 软硬链接开时，不移动
    # （分离模式取右侧分离开关，否则取左侧正常开关）
    # 注意：这里必须用「本次运行实际生效的模式」——整理模式自动切换成读取模式后，
    # 失败文件同样不许再被搬走（成功输出目录内的文件绝不能被移动）。
    main_mode = get_runtime_main_mode()
    if main_mode == 4 or main_mode == READ_MAIN_MODE or not eff_failed_file_move() or manager.config.soft_link != 0:
        LogBuffer.log().write(f"\n 🙊 [Movie] {file_path}")
        return file_path

    # 创建failed文件夹
    if eff_failed_file_move():
        try:
            await aiofiles.os.makedirs(failed_folder, exist_ok=True)
        except Exception:
            log_console.show_traceback_log(traceback.format_exc())
            log_console.log_text(traceback.format_exc())

    # 获取文件路径
    file_full_name = file_path.name
    file_ext = file_path.suffix
    trailer_old_path_no_filename = folder_old_path / "trailers/trailer.mp4"
    trailer_old_path_with_filename = file_path.with_name(file_path.stem + "-trailer.mp4")

    # 重复改名
    file_new_path = failed_folder / file_full_name
    while await aiofiles.os.path.exists(file_new_path) and file_new_path != file_path:
        file_new_path = file_new_path.with_name(file_new_path.stem + "@" + file_ext)

    # 移动
    try:
        await move_file_async(file_path, file_new_path)
        LogBuffer.log().write("\n 🔴 Move file to the failed folder!")
        LogBuffer.log().write(f"\n 🙊 [Movie] {file_new_path}")
        error_info = LogBuffer.error().get(only_self=True)
        LogBuffer.error().clear()
        LogBuffer.error().write(error_info.replace(str(file_path), str(file_new_path)))

        # 同步移动预告片
        trailer_new_path = file_new_path.with_name(file_new_path.stem + "-trailer.mp4")
        if not await aiofiles.os.path.exists(trailer_new_path):
            try:
                has_trailer = False
                if await aiofiles.os.path.exists(trailer_old_path_with_filename):
                    has_trailer = True
                    await move_file_async(trailer_old_path_with_filename, trailer_new_path)
                elif await aiofiles.os.path.exists(trailer_old_path_no_filename):
                    has_trailer = True
                    await move_file_async(trailer_old_path_no_filename, trailer_new_path)
                if has_trailer:
                    LogBuffer.log().write("\n 🔴 Move trailer to the failed folder!")
                    LogBuffer.log().write(f"\n 🔴 [Trailer] {trailer_new_path}")
            except Exception as e:
                LogBuffer.log().write(f"\n 🔴 Failed to move trailer to the failed folder! \n    {e!s}")

        # 同步移动字幕
        sub_types = [".chs" + i for i in manager.config.sub_type if ".chs" not in i]
        for sub in sub_types:
            sub_old_path = file_path.with_suffix(sub)
            sub_new_path = file_new_path.with_suffix(sub)
            if await aiofiles.os.path.exists(sub_old_path) and not await aiofiles.os.path.exists(sub_new_path):
                result, error_info = await move_file_async(sub_old_path, sub_new_path)
                if not result:
                    LogBuffer.log().write(f"\n 🔴 Failed to move sub to the failed folder!\n     {error_info}")
                else:
                    LogBuffer.log().write("\n 💡 Move sub to the failed folder!")
                    LogBuffer.log().write(f"\n 💡 [Sub] {sub_new_path}")
        return file_new_path
    except Exception as e:
        LogBuffer.log().write(f"\n 🔴 Failed to move the file to the failed folder! \n    {e!s}")
        return file_path


async def check_file(file_path: Path, file_escape_size: float) -> bool:
    if await aiofiles.os.path.islink(file_path):
        file_path = file_path.resolve()
        if NoEscape.CHECK_SYMLINK not in manager.config.no_escape:
            return True

    if not await aiofiles.os.path.exists(file_path):
        LogBuffer.error().write("文件不存在")
        return False
    # STRM 只是链接文本，不能用视频文件大小阈值过滤
    if file_path.suffix.lower() != ".strm" and NoEscape.NO_SKIP_SMALL_FILE not in manager.config.no_escape:
        try:
            file_size = await aiofiles.os.path.getsize(file_path) / float(1024 * 1024)
        except OSError:
            # exists 与 getsize 之间文件被删/移动（TOCTOU）：按不存在处理，避免打穿整批
            LogBuffer.error().write("文件不存在")
            return False
        if file_size < file_escape_size:
            LogBuffer.error().write(
                f"文件小于 {file_escape_size} MB 被过滤!（实际大小 {round(file_size, 2)} MB）已跳过刮削！"
            )
            return False
    return True


async def move_torrent(old_dir: Path, new_dir: Path, file_name: str, number: str, naming_rule: str):
    # 更新模式 或 读取模式
    if get_runtime_main_mode() in (4, READ_MAIN_MODE):
        if manager.config.update_mode == "c" and not eff_success_file_rename():
            return

    # 软硬链接开时，不移动
    elif manager.config.soft_link != 0 or not eff_success_file_move() and not eff_success_file_rename():
        return
    torrent_file1 = old_dir / (file_name + ".torrent")
    torrent_file2 = old_dir / (number + ".torrent")
    torrent_file1_new_path = new_dir / (naming_rule + ".torrent")
    torrent_file2_new_path = new_dir / (number + ".torrent")
    if (
        await aiofiles.os.path.exists(torrent_file1)
        and torrent_file1 != torrent_file1_new_path
        and not await aiofiles.os.path.exists(torrent_file1_new_path)
    ):
        await move_file_async(torrent_file1, torrent_file1_new_path)
        LogBuffer.log().write("\n 🍀 Torrent done!")

    if torrent_file2 != torrent_file1 and (
        await aiofiles.os.path.exists(torrent_file2)
        and torrent_file2 != torrent_file2_new_path
        and not await aiofiles.os.path.exists(torrent_file2_new_path)
    ):
        await move_file_async(torrent_file2, torrent_file2_new_path)
        LogBuffer.log().write("\n 🍀 Torrent done!")


async def move_bif(old_dir: Path, new_dir: Path, file_name: str, naming_rule: str) -> None:
    # 更新模式 或 读取模式
    if get_runtime_main_mode() in (4, READ_MAIN_MODE):
        if manager.config.update_mode == "c" and not eff_success_file_rename():
            return

    elif not eff_success_file_move() and not eff_success_file_rename():
        return
    bif_old_path = old_dir / (file_name + "-320-10.bif")
    bif_new_path = new_dir / (naming_rule + "-320-10.bif")
    if (
        bif_old_path != bif_new_path
        and await aiofiles.os.path.exists(bif_old_path)
        and not await aiofiles.os.path.exists(bif_new_path)
    ):
        await move_file_async(bif_old_path, bif_new_path)
        LogBuffer.log().write("\n 🍀 Bif done!")


async def move_trailer_video(old_dir: Path, new_dir: Path, file_name: str, naming_rule: str) -> None:
    runtime_mode = get_runtime_main_mode()
    if runtime_mode < 2 and not eff_success_file_move() and not eff_success_file_rename():
        return
    if runtime_mode in (4, READ_MAIN_MODE):
        update_mode = manager.config.update_mode
        if update_mode == "c" and not eff_success_file_rename():
            return

    for media_type in manager.config.media_type:
        trailer_old_path = old_dir / (file_name + "-trailer" + media_type)
        trailer_new_path = new_dir / (naming_rule + "-trailer" + media_type)
        if await aiofiles.os.path.exists(trailer_old_path) and not await aiofiles.os.path.exists(trailer_new_path):
            await move_file_async(trailer_old_path, trailer_new_path)
            LogBuffer.log().write("\n 🍀 Trailer done!")
