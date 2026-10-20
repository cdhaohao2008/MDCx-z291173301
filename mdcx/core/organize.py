import asyncio
import os
import time
import unicodedata
from pathlib import Path

import aiofiles.os

from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..utils.file import copy_then_delete_file, elevated_move_file, move_file_async

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_ORGANIZE_BACKUP_MARK = ".mdcx_organize_backup_"


def _walk_files(folder: Path) -> list[tuple[str, list[str], list[str]]]:
    """在线程中遍历目录，显式标注类型以便 mypy 检查。"""
    return list(os.walk(folder))


def _name_key(name: str) -> str:
    """网络盘/WebDAV 可能区分大小写，统一用归一化名称匹配。"""
    return unicodedata.normalize("NFC", name).casefold()


def _list_entries(folder: Path) -> list[Path]:
    return list(folder.iterdir())


def _safe_is_file(path: Path) -> bool:
    """网络盘上的 stat 可能失败，失败时不让单个文件中断整个整理计划。"""
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_trailer_stem(stem: str) -> bool:
    key = _name_key(stem)
    return key.endswith("-trailer") or "-trailer-" in key


def _is_backup_name(name: str) -> bool:
    """上次整理中断留下的目标备份不应再次参与整理。"""
    return _ORGANIZE_BACKUP_MARK in name


class OrganizePlanError(Exception):
    """整理计划无法安全执行（例如多个源文件映射到同一个目标）。"""


