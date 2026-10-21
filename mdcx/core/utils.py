import asyncio
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiofiles.os

from ..config.enums import FieldRule, Language, NfoInclude, NoEscape, TagInclude
from ..config.manager import manager
from ..config.resources import resources
from ..gen.field_enums import CrawlerResultFields
from ..log_console import log_console
from ..manual import ManualConfig
from ..models.log_buffer import LogBuffer
from ..models.model_types import BaseCrawlerResult, CrawlersResult, FileInfo
from ..number import get_number_letters, strip_escape_strings
from ..utils import get_used_time
from ..utils.video import get_video_metadata


def replace_word(json_data: BaseCrawlerResult):
    # 常见字段替换的字符
    for key, value in ManualConfig.ALL_REP_WORD.items():
        for field_name in ManualConfig.ALL_KEY_WORD:
            setattr(json_data, field_name, getattr(json_data, field_name).replace(key, value))

    # 简体时替换的字符
    key_word = []
    if manager.config.get_field_config(CrawlerResultFields.TITLE).language == Language.ZH_CN:
        key_word.append("title")
    if manager.config.get_field_config(CrawlerResultFields.OUTLINE).language == Language.ZH_CN:
        key_word.append("outline")

    for key, value in ManualConfig.CHINESE_REP_WORD.items():
        for cn_field_name in key_word:
            setattr(json_data, cn_field_name, getattr(json_data, cn_field_name).replace(key, value))

    # 替换标题的上下集信息
    for field in (CrawlerResultFields.TITLE, CrawlerResultFields.ORIGINALTITLE):
        for each in ManualConfig.TITLE_REP:
            setattr(json_data, field, getattr(json_data, field).replace(each, "").strip(":， ").strip())


def replace_special_word(json_data: BaseCrawlerResult):
    # 常见字段替换的字符
    all_key_word = [
        "title",
        "originaltitle",
        "outline",
        "originalplot",
        "series",
        "director",
        "studio",
        "publisher",
        "tag",
    ]
    for key, value in ManualConfig.SPECIAL_WORD.items():
        for each in all_key_word:
            setattr(json_data, each, getattr(json_data, each).replace(key, value))


def deal_some_field(json_data: CrawlersResult):
    fields_rule = manager.config.fields_rule
    title = json_data.title
    originaltitle = json_data.originaltitle
    number = json_data.number

    # 演员处理
    if json_data.actors:
        # 去除演员名中的括号
        temp_actor_list = []
        actors = json_data.actors.copy()
        json_data.actors = []
        for raw_name in actors:
            if not raw_name:
                continue
            cleaned = re.findall(r"[^\(\)\（\）]+", raw_name)
            temp_actor_list.extend(cleaned)
            if FieldRule.DEL_CHAR in fields_rule:
                json_data.actors.append(cleaned[0])
            else:
                json_data.actors.append(raw_name)

        # 去除 all_actors 中的括号
        all_actors = json_data.all_actors.copy()
        json_data.all_actors = []
        for raw_name in all_actors:
            if not raw_name:
                continue
            cleaned = re.findall(r"[^\(\)\（\）]+", raw_name)
            if FieldRule.DEL_CHAR in fields_rule:
                json_data.all_actors.append(cleaned[0])
            else:
                json_data.all_actors.append(raw_name)

        # 去除标题后的演员名
        if FieldRule.DEL_ACTOR in fields_rule:
            new_all_actor_name_list = []
            for each_actor in json_data.actor_amazon + temp_actor_list:
                # 获取演员映射表的所有演员别名进行替换
                actor_keyword_list: list[str] = resources.get_actor_data(each_actor).get("keyword", [])
                new_all_actor_name_list.extend(actor_keyword_list)
            for each_actor in set(new_all_actor_name_list):
                title = title.removesuffix(f" {each_actor}")
                originaltitle = originaltitle.removesuffix(f" {each_actor}")
        json_data.title = title.strip()
        json_data.originaltitle = originaltitle.strip()

    # 去除标题中的番号
    if number != title and title.startswith(number):
        title = title.replace(number, "").strip()
        json_data.title = title
    if number != originaltitle and originaltitle.startswith(number):
        originaltitle = originaltitle.replace(number, "").strip()
        json_data.originaltitle = originaltitle

    # 去除标题中的/
    json_data.title = json_data.title.replace("/", "#").strip(" -")
    json_data.originaltitle = json_data.originaltitle.replace("/", "#").strip(" -")

    # 去除素人番号前缀数字
    if FieldRule.DEL_NUM in fields_rule:
        temp_n = re.findall(r"\d{3,}([a-zA-Z]+-\d+)", number)
        if temp_n:
            json_data.number = temp_n[0]
            json_data.letters = get_number_letters(json_data.number)

    # DMM 图床部分番号带 `z` 尾缀（IBW-786z，站内收录为 IBW-786），
    # 统一按基础番号命名落库；爬虫/文件名残留大写 Z 时兜底剥掉
    if number.endswith("Z"):
        json_data.number = json_data.number[:-1]
    return json_data


