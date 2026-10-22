import os
from dataclasses import dataclass
from pathlib import Path

from ..manual import ManualConfig
from ..utils.path import is_descendant
from .enums import Switch, Website
from .manager import manager
from .models import CleanAction


@dataclass
class MoviePathSetting:
    """路径设置"""

    movie_path: Path  # 电影路径
    movie_paths: list[Path]  # 电影路径列表
    success_folder: Path  # 成功目录
    failed_folder: Path  # 失败目录
    ignore_dirs: list[Path]  # 排除目录列表
    extrafanart_folder: Path  # 剧照副本目录
    softlink_path: Path  # 软链接路径


def parse_media_paths(media_path: str | Path | None = None) -> list[Path]:
    """解析待刮削目录，支持使用英文/中文分号分隔多个目录。"""
    if media_path is None:
        media_path = manager.config.media_path
    if media_path == "":
        return [manager.data_folder]
    if isinstance(media_path, Path):
        return [media_path]

    paths: list[Path] = []
    for item in str(media_path).replace("；", ";").split(";"):
        path_text = item.strip().strip("\"'")
        if not path_text:
            continue
        path = Path(path_text)
        if path not in paths:
            paths.append(path)
    return paths or [manager.data_folder]


SEPARATE_MAIN_MODE = 2
"""分离模式的 main_mode 值：视频与元数据分开存放，其余逻辑同正常模式。"""

VIDEO_MAIN_MODE = 3
"""视频模式的 main_mode 值：只刮削并重命名视频本体，不下载图片、不生成 nfo。"""

ORGANIZE_MAIN_MODE = 6
"""整理模式的 main_mode 值：不联网刮削，读取同目录 nfo 字段后按命名规则重新整理文件。"""

READ_MAIN_MODE = 5
"""读取模式的 main_mode 值：只读取同目录 nfo 字段，不联网刮削、不移动文件。"""

SEPARATE_META_EXTS = frozenset({".nfo", ".jpg", ".jpeg", ".png", ".webp", ".strm"})
"""分离模式下归入数据存放目录的元数据文件扩展名（小写）。

含 .strm：STRM 与 nfo/封面同属元数据，放在数据存放目录才能被播放库直接扫描，
若跟随视频留在刮削目录会与「为本地视频文件生成STRM链接文本」的存放位置冲突。
"""

FILE_MOVE_OVERWRITE = "overwrite"
"""文件移动策略：目标目录已有同名文件时，用被移动文件直接覆盖目标文件。"""

FILE_MOVE_KEEP = "keep"
"""文件移动策略：目标目录已有同名文件时，保留目标文件，被移动文件留在原目录。"""


_runtime_main_mode: int | None = None
"""运行时刮削模式覆盖：仅在本次运行内生效，绝不写回配置文件。

整理模式下若扫描到的文件已全部位于「成功输出目录」内，运行时会临时把
刮削模式切成读取模式（见 `set_runtime_main_mode`），避免重复整理自己
上一次的产物；该覆盖在运行结束（或下次运行开始）时清除。
"""


def get_runtime_main_mode() -> int:
    """获取本次运行实际生效的刮削模式。

    优先返回运行时覆盖（临时切换，不落盘），没有覆盖时以配置文件为准。
    """
    if _runtime_main_mode is not None:
        return _runtime_main_mode
    return manager.config.main_mode


def set_runtime_main_mode(mode: int | None) -> None:
    """临时覆盖本次运行的刮削模式（不修改配置文件、不落盘）。

    传 None 表示取消覆盖，恢复以配置文件为准。
    """
    global _runtime_main_mode
    _runtime_main_mode = mode


def reset_runtime_main_mode() -> None:
    """清除运行时刮削模式覆盖（恢复以配置文件为准）。"""
    global _runtime_main_mode
    _runtime_main_mode = None


