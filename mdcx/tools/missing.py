"""
查找指定演员缺少作品
"""

import json
import re
import time
from pathlib import Path
from typing import cast

import aiofiles
import aiofiles.os

from ..base.file import movie_lists
from ..config.manager import manager
from ..config.resources import resources
from ..core.file import get_file_info_v2
from ..models.flags import Flags
from ..signals import signal
from ..utils import get_used_time
from ..utils.file import write_file_atomic_async
from .actor_sources import NumberHit, collect_numbers, normalize_key, resolve_actor_names

_ACTOR_TYPE_PATTERN = re.compile(r"[（(]\s*(有码|无码|欧美|国产|动漫|FC2)\s*[)）]", re.IGNORECASE)

# 工具页「类型」下拉框文案 → 内部演员类型。
# 文案与「软件设置 → 锁定类型」同源（FixedScrapingType.names()），顺序也一致，
# 只少了「国产短剧」——国产短剧多为 AI 生成、没有演员，按演员名查不到东西。
# 个摄番号对应内部的 FC2 类型（FC2 / 1pondo 这类个人拍摄）。
_FORCED_TYPE_BY_COMBO = {
    "有码番号": "有码",
    "无码番号": "无码",
    "个摄番号": "FC2",
    "欧美视频": "欧美",
    "国产传媒": "国产",
    "动漫里番": "动漫",
}


def resolve_forced_type(label: str) -> str:
    """下拉框文案 → 内部演员类型；「自动判断」或认不出的文案返回空串。"""
    return _FORCED_TYPE_BY_COMBO.get(str(label or "").strip(), "")


def apply_forced_type(entries: list[tuple[str, str]], label: str) -> list[tuple[str, str]]:
    """下拉框选了具体类型时，把所有演员的类型统一成该类型（忽略名字后的标注）。"""
    forced = resolve_forced_type(label)
    if not forced:
        return entries
    return [(name, forced) for name, _type in entries]


def _parse_actor_entry(entry: str) -> tuple[str, str]:
    """解析演员名条目，提取类型标注。返回 (演员名, 类型)。

    格式: "波多野結衣" 或 "水菜麗(无码)" 或 "Angela White(欧美)"。
    不标注的默认有码。

    动漫 / FC2 不是演员名，填的是 JavDB 关键字（社团名/作品关键词、FC2 卖家名）。
    """
    entry = entry.strip()
    m = _ACTOR_TYPE_PATTERN.search(entry)
    if m:
        actor_type = m.group(1)
        if actor_type.upper() == "FC2":  # 允许用户写 (fc2)
            actor_type = "FC2"
        name = _ACTOR_TYPE_PATTERN.sub("", entry).strip()
        return name, actor_type
    return entry, "有码"


async def _fetch_actor_numbers(name: str, actor_type: str) -> dict[str, NumberHit]:
    """解析演员名变体，再按类型汇总各站点番号。"""
    names = await resolve_actor_names(name)
    if len(names) > 1:
        signal.show_log_text(f"   名字变体：{' / '.join(names)}")
    return await collect_numbers(actor_type, names, log=signal.show_log_text)


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _excel_target(actor_name: str) -> Path | None:
    """缺失番号表格的落盘路径：本地资源库目录 / 演员姓名.xlsx。"""
    libraries = [p for p in manager.config.local_library if str(p).strip()]
    if not libraries:
        return None
    folder = Path(libraries[0])
    safe_name = _INVALID_FILENAME_CHARS.sub("_", actor_name).strip() or "actor"
    return folder / f"{safe_name}.xlsx"


