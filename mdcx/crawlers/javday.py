#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override
from urllib.parse import parse_qs, quote, urljoin, urlparse

import zhconv
from lxml import etree
from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData, CrawlerException
from .guochan import get_actor_list, get_lable_list, get_number_list

# 国产短剧（DUANJU）条目本身没有番号，JavDay 只给站内随机 ID（/videos/Gb5WuoJw/），
# 所以锁定刮削类型选「短剧」时拿不到番号，只能改走站内搜索页按标题（剧名）找页面。
JAVDAY_SEARCH_PATH = "/search/"
# 标题关键词最多探几个（文件名往往能切出多个变体），结果页最多取几个候选详情页。
MAX_TITLE_SEARCH_KEYWORDS = 3
MAX_TITLE_SEARCH_RESULTS = 5
# 相似度低于这条线的搜索结果直接丢弃：只共用一两个字（「的」「人」这种）的纯属沾边，
# 抓回来等于给用户换了一部不相干的短剧，宁可报搜索失败。
MIN_TITLE_MATCH_SCORE = 20.0
# 文件名里的噪声片段：分辨率/画质/语言/版本标记，不是剧名的一部分，搜索时要剔掉。
_NOISE_TOKEN_RE = re.compile(
    r"^(?:\d{3,4}[pP]|[248]K|UHD|FHD|HD|BD|DV|x\d{3,4}|"
    r"高清|超清|蓝光|原盘|修复|完整版|未删减|无删减|无码|有码|破解|"
    r"中字|中文字幕|字幕|国语|粤语|日语|英语|uncensored|hd|bd)$"
)


def normalize_title_key(text: str) -> str:
    """标题归一化：繁转简、去空白与标点、转小写，供标题相似度比较。"""
    return re.sub(r"[^\w一-鿿]+", "", zhconv.convert(text or "", "zh-cn")).lower()


def clean_title_keyword(text: str) -> str:
    """把文件名切成搜索关键词：去掉括号内容与分辨率/画质/语言等噪声片段。

    「继母与女儿.国语.1080P.mp4」→「继母与女儿」。JavDay 的搜索按整串匹配，
    带着「1080P」「国语」去搜会明显变差，故清洗后的变体排在原始变体前面。
    清洗后什么都没剩下（文件名全是噪声）时返回空串，由调用方回退用原名。
    """
    text = re.sub(r"[【】\[\]（）()]+", " ", text or "")
    parts = [part for part in re.split(r"[.\s_\-–—+、]+", text) if part]
    kept = [part for part in parts if not _NOISE_TOKEN_RE.match(part)]
    return " ".join(kept)


def title_match_score(keyword: str, title: str) -> float:
    """搜索词与结果标题的相似度（0 表示毫无共同字）。

    JavDay 的搜索是模糊匹配（搜「继母与女儿」会返回一堆只是沾边的短剧），
    因此不能把结果原样交给详情页解析——那等于随便抓一部。评分口径：
      1. 完全相同          → 100
      2. 一方包含另一方    → 80 + 较短一方长度（余下字越多越像）
      3. 较短一方的字覆盖率 → 0~50（共用字 / 较短一方去重字数）
    低于 MIN_TITLE_MATCH_SCORE 的结果直接丢弃，不去请求它的详情页。
    """
    key = normalize_title_key(keyword)
    title = normalize_title_key(title)
    if not key or not title:
        return 0.0
    if key == title:
        return 100.0
    if key in title or title in key:
        return 80.0 + min(len(key), len(title))
    common = len(set(key) & set(title))
    if not common:
        return 0.0
    return 50.0 * common / min(len(set(key)), len(set(title)))


def get_title(html):
    result = html.xpath('//*[@id="videoInfo"]/div/h1')
    return result[0].text if result else ""


def get_some_info(html, title, file_path):
    series_list = html.xpath('//*[@id="videoInfo"]/div/div/p[3]/span[2]/a/text()')
    tag_list = html.xpath('//*[@id="videoInfo"]/div/div/p[1]/span[2]/a/text()')
    actor_list = html.xpath('//*[@id="videoInfo"]/div/div/p[1]/span[2]/a/text()')

    series = series_list[0] if series_list else ""
    tag = ",".join(tag_list)
    actor_fake_name = any("未知" in item for item in actor_list)
    actor_list = [] if actor_fake_name else actor_list
    if not actor_list:
        all_info = title + series + tag + file_path
        all_actor = get_actor_list()
        for each in all_actor:
            if each in all_info:
                actor_list.append(each)
    new_actor_list = []
    [new_actor_list.append(i) for i in actor_list if i and i not in new_actor_list]

    return series, ",".join(tag_list), ",".join(new_actor_list)