def show_movie_info(file_info: FileInfo, result: CrawlersResult):
    if not manager.config.show_data_log:  # 调试模式打开时显示详细日志
        return
    for key in ManualConfig.SHOW_KEY:  # 大部分来自 CrawlersResultDataClass, 少部分来自 FileInfo
        value = getattr(result, key, getattr(file_info, key, ""))
        if not value:
            continue
        if (key == CrawlerResultFields.OUTLINE or key == CrawlerResultFields.ORIGINALPLOT) and len(value) > 100:
            value = str(value)[:98] + "……（略）"
        elif key == "has_sub":
            value = "中文字幕"
        elif key == CrawlerResultFields.ACTORS and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
            value = result.all_actor
        LogBuffer.log().write(f"\n     {key:<13}: {value}")


def _normalize_path_for_definition(file_path: Path, file_number: str = "") -> str:
    definition_markers = {
        "8K",
        "4K",
        "4KS",
        "4K60FPS",
        "UHD",
        "UHD8",
        "QHD",
        "FHD",
        "HD",
        "1440P",
        "1080P",
        "960P",
        "720P",
        "540P",
        "480P",
        "360P",
        "144P",
    }
    escape_strings = [
        each for each in manager.config.string if re.sub(r"[^A-Z0-9]", "", each.upper()) not in definition_markers
    ]
    normalized = strip_escape_strings(file_path.as_posix(), escape_strings)
    number_candidates = {file_number.upper()} if file_number else set()

    if file_number:
        short_number = re.findall(r"\d{3,}([A-Z]+-\d+)", file_number.upper())
        number_candidates.update(short_number)

    for each in sorted((candidate for candidate in number_candidates if candidate), key=len, reverse=True):
        normalized = normalized.replace(each, "-")

    return normalized


def _detect_height_from_path(file_path: Path, file_number: str = "") -> int:
    normalized = _normalize_path_for_definition(file_path, file_number)
    normalized_name = normalized.rsplit("/", 1)[-1]
    pattern_height_map = (
        ((r"(?<![A-Z0-9])8K(?![A-Z0-9])",), 4000),
        ((r"(?<![A-Z0-9])4K(?![A-Z0-9])", r"(?<![A-Z0-9])UHD(?![A-Z0-9])"), 2000),
        ((r"(?<![A-Z0-9])1440P(?![A-Z0-9])", r"(?<![A-Z0-9])QHD(?![A-Z0-9])"), 1440),
        ((r"(?<![A-Z0-9])1080P(?![A-Z0-9])", r"(?<![A-Z0-9])FHD(?![A-Z0-9])"), 1080),
        ((r"(?<![A-Z0-9])960P(?![A-Z0-9])",), 960),
        ((r"(?<![A-Z0-9])720P(?![A-Z0-9])", r"(?<![A-Z0-9])HD(?![A-Z0-9])"), 720),
    )
    for patterns, height in pattern_height_map:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return height
    # 文件名尾部的 4K 扩展标记单独处理，如 IPZZ-841_4K60FPS / IPZZ-841_4KS。
    if re.search(r"(?:^|[-_ .\[])(?:4K60FPS|4KS)(?=\.[^.\\/]+$)", normalized_name):
        return 2000
    # 无码破解标记和 4K 紧贴时也保留 4K 识别，如 JUR-615-U4K / JUR-615-UC4K。
    if re.search(r"(?:^|[-_ .\[])U(?:C)?-?4K(?=\.[^.\\/]+$)", normalized_name):
        return 2000
    return 0


