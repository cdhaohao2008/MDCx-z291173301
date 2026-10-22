import asyncio
import os
import time
import unicodedata
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import aiofiles.os

from ..config.extend import FILE_MOVE_KEEP, FILE_MOVE_OVERWRITE, get_file_move_policy, is_in_success_folder
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..number import get_file_number
from ..utils.file import elevated_move_file, move_file_async
from ..utils.picture import IMAGE_SUFFIXES, image_path_with_suffix

_ORGANIZE_BACKUP_MARK = ".mdcx_organize_backup_"
_ASSET_FOLDER_NAMES = ("extrafanart", "backdrops", "behind the scenes", "trailers")
# 剧照类目录名关键词：容忍 extarfanart、extrafanart_copy 等非标准写法
_ASSET_NAME_HINTS = ("fanart", "backdrop", "scene", "trailer")


def _name_key(name: str) -> str:
    """网络盘/WebDAV 可能区分大小写，统一用归一化名称匹配。"""
    return unicodedata.normalize("NFC", name).casefold()


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


async def _exists_settled(path: Path, attempts: int = 4) -> bool:
    """确认目标存在；网络盘瞬时返回 False 时短暂重试，避免成功后误回滚。"""
    for attempt in range(attempts):
        try:
            if await aiofiles.os.path.exists(path):
                return True
        except OSError:
            pass
        if attempt + 1 < attempts:
            await asyncio.sleep(0.05 * (attempt + 1))
    return False


def _is_trailer_stem(stem: str) -> bool:
    key = _name_key(stem)
    return key.endswith("-trailer") or "-trailer-" in key


def _is_backup_name(name: str) -> bool:
    """上次整理中断留下的目标备份不应再次参与整理。"""
    return _ORGANIZE_BACKUP_MARK in name


def _configured_media_suffixes() -> set[str]:
    result: set[str] = {".strm"}
    for item in manager.config.media_type:
        suffix = str(item).lower().strip()
        if suffix:
            result.add(suffix if suffix.startswith(".") else f".{suffix}")
    return result


def _configured_asset_folder_keys() -> set[str]:
    """整理时会整体搬走的伴生目录（名称按大小写不敏感比较）。"""
    names = [*_ASSET_FOLDER_NAMES, manager.config.extrafanart_folder]
    return {_name_key(str(name)) for name in names if name}


def _looks_like_asset_folder(name: str, known_keys: set[str] | None = None) -> bool:
    """判断目录名是否属于剧照类目录。

    除了配置里的标准名，还按关键词识别，容忍 extarfanart、extrafanart_copy
    这类非标准写法——否则剧照目录会整体漏搬。
    """
    key = _name_key(str(name))
    if not key:
        return False
    if known_keys is None:
        known_keys = _configured_asset_folder_keys()
    if key in known_keys:
        return True
    return any(hint in key for hint in _ASSET_NAME_HINTS)


# 非标准剧照目录名归一化目标：extarfanart（错别字）→ extrafanart
_ASSET_CANONICAL_NAMES = (
    ("fanart", "extrafanart"),
    ("backdrop", "backdrops"),
    ("scene", "behind the scenes"),
    ("trailer", "trailers"),
)


def _canonical_asset_folder_name(name: str) -> str:
    """把剧照目录的非标准写法归一到标准目录名。

    已经是标准名（或配置里自定义的名，如 extrafanart_copy）的原样保留；
    像 extarfanart 这种错别字按关键词归一到 extrafanart，搬走时目录名一并改对。
    """
    raw = str(name)
    key = _name_key(raw)
    if not key:
        return raw
    if key in _configured_asset_folder_keys():
        return raw
    for hint, canonical in _ASSET_CANONICAL_NAMES:
        if hint not in key:
            continue
        if key.endswith("_copy"):
            return f"{canonical}_copy"
        return canonical
    return raw


def _matches_alias(name_key: str, alias_key: str) -> bool:
    """文件名等于番号，或以番号加分隔符开头。"""
    if not alias_key:
        return False
    if name_key == alias_key:
        return True
    return name_key.startswith(alias_key) and len(name_key) > len(alias_key) and name_key[len(alias_key)] in "-_. "


