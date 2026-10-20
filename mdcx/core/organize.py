import asyncio
import os
import time
from pathlib import Path

import aiofiles.os

from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..utils.file import elevated_move_file, move_file_async

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_ORGANIZE_BACKUP_MARK = ".mdcx_organize_backup_"


def _walk_files(folder: Path) -> list[tuple[str, list[str], list[str]]]:
    """在线程中遍历目录，显式标注类型以便 mypy 检查。"""
    return list(os.walk(folder))


class OrganizePlanError(Exception):
    """整理计划无法安全执行（例如多个源文件映射到同一个目标）。"""


class OrganizeTransaction:
    """整理模式的移动事务：任一文件失败则把已移动文件全部退回原位置。"""

    def __init__(self) -> None:
        self._ops: list[tuple[str, Path, Path]] = []

    async def _exists(self, path: Path) -> bool:
        return await aiofiles.os.path.exists(path) or await aiofiles.os.path.islink(path)

    async def _ensure_parent(self, dst: Path) -> bool:
        if await aiofiles.os.path.isdir(dst.parent):
            return True
        try:
            await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    async def _move_once(self, src: Path, dst: Path) -> tuple[bool, str]:
        """普通移动失败后，使用管理员权限重试一次。"""
        if not await self._ensure_parent(dst):
            return False, f"无法创建目标目录: {dst.parent}"
        result, error = await move_file_async(src, dst, overwrite=True)
        if result and await self._exists(dst) and not await self._exists(src):
            return True, ""
        elevated_ok, elevated_error = await elevated_move_file(src, dst)
        if elevated_ok:
            return True, ""
        return False, f"普通移动失败: {error or '未完成'}; 管理员重试失败: {elevated_error}"

    async def move_file(self, src: str | Path, dst: str | Path) -> tuple[bool, str]:
        src = Path(src)
        dst = Path(dst)
        if src == dst:
            return True, ""
        src_exists = await self._exists(src)
        dst_exists = await self._exists(dst)
        if not src_exists:
            return (True, "") if dst_exists else (False, f"源文件不存在: {src}")
        if dst_exists:
            same = False
            try:
                same = await asyncio.to_thread(os.path.samefile, src, dst)
            except OSError:
                pass
            if same:
                return True, ""
            # 保留目标位置已有文件，失败回滚时恢复；成功后保留为备份文件，避免数据丢失。
            backup = dst.with_name(f"{dst.stem}{_ORGANIZE_BACKUP_MARK}{time.time_ns()}{dst.suffix}")
            backup_ok, backup_error = await self._move_once(dst, backup)
            if not backup_ok:
                return False, f"无法备份目标文件: {dst}; {backup_error}"
            self._ops.append(("backup", backup, dst))
        move_ok, move_error = await self._move_once(src, dst)
        if not move_ok:
            return False, move_error
        self._ops.append(("move", src, dst))
        return True, ""

    async def rollback(self) -> bool:
        """逆序撤销全部已执行操作，确保文件回到整理前的位置。"""
        success = True
        for kind, first, second in reversed(self._ops):
            if kind == "move":
                src, dst = second, first
            else:
                src, dst = first, second
            if not await self._exists(src):
                if await self._exists(dst):
                    continue
                success = False
                LogBuffer.error().write(f"整理回滚失败：找不到待恢复文件 {src}")
                continue
            if await self._exists(dst):
                # 目标已存在时不再覆盖，避免回滚造成二次数据丢失。
                LogBuffer.error().write(f"整理回滚跳过：目标已存在 {dst}")
                success = False
                continue
            ok, error = await self._move_once(src, dst)
            if not ok:
                success = False
                LogBuffer.error().write(f"整理回滚失败：{src} -> {dst}; {error}")
        self._ops.clear()
        return success

    def commit(self) -> None:
        self._ops.clear()