def _write_missing_excel(path: Path, rows: list[NumberHit]) -> None:
    """写缺失番号表：三列（番号 / 网站 / 链接地址），番号 A-Z 排列。

    版式照用户给的样表：番号与网站居中，链接靠左，列宽 8.8 / 11 / 100。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["番号", "网站", "链接地址"])
    for hit in rows:
        sheet.append([hit.number, hit.site, hit.url])

    sheet.column_dimensions["A"].width = 8.8
    sheet.column_dimensions["B"].width = 11
    sheet.column_dimensions["C"].width = 100

    font = Font(name="宋体", size=11)
    for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, max_col=3):
        for cell in row:
            cell.font = font
            # 第 3 列是链接，靠左；前两列居中
            cell.alignment = Alignment(horizontal="left" if cell.column == 3 else "center", vertical="center")

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _report_actor_result(actor_name: str, actor_type: str, net_hits: dict[str, NumberHit]) -> None:
    """汇总一个演员的对比结果，并把缺失项写进 Excel（日志里不再打印番号列表）。"""
    local_set = Flags.local_number_set
    local_keys = {normalize_key(n) for n in local_set}

    missing = sorted(
        (hit for key, hit in net_hits.items() if key not in local_keys),
        key=lambda hit: hit.number,
    )
    type_tag = f"[{actor_type}]" if actor_type != "有码" else ""
    signal.show_log_text(
        f"\n📊 {type_tag} {actor_name}：网络番号 {len(net_hits)} 个，本地已有 "
        f"{len(net_hits) - len(missing)} 个，缺失 {len(missing)} 个"
    )
    if not missing:
        signal.show_log_text("   没有缺失的番号，已全部收集！")
        return

    target = _excel_target(actor_name)
    if target is None:
        signal.show_log_text("   ⚠️ 未设置本地资源库目录，缺失番号未写入 Excel（请先在设置里选择本地资源库）")
        return
    try:
        _write_missing_excel(target, missing)
    except Exception as e:  # 写表格失败不该让整个查询任务中断
        signal.show_log_text(f"   ⚠️ 缺失番号表格写入失败：{e}")
        return
    signal.show_log_text(f"   📗 缺失番号已写入：{target}")


async def _try_write_cache_async(p: str | Path, content: str, start_time: float) -> None:
    """写缓存文件，失败只记录日志，不让整个查询任务中断。

    缺失番号查询已耗时遍历整个资源库，若结尾写缓存失败（磁盘满、
    目录只读、文件被占用等）导致任务中断，之前的查询结果全部白费。
    """
    try:
        await write_file_atomic_async(p, content)
    except Exception as e:
        signal.show_log_text(f"   ⚠️ 缓存文件写入失败（不影响本次查询结果，但下次会重新扫描）：{e}")


async def check_missing_number(actor_flag, forced_type: str = ""):
    """
    检查缺失番号

    forced_type 是工具页「类型」下拉框的文案：选具体类型时所有演员都按该类型的
    网站列表查，跳过演员名后的 (无码)(欧美) 标注；「自动判断」/空串按标注走。
    """
    signal.change_buttons_status.emit()
    start_time = time.time()
    local_movies: dict[str, tuple[str, bool]] = {}

    # 获取资源库配置
    movie_type = manager.config.media_type
    # 用户设置的扫描媒体路径（去空项并转成 Path，下面 movie_lists 要 Path）
    libraries = {Path(p) for p in manager.config.local_library if str(p).strip()}

    # 遍历本地资源库
    signal.show_log_text("")
    library_lines = "\n   ".join(str(p) for p in libraries)
    signal.show_log_text(
        f"\n本地资源库地址:\n   {library_lines}\n\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 开始遍历本地资源库，以获取本地视频的最新列表...\n   提示：每次启动第一次查询将更新本地视频数据。（大概1000个/30秒，如果视频较多，请耐心等待。）"
    )
    all_movies: list[Path] = []
    for p in libraries:
        movies = await movie_lists([], movie_type, p)  # 获取所有需要刮削的影片列表
        all_movies.extend(movies)
    signal.show_log_text(f"🎉 获取完毕！共找到视频数量（{len(all_movies)}）({get_used_time(start_time)}s)")

    # 获取本地番号
    start_time_local = time.time()
    signal.show_log_text("\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 开始获取本地视频的番号信息...")
    local_number_list = resources.u("number_list.json")
    if not await aiofiles.os.path.exists(local_number_list):
        signal.show_log_text(
            "   提示：正在生成本地视频的番号信息数据...（第一次较慢，请耐心等待，以后只需要查找新视频，速度很快）"
        )
        await _try_write_cache_async(local_number_list, "{}", start_time)
    async with aiofiles.open(local_number_list, encoding="utf-8") as data:
        json_data = json.loads(await data.read())
        json_data = cast("dict[str, tuple[str, bool]]", json_data)
    for movie in all_movies:
        nfo_path = movie.with_suffix(".nfo")
        number = ""
        has_sub = False
        if r := json_data.get(movie.as_posix()):
            number, has_sub = r
        else:
            if await aiofiles.os.path.exists(nfo_path):
                async with aiofiles.open(nfo_path, encoding="utf-8") as f:
                    nfo_content = await f.read()
                number_result = re.findall(r"<num>(.+)</num>", nfo_content)
                if number_result:
                    number = number_result[0]

                    if "<genre>中文字幕</genre>" in nfo_content or "<tag>中文字幕</tag>" in nfo_content:
                        has_sub = True
                    else:
                        has_sub = False
            if not number:
                file_info = await get_file_info_v2(movie, copy_sub=False)
                has_sub = file_info.has_sub
                number = file_info.number
            cn_word_icon = "🀄️" if has_sub else ""
            signal.show_log_text(f"   发现新番号：{number:<10} {cn_word_icon}")
        temp_number = re.findall(r"\d{3,}([a-zA-Z]+-\d+)", number)  # 去除前缀，因为 javdb 不带前缀
        number = temp_number[0] if temp_number else number
        local_movies[movie.as_posix()] = (number, has_sub)  # 用新表，更新完重新写入到本地文件中
        Flags.local_number_set.add(number)  # 添加到本地番号集合
        if has_sub:
            Flags.local_number_cnword_set.add(number)  # 添加到本地有字幕的番号集合

        await _try_write_cache_async(
            local_number_list,
            json.dumps(
                local_movies,
                ensure_ascii=False,
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            ),
            start_time,
        )
    signal.show_log_text(f"🎉 获取完毕！共获取番号数量（{len(local_movies)}）({get_used_time(start_time_local)}s)")

    # 查询演员番号
    if manager.config.actors_name:
        raw_list = re.split(r"[,，]", manager.config.actors_name)
        actor_entries = [_parse_actor_entry(e) for e in raw_list if e.strip()]
        # 下拉框选了具体类型就统一按该类型查，忽略名字后面的 (无码)(欧美) 标注
        actor_entries = apply_forced_type(actor_entries, forced_type)
        summary = ", ".join(f"{n}({t})" if t != "有码" else n for n, t in actor_entries)
        signal.show_log_text(
            f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n🔍 需要查询的演员：\n   {summary}"
        )
        for actor_name, actor_type in actor_entries:
            signal.show_log_text(
                f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 查询 [ {actor_name} ]({actor_type}) 的所有番号列表..."
            )
            try:
                net_hits = await _fetch_actor_numbers(actor_name, actor_type)
            except Exception as e:
                signal.show_log_text(f"   查询出错: {e}")
                continue
            if net_hits:
                _report_actor_result(actor_name, actor_type, net_hits)
            else:
                signal.show_log_text(f"\n🔴 未找到 [ {actor_name} ] 的作品，请检查演员名或类型标注是否正确")
    else:
        signal.show_log_text("\n🔴 没有要查询的演员！")

    signal.show_log_text(f"\n🎉 查询完毕！共用时({get_used_time(start_time)}s)")
    signal.reset_buttons_status.emit()