async def get_video_size(file_path: Path, file_number: str = ""):
    """
    获取视频分辨率和编码格式

    Args:
        file_path (Path): 视频文件的完整路径

    Returns:
        definition,codec (tuple[str, str]): 视频分辨率, 编码格式
    """
    # 获取本地分辨率 同时获取视频编码格式
    definition = ""
    height = 0
    hd_get = manager.config.hd_get
    if await aiofiles.os.path.islink(file_path):
        if NoEscape.SYMLINK_DEFINITION in manager.config.no_escape:
            file_path = file_path.resolve()
        else:
            hd_get = "path"
    codec = ""
    if hd_get == "video":
        try:
            height, codec = await asyncio.to_thread(get_video_metadata, file_path)
        except Exception as e:
            log_console.log_text(f" 🔴 无法获取视频分辨率! 文件地址: {file_path}  错误信息: {e}")
    elif hd_get == "path":
        height = _detect_height_from_path(file_path, file_number)

    definition = _definition_from_height(height)

    return definition, codec


def _definition_from_height(height: int) -> str:
    """将视频高度映射为配置对应的清晰度名称。"""
    if not height:
        return ""
    hd_name = manager.config.hd_name
    if height >= 4000:
        return "8K" if hd_name == "height" else "UHD8"
    if height >= 2000:
        return "4K" if hd_name == "height" else "UHD"
    if height >= 1400:
        return "1440P" if hd_name == "height" else "QHD"
    if height >= 1000:
        return "1080P" if hd_name == "height" else "FHD"
    if height >= 900:
        return "960P" if hd_name == "height" else "HD"
    if height >= 700:
        return "720P" if hd_name == "height" else "HD"
    if height >= 500:
        return "540P" if hd_name == "height" else "qHD"
    if height >= 400:
        return "480P"
    if height >= 300:
        return "360P"
    if height >= 100:
        return "144P"
    return ""


def _mediainfo_video_height(data) -> int:
    """从 MediaInfo JSON 中递归查找视频轨高度。"""
    if isinstance(data, dict):
        track_type = str(data.get("@type") or data.get("type") or "").lower()
        if "video" in track_type:
            for key in ("Height", "height", "Video_Height", "video_height"):
                value = data.get(key)
                if value is not None:
                    match = re.search(r"\d+", str(value).replace(" ", ""))
                    if match:
                        return int(match.group())
        for value in data.values():
            height = _mediainfo_video_height(value)
            if height:
                return height
    elif isinstance(data, list):
        for value in data:
            height = _mediainfo_video_height(value)
            if height:
                return height
    return 0


def _mediainfo_codec(data) -> str:
    """从 MediaInfo JSON 中提取常见视频编码。"""
    codec_map = {
        "avc": "H264",
        "h264": "H264",
        "hevc": "HEVC",
        "h265": "HEVC",
        "vp9": "VP9",
        "av1": "AV1",
        "mpeg4": "MPEG4",
    }
    text = json.dumps(data, ensure_ascii=False)
    match = re.search(r'"Format"\s*:\s*"([^"]+)"', text)
    if match:
        return codec_map.get(match.group(1).strip().lower(), "")
    return ""