def _extract_media_number(path: Path) -> str:
    """用与 get_file_info_v2 相同的预处理从媒体文件名提取番号。"""
    raw = str(path).replace("\\", "/")
    prevent_char = str(manager.config.prevent_char or "")
    if prevent_char:
        raw = raw.replace(prevent_char, "")
    try:
        return str(get_file_number(raw, manager.computed.escape_string_list) or "").strip()
    except Exception:
        return ""


@dataclass(slots=True)
class _OrganizeMedia:
    path: Path
    folder: Path
    stem: str
    stem_key: str
    number: str
    number_key: str
    aliases: tuple[str, ...]


@dataclass(slots=True)
class _OrganizeEntry:
    path: Path
    folder: Path
    name_key: str
    is_dir: bool
    is_media: bool = False
    owner: Path | None = None
    association: str = "shared"


class OrganizeIndex:
    """整理开始前的只读目录快照。

    归属关系在第一次移动前一次性算好。后续每个番号只读本索引，
    不会因为前面番号已经移动文件而改变“这个文件属于谁”的判断。
    """

    def __init__(self) -> None:
        self._entries: dict[Path, _OrganizeEntry] = {}
        self._media: dict[Path, _OrganizeMedia] = {}
        self._direct_files: dict[Path, list[Path]] = defaultdict(list)
        self._child_dirs: dict[Path, set[Path]] = defaultdict(set)
        self._media_by_folder: dict[Path, list[Path]] = defaultdict(list)
        self._media_by_number: dict[str, list[Path]] = defaultdict(list)
        self._numbers: set[str] = set()
        self._file_count = 0
        self._media_types = _configured_media_suffixes()
        self._asset_folder_keys = _configured_asset_folder_keys()
        self._asset_dirs: set[Path] = set()

    @property
    def file_count(self) -> int:
        return self._file_count

    @property
    def media_count(self) -> int:
        return len(self._media)

    @property
    def number_count(self) -> int:
        return len(self._numbers)

    @property
    def companion_count(self) -> int:
        return sum(
            1 for entry in self._entries.values() if not entry.is_dir and not entry.is_media and entry.owner is not None
        )

    @property
    def shared_count(self) -> int:
        return sum(
            1 for entry in self._entries.values() if not entry.is_dir and not entry.is_media and entry.owner is None
        )

    @property
    def media_suffixes(self) -> set[str]:
        return set(self._media_types)

    def _register_dir(self, path: Path) -> None:
        if path in self._entries:
            return
        self._entries[path] = _OrganizeEntry(
            path=path,
            folder=path.parent,
            name_key=_name_key(path.name),
            is_dir=True,
        )
        self._child_dirs[path.parent].add(path)

    def _register_file(self, path: Path) -> None:
        if path in self._entries:
            return
        self._entries[path] = _OrganizeEntry(
            path=path,
            folder=path.parent,
            name_key=_name_key(path.stem),
            is_dir=False,
        )
        self._direct_files[path.parent].append(path)
        self._file_count += 1

    def _in_asset_folder(self, path: Path) -> bool:
        """剧照/预告片目录里的视频是附件，不应成为独立的整理主体。"""
        return any(parent in self._asset_dirs for parent in path.parents)

    def _is_asset_dir_name(self, name: str) -> bool:
        return _looks_like_asset_folder(name, self._asset_folder_keys)

    def _refresh_asset_dirs(self) -> bool:
        """计算「剧照/附件目录」：媒体所在目录下的直接子目录。

        目录名疑似剧照（fanart/backdrop/scene/trailer）或其中不含媒体文件时，
        视为当前番号的伴生目录，整体搬迁时保持原目录名。返回目录集合是否变化。
        """
        dirs_with_media: set[Path] = set()
        for media_path in self._media:
            parent = media_path.parent
            while True:
                dirs_with_media.add(parent)
                if parent == parent.parent:
                    break
                parent = parent.parent

        asset_dirs: set[Path] = set()
        for folder in self._media_by_folder:
            for child in self._child_dirs.get(folder, set()):
                if _is_backup_name(child.name):
                    continue
                if child in dirs_with_media and not self._is_asset_dir_name(child.name):
                    # 自身还含媒体的子目录是「另一部作品」的目录，不属于当前番号
                    continue
                asset_dirs.add(child)
        if asset_dirs == self._asset_dirs:
            return False
        self._asset_dirs = asset_dirs
        return True

    def _detect_media(self) -> dict[Path, _OrganizeMedia]:
        """识别媒体主体（视频/STRM），剧照目录里的视频不算独立主体。"""
        media: dict[Path, _OrganizeMedia] = {}
        for path, entry in self._entries.items():
            if entry.is_dir or _is_backup_name(path.name):
                continue
            if path.suffix.lower() not in self._media_types or _is_trailer_stem(path.stem):
                continue
            if self._in_asset_folder(path):
                continue
            number = _extract_media_number(path)
            number_key = _name_key(number)
            aliases = tuple(dict.fromkeys(alias for alias in (entry.name_key, number_key) if alias))
            media[path] = _OrganizeMedia(
                path=path,
                folder=entry.folder,
                stem=path.stem,
                stem_key=entry.name_key,
                number=number,
                number_key=number_key,
                aliases=aliases,
            )
        return media

    def _apply_media(self, media: dict[Path, _OrganizeMedia]) -> None:
        self._media = media
        self._media_by_folder = defaultdict(list)
        self._media_by_number = defaultdict(list)
        self._numbers = set()
        for path, item in media.items():
            self._media_by_folder[item.folder].append(path)
            if item.number_key:
                self._numbers.add(item.number_key)
                self._media_by_number[item.number_key].append(path)
        for paths in (*self._media_by_folder.values(), *self._media_by_number.values()):
            paths.sort(key=lambda path: (_name_key(path.name), str(path)))

    def _finalize(self) -> None:
        # 剧照目录与媒体主体互相影响（剧照目录里的视频不算主体，剧照目录本身
        # 又是媒体所在目录的子目录），迭代到稳定为止。
        for _ in range(3):
            self._apply_media(self._detect_media())
            if not self._refresh_asset_dirs():
                break

        for entry in self._entries.values():
            entry.is_media = entry.path in self._media
            if entry.is_dir or entry.is_media:
                continue
            media_paths = self._media_by_folder.get(entry.folder) or self._context_media(entry)
            entry.owner, entry.association = self._resolve(entry, media_paths)

    def _context_media(self, entry: _OrganizeEntry) -> list[Path]:
        """沿伴生目录（extrafanart 等）向上找最近的媒体目录。"""
        child = entry.folder
        parent = child.parent
        while parent != child:
            media_paths = self._media_by_folder.get(parent)
            if media_paths:
                try:
                    relative = entry.path.relative_to(parent)
                except ValueError:
                    return []
                if relative.parts and (parent / relative.parts[0]) in self._asset_dirs:
                    return media_paths
                return []
            child, parent = parent, parent.parent
        return []

    def _pick_owner(self, media_paths: Iterable[Path]) -> Path:
        """同一文件名同时匹配多个媒体时，优先无分集后缀的主体，其次按名称排序。"""
        ordered = sorted(media_paths, key=lambda path: (_name_key(path.name), str(path)))
        base = [
            path
            for path in ordered
            if self._media[path].number_key and self._media[path].stem_key == self._media[path].number_key
        ]
        return (base or ordered)[0]

    def _resolve(self, entry: _OrganizeEntry, media_paths: list[Path]) -> tuple[Path | None, str]:
        best_length = -1
        best: set[Path] = set()
        for media_path in media_paths:
            for alias in self._media[media_path].aliases:
                if not _matches_alias(entry.name_key, alias):
                    continue
                if len(alias) > best_length:
                    best_length = len(alias)
                    best = {media_path}
                elif len(alias) == best_length:
                    best.add(media_path)
        if best:
            return self._pick_owner(best), "prefix"
        if len(media_paths) == 1:
            return media_paths[0], "folder"
        return None, "shared"

    def entry(self, path: Path) -> _OrganizeEntry | None:
        return self._entries.get(path)

    def owner_of(self, path: Path) -> Path | None:
        entry = self._entries.get(path)
        return entry.owner if entry is not None and not entry.is_dir else None

    def resolve_owner(self, path: Path, current: Path, extra_aliases: Iterable[str] = ()) -> Path | None:
        """返回文件归属；索引已有的归属优先，无法确定时再按当前番号别名补判。"""
        entry = self._entries.get(path)
        if entry is None:
            return None
        if entry.owner is not None:
            return entry.owner
        media_paths = self._media_by_folder.get(entry.folder) or self._context_media(entry)
        if not media_paths:
            return None
        extra_keys = {_name_key(alias) for alias in extra_aliases if alias}
        best_length = -1
        best: set[Path] = set()
        for media_path in media_paths:
            aliases = set(self._media[media_path].aliases)
            if media_path == current:
                aliases |= extra_keys
            for alias in aliases:
                if not _matches_alias(entry.name_key, alias):
                    continue
                if len(alias) > best_length:
                    best_length = len(alias)
                    best = {media_path}
                elif len(alias) == best_length:
                    best.add(media_path)
        if best:
            return self._pick_owner(best)
        return media_paths[0] if len(media_paths) == 1 else None

    def folder_entries(self, folder: Path) -> list[Path]:
        """按原始目录返回直接子文件与子目录（目录在末尾按名称排序）。"""
        child_dirs = sorted(self._child_dirs.get(folder, set()), key=lambda path: _name_key(path.name))
        return [*self._direct_files.get(folder, []), *child_dirs]

    def asset_dirs_in(self, folder: Path) -> list[Path]:
        """返回该目录下的剧照/附件子目录（保持原目录名，整体搬迁）。"""
        return sorted(
            (path for path in self._asset_dirs if path.parent == folder),
            key=lambda path: _name_key(path.name),
        )

    def files_under(self, folder: Path) -> list[Path]:
        """返回原始快照中该目录及其子目录的全部文件。"""
        result: list[Path] = []
        stack = [folder]
        seen: set[Path] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            result.extend(self._direct_files.get(current, []))
            children = sorted(self._child_dirs.get(current, set()), key=lambda path: _name_key(path.name))
            for child in children:
                try:
                    if child.is_symlink():
                        continue
                except OSError:
                    continue
                stack.append(child)
        return result

    def media_in_folder(self, folder: Path) -> list[Path]:
        return list(self._media_by_folder.get(folder, []))

    def other_media_in_folder(self, folder: Path, current: Path) -> list[Path]:
        return [path for path in self._media_by_folder.get(folder, []) if path != current]

    def media_for_number(self, number: str) -> list[Path]:
        return list(self._media_by_number.get(_name_key(number), []))

    def media_info(self, path: Path) -> _OrganizeMedia | None:
        return self._media.get(path)