class OrganizeTransaction:
    """整理模式的移动事务：任一文件失败则把已移动文件全部退回原位置。"""

    def __init__(self) -> None:
        self._ops: list[tuple[str, Path, Path]] = []

    async def _exists(self, path: Path) -> bool:
        try:
            return await aiofiles.os.path.exists(path) or await aiofiles.os.path.islink(path)
        except OSError:
            return False

    async def _ensure_parent(self, dst: Path) -> bool:
        try:
            if await aiofiles.os.path.isdir(dst.parent):
                return True
        except OSError:
            pass
        try:
            await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    async def _move_once(self, src: Path, dst: Path) -> tuple[bool, str]:
        """普通移动失败后，先管理员重试一次，再用复制+删除兜底网络盘。"""
        if not await self._ensure_parent(dst):
            return False, f"无法创建目标目录: {dst.parent}"
        result, error = await move_file_async(src, dst, overwrite=True)
        if result and await self._exists(dst) and not await self._exists(src):
            return True, ""
        elevated_ok, elevated_error = await elevated_move_file(src, dst)
        if elevated_ok:
            return True, ""
        # WebDAV / 部分网盘映射盘不支持 rename；复制成功后再删除源文件。
        copy_ok, copy_error = await copy_then_delete_file(src, dst)
        if copy_ok:
            return True, ""
        return False, (
            f"普通移动失败: {error or '未完成'}; 管理员重试失败: {elevated_error}; 复制后删除失败: {copy_error}"
        )

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
            try:
                dst_is_dir = await aiofiles.os.path.isdir(dst)
            except OSError:
                dst_is_dir = False
            if dst_is_dir:
                return False, f"目标位置已存在同名目录: {dst}"
            same = False
            try:
                same = await asyncio.to_thread(os.path.samefile, src, dst)
            except OSError:
                pass
            if same:
                return True, ""
            # 保留目标位置已有文件，失败回滚时恢复；成功后删除备份。
            backup = dst.with_name(f"{dst.stem}{_ORGANIZE_BACKUP_MARK}{time.time_ns()}{dst.suffix}")
            backup_ok, backup_error = await self._move_once(dst, backup)
            if not backup_ok:
                return False, f"无法备份目标文件: {dst}; {backup_error}"
            self._ops.append(("backup", backup, dst))
        move_ok, move_error = await self._move_once(src, dst)
        if not move_ok:
            # 某些网络盘会在失败时留下半成品；先删掉，回滚时才能恢复被备份的目标。
            if await self._exists(dst):
                if await self._exists(src):
                    try:
                        await asyncio.to_thread(dst.unlink, missing_ok=True)
                    except OSError:
                        pass
                else:
                    self._ops.append(("move", src, dst))
                    return True, ""
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
            try:
                ok, error = await self._move_once(src, dst)
            except Exception as e:
                ok, error = False, str(e)
            if not ok:
                success = False
                LogBuffer.error().write(f"整理回滚失败：{src} -> {dst}; {error}")
        self._ops.clear()
        return success

    async def commit(self) -> None:
        """提交事务：删除被覆盖目标留下的备份文件。"""
        for kind, backup, _ in self._ops:
            if kind != "backup":
                continue
            try:
                await asyncio.to_thread(backup.unlink, missing_ok=True)
            except Exception as e:
                LogBuffer.error().write(f"整理完成，但清理旧目标文件失败：{backup}; {e}")
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
    try:
        if not (src.exists() or src.is_symlink()):
            return
    except OSError:
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
    number: str,
    sub_list: list[str],
    poster_final_path: Path,
    thumb_final_path: Path,
    fanart_final_path: Path,
) -> list[tuple[Path, Path]]:
    """生成整理计划：只包含当前番号真实存在的关联文件。"""
    plan: list[tuple[Path, Path]] = []
    seen_sources: set[Path] = set()
    destinations: dict[Path, Path] = {}

    def add(src: Path, dst: Path) -> None:
        _add_plan(plan, seen_sources, destinations, src, dst)

    def add_variant(src: Path, preferred: Path) -> None:
        """同名目标已被占用时，保留第二个文件的原始名称或追加序号。"""
        if src in seen_sources:
            return
        dst = preferred
        index = 2
        while dst in destinations:
            dst = preferred.with_name(f"{preferred.stem}-{index}{preferred.suffix}")
            index += 1
        add(src, dst)

    try:
        entries = await asyncio.to_thread(_list_entries, folder_old_path)
    except OSError:
        entries = []
    entry_by_name = {_name_key(entry.name): entry for entry in entries}

    def find(name: str) -> Path | None:
        return entry_by_name.get(_name_key(name))

    def media_suffixes() -> set[str]:
        result: set[str] = {".strm"}
        for item in manager.config.media_type:
            suffix = str(item).lower().strip()
            result.add(suffix if suffix.startswith(".") else f".{suffix}")
        return result

    def is_media_entry(entry: Path) -> bool:
        return (
            _safe_is_file(entry)
            and entry.suffix.lower() in media_types
            and not _is_trailer_stem(entry.stem)
            and not _is_backup_name(entry.name)
        )

    source_name = file_path.stem
    current_key = _name_key(source_name)
    media_types = media_suffixes()
    current_aliases = {current_key}
    if number:
        current_aliases.add(_name_key(number))

    # 同目录还有其它视频时，不能把 poster.jpg / extrafanart 等公共文件当成当前番号独有。
    other_media_stems = {
        _name_key(entry.stem)
        for entry in entries
        if is_media_entry(entry) and _name_key(entry.stem) not in current_aliases
    }
    folder_has_other_media = bool(other_media_stems)

    def matches_stem(name_key: str, stem_key: str) -> bool:
        if not stem_key:
            return False
        if name_key == stem_key:
            return True
        return name_key.startswith(stem_key) and len(name_key) > len(stem_key) and name_key[len(stem_key)] in "-_. "

    def owner_is_current(name: str) -> bool:
        """按最长文件名匹配归属，避免 ABS-040 误移 ABS-040-1 的文件。"""
        name_key = _name_key(name)
        best = ""
        for stem_key in current_aliases | other_media_stems:
            if matches_stem(name_key, stem_key) and len(stem_key) > len(best):
                best = stem_key
        return bool(best) and best in current_aliases

    def companion_suffix(name: str) -> str:
        # 使用 NFC 归一化后的长度切分，避免 NFD 文件名长度变化导致后缀被截断。
        normalized_name = unicodedata.normalize("NFC", name)
        name_key = _name_key(normalized_name)
        for stem in sorted((source_name, number), key=len, reverse=True):
            if not stem:
                continue
            normalized_stem = unicodedata.normalize("NFC", stem)
            stem_key = _name_key(normalized_stem)
            if name_key.startswith(stem_key) and len(normalized_name) >= len(normalized_stem):
                return normalized_name[len(normalized_stem) :]
        return ""

    # nfo（网络盘可能大小写敏感，按目录实际文件名查找）
    nfo_source = find(f"{source_name}.nfo")
    if nfo_source is not None:
        add(nfo_source, nfo_new_path)

    # 图片：先确定 poster/thumb/fanart 的主文件，其余同番号图片一并移动。
    image_entries = [
        entry
        for entry in entries
        if _safe_is_file(entry) and entry.suffix.lower() in _IMAGE_SUFFIXES and not _is_backup_name(entry.name)
    ]
    for kind, final_path in (
        ("poster", poster_final_path),
        ("thumb", thumb_final_path),
        ("fanart", fanart_final_path),
    ):
        candidate_stems = {f"{source_name}-{kind}", kind}
        if number:
            candidate_stems.add(f"{number}-{kind}")
        candidates = [
            entry for entry in image_entries if entry.stem.lower() in {stem.lower() for stem in candidate_stems}
        ]
        if folder_has_other_media:
            # 多番号共用目录时，只认带当前文件名的图片，避免误移其它番号的 poster.jpg。
            candidates = [entry for entry in candidates if owner_is_current(entry.name)]
        if not candidates:
            continue
        candidates.sort(
            key=lambda path: (
                _name_key(path.name) != _name_key(final_path.name),
                not owner_is_current(path.name),
                path.suffix.lower() != ".jpg",
                path.name.lower(),
            )
        )
        add(candidates[0], final_path)
        for extra in candidates[1:]:
            add_variant(extra, folder_new_path / extra.name)

    for entry in image_entries:
        if entry in seen_sources:
            continue
        if folder_has_other_media and not owner_is_current(entry.name):
            continue
        add_variant(entry, folder_new_path / entry.name)

    # json（含 -mediainfo.json），按大小写不敏感匹配。
    for entry in entries:
        if not _safe_is_file(entry) or entry.suffix.lower() != ".json" or _is_backup_name(entry.name):
            continue
        if not owner_is_current(entry.name):
            continue
        suffix = companion_suffix(entry.name)
        if suffix:
            add(entry, folder_new_path / f"{naming_rule}{suffix}")

    # 字幕：sub_list 与目录扫描双保险。
    sub_types = [str(item).lower() for item in manager.config.sub_type]

    def sub_destination(suffix: str) -> Path:
        if manager.config.subtitle_add_chs and ".chs" not in suffix.lower():
            suffix = ".chs" + suffix
        return folder_new_path / f"{naming_rule}{suffix}"

    for sub in sub_list:
        if not sub:
            continue
        sub_source = find(source_name + sub)
        if sub_source is not None:
            add(sub_source, sub_destination(sub))
    for entry in entries:
        if not _safe_is_file(entry) or not owner_is_current(entry.name) or _is_backup_name(entry.name):
            continue
        if entry.suffix.lower() not in sub_types:
            continue
        suffix = companion_suffix(entry.name)
        if suffix:
            add(entry, sub_destination(suffix))

    # 种子、bif。
    torrent_source = find(f"{source_name}.torrent")
    if torrent_source is not None:
        add(torrent_source, folder_new_path / f"{naming_rule}.torrent")
    if number:
        number_torrent = find(f"{number}.torrent")
        if number_torrent is not None:
            add(number_torrent, folder_new_path / f"{number}.torrent")
    bif_source = find(f"{source_name}-320-10.bif")
    if bif_source is not None:
        add(bif_source, folder_new_path / f"{naming_rule}-320-10.bif")

    # 单文件预告片。
    for entry in entries:
        if (
            _safe_is_file(entry)
            and entry.stem.lower() == f"{source_name}-trailer".lower()
            and entry.suffix.lower() in media_types
            and not _is_backup_name(entry.name)
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
        if not folder_name:
            continue
        folder_key = _name_key(str(folder_name))
        if folder_key in handled_folders:
            continue
        handled_folders.add(folder_key)
        source_folder = find(str(folder_name))
        if source_folder is None or not _safe_is_dir(source_folder):
            source_folder = folder_old_path / str(folder_name)
        if not _safe_is_dir(source_folder):
            continue
        try:
            walked_files = await asyncio.to_thread(_walk_files, source_folder)
        except OSError:
            continue
        for root, _, files in walked_files:
            root_path = Path(root)
            for name in files:
                # 共用目录中只移动文件名带当前番号/文件名的剧照，避免动到其它番号。
                if folder_has_other_media and not owner_is_current(name):
                    continue
                if _is_backup_name(name):
                    continue
                source = root_path / name
                relative = source.relative_to(source_folder)
                add(source, folder_new_path / str(folder_name) / relative)

    # 其余与文件同名的伴生文件（不含媒体、nfo、json，它们已单独处理）。
    handled_suffixes = media_types | {".nfo", ".json"} | set(sub_types) | _IMAGE_SUFFIXES
    for entry in entries:
        if not _safe_is_file(entry) or entry in seen_sources or not owner_is_current(entry.name):
            continue
        suffix = companion_suffix(entry.name)
        suffix_lower = suffix.lower()
        if not suffix or suffix_lower in handled_suffixes:
            continue
        if "-cd" in entry.stem.lower() or _is_backup_name(entry.name):
            continue
        add_variant(entry, folder_new_path / f"{naming_rule}{suffix}")

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
    number: str,
    sub_list: list[str],
    poster_final_path: Path,
    thumb_final_path: Path,
    fanart_final_path: Path,
) -> tuple[bool, str]:
    """按命名规则原子地整理当前番号的视频/STRM 及其全部伴生文件。

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
            number=number,
            sub_list=sub_list,
            poster_final_path=poster_final_path,
            thumb_final_path=thumb_final_path,
            fanart_final_path=fanart_final_path,
        )
    except OrganizePlanError as e:
        LogBuffer.error().write(f"整理失败：{e}")
        return False, str(e)
    except Exception as e:
        LogBuffer.error().write(f"整理失败：生成整理计划时出错：{e}")
        return False, str(e)

    if not plan:
        return True, ""

    transaction = OrganizeTransaction()
    try:
        for src, dst in plan:
            ok, error = await transaction.move_file(src, dst)
            if not ok:
                await transaction.rollback()
                message = f"整理失败，已回滚到原目录：{src} -> {dst}; {error}"
                LogBuffer.error().write(message)
                return False, message
    except Exception as e:
        await transaction.rollback()
        message = f"整理失败，已回滚到原目录：{e}"
        LogBuffer.error().write(message)
        return False, message

    try:
        missing = [dst for _, dst in plan if not await aiofiles.os.path.exists(dst)]
    except OSError as e:
        await transaction.rollback()
        message = f"整理失败，无法确认目标文件，已回滚到原目录：{e}"
        LogBuffer.error().write(message)
        return False, message
    if missing:
        await transaction.rollback()
        message = f"整理失败，目标文件缺失，已回滚到原目录：{missing[0]}"
        LogBuffer.error().write(message)
        return False, message

    await transaction.commit()
    LogBuffer.log().write(f"\n 🍀 Organize done: {file_path} -> {file_new_path}")
    return True, ""
