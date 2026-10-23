"""视频 / STRM 与伴生文件的关联索引（整理模式、视频模式、补全模式共用）。

这个模块只做一件事：在**任何文件被移动之前**，把目录快照里的每个文件归属到
某个媒体主体（视频或 STRM），并给出「这个媒体当前已经有哪些伴生文件」。

归属规则（与整理模式原有实现逐条一致）：

1. 媒体主体 = 配置里「媒体类型」列表中的扩展名（含 ``.strm``），排除预告片
   （``-trailer``）与剧照/附件目录里的视频；
2. 伴生文件优先按「文件名 == 番号，或以番号加分隔符开头」匹配，最长匹配优先；
3. 同一目录下只有一个媒体时，目录内的文件默认归它（``folder`` 关联）；
4. 同目录有多个媒体、又匹配不上任何一个时算 ``shared``（共用文件，不搬动）。

各模式的用法：

- 整理模式：``build_organize_index()`` 建索引，按索引生成移动计划；
- 视频模式：勾选「移动已下载图片和文件到新目录」时同样先建索引；
- 补全模式：``collect_media_assets()`` 查询当前媒体已有哪些 nfo / 图片 / 字幕 /
  mediainfo / 种子，据此决定还需要刮削补哪些。
"""

import os
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import aiofiles.os

from ..config.manager import manager
from ..number import get_file_number
from ..utils.picture import IMAGE_SUFFIXES

ORGANIZE_BACKUP_MARK = ".mdcx_organize_backup_"
"""整理/补全事务覆盖目标文件时留下的备份文件标记（回滚用）。"""

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
    import asyncio

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
    return ORGANIZE_BACKUP_MARK in name


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


@dataclass(slots=True)
class MediaAssets:
    """某个视频 / STRM 当前已有的伴生文件清单（只读查询结果）。

    补全模式据此判断「还缺什么」：缺 nfo 就整片按正常模式重刮，缺封面/缩略图/
    背景图就只补这几张，缺字幕就回字幕目录找同名文件。
    """

    media: Path
    folder: Path
    number: str
    nfo: Path | None = None
    poster: Path | None = None
    thumb: Path | None = None
    fanart: Path | None = None
    images: list[Path] = field(default_factory=list)
    subtitles: list[Path] = field(default_factory=list)
    torrents: list[Path] = field(default_factory=list)
    mediainfo: Path | None = None
    bifs: list[Path] = field(default_factory=list)
    trailer: Path | None = None
    asset_dirs: list[Path] = field(default_factory=list)

    @property
    def has_nfo(self) -> bool:
        return self.nfo is not None

    @property
    def missing_main_images(self) -> list[str]:
        """缺失的主图种类（poster / thumb / fanart）。"""
        return [
            name
            for name, path in (("poster", self.poster), ("thumb", self.thumb), ("fanart", self.fanart))
            if path is None
        ]

    @property
    def has_subtitle(self) -> bool:
        return bool(self.subtitles)


def _companion_suffix(name: str, stems: Iterable[str]) -> str:
    """取「文件名去掉番号/媒体名之后」的剩余部分（含扩展名）。

    用 NFC 归一化后的长度切分，避免 NFD 文件名长度变化导致后缀被截断。
    """
    normalized_name = unicodedata.normalize("NFC", name)
    name_key = _name_key(normalized_name)
    for stem in sorted((stem for stem in stems if stem), key=len, reverse=True):
        normalized_stem = unicodedata.normalize("NFC", stem)
        stem_key = _name_key(normalized_stem)
        if name_key.startswith(stem_key) and len(normalized_name) >= len(normalized_stem):
            return normalized_name[len(normalized_stem) :]
    return ""


def collect_media_assets(
    file_path: str | Path,
    *,
    index: OrganizeIndex | None = None,
    number: str = "",
    sub_types: Iterable[str] = (),
) -> MediaAssets:
    """查询当前视频 / STRM 已关联的 nfo、图片、封面、缩略图、mediainfo、字幕、种子。

    ``index`` 为 ``build_organize_index()`` 建立的目录快照；不传时按当前目录
    临时建立（只读，不移动任何文件）。``number`` 用于匹配「番号-poster.jpg」
    这类不带媒体文件名的图片；``sub_types`` 是配置里的字幕扩展名列表。

    与移动计划（``organize._build_plan``）用同一套归属判断，保证「查到的」
    和「会搬走的」是同一批文件。
    """
    path = Path(file_path)
    folder = path.parent
    if index is None or index.entry(path) is None:
        index = build_organize_index([folder])

    media_info = index.media_info(path)
    resolved_number = number or (media_info.number if media_info is not None else "")
    stems = [path.stem]
    if resolved_number:
        stems.append(resolved_number)
    aliases = {_name_key(stem) for stem in stems if stem}

    assets = MediaAssets(media=path, folder=folder, number=resolved_number)
    try:
        entries = index.folder_entries(folder)
    except OSError:
        entries = []

    def belongs(candidate: Path) -> bool:
        return index.resolve_owner(candidate, path, aliases) == path

    sub_suffixes = {str(item).lower() for item in sub_types if item}
    image_entries: list[Path] = []
    for entry in entries:
        if not _safe_is_file(entry) or _is_backup_name(entry.name):
            continue
        suffix = entry.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            image_entries.append(entry)
            continue
        if not belongs(entry):
            continue
        if suffix == ".nfo" and _name_key(entry.stem) == _name_key(path.stem):
            assets.nfo = entry
        elif suffix == ".json":
            if _name_key(entry.stem) in {_name_key(f"{stem}-mediainfo") for stem in stems} or _name_key(
                entry.name
            ) == _name_key(f"{resolved_number}-mediainfo.json"):
                assets.mediainfo = entry
        elif suffix == ".torrent":
            assets.torrents.append(entry)
        elif suffix == ".bif":
            assets.bifs.append(entry)
        elif suffix in sub_suffixes:
            assets.subtitles.append(entry)

    # 图片：先按「媒体名-种类 / 番号-种类 / 种类」确定主图，其余同番号图片归入 images
    for kind in ("poster", "thumb", "fanart"):
        candidates = [
            entry
            for entry in image_entries
            if _name_key(entry.stem) in {_name_key(f"{stem}-{kind}") for stem in stems} | {_name_key(kind)}
            and belongs(entry)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item.suffix.lower() != ".jpg", _name_key(item.name)))
        setattr(assets, kind, candidates[0])
    assets.images = [entry for entry in image_entries if belongs(entry)]

    # 预告片（单文件）
    for entry in entries:
        if not _safe_is_file(entry) or _is_backup_name(entry.name):
            continue
        if _name_key(entry.stem) == _name_key(f"{path.stem}-trailer") and belongs(entry):
            assets.trailer = entry
            break

    assets.asset_dirs = index.asset_dirs_in(folder)
    return assets