def _dedupe_roots(roots: Iterable[str | Path]) -> list[Path]:
    """去掉重复及被其它根目录包含的扫描根，避免同一文件被索引两次。"""
    result: list[Path] = []
    normalized: list[str] = []
    for root in sorted((Path(root) for root in roots), key=lambda path: (len(path.parts), str(path))):
        absolute_key = _name_key(str(Path(os.path.abspath(root))))
        if any(absolute_key == seen or absolute_key.startswith(seen + os.sep) for seen in normalized):
            continue
        result.append(root)
        normalized.append(absolute_key)
    return result


def build_organize_index(
    roots: Iterable[str | Path],
    *,
    ignore_dirs: Iterable[str | Path] = (),
) -> OrganizeIndex:
    """在移动任何文件前遍历目录，建立媒体番号与全部伴生文件的归属快照。"""
    index = OrganizeIndex()
    ignored = {Path(os.path.abspath(path)) for path in ignore_dirs}
    deduped_roots = _dedupe_roots(roots)
    for root in deduped_roots:
        if _safe_is_file(root):
            index._register_file(root)
            continue
        if not _safe_is_dir(root):
            continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if Path(os.path.abspath(current_path / name)) not in ignored]
            if any(_name_key(name) in {"skip", ".skip", ".ignore"} for name in files):
                dirs.clear()
                continue
            for name in dirs:
                index._register_dir(current_path / name)
            for name in files:
                if _is_backup_name(name):
                    continue
                index._register_file(current_path / name)
    index._finalize()
    return index