def is_organize_selected() -> bool:
    """用户在「软件设置」里选择的刮削模式是否为整理模式（不受运行时覆盖影响）。

    「文件是否已经在成功输出目录内、是否允许移动」这类判断必须依据用户
    的选择而非运行时的临时切换：整理模式下已在成功输出目录内的文件，
    任何情况下都不移动、不复制后删源。
    """
    return manager.config.main_mode == ORGANIZE_MAIN_MODE


def is_separate_mode() -> bool:
    """当前是否为分离模式（刮削模式 == 2）。

    分离模式下，视频刮削目录内的视频文件（移动/重命名/失败移动）走右侧
    「分离模式」开关；正常模式下全部走左侧开关（右侧开关被忽略）。
    """
    return get_runtime_main_mode() == SEPARATE_MAIN_MODE


def is_organize_mode() -> bool:
    """当前是否为整理模式（刮削模式 == 6）。

    整理模式不联网刮削、不下载图片、不生成/更新 nfo，只读取同目录 nfo
    中的字段，按「设置→命名」重新组织视频/STRM、图片、nfo 及 mediainfo。

    运行时被临时切成读取模式后，本函数返回 False（本次运行不再整理文件）。
    """
    return get_runtime_main_mode() == ORGANIZE_MAIN_MODE


def is_video_move_companions_enabled() -> bool:
    """视频模式是否启用了「移动已下载图片和文件到新目录」。

    该开关与「删除本地已下载的图片和信息文件」互斥（同一时刻只能选中一个），
    配置层已归一：两个都勾上时保留原有的 sort_del、去掉 sort_move。
    """
    return get_runtime_main_mode() == VIDEO_MAIN_MODE and Switch.SORT_MOVE in manager.config.switch_on


def get_file_move_policy() -> str:
    """文件移动冲突策略（设置 → 高级 → 移动文件）。

    返回值：
    - ``FILE_MOVE_OVERWRITE``（"overwrite"）：目标目录已有同名文件时，用被移动文件直接覆盖。
    - ``FILE_MOVE_KEEP``（"keep"）：目标目录已有同名文件时，保留目标文件，被移动文件留在原目录。
    - 空字符串：未选择任一策略，保持原有的移动行为。

    「覆盖旧文件」与「保留旧文件」互斥（同一时刻只能选中一个），配置层已归一：
    两个都勾上时保留更安全的 move_keep、去掉 move_overwrite。
    """
    switch_on = manager.config.switch_on
    if Switch.MOVE_OVERWRITE in switch_on:
        return FILE_MOVE_OVERWRITE
    if Switch.MOVE_KEEP in switch_on:
        return FILE_MOVE_KEEP
    return ""


def is_file_move_overwrite() -> bool:
    """是否启用了「覆盖旧文件」策略。"""
    return get_file_move_policy() == FILE_MOVE_OVERWRITE


def is_file_move_keep() -> bool:
    """是否启用了「保留旧文件」策略。"""
    return get_file_move_policy() == FILE_MOVE_KEEP


def should_generate_strm(meta_root: Path | None, skip_reorganize: bool) -> bool:
    """是否生成 STRM：仅分离模式 + 已勾选 + 元数据根有效 + 非跳过整理时生效。

    其他模式（正常/视频/更新/读取）下即使勾选也不生成。
    """
    return (
        meta_root is not None and not skip_reorganize and is_separate_mode() and manager.config.separate_generate_strm
    )


def should_overwrite_strm() -> bool:
    """是否覆盖已存在 STRM：仅分离模式 + 已勾选生成 STRM + 已勾选覆盖时生效。

    与 should_generate_strm 同门：未勾选「为本地视频文件生成STRM链接文本」时，
    根本不会生成 STRM，也就不存在「覆盖本地已存在的STRM链接文本」这件事，
    此时即使勾选覆盖开关也不生效（调用方不得直接读 manager.config.separate_overwrite_strm）。
    """
    return is_separate_mode() and manager.config.separate_generate_strm and manager.config.separate_overwrite_strm


