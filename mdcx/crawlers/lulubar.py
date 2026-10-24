#!/usr/bin/env python3

import re
from dataclasses import dataclass
from typing import override

from lxml import etree
from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year

_DEFAULT_BASE_URL = "https://www.lulubar.co"


def _absolute_url(url: str, base_url: str = "") -> str:
    """把站点返回的相对地址补全为绝对地址，已是绝对地址时原样返回."""
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.lower().startswith(("http://", "https://")):
        return url
    base = (base_url or _DEFAULT_BASE_URL).rstrip("/")
    return base + (url if url.startswith("/") else "/" + url)


def _matches_number(text: str, number: str) -> bool:
    """按番号整词匹配，兼容标题前缀/后缀和大小写，避免 IPZZ-5470 误命中 IPZZ-547."""
    target = str(number or "").strip().upper()
    if not target:
        return False
    pattern = rf"(?<![0-9A-Z]){re.escape(target)}(?![0-9A-Z])"
    return re.search(pattern, str(text or "").upper()) is not None


def get_web_number(html, number):
    result = html.xpath("//dt[contains(text(),'作品番号')]/following-sibling::dd/text()")
    return result[0].strip() if result else number


def get_title(html):
    try:
        result = html.xpath("//title/text()")[0].split("|")
        number = result[0].strip()
        title = result[1].replace(number, "").strip()
        if not title or "撸撸吧" in title:
            title = number
        return title, number
    except Exception:
        return "", ""


def get_actor(html):
    actor_list = html.xpath('//a[@title="女优"]/text()')
    actor_new_list = []
    for a in actor_list:
        if a.strip():
            actor_new_list.append(a.strip())
    return ",".join(actor_new_list) if actor_new_list else ""


def get_studio(html):
    result = html.xpath("string(//div[contains(@class,'tag_box')]/a[@title='片商'])")
    return result.strip()


def get_extrafanart(html, base_url: str = ""):
    result = html.xpath('//div[@id="stills"]//img/@src')
    if not result:
        result = html.xpath('//div[@id="lightgallery"]//a/@href')
    return [_absolute_url(src, base_url) for src in result if src]


def get_release(html):
    result = html.xpath("//a[contains(@title,'上架日')]/@title")
    return result[0].replace("上架日", "").strip() if result else ""


def get_mosaic(html):
    result = html.xpath('//div[contains(@class,"tag_box")]/a[@class="tag"]/text()')
    total = ",".join(result)
    mosaic = ""
    if "有码" in total:
        mosaic = "有码"
    elif "国产" in total:
        mosaic = "国产"
    elif "无码" in total:
        mosaic = "无码"
    return mosaic


def get_tag(html):
    result = html.xpath('//div[contains(@class,"tag_box")]/a[@class="tag" and contains(@href,"bytagdetail")]/text()')
    new_list = []
    for a in result:
        new_list.append(a.strip())
    return ",".join(new_list)


def get_cover(html, base_url: str = ""):
    # 新版详情页把封面放在播放器 poster 的 background-image 里（pl.jpg 大图）
    for style in html.xpath('//div[contains(@class,"plyr__poster")]/@style'):
        match = re.search(r'url\(["\']?([^"\')]+)', style)
        if match:
            return _absolute_url(match.group(1), base_url)
    # 旧版详情页封面锚点，img 可能被额外容器包裹
    for src in html.xpath('//a[contains(@class,"notVipAd")]//img/@src'):
        if src:
            return _absolute_url(src, base_url)
    # 兜底使用 og:image（ps.jpg 竖版封面）
    for content in html.xpath('//meta[@property="og:image"]/@content'):
        if content:
            return _absolute_url(content, base_url)
    return ""


def get_outline(html):
    a = html.xpath('//p[@class="video_container_info"]/text()')
    return a[0] if a else ""


def get_real_url(html, number, base_url: str = ""):
    # 新版搜索页的 img 被包在 div.img_frame 里，不能再用直接子节点 img 取属性
    for each in html.xpath('//a[contains(@class,"imgBoxW")]'):
        href = each.get("href")
        if not href:
            continue
        images = each.xpath(".//img")
        image = images[0] if images else None
        alt = image.get("alt") if image is not None else ""
        title = alt or each.get("title") or " ".join(each.xpath(".//text()"))
        if not _matches_number(title, number):
            continue
        poster = ""
        if image is not None:
            poster = image.get("data-src") or image.get("data-original") or image.get("src") or ""
        return _absolute_url(href, base_url), _absolute_url(poster, base_url)
    return "", ""


@dataclass
class LulubarContext(Context):
    search_poster: str = ""


class LulubarCrawler(BaseCrawler[LulubarContext]):
    description = "综合：仅限有码"
    probe_number = "IPZZ-547"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.LULUBAR

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.LULUBAR, "https://www.lulubar.co")

    @classmethod
    @override
    def display_name(cls) -> str:
        return "Lulubar"

    @override
    def new_context(self, input: CrawlerInput) -> LulubarContext:
        return LulubarContext(input=input)

    @override
    async def _generate_search_url(self, ctx: LulubarContext) -> list[str] | str | None:
        return f"{self.base_url}/video/bysearch?search={ctx.input.number}&page=1"

    @override
    async def _parse_search_page(self, ctx: LulubarContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url, poster = get_real_url(search_page, ctx.input.number, self.base_url)
        if not detail_url:
            ctx.debug("lulubar 搜索页没有匹配结果")
            return None
        ctx.search_poster = poster
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: LulubarContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        title, number = get_title(detail_page)
        if not title:
            raise CrawlerException("数据获取失败: 未获取到 title！")
        actor = get_actor(detail_page)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tag = get_tag(detail_page)
        release = get_release(detail_page)
        # DMM 高清直链升级（横版+竖版，无码番号内部跳过）
        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        thumb, upgraded_poster = await upgrade_dmm_cover(ctx, number, get_cover(detail_page, self.base_url), "")
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=get_outline(detail_page),
            originalplot="",
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=get_year(release),
            studio=get_studio(detail_page),
            thumb=thumb,
            poster=upgraded_poster or ctx.search_poster,
            extrafanart=get_extrafanart(detail_page, self.base_url),
            trailer="",
            image_download=False,
            mosaic=get_mosaic(detail_page),
            external_id=detail_url,
        )
