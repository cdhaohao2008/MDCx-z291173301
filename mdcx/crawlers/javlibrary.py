#!/usr/bin/env python3
import re
import urllib.parse
from typing import override

from lxml import etree

from ..base.web import _JAVLIBRARY_DOMAINS, get_javlibrary_domain
from ..cf_bypass.selenium_adapter import is_cf_html as is_selenium_cf_html
from ..config.enums import Language, Website
from ..config.manager import manager
from ..gen.field_enums import CrawlerResultFields
from ..models.model_types import CrawlerResult
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year
from .base.base_types import split_csv


def _xpath_joined_text(html, xpath: str) -> str:
    return ",".join(text.strip() for text in html.xpath(xpath) if text and text.strip())


def is_match(text: str, number: str) -> bool:
    """标题/文本与番号匹配判定。

    两侧归一对齐：javlibrary 页面标题形如 FC2-PPV-1234567（剥横杠后 FC2PPV1234567），
    FC2 番号侧同样剥 "PPV"——否则恒不匹配，搜索兜底对 FC2 番号必然失败（全库审查 A5）。
    """
    normalized = number.strip().replace("-", "").upper().replace("PPV", "", 1) + " "
    return normalized in text.replace("-", "").upper().replace("PPV", "", 1)


def get_real_url(html, number, domain_2):
    real_url = ""
    origin = urllib.parse.urlsplit(domain_2)._replace(path="", query="", fragment="").geturl()
    result = html.xpath('//div[@id="video_title"]/h3/a/text()')

    for each in result:
        if is_match(each, number):
            hrefs = html.xpath('//div[@id="video_title"]/h3/a[contains(text(), $title)]/@href', title=each)
            if hrefs:
                return urllib.parse.urljoin(origin, hrefs[0])
            return ""
    result = html.xpath('//a[contains(@href, "/?v=jav")]/@title')

    for each in result:
        if is_match(each, number):
            hrefs = html.xpath("//a[@title=$title]/@href", title=each)
            if hrefs:
                real_url = hrefs[0]
            real_url = urllib.parse.urljoin(domain_2 + "/", real_url)
            if "ブルーレイディスク" not in each:
                return real_url
    if real_url:
        return real_url
    return ""


def get_title(html):
    result = html.xpath('//div[@id="video_title"]/h3/a/text()')
    return result[0].strip() if result else ""


def get_number(html, number):
    result = html.xpath('//div[@id="video_id"]//td[@class="text"]/text()')
    return result[0] if result else number


def get_actor(html):
    return _xpath_joined_text(html, '//div[@id="video_cast"]//span[@class="star"]/a/text()')


def get_cover(html):
    result = html.xpath("//img[@id='video_jacket_img']/@src")
    return ("https:" + result[0] if "http" not in result[0] else result[0]) if result else ""


def get_tag(html):
    return _xpath_joined_text(html, '//div[@id="video_genres"]//td[@class="text"]//span/a/text()')


def get_release(html):
    return _xpath_joined_text(html, '//div[@id="video_date"]//td[@class="text"]/text()')