def _add_plan(
    plan: list[tuple[Path, Path]],
    seen_sources: set[Path],
    destinations: dict[Path, Path],
    src: Path,
    dst: Path,
) -> None:
    if src == dst or src in seen_sources:
        return
    if not (src.exists() or src.is_symlink()):
        return
    previous = destinations.get(dst)
    if previous is not None and previous != src:
        raise OrganizePlanError(f"多个文件映射到同一个目标: {dst}")
    seen_sources.add(src)
    destinations[dst] = src
    plan.append((src, dst))


async def _build_plan(
    *,
    file_path: Path,
    file_new_path: Path,
    folder_old_path: Path,
    folder_new_path: Path,
    nfo_new_path: Path,
    naming_rule: str,
    file_name: str,
    number: str,
    sub_list: list[str],
    poster_final_path: Path,
    thumb_final_path: Path,
    fanart_final_path: Path,
) -> list[tuple[Path, Path]]:
    """生成整理计划：只包含真实存在、且目标位置不同的文件。"""
    plan: list[tuple[Path, Path]] = []
    seen_sources: set[Path] = set()
    destinations: dict[Path, Path] = {}

    def add(src: Path, dst: Path) -> None:
        _add_plan(plan, seen_sources, destinations, src, dst)

    try:
        entries = await asyncio.to_thread(lambda: list(folder_old_path.iterdir()))
    except OSError:
        entries = []

    # nfo
    add(file_path.with_suffix(".nfo"), nfo_new_path)

    # 图片：同名前缀优先，其次 poster.jpg / thumb.jpg / fanart.jpg。
    for kind, final_path in (
        ("poster", poster_final_path),
        ("thumb", thumb_final_path),
        ("fanart", fanart_final_path),
    ):
        candidates = [
            entry
            for entry in entries
            if entry.is_file()
            and entry.suffix.lower() in _IMAGE_SUFFIXES
            and entry.stem.lower() in {f"{file_name}-{kind}".lower(), kind.lower()}
        ]
        candidates.sort(
            key=lambda path: (
                not path.stem.lower().startswith(file_name.lower()),
                path.suffix.lower() != ".jpg",
                path.name.lower(),
            )
        )
        if candidates:
            add(candidates[0], final_path)

    # json（含 -mediainfo.json）
    for entry in entries:
        if not entry.is_file() or entry.suffix.lower() != ".json":
            continue
        lower_name = entry.name.lower()
        stem = file_name.lower()
        if lower_name == f"{stem}.json":
            add(entry, folder_new_path / f"{naming_rule}.json")
        elif lower_name.startswith(stem + "-") or lower_name.startswith(stem + "."):
            add(entry, folder_new_path / f"{naming_rule}{entry.name[len(file_name) :]}")
    if number and number.lower() != file_name.lower():
        add(
            folder_old_path / f"{number}-mediainfo.json",
            folder_new_path / f"{naming_rule}-mediainfo.json",
        )

    # 字幕：sub_list 与目录扫描双保险。
    sub_types = [str(item).lower() for item in manager.config.sub_type]

    def sub_destination(suffix: str) -> Path:
        if manager.config.subtitle_add_chs and ".chs" not in suffix.lower():
            suffix = ".chs" + suffix
        return folder_new_path / f"{naming_rule}{suffix}"

    for sub in sub_list:
        add(folder_old_path / (file_name + sub), sub_destination(sub))
    for entry in entries:
        if not entry.is_file() or not entry.name.lower().startswith(file_name.lower()):
            continue
        if entry.suffix.lower() not in sub_types:
            continue
        suffix = entry.name[len(file_name) :]
        add(entry, sub_destination(suffix))

    # 种子、bif。
    add(folder_old_path / f"{file_name}.torrent", folder_new_path / f"{naming_rule}.torrent")
    if number:
        add(folder_old_path / f"{number}.torrent", folder_new_path / f"{number}.torrent")
    add(
        folder_old_path / f"{file_name}-320-10.bif",
        folder_new_path / f"{naming_rule}-320-10.bif",
    )

    # 单文件预告片。
    for entry in entries:
        if (
            entry.is_file()
            and entry.stem.lower() == f"{file_name}-trailer".lower()
            and entry.suffix.lower() in {str(item).lower() for item in manager.config.media_type}
        ):
            if manager.config.trailer_simple_name:
                dst = folder_new_path / "trailers" / f"trailer{entry.suffix}"
            else:
                dst = folder_new_path / f"{naming_rule}-trailer{entry.suffix}"
            add(entry, dst)

    # 剧照、背景图等文件夹，保持相对目录结构。
    folder_names = ["extrafanart", manager.config.extrafanart_folder, "backdrops", "behind the scenes", "trailers"]
    handled_folders: set[str] = set()
    for folder_name in folder_names:
        if not folder_name or folder_name.lower() in handled_folders:
            continue
        handled_folders.add(folder_name.lower())
        source_folder = folder_old_path / folder_name
        if not await aiofiles.os.path.isdir(source_folder):
            continue
        for root, _, files in await asyncio.to_thread(_walk_files, source_folder):
            root_path = Path(root)
            for name in files:
                source = root_path / name
                relative = source.relative_to(source_folder)
                add(source, folder_new_path / folder_name / relative)

    # 其余与文件同名的伴生文件。
    media_suffixes = {str(item).lower() for item in manager.config.media_type} | {".strm"}
    for entry in entries:
        if not entry.is_file():
            continue
        if entry in seen_sources or entry.name.lower().startswith(file_name.lower()) is False:
            continue
        if entry.suffix.lower() in media_suffixes | {".nfo", ".json"}:
            continue
        if "-cd" in entry.stem.lower() or _ORGANIZE_BACKUP_MARK in entry.name:
            continue
        suffix = entry.name[len(file_name) :]
        add(entry, folder_new_path / f"{naming_rule}{suffix}")

    # 视频/STRM 最后移动，其余资源全部落位后再移动主体文件。
    add(file_path, file_new_path)
    return plan