def should_reuse_metadata(meta_root: Path | None) -> bool:
    """是否复用数据存放目录中的元数据文件：仅分离模式 + 元数据根有效 + 已勾选时生效。

    与 should_generate_strm 同门：非分离模式下不生效；数据存放目录无效（data_path
    为空/不可创建，元数据退回视频目录）时同样不生效 —— 没有数据存放目录就无从
    「复用其中的元数据」，此时若仍生效会误跳图片下载与 NFO 写入（调用方不得直接读
    manager.config.separate_reuse_metadata）。
    """
    return meta_root is not None and is_separate_mode() and manager.config.separate_reuse_metadata


def should_overwrite_meta(meta_root: Path | None) -> bool:
    """是否覆盖本地保存的视频元数据文件：仅分离模式 + 元数据根有效 + 已勾选时生效。

    与 should_reuse_metadata 互斥：界面层二者只许其一（勾选其一自动取消另一）；
    若配置被手改成两开，运行时以覆盖为准（调用方不得直接读配置项）。
    """
    return meta_root is not None and is_separate_mode() and manager.config.separate_overwrite_meta


def eff_success_file_move() -> bool:
    """视频文件「刮削成功后移动」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_success_file_move if is_separate_mode() else manager.config.success_file_move


def eff_failed_file_move() -> bool:
    """视频文件「失败移动文件」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_failed_file_move if is_separate_mode() else manager.config.failed_file_move