async def _get_mediainfo_size(file_path: Path, file_number: str = "") -> tuple[str, str]:
    """读取同目录 ``<文件名>-mediainfo.json`` 或 ``<番号>-mediainfo.json``。"""
    candidates = [f"{file_path.stem}-mediainfo.json"]
    if file_number and file_number.casefold() != file_path.stem.casefold():
        candidates.append(f"{file_number}-mediainfo.json")
    mediainfo_path: Path | None = None
    for name in candidates:
        candidate = file_path.with_name(name)
        try:
            candidate_is_file = await aiofiles.os.path.isfile(candidate)
        except OSError:
            candidate_is_file = False
        if candidate_is_file:
            mediainfo_path = candidate
            break
    if mediainfo_path is None:
        # 网络盘可能大小写敏感，按实际文件名再找一次。
        wanted = {name.casefold() for name in candidates}
        try:
            for name in await aiofiles.os.listdir(file_path.parent):
                if name.casefold() in wanted:
                    mediainfo_path = file_path.parent / name
                    break
        except OSError:
            pass
    if mediainfo_path is None:
        return "", ""
    try:
        async with aiofiles.open(mediainfo_path, encoding="utf-8") as f:
            content = await f.read()
        data = json.loads(content)
    except OSError, ValueError:
        return "", ""
    height = _mediainfo_video_height(data)
    if not height:
        match = re.search(r'"(?:Height|height)"\s*:\s*"?([0-9 ]+)"?', content)
        if match:
            height = int(match.group(1).replace(" ", ""))
    return _definition_from_height(height), _mediainfo_codec(data)


async def get_video_size_for_file(file_path: Path, file_number: str = "") -> tuple[str, str]:
    """获取视频/STRM 的清晰度与编码。

    STRM 本身不是视频，优先读取其指向的本地视频；无法访问时（网盘链接、
    URL 等）退回到 STRM 文件名/路径中的分辨率标记，最后读取同名或同番号的
    ``-mediainfo.json``。整理模式只移动文件、不联网，因此该链路不回退到刮削。
    """
    target_path: Path | None = file_path
    path_fallback = file_path
    if file_path.suffix.lower() == ".strm":
        target_path = None
        try:
            async with aiofiles.open(file_path, encoding="utf-8-sig") as f:
                content = await f.read()
            for line in content.splitlines():
                target_text = line.strip()
                if not target_text or target_text.startswith("#"):
                    continue
                if "://" in target_text:
                    # 网盘链接无法直接探测，退回到 URL 文件名中的分辨率标记。
                    url_name = unquote(Path(urlparse(target_text).path).name)
                    if url_name:
                        path_fallback = file_path.parent / url_name
                else:
                    target = Path(target_text)
                    if not target.is_absolute():
                        target = file_path.parent / target
                    path_fallback = target
                    if await aiofiles.os.path.exists(target):
                        target_path = target
                break
        except OSError:
            pass

    definition, codec = "", ""
    if target_path is not None:
        definition, codec = await get_video_size(target_path, file_number)
    if not definition:
        mediainfo_definition, mediainfo_codec = await _get_mediainfo_size(file_path, file_number)
        definition = mediainfo_definition
        codec = codec or mediainfo_codec
    if not definition:
        definition = _definition_from_height(_detect_height_from_path(path_fallback, file_number))
    return definition, codec


def add_definition_tag(res: BaseCrawlerResult, definition, codec):
    remove_key = ["144P", "360P", "480P", "540P", "720P", "960P", "1080P", "1440P", "2160P", "4K", "8K"]
    tag = res.tag
    for each_key in remove_key:
        tag = tag.replace(each_key, "").replace(each_key.lower(), "")
    tag_list = re.split(r"[,，]", tag)
    new_tag_list = []
    for i in tag_list:
        if i:
            new_tag_list.append(i)
    if definition and TagInclude.DEFINITION in manager.config.nfo_tag_include:
        new_tag_list.insert(0, definition)
        if manager.config.hd_get == "video" and codec and codec not in new_tag_list:
            new_tag_list.insert(0, codec)  # 插入编码格式
    res.tag = ",".join(new_tag_list)


def show_result(res: CrawlersResult, start_time: float):
    LogBuffer.log().write(res.site_log)
    # 议题 #98-3：逐字段来源排障块归过程明细通道（show_web_log 控制）；
    # show_from_log 本身不再触发逐字段展开，开启时输出保持 [website] 站点摘要精简形态
    if manager.config.show_web_log and res.field_log:
        LogBuffer.web().write("\n\n 📒 字段来源\n\n" + res.field_log.strip(" ").strip("\n"))
    LogBuffer.log().write(f"\n 🍀 Data done!({get_used_time(start_time)}s)")
