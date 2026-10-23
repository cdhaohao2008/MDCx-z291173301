"""整理 / 视频 / 补全模式共用的「移动计划 + 事务 + 回滚」实现。

「番号 ↔ 伴生文件」的归属索引已抽到 :mod:`mdcx.core.file_association`，
这里只负责：按归属索引生成移动计划、事务式执行、失败回滚。
"""

import asyncio
import os
import time
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiofiles.os

from ..config.extend import FILE_MOVE_KEEP, FILE_MOVE_OVERWRITE, get_file_move_policy, is_in_success_folder
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..utils.file import elevated_move_file, move_file_async
from ..utils.picture import IMAGE_SUFFIXES, image_path_with_suffix
from .file_association import (
    OrganizeIndex,
    _canonical_asset_folder_name,
    _exists_settled,
    _is_backup_name,
    _name_key,
    _safe_is_file,
    build_organize_index,
)

# 兼容旧引用：整理模式内部的备份标记沿用原私有名
_ORGANIZE_BACKUP_MARK = ".mdcx_organize_backup_"

__all__ = [
    "OrganizeIndex",
    "OrganizePlanError",
    "OrganizeTransaction",
    "build_organize_index",
    "organize_companion_files",
    "organize_files",
]


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
                # 「保留目标文件」：目标位置已有同名文件 → 保留目标文件，
                # 被移动的源文件留在原目录不移动（不覆盖、不删除任何一方）。
                LogBuffer.log().write(f"\n 📖 目标位置已存在同名文件，按「保留目标文件」策略不移动：{src}")
                return True, ""
            # 保留目标位置已有文件，失败回滚时恢复；成功后删除备份。
            # 「覆盖目标文件」策略下同样走这条路径：备份后覆盖，commit 时删除备份。
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
                # 「覆盖目标文件」策略：允许覆盖成功输出目录内的既有文件
                LogBuffer.log().write(f"\n 📖 目标位置已被成功输出目录内的文件占用，按「覆盖目标文件」策略覆盖：{dst}")
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