def eff_success_file_rename() -> bool:
    """视频文件「刮削成功重命名」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_success_file_rename if is_separate_mode() else manager.config.success_file_rename


def eff_del_empty_folder() -> bool:
    """数据存放目录「刮削结束删除空目录」生效值：分离模式取右侧，否则取左侧。

    注意：视频刮削目录下的空目录清理永远走左侧 del_empty_folder（见调用方显式传参），
    本函数只用于数据存放目录（meta_root）一侧。
    """
    return manager.config.separate_del_empty_folder if is_separate_mode() else manager.config.del_empty_folder


def resolve_data_dir(movie_path: Path) -> Path | None:
    """解析数据存放目录；分离模式未启用/未设置/不可用时返回 None（回退正常模式）。

    目录不存在时会自动新建（见 ensure_data_dir），新建失败则回退正常模式。
    """
    if manager.config.main_mode != SEPARATE_MAIN_MODE:
        return None
    data_path = (getattr(manager.config, "data_path", "") or "").strip()
    if not data_path:
        return None
    return ensure_data_dir(movie_path)


_data_dir_logged: set[str] = set()
"""已打过新建/回退日志的数据目录（绝对路径字符串），避免每个文件重复刷屏。"""

_admin_mkdir_attempted = False
"""进程内是否已尝试过提权建目录（只弹一次 UAC，避免每个文件都弹窗）。"""


def _separate_log(text: str) -> None:
    """分离模式日志：优先走 UI 日志通道，失败时退到标准 logging（无 Qt 的测试桩环境不炸）。"""
    try:
        from ..log_console import log_console

        log_console.log_text(text)
    except Exception:
        import logging

        logging.getLogger("mdcx.separate").warning(text)


def _elevated_mkdir(target: Path) -> bool:
    """提权新建目录：Windows 用 runas 拉起 UAC 并等待完成，POSIX 用 sudo -n（免交互，失败即放弃）。"""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class SHELLEXECUTEINFOW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]

            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
            sei.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS：拿到进程句柄以便等待完成
            sei.lpVerb = "runas"
            sei.lpFile = "cmd.exe"
            sei.lpParameters = f'/c mkdir "{target}"'
            sei.nShow = 0  # SW_HIDE
            if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
                return False
            try:
                ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 60000)
                ctypes.windll.kernel32.CloseHandle(sei.hProcess)
            except Exception:
                return False
        else:
            result = subprocess.run(["sudo", "-n", "mkdir", "-p", str(target)], timeout=60, capture_output=True)
            if result.returncode != 0:
                return False
    except Exception:
        return False
    return target.is_dir()


def ensure_data_dir(movie_path: Path) -> Path | None:
    """确保数据存放目录可用：不存在则新建；新建失败则尝试提权新建；仍失败返回 None（回退正常模式）。"""
    global _admin_mkdir_attempted
    if manager.config.main_mode != SEPARATE_MAIN_MODE:
        return None
    data_path = (getattr(manager.config, "data_path", "") or "").strip()
    if not data_path:
        return None
    data_dir = Path(data_path)
    if not data_dir.is_absolute():
        data_dir = movie_path / data_dir
    if data_dir.is_dir():
        return data_dir
    key = str(data_dir)
    if data_dir.exists():
        if key not in _data_dir_logged:
            _data_dir_logged.add(key)
            _separate_log(f"⚠️ 数据存放目录已存在但不是目录：{data_dir}，本次回退到正常模式")
        return None
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if data_dir.is_dir():
        if key not in _data_dir_logged:
            _data_dir_logged.add(key)
            _separate_log(f"📁 数据存放目录不存在，已自动新建：{data_dir}")
        return data_dir
    if not _admin_mkdir_attempted:
        _admin_mkdir_attempted = True
        _separate_log(f"⚠️ 无权限新建数据存放目录，尝试以管理员权限新建：{data_dir}")
        try:
            _elevated_mkdir(data_dir)
        except Exception:
            pass
        if data_dir.is_dir():
            if key not in _data_dir_logged:
                _data_dir_logged.add(key)
                _separate_log(f"📁 已以管理员权限新建数据存放目录：{data_dir}")
            return data_dir
    if key not in _data_dir_logged:
        _data_dir_logged.add(key)
        _separate_log(f"⚠️ 数据存放目录无法新建（管理员权限也失败）：{data_dir}，本次回退到正常模式")
    return None


def get_separate_meta_root(movie_path: Path, success_folder: Path) -> Path | None:
    """分离模式元数据根目录 = 数据目录/success_folder 名；无效时返回 None。"""
    data_dir = resolve_data_dir(movie_path)
    if data_dir is None:
        return None
    meta_root = data_dir / success_folder.name
    if meta_root == success_folder:
        return None
    return meta_root


def mirror_meta_folder(folder: Path, success_folder: Path, meta_root: Path) -> Path:
    """把视频输出目录映射为数据目录下的镜像目录；映射失败回退原目录。"""
    try:
        rel = folder.relative_to(success_folder)
    except ValueError:
        return folder
    if not rel.parts:
        return meta_root
    return meta_root / rel


def remap_meta_paths(paths: dict[str, Path | None], meta_folder: Path) -> dict[str, Path | None]:
    """保留文件名、把元数据路径换到镜像目录下（None 保持 None）。"""
    return {key: (meta_folder / path.name if path is not None else None) for key, path in paths.items()}


def _select_movie_path(movie_paths: list[Path], file_path: Path | None) -> Path:
    if not file_path:
        return movie_paths[0]
    for movie_path in movie_paths:
        if is_descendant(file_path, movie_path):
            return movie_path
    if manager.config.scrape_softlink_path:
        for movie_path in movie_paths:
            end_folder_name = movie_path.name
            softlink_path = Path(manager.config.softlink_path.replace("end_folder_name", end_folder_name))
            if not softlink_path.is_absolute():
                softlink_path = movie_path / softlink_path
            if is_descendant(file_path, softlink_path):
                return movie_path
    return movie_paths[0]


def get_movie_path_setting(
    file_path: Path | None = None, movie_path_override: str | Path | None = None
) -> MoviePathSetting:
    movie_paths = parse_media_paths(movie_path_override)  # 用户设置的扫描媒体路径
    movie_path = _select_movie_path(movie_paths, file_path)
    end_folder_name = movie_path.name
    # 用户设置的软链接输出目录
    softlink_path = Path(manager.config.softlink_path.replace("end_folder_name", end_folder_name))
    # 用户设置的成功输出目录
    success_folder = Path(manager.config.success_output_folder.replace("end_folder_name", end_folder_name))
    # 用户设置的失败输出目录
    failed_folder = Path(manager.config.failed_output_folder.replace("end_folder_name", end_folder_name))
    # 用户设置的排除目录, 转换相对路径
    ignore_dirs = []
    for f in manager.config.folders:
        p = Path(f.replace("end_folder_name", end_folder_name))
        if not p.is_absolute():
            p = movie_path / p
        ignore_dirs.append(p)
    # 用户设置的剧照副本目录
    extrafanart_folder = Path(manager.config.extrafanart_folder)

    # 转换相对路径
    if not softlink_path.is_absolute():
        softlink_path = movie_path / softlink_path
    if not success_folder.is_absolute():
        success_folder = movie_path / success_folder
    if not failed_folder.is_absolute():
        failed_folder = movie_path / failed_folder

    if file_path:
        file_path = Path(file_path)
        temp_path = movie_path
        if manager.config.scrape_softlink_path:
            temp_path = softlink_path
        if "first_folder_name" in success_folder.as_posix() or "first_folder_name" in failed_folder.as_posix():
            try:
                first_folder_parts = file_path.relative_to(temp_path).parts
            except ValueError:
                first_folder_parts = ()
            first_folder_name = first_folder_parts[0] if first_folder_parts else ""
            success_folder = Path(success_folder.as_posix().replace("first_folder_name", first_folder_name))
            failed_folder = Path(failed_folder.as_posix().replace("first_folder_name", first_folder_name))

    # 分离模式：数据目录落在扫描树内时，把元数据镜像根目录加入排除，避免二次扫描
    meta_root = get_separate_meta_root(movie_path, success_folder)
    if meta_root is not None and meta_root not in ignore_dirs and is_descendant(meta_root, movie_path):
        ignore_dirs.append(meta_root)

    return MoviePathSetting(
        movie_path=movie_path,
        movie_paths=movie_paths,
        success_folder=success_folder,
        failed_folder=failed_folder,
        ignore_dirs=ignore_dirs,
        extrafanart_folder=extrafanart_folder,
        softlink_path=softlink_path,
    )


def _path_key(path: Path) -> str:
    """归一化路径用于比较：解析成绝对路径并统一大小写（Windows 不区分大小写）。"""
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    return os.path.normcase(str(resolved))


def drop_ignore_dir(ignore_dirs: list[Path], target: Path | None) -> list[Path]:
    """从排除目录列表中移除指定目录（比较时忽略大小写与路径分隔符差异）。

    整理模式专用：整理结果写入「成功输出目录」（默认 JAV_output），而该目录默认
    也在「排除目录」列表里。扫描时若不把它摘掉，整棵成功输出目录会被跳过，整理
    模式就看不到自己上一次的产物，于是再次点「开始」只会得到「共 0 个文件」。
    """
    if target is None:
        return list(ignore_dirs)
    key = _path_key(target)
    return [item for item in ignore_dirs if _path_key(item) != key]


def get_success_output_name(success_output_folder: str | None = None) -> str:
    """取「成功输出目录」配置的目录名（默认 JAV_output）。

    配置可以是相对名（`JAV_output`）、多段相对路径（`output/JAV_output`）
    或绝对路径，这里统一取最后一段目录名用于目录名比对。
    """
    if success_output_folder is None:
        success_output_folder = manager.config.success_output_folder
    raw = str(success_output_folder or "").replace("\\", "/").strip("/")
    return raw.rsplit("/", 1)[-1].strip()


def is_success_output_tree(path: Path | str, success_output_folder: str | None = None) -> bool:
    """判断目录是否落在「成功输出目录」树内（目录本身就是成功输出目录，或是它的子目录）。

    「成功输出目录」通常配置为相对名（默认 `JAV_output`），相对待刮削目录解析。
    用户若直接把成功输出目录（或它的子目录）当成待刮削目录来跑，目标目录会被
    算成 `<选中目录>/JAV_output` 这种套娃路径，整理没有意义，应当按读取模式处理。

    判定方式：从目录自身开始逐级向上，任何一级目录名与成功输出目录名一致，
    即说明该目录落在成功输出目录树内。
    """
    name = get_success_output_name(success_output_folder)
    if not name:
        return False
    try:
        parts = Path(path).parts
    except TypeError, ValueError:
        return False
    target = name.casefold()
    return any(part.casefold() == target for part in parts)


def is_in_success_folder(file_path: Path | str, success_folder: Path | str | None) -> bool:
    """判断文件是否已经位于「成功输出目录」之内。

    整理模式专用：已经躺在成功输出目录里的文件就是上一轮整理的产物，再整理一遍
    只会原地搬动自己（无谓的移动/复制，且网盘目录缓存未刷新时容易报错），
    故这类文件直接按「读取模式」处理：只读 nfo 展示结果，不做任何移动/复制/重命名。
    """
    if success_folder is None:
        return False
    try:
        return is_descendant(file_path, success_folder)
    except OSError, ValueError:
        return False


def organize_netdisk_rest_enabled() -> bool:
    """整理模式是否启用「网盘按照自动休息间隔整理文件」。

    只有整理模式 + 勾选「网盘按照自动休息间隔」+ 未勾「本地存储不设置时间间隔」
    时才生效（两枚复选框互斥，配置层已归一，这里再兜一层防手改配置）。
    """
    if not is_organize_mode():
        return False
    if manager.config.organize_local_no_interval:
        return False
    return bool(manager.config.organize_netdisk_rest_interval)


def organize_rest_seconds() -> int:
    """整理模式两次运行之间必须间隔的秒数（取「高级 → 间歇刮削 → 自动休息」）。

    下限 40s：网盘目录缓存刷新有延迟，间隔太短整理会因目录缓存未刷新而报错
    （见 `models.MIN_REST_TIME_SECONDS`）。
    """
    from .models import MIN_REST_TIME_SECONDS

    seconds = int(manager.config.rest_time.total_seconds())
    return max(seconds, MIN_REST_TIME_SECONDS)


def need_clean(file_path: Path, file_name: str, file_ext: str) -> bool:
    # 判断文件是否需清理
    if not manager.computed.can_clean:
        return False

    # 不清理的扩展名
    if CleanAction.CLEAN_IGNORE_EXT in manager.config.clean_enable and file_ext in manager.config.clean_ignore_ext:
        return False

    # 不清理的文件名包含
    if CleanAction.CLEAN_IGNORE_CONTAINS in manager.config.clean_enable:
        for each in manager.config.clean_ignore_contains:
            if each in file_name:
                return False

    # 清理的扩展名
    if CleanAction.CLEAN_EXT in manager.config.clean_enable and file_ext in manager.config.clean_ext:
        return True

    # 清理的文件名等于
    if CleanAction.CLEAN_NAME in manager.config.clean_enable and file_name in manager.config.clean_name:
        return True

    # 清理的文件名包含
    if CleanAction.CLEAN_CONTAINS in manager.config.clean_enable:
        for each in manager.config.clean_contains:
            if each in file_name:
                return True

    # 清理的文件大小<=(KB)
    if CleanAction.CLEAN_SIZE in manager.config.clean_enable:
        try:  # 路径太长时，此处会报错 FileNotFoundError: [WinError 3] 系统找不到指定的路径。
            return file_path.stat().st_size <= manager.config.clean_size * 1024
        except Exception:
            pass
    return False


def deal_url(url: str) -> tuple[str | None, str]:
    # 先 strip 再补 scheme，避免带首尾空格的 URL 补成 "https:// example.com"（中间含空格失效）
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    for key, site in ManualConfig.WEB_DIC.items():
        if key.lower() in url.lower():
            return site.value, url

    # 自定义的网址
    for site in Website:
        if (r := manager.config.site_configs.get(site)) and r.custom_url:
            if str(r.custom_url) in url:
                return site.value, url

    return None, url