def get_studio(html):
    result = html.xpath('//div[@id="video_maker"]//td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_publisher(html):
    result = html.xpath('//div[@id="video_label"]//td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_runtime(html):
    result = html.xpath('//div[@id="video_length"]//span[@class="text"]/text()')
    return result[0] if result else ""


def get_score(html):
    results = html.xpath('//div[@id="video_review"]//span[@class="score"]/text()')
    for raw in results:
        # 真实页面多为 pretty-printed HTML，文本节点常带换行缩进
        # （如 "\n  (8.13)\n"），必须先 strip 空白再去括号，
        # 否则旧写法 .strip("()") 原样返回，float() 失败导致漏抓
        text = (raw or "").strip().strip("()").strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return text
    # 兜底：review 块整体文本中找括号包裹的数字（兼容 span 缺失或嵌套变体）
    try:
        block = html.xpath('string(//div[@id="video_review"])')
    except Exception:
        block = ""
    if block:
        match = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*\)", block)
        if match:
            return match.group(1)
    return ""


def get_director(html):
    result = html.xpath('//div[@id="video_director"]//td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_wanted(html):
    result = html.xpath('//a[contains(@href, "userswanted.php?")]/text()')
    return str(result[0]) if result else ""


def normalize_language(language: Language | str) -> Language:
    if isinstance(language, Language):
        return language
    try:
        return Language(language)
    except ValueError:
        return Language.ZH_CN


def language_path(language: Language) -> str:
    if language == Language.ZH_CN:
        return "cn"
    if language == Language.ZH_TW:
        return "tw"
    return "ja"


class JavLibraryCrawler(BaseCrawler):
    description = "有码：仅限有码"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVLIBRARY

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVLIBRARY, "https://www.javlibrary.com")

    @classmethod
    @override
    def display_name(cls) -> str:
        return "JavLibrary"

    @classmethod
    @override
    def known_hosts(cls) -> frozenset[str]:
        """javlibrary 额外并入静态镜像表与运行时学习到的最新直连域名（议题 #83）。"""
        from urllib.parse import urlparse

        from ..base.web import _JAVLIBRARY_DOMAINS, _get_cached_javlibrary_domain

        hosts = set(super().known_hosts())
        for url in [*_JAVLIBRARY_DOMAINS, _get_cached_javlibrary_domain()]:
            host = urlparse(str(url)).netloc.lower().split(":", 1)[0]
            if host:
                hosts.add(host)
                if host.startswith("www."):
                    hosts.add(host[4:])
        return frozenset(hosts)

    @classmethod
    @override
    async def check_urls(cls) -> list[str]:
        urls: list[str] = []
        try:
            latest = await get_javlibrary_domain()
            if latest and latest not in urls:
                urls.append(latest)
        except Exception:
            pass
        for candidate in _JAVLIBRARY_DOMAINS:
            if candidate not in urls:
                urls.append(candidate)
        return urls or [cls.base_url_()]

    @property
    def use_proxy(self) -> bool:
        return not manager.config.get_site_config(Website.JAVLIBRARY).custom_url

    def _needs_localized_language(self) -> Language | None:
        field_languages = [
            manager.config.get_field_config(field).language
            for field in (
                CrawlerResultFields.TITLE,
                CrawlerResultFields.OUTLINE,
                CrawlerResultFields.ACTORS,
                CrawlerResultFields.TAGS,
                CrawlerResultFields.SERIES,
                CrawlerResultFields.STUDIO,
            )
        ]
        if Language.ZH_CN in field_languages:
            return Language.ZH_CN
        if Language.ZH_TW in field_languages:
            return Language.ZH_TW
        return None

    @override
    def __init__(self, client, base_url: str = "", browser=None):
        super().__init__(client, base_url=base_url, browser=browser)
        self._explicit_base_url = bool(base_url)

    @override
    async def _run(self, ctx: Context):
        # 未显式指定 base_url 且未配置自定义 URL 时，动态获取 javlibrary 最新直连地址
        # （github.com/javlibcom），避免 javlibrary.com 主站被墙时刮削失败。
        if not self._explicit_base_url and not manager.config.get_site_config(Website.JAVLIBRARY).custom_url:
            try:
                latest_domain = await get_javlibrary_domain()
                if latest_domain and latest_domain != self.base_url:
                    ctx.debug(f"使用 javlibrary 直连地址: {latest_domain}")
                    self.base_url = latest_domain
            except Exception as e:
                ctx.debug(f"获取 javlibrary 直连地址失败，使用默认: {e}")

        requested_language = normalize_language(ctx.input.language)
        jp_url = ctx.input.appoint_url.replace("/cn/", "/ja/").replace("/tw/", "/ja/")
        jp_data = await self._scrape_language(ctx, Language.JP, jp_url)
        target_language = requested_language if requested_language in {Language.ZH_CN, Language.ZH_TW} else None
        target_language = target_language or self._needs_localized_language()  # type: ignore[assignment]
        if not target_language:
            result = jp_data.to_result()
            result.source = self.site().value
            ctx.debug("数据获取成功！")
            return result

        localized_url = ""
        if isinstance(jp_data.external_id, str) and jp_data.external_id:
            localized_url = jp_data.external_id.replace("/ja/", f"/{language_path(target_language)}/")
        localized_data = await self._scrape_language(ctx, target_language, localized_url)
        localized_data.originaltitle = jp_data.originaltitle or jp_data.title
        localized_data.originalplot = jp_data.originalplot or jp_data.outline
        result = localized_data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    async def _scrape_language(self, ctx: Context, language: Language, appoint_url: str = "") -> CrawlerData:
        number = ctx.input.number
        lang_path = language_path(language)
        domain_2 = f"{self.base_url}/{lang_path}"
        real_url = appoint_url
        # 浏览器 bypass 解出的 cookie：搜索页带上后，详情页直连大概率直接 200，省一次解挑战
        search_cookies: dict[str, str] = {}
        if not real_url:
            search_url = f"{domain_2}/vl_searchbyid.php?keyword={number}"
            ctx.debug(f"搜索地址[{language.value}]: {search_url}")
            ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), search_url]
            html_search, error = await self.async_client.get_text(search_url, use_proxy=self.use_proxy)
            if html_search is None or is_selenium_cf_html(html_search):
                ctx.debug(f"搜索页遇 CF challenge，尝试浏览器 bypass: {search_url}")
                bypass_html, bypass_cookies = await self._browser_bypass(ctx, search_url)
                if bypass_html:
                    html_search = bypass_html
                    search_cookies = bypass_cookies
                    if search_cookies:
                        ctx.debug(f"浏览器 cookie 已透传到详情请求（{len(search_cookies)} 个）")
                    else:
                        ctx.debug("浏览器未带回可用 cookie，详情页仍裸请求")
                    # 钉住当前池指纹：详情直连（带透传 cookie）沿用同一指纹，避免轮换导致再挑战
                    pin = getattr(self.async_client, "pin_current_fingerprint", None)
                    if callable(pin):
                        try:
                            if pin(search_url, use_proxy=self.use_proxy):
                                ctx.debug("当前池指纹已钉住，详情请求沿用同一指纹")
                        except Exception as e:
                            ctx.debug(f"指纹钉住失败（不影响继续）: {e}")
                elif html_search is None:
                    raise CrawlerException(f"请求错误:{error}")
                else:
                    raise CrawlerException("搜索结果: 被 Cloudflare 拦截，浏览器 bypass 失败！")
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_url = get_real_url(html, number, domain_2)
            if not real_url:
                raise CrawlerException("搜索结果: 未匹配到番号！")

        ctx.debug(f"番号地址[{language.value}]: {real_url}")
        ctx.debug_info.detail_urls = [*(ctx.debug_info.detail_urls or []), real_url]
        if search_cookies:
            ctx.debug(f"详情页直连携带浏览器 cookie（{len(search_cookies)} 个）")
        html_info, error = await self.async_client.get_text(
            real_url, use_proxy=self.use_proxy, cookies=search_cookies or None
        )
        if html_info is None or is_selenium_cf_html(html_info):
            ctx.debug(f"详情页遇 CF challenge，尝试浏览器 bypass: {real_url}")
            bypass_html, _ = await self._browser_bypass(ctx, real_url)
            if bypass_html:
                html_info = bypass_html
            elif html_info is None:
                raise CrawlerException(f"请求错误:{error}")
            else:
                raise CrawlerException("详情页: 被 Cloudflare 拦截，浏览器 bypass 失败！")

        html_detail = etree.fromstring(html_info, etree.HTMLParser())
        title = get_title(html_detail)
        if not title:
            raise CrawlerException("数据获取失败: 未获取到标题！")
        web_number = get_number(html_detail, number)
        title = title.replace(web_number + " ", "")
        release = get_release(html_detail)
        return CrawlerData(
            number=web_number,
            title=title,
            originaltitle=title,
            actors=split_csv(get_actor(html_detail)),
            outline="",
            originalplot="",
            tags=split_csv(get_tag(html_detail)),
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_detail),
            score=get_score(html_detail),
            series="",
            directors=split_csv(get_director(html_detail)),
            studio=get_studio(html_detail),
            publisher=get_publisher(html_detail),
            thumb=get_cover(html_detail),
            poster="",
            extrafanart=[],
            trailer="",
            image_download=False,
            mosaic="有码",
            external_id=real_url,
            wanted=get_wanted(html_detail),
        )

    async def _browser_bypass(self, ctx: Context, url: str) -> tuple[str | None, dict[str, str]]:
        """浏览器 CF bypass fallback：Selenium+Edge 第一顺位，Playwright+Edge 第二顺位。

        单次浏览器会话同时返回 HTML 与 cookie，调用方可把 cookie 透传给后续
        直连请求（省一次解挑战）。配置开关关闭或双后端都不可用时返回 (None, {})。
        """
        if not manager.config.cf_selenium_bypass:
            ctx.debug("浏览器 bypass 已在配置中关闭")
            return None, {}

        from ..cf_bypass.selenium_adapter import get_html_and_cookies as selenium_get
        from ..cf_bypass.selenium_adapter import is_available as selenium_available
        from ..cf_bypass.selenium_adapter import is_cf_html

        if selenium_available():
            try:
                html, cookies = await selenium_get(url)
                if html and not is_cf_html(html):
                    ctx.debug(f"Selenium bypass 成功（带回 {len(cookies)} 个 cookie）")
                    return html, cookies
                ctx.debug("Selenium bypass 后仍含 CF 标记，换 Playwright 再试")
            except Exception as e:
                ctx.debug(f"Selenium bypass 异常: {e}，换 Playwright 再试")
        else:
            ctx.debug("Selenium bypass 不可用（无 Edge 或 selenium 未安装），换 Playwright 再试")

        from ..cf_bypass.playwright_adapter import get_html_and_cookies as playwright_get
        from ..cf_bypass.playwright_adapter import is_available as playwright_available

        if not playwright_available():
            ctx.debug("Playwright bypass 不可用（无 Edge 或 playwright 未安装）")
            return None, {}

        try:
            html, cookies = await playwright_get(url)
            if html and not is_cf_html(html):
                ctx.debug(f"Playwright bypass 成功（带回 {len(cookies)} 个 cookie）")
                return html, cookies
            ctx.debug("Playwright bypass 后仍含 CF 标记")
            return None, {}
        except Exception as e:
            ctx.debug(f"Playwright bypass 异常: {e}")
            return None, {}

    @override
    async def post_process(self, ctx: Context, res: CrawlerResult) -> CrawlerResult:
        """DMM 高清封面升级，与 JavBus/JavDB 对齐。"""
        number = (res.number or "").strip()
        if number and not number.startswith("FC2"):
            from ..crawlers.dmm_direct import is_uncensored_number, upgrade_dmm_cover

            if not is_uncensored_number(number):
                thumb, poster = await upgrade_dmm_cover(ctx, number, res.thumb, res.poster)
                res.thumb = thumb
                res.poster = poster
        return res

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