def get_studio(series, tag, lable_list):
    word_list = [series]
    word_list.extend(tag.split(","))
    for word in word_list:
        if word in lable_list:
            return word
    return ""


def get_cover(html, javday_url):
    # 语义定位替代绝对位置 meta[8]：页面 head 增删任一 meta（统计脚本/SEO）
    # 都会让 meta[8] 指向无关元素，静默产出错误封面 URL（全库审查 C3）
    result = html.xpath("//meta[@property='og:image']/@content")
    if not result:
        result = html.xpath("//meta[contains(@name, 'image')]/@content")
    if result:
        result = result[0]
        if "http" not in result:
            result = javday_url + result
    return result if result else ""


def get_tag(html):
    result = html.xpath('//div[@class="category"]/a[contains(@href, "/class/")]/text()')
    return ",".join(result)


def get_real_number_title(
    number, title, number_list, appoint_number, appoint_url, lable_list, tag, actor, series, file_path_text=""
):
    if appoint_number:
        number = appoint_number
        temp_title = title.replace(number, "")
        if len(temp_title) > 4:
            title = temp_title
    else:
        if number not in number_list or appoint_url:
            title_number_list, filename_list = get_number_list(number, appoint_number, file_path_text)
            if title_number_list:
                number = title_number_list[0]
                number_list = title_number_list

        if number in number_list:
            if number != title:
                title = title.replace(number, "").replace(number.lower(), "")
            if "-" not in number:
                if re.search(r"[A-Z]{4,}\d{2,}", number):
                    result = re.search(r"([A-Z]{4,})(\d{2,})", number)
                    number = result[1] + "-" + result[2]
                else:
                    result = re.search(r"\d{3,}", number)
                    if result:
                        number = number.replace(result[0], "-" + result[0])
            if number != title:
                title = title.replace(number, "")
        else:
            number = title
    temp_title = get_real_title(title, number_list, lable_list, tag, actor, series)
    if number == title:
        number = temp_title

    cd = re.findall(r"((AV|EP)\d{1})", title.upper())
    if cd and cd[0][0] not in number:
        number = number + " " + cd[0][0]

    return number, temp_title


def get_real_title(title, number_list, lable_list, tag, actor, series):
    for number in number_list:
        title = title.replace(number, "")

    title_list = re.split("[. ]", title)
    if len(title_list) > 1:
        for key in lable_list:
            for each in title_list:
                if key in each:
                    title_list.remove(each)
        if title_list[-1].lower() == "x":
            title_list.pop()
        title = " ".join(title_list)
    for each in tag.split(","):
        if each:
            title = title.replace("" + each, "")
    for each in actor.split(","):
        if each:
            title = title.replace(" " + each, "")
    title = title.lstrip(series + " ").replace("..", ".").replace("  ", " ")

    return title.replace(" x ", "").replace(" X ", "").strip(" -.")


@dataclass
class JavDayContext(Context):
    label_list: list[str] = field(default_factory=list)
    number_list: list[str] = field(default_factory=list)
    file_path_text: str = ""