async def organize_files(
    *,
    file_path: Path,
    file_new_path: Path,
    folder_old_path: Path,
    folder_new_path: Path,
    nfo_new_path: Path,
    naming_rule: str,
    file_name: str,
    number: str,
    sub_list: list[str],
    poster_final_path: Path,
    thumb_final_path: Path,
    fanart_final_path: Path,
) -> tuple[bool, str]:
    """按命名规则原子地整理视频/STRM 及其全部伴生文件。

    返回 ``(成功, 错误信息)``。失败时会回滚已移动文件，源文件保持在原目录。
    """
    try:
        plan = await _build_plan(
            file_path=file_path,
            file_new_path=file_new_path,
            folder_old_path=folder_old_path,
            folder_new_path=folder_new_path,
            nfo_new_path=nfo_new_path,
            naming_rule=naming_rule,
            file_name=file_name,
            number=number,
            sub_list=sub_list,
            poster_final_path=poster_final_path,
            thumb_final_path=thumb_final_path,
            fanart_final_path=fanart_final_path,
        )
    except OrganizePlanError as e:
        LogBuffer.error().write(f"整理失败：{e}")
        return False, str(e)

    if not plan:
        return True, ""

    transaction = OrganizeTransaction()
    for src, dst in plan:
        ok, error = await transaction.move_file(src, dst)
        if not ok:
            await transaction.rollback()
            message = f"整理失败，已回滚到原目录：{src} -> {dst}; {error}"
            LogBuffer.error().write(message)
            return False, message

    missing = [dst for _, dst in plan if not await aiofiles.os.path.exists(dst)]
    if missing:
        await transaction.rollback()
        message = f"整理失败，目标文件缺失，已回滚到原目录：{missing[0]}"
        LogBuffer.error().write(message)
        return False, message

    transaction.commit()
    LogBuffer.log().write(f"\n 🍀 Organize done: {file_path} -> {file_new_path}")
    return True, ""