class OrganizePlanError(Exception):
    """整理计划无法安全执行（例如多个源文件映射到同一个目标）。"""


class OrganizeTransaction:
    """整理模式的移动事务：任一文件失败则把已移动文件全部退回原位置。"""

    def __init__(self, *, elevated: bool = False) -> None:
        self._ops: list[tuple[str, Path, Path]] = []
        self._elevated = elevated

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

    async def _wait_moved(self, src: Path, dst: Path, attempts: int = 4) -> bool:
        """网络盘目录缓存可能短暂滞后：以“目标已出现且源已消失”为最终成功。"""
        for attempt in range(attempts):
            if await self._exists(dst) and not await self._exists(src):
                return True
            if attempt + 1 < attempts:
                await asyncio.sleep(0.05 * (attempt + 1))
        return False

    async def _move_once(self, src: Path, dst: Path) -> tuple[bool, str]:
        """整理只做直接移动；管理员重试只在整个任务队列结束后统一执行。"""
        if not await self._ensure_parent(dst):
            return False, f"无法创建目标目录: {dst.parent}"
        if self._elevated:
            _elevated_ok, elevated_error = await elevated_move_file(src, dst)
            if await self._wait_moved(src, dst):
                return True, ""
            return False, f"管理员移动失败: {elevated_error or '未完成'}"
        _result, error = await move_file_async(src, dst, overwrite=True)
        if await self._wait_moved(src, dst):
            return True, ""
        return False, f"直接移动失败: {error or '未完成'}"

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
            if get_file_move_policy() == FILE_MOVE_KEEP:
                # 「保留旧文件」：目标位置已有同名文件 → 保留目标文件，
                # 被移动的源文件留在原目录不移动（不覆盖、不删除任何一方）。
                LogBuffer.log().write(f"\n 📖 目标位置已存在同名文件，按「保留旧文件」策略不移动：{src}")
                return True, ""
            # 保留目标位置已有文件，失败回滚时恢复；成功后删除备份。
            # 「覆盖旧文件」策略下同样走这条路径：备份后覆盖，commit 时删除备份。
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
    index: OrganizeIndex | None = None,
    include_media: bool = True,
) -> list[tuple[Path, Path]]:
    """生成整理计划：只包含当前番号真实存在的关联文件。

    ``include_media=False`` 时不把视频/STRM 主体放进计划（视频模式自行搬运
    视频本体，伴生文件先落位、主体后搬）。
    """
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
        suffix_index = 2
        while dst in destinations:
            dst = preferred.with_name(f"{preferred.stem}-{suffix_index}{preferred.suffix}")
            suffix_index += 1
        add(src, dst)

    if index is None or index.entry(file_path) is None:
        index = await asyncio.to_thread(build_organize_index, [folder_old_path])
    try:
        entries = index.folder_entries(folder_old_path)
    except OSError:
        entries = []
    entry_by_name = {_name_key(entry.name): entry for entry in entries}

    def find(name: str) -> Path | None:
        return entry_by_name.get(_name_key(name))

    media_types = index.media_suffixes
    source_name = file_path.stem
    current_key = _name_key(source_name)
    current_aliases = {current_key}
    if number:
        current_aliases.add(_name_key(number))

    def belongs(entry: Path) -> bool:
        """只认索引中唯一归属当前媒体的文件，避免多个番号抢同一个文件。"""
        return index.resolve_owner(entry, file_path, current_aliases) == file_path

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
    if nfo_source is not None and belongs(nfo_source):
        add(nfo_source, nfo_new_path)

    # 图片：先确定 poster/thumb/fanart 的主文件，其余同番号图片一并移动。
    image_entries = [
        entry
        for entry in entries
        if _safe_is_file(entry) and entry.suffix.lower() in IMAGE_SUFFIXES and not _is_backup_name(entry.name)
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
        # 共用目录中只认索引归属当前媒体的图片，避免误移其它番号的 poster.jpg。
        candidates = [entry for entry in candidates if belongs(entry)]
        if not candidates:
            continue
        candidates.sort(
            key=lambda path: (
                _name_key(path.name) != _name_key(final_path.name),
                not belongs(path),
                path.suffix.lower() != ".jpg",
                path.name.lower(),
            )
        )
        # 主图保留源文件的真实扩展名：poster.png → poster.png、fanart.gif → fanart.gif。
        # 不改成 .jpg 是为了不做"格式伪装"，也保住 gif 动图。
        add(candidates[0], image_path_with_suffix(final_path, candidates[0].suffix))
        for extra in candidates[1:]:
            add_variant(extra, folder_new_path / extra.name)

    for entry in image_entries:
        if entry in seen_sources or not belongs(entry):
            continue
        add_variant(entry, folder_new_path / entry.name)

    # json（含 -mediainfo.json），按大小写不敏感匹配。
    for entry in entries:
        if not _safe_is_file(entry) or entry.suffix.lower() != ".json" or _is_backup_name(entry.name):
            continue
        if not belongs(entry):
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
        if sub_source is not None and belongs(sub_source):
            add(sub_source, sub_destination(sub))
    for entry in entries:
        if not _safe_is_file(entry) or not belongs(entry) or _is_backup_name(entry.name):
            continue
        if entry.suffix.lower() not in sub_types:
            continue
        suffix = companion_suffix(entry.name)
        if suffix:
            add(entry, sub_destination(suffix))

    # 种子、bif。
    torrent_source = find(f"{source_name}.torrent")
    if torrent_source is not None and belongs(torrent_source):
        add(torrent_source, folder_new_path / f"{naming_rule}.torrent")
    if number:
        number_torrent = find(f"{number}.torrent")
        if number_torrent is not None and belongs(number_torrent):
            add(number_torrent, folder_new_path / f"{number}.torrent")
    bif_source = find(f"{source_name}-320-10.bif")
    if bif_source is not None and belongs(bif_source):
        add(bif_source, folder_new_path / f"{naming_rule}-320-10.bif")

    # 单文件预告片。
    for entry in entries:
        if (
            _safe_is_file(entry)
            and entry.stem.lower() == f"{source_name}-trailer".lower()
            and entry.suffix.lower() in media_types
            and not _is_backup_name(entry.name)
            and belongs(entry)
        ):
            if manager.config.trailer_simple_name:
                dst = folder_new_path / "trailers" / f"trailer{entry.suffix}"
            else:
                dst = folder_new_path / f"{naming_rule}-trailer{entry.suffix}"
            add(entry, dst)

    # 剧照、背景图等文件夹，保持相对目录结构。
    # 目录来源是索引动态识别出的「媒体目录下的伴生子目录」，因此像 extarfanart
    # 这类非标准写法的剧照目录同样会被整体搬走；目录名按标准名归一
    # （extarfanart → extrafanart），文件本身保持原文件名与相对层级。
    for source_folder in index.asset_dirs_in(folder_old_path):
        target_name = _canonical_asset_folder_name(source_folder.name)
        for source in index.files_under(source_folder):
            # 共用目录中只移动索引归属当前媒体的剧照，避免动到其它番号。
            if _is_backup_name(source.name) or not belongs(source):
                continue
            relative = source.relative_to(source_folder)
            add_variant(source, folder_new_path / target_name / relative)

    # 其余与文件同名的伴生文件（不含媒体、nfo、json，它们已单独处理）。
    handled_suffixes = media_types | {".nfo", ".json"} | set(sub_types) | IMAGE_SUFFIXES
    for entry in entries:
        if not _safe_is_file(entry) or entry in seen_sources or not belongs(entry):
            continue
        suffix = companion_suffix(entry.name)
        suffix_lower = suffix.lower()
        if not suffix or suffix_lower in handled_suffixes:
            continue
        if "-cd" in entry.stem.lower() or _is_backup_name(entry.name):
            continue
        add_variant(entry, folder_new_path / f"{naming_rule}{suffix}")

    # 视频/STRM 最后移动，其余资源全部落位后再移动主体文件。
    # include_media=False 时主体不参与本次计划（视频模式自己搬视频本体）。
    if include_media:
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
    elevated: bool = False,
    index: OrganizeIndex | None = None,
    success_folder: Path | None = None,
) -> tuple[bool, str]:
    """按命名规则原子地整理当前番号的视频/STRM 及其全部伴生文件。

    返回 ``(成功, 错误信息)``。失败时会回滚已移动文件，源文件保持在原目录。
    ``elevated=True`` 用于所有其他番号处理完成后，对失败番号统一做一次管理员重试。
    ``index`` 是移动前建立的全目录关联快照；不传时按当前目录临时建立。
    ``success_folder`` 是「成功输出目录」：已经躺在该目录内的文件一律不移动
    （整理模式硬性要求：已在成功输出目录内的文件任何情况下都不移动、不复制后删源）。
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
            index=index,
        )
    except OrganizePlanError as e:
        LogBuffer.error().write(f"整理失败：{e}")
        return False, str(e)
    except Exception as e:
        LogBuffer.error().write(f"整理失败：生成整理计划时出错：{e}")
        return False, str(e)

    if success_folder is not None:
        kept: list[tuple[Path, Path]] = []
        for src, dst in plan:
            if is_in_success_folder(src, success_folder):
                # 源文件已经在「成功输出目录」内 → 一律不移动
                # （跨盘 shutil.move 会退化成「复制 + 删除源文件」，风险最高）
                LogBuffer.log().write(f"\n 📖 文件已在成功输出目录内，跳过移动（未移动任何文件）：{src}")
                continue
            if is_in_success_folder(dst, success_folder) and await _exists_settled(dst):
                # 目标位置已被「成功输出目录」内的既有文件占用 → 既有文件不移动、
                # 不覆盖、不删除，本次也不搬动新文件（宁可留在原地也不动既有产物）
                if get_file_move_policy() != FILE_MOVE_OVERWRITE:
                    LogBuffer.log().write(f"\n 📖 目标位置已被成功输出目录内的文件占用，既有文件不移动、不覆盖：{dst}")
                    continue
                # 「覆盖旧文件」策略：允许覆盖成功输出目录内的既有文件
                LogBuffer.log().write(f"\n 📖 目标位置已被成功输出目录内的文件占用，按「覆盖旧文件」策略覆盖：{dst}")
            kept.append((src, dst))
        plan = kept

    if not plan:
        return True, ""

    transaction = OrganizeTransaction(elevated=elevated)
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
        missing = [dst for _, dst in plan if not await _exists_settled(dst)]
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


async def organize_companion_files(
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
    move_media: Callable[[], Awaitable[bool]],
    index: OrganizeIndex | None = None,
    elevated: bool = False,
) -> tuple[bool, str]:
    """视频模式「移动已下载图片和文件到新目录」：按番号关联事务式搬运伴生文件。

    与整理模式共用同一套「计划 → 事务 → 校验 → 回滚」机制，只有两点不同：

    1. 伴生文件先落位、视频本体最后搬（``move_media`` 由调用方提供，保留
       视频模式原有的软链接/硬链接语义）；
    2. 视频本体搬运失败时，已经搬走的伴生文件一并回滚，保证「全有或全无」。

    搬运范围与整理模式一致：NFO、图片（poster/thumb/fanart 及同番号全部图片）、
    JSON（含 ``-mediainfo.json``，按新命名规则改名）、字幕、种子、bif、
    单文件预告片、剧照目录（保持相对结构）、其余同名前缀伴生文件。

    与整理模式不同：这里**不套用「成功输出目录」过滤**——视频模式的目标目录
    就在成功输出目录里，用户要的正是「伴生文件跟着视频一起搬」；若沿用整理
    模式的「源文件在成功输出目录内就不动」，扫描成功输出目录时会一个都不搬。

    返回 ``(成功, 错误信息)``。失败时伴生文件已回滚到原目录。
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
            index=index,
            include_media=False,
        )
    except OrganizePlanError as e:
        LogBuffer.error().write(f"移动失败：{e}")
        return False, str(e)
    except Exception as e:
        LogBuffer.error().write(f"移动失败：生成移动计划时出错：{e}")
        return False, str(e)

    if not plan:
        # 没有可搬的伴生文件：视频本体仍要按视频模式规则搬过去
        if not await move_media():
            message = "视频文件移动失败"
            LogBuffer.error().write(message)
            return False, message
        return True, ""

    transaction = OrganizeTransaction(elevated=elevated)
    try:
        for src, dst in plan:
            ok, error = await transaction.move_file(src, dst)
            if not ok:
                await transaction.rollback()
                message = f"移动失败，已回滚到原目录：{src} -> {dst}; {error}"
                LogBuffer.error().write(message)
                return False, message
    except Exception as e:
        await transaction.rollback()
        message = f"移动失败，已回滚到原目录：{e}"
        LogBuffer.error().write(message)
        return False, message

    try:
        missing = [dst for _, dst in plan if not await _exists_settled(dst)]
    except OSError as e:
        await transaction.rollback()
        message = f"移动失败，无法确认目标文件，已回滚到原目录：{e}"
        LogBuffer.error().write(message)
        return False, message
    if missing:
        await transaction.rollback()
        message = f"移动失败，目标文件缺失，已回滚到原目录：{missing[0]}"
        LogBuffer.error().write(message)
        return False, message

    # 伴生文件全部落位后再搬视频本体；视频搬运失败时伴生文件一并回滚
    if not await move_media():
        await transaction.rollback()
        message = "视频文件移动失败，伴生文件已回滚到原目录"
        LogBuffer.error().write(message)
        return False, message

    await transaction.commit()
    LogBuffer.log().write(f"\n 🍀 Companion files done: {folder_old_path} -> {folder_new_path}")
    return True, ""