class JavDayCrawler(BaseCrawler[JavDayContext]):
    description = "综合：有码+无码+短剧+国产"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVDAY

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVDAY, "https://www.javday.app")

    @classmethod
    @override
    def display_name(cls) -> str:
        return "JavDay"

    @override
    def new_context(self, input: CrawlerInput) -> JavDayContext:
        file_path = str(input.file_path or "")
        number_list, filename_list = get_number_list(input.number, input.appoint_number, file_path)
        return JavDayContext(
            input=input,
            label_list=get_lable_list(),
            number_list=number_list,
            file_path_text=file_path,
        )

    @override
    async def _generate_search_url(self, ctx: JavDayContext) -> list[str] | str | None:
        number_list, filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, ctx.file_path_text)
        if number_list:
            total_number_list = number_list + filename_list
            number_candidates = list(set(total_number_list))
            number_candidates.sort(key=total_number_list.index)
            return [f"{self.base_url}/videos/{number}/" for number in number_candidates]
        # 取不到番号：国产短剧就是这种（条目无番号、文件名千奇百怪没有统一格式），
        # 改按标题搜 JavDay 站内搜索页，从结果里挑标题最接近的详情页。
        return self._title_search_urls(ctx, filename_list)

    def _title_search_urls(self, ctx: JavDayContext, filename_list: list[str]) -> list[str]:
        """按标题关键词拼 JavDay 站内搜索页 URL（filename_list 已去转义并转简体）。

        清洗过的剧名排在原始文件名变体前面：JavDay 按整串匹配，带「1080P」「国语」
        去搜结果明显变差，而 _search 是「第一个有结果的搜索页就停」，所以顺序即优先级。
        """
        cleaned = [clean_title_keyword(item) for item in filename_list if item and item.strip()]
        keywords = [item for item in cleaned if item] + [
            item.strip() for item in filename_list if item and item.strip()
        ]
        if not keywords:
            number = str(ctx.input.number or "").strip()
            keywords = [number] if number else []
        if not keywords:
            return []
        keywords = list(dict.fromkeys(keywords))[:MAX_TITLE_SEARCH_KEYWORDS]
        ctx.debug(f"Javday 未识别到番号，改按标题搜索: {keywords}")
        return [f"{self.base_url}{JAVDAY_SEARCH_PATH}?q={quote(keyword)}" for keyword in keywords]

    @override
    async def _parse_search_page(self, ctx: JavDayContext, html: Selector, search_url: str) -> list[str] | str | None:
        if JAVDAY_SEARCH_PATH in urlparse(search_url).path:
            return self._parse_title_search_page(ctx, html, search_url)
        if "你似乎來到了沒有視頻存在的荒原" in html.get():
            ctx.debug(f"Javday 找不到番号: {search_url}")
            return None
        return [search_url]

    def _parse_title_search_page(self, ctx: JavDayContext, html: Selector, search_url: str) -> list[str] | None:
        """从站内搜索结果页挑出标题最接近搜索词的几个详情页，按相似度从高到低排。

        结果页是 `<a href="/videos/<随机ID>/" class="videoBox"><div class="videoBox-info">
        <span class="title">剧名</span>…`，页面底部还混着推荐位，故按标题相似度过滤后再排序，
        相似度为 0 的一律丢掉（否则等于随机抓一部不相干的短剧）。
        """
        keyword = (parse_qs(urlparse(search_url).query).get("q") or [""])[0]
        scored: list[tuple[float, str]] = []
        for item in html.css("a.videoBox"):
            href = (item.attrib.get("href") or "").strip()
            if not re.fullmatch(r"/videos/[^/]+/?", href):
                continue
            title = "".join(item.css(".videoBox-info .title::text").getall()).strip()
            score = title_match_score(keyword, title)
            if score < MIN_TITLE_MATCH_SCORE:
                continue
            scored.append((score, urljoin(self.base_url, href)))
        if not scored:
            ctx.debug(f"Javday 标题搜索无匹配结果: {search_url}")
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        picked = list(dict.fromkeys(url for _, url in scored))[:MAX_TITLE_SEARCH_RESULTS]
        ctx.debug(f"Javday 标题搜索「{keyword}」命中: {picked}")
        return picked

    @override
    async def _parse_detail_page(self, ctx: JavDayContext, html: Selector, detail_url: str) -> CrawlerData | None:
        html_info = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CrawlerException("获取失败: 没有获取到番号标题")
        series, tag, actor = get_some_info(html_info, title, ctx.file_path_text)
        cover_url = get_cover(html_info, self.base_url)
        studio = get_studio(series, tag, ctx.label_list)
        number, title = get_real_number_title(
            ctx.input.number,
            title,
            ctx.number_list,
            ctx.input.appoint_number,
            ctx.input.appoint_url,
            ctx.label_list,
            tag,
            actor,
            series,
            ctx.file_path_text,
        )
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        # DMM 高清直链升级（横版+竖版，无码番号内部跳过）
        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        cover_url, poster_url = await upgrade_dmm_cover(ctx, number, cover_url, "")
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release="",
            year="",
            runtime="",
            score="",
            series=series,
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster=poster_url,
            extrafanart=[],
            trailer="",
            image_download=False,
            mosaic="国产",
            external_id=detail_url,
        )
