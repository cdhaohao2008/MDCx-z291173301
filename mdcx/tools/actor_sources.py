"""
演员作品数据源：为「检查演员缺失番号」提供按演员拉取全部番号的能力。

站点清单有两条路（`build_sources(actor_type, use_config_sites=...)`）：

* **自动判断**（下拉框选「自动判断」）走 `_AUTO_SITE_ORDER` 里的固定站点链：
  有码 DMM→DMM_API→LibreDMM→JavDB→JavDB_API→JavDB_APP→Javlibrary·镜像→
  JavLibrary→JavBus；无码 AVSOX→JavDB→JavDB_API→JavDB_APP；
  FC2 AVSOX→FC2→FC2PPVDB→JavDB→JavDB_API→JavDB_APP；
  欧美 AVheat→ThepornDB→JavDB→JavDB_API→JavDB_APP；
  国产 IQQTV→Madou.club→Madouqu→JavDay；动漫 JavDB_APP→Getchu。
  类型本身按演员名后的 `(无码)(欧美)(国产)(动漫)(FC2)` 标注判断，未标注按有码。
* **指定类型**（下拉框选了有码/无码/个摄/欧美/传媒/动漫）走
  「软件设置 → 类型刮削网站 → 编辑网站」里对应那一组，组内顺序即优先级，
  **组内被禁用的站点照样参与查缺**（禁用只影响批量刮削）。

能按演员/关键字列出全部作品的站点登记在 `_SITE_FETCHERS`；配置里其余站点
（厂牌官网、聚合站等）没有这种入口，跳过并在日志里说明。

两个硬约束：

1. **每个站点最多重试一次**（首次 + 1 次重试，共 2 次请求机会），由
   `collect_numbers` 统一控制，各站点实现内部不再自行重试；
2. **各站点的番号先归一化再比较**：站点返回的形态五花八门（DMM 的
   `ssis00006`、JavDB 的 `SSIS-006`、FC2 的 `FC2-PPV-1234567`），统一经
   `normalize_key()` 折叠成比较键后，才与本地 number_list 比对。

每条记录还会带上站点顺带给的元数据（演员 / 发行日 / 时长），缺失表里直接用。

动漫 / FC2 没有「演员→作品」页可抓，这两类统一走关键字搜索，
所以用户填的是社团名/作品关键词（动漫）或卖家名（FC2），不是演员名。
"""

import asyncio
import json
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import quote, urljoin

from lxml import etree

from ..base.web import get_aio_domain, get_javlibrary_domain, get_javlibrary_mirror_domain
from ..config.enums import FixedScrapingType
from ..config.manager import manager
from ..config.models import SCRAPING_TYPE_SITE_FIELDS, Website
from ..log_console import log_console
from ..utils.domain_rotate import DomainRotator
from ..utils.site_url import strip_redundant_www

# ---------------------------------------------------------------------------
# 站点常量
# ---------------------------------------------------------------------------

_DMM = "https://www.dmm.co.jp"
_DMM_API = "https://api.dmm.com"
_LIBREDMM = "https://www.libredmm.com"
_JAVDB_FALLBACK = "https://javdb580.com"
_IQQTV_DOMAINS = ["https://iqqq3.quest", "https://iqq5.xyz", "https://iqqk4.quest"]
_FC2_BASE = "https://adult.contents.fc2.com"
_FC2PPVDB_BASE = "https://fc2ppvdb.com"
_FC2CMADB_BASE = "https://fc2cmadb.com"
_THEPORNDB_API = "https://api.theporndb.net"
_THEPORNDB_WEB = "https://theporndb.net"
_MADOU_CLUB = "https://madou.club"
_MADOUQU_FALLBACK = "https://madouqu.shop"
_JAVDAY_FALLBACK = "https://javday.app"
_GETCHU_FALLBACK = "http://getchu.com"

# 2026-10-25 实测（应用自身代理 + 真实 UA，逐个 GET 首页并校验页面内容）：
#   busjav.bond  → 5568 字节 JS 跳转壳（"Redirecting..."，非站点内容）
#   seejav.cyou  → 同上
#   javbus.bond  → 同上（HTTP/2 偶发 RST，重试后仍是跳转壳）
#   buscdn.bond  → HTTP 404
# 四个已删除，只保留实测能返回真实 JavBus 页面的 8 个。
_JAVBUS_DOMAINS = [
    "https://www.javbus.com",
    "https://www.dmmsee.casa",
    "https://www.cdnbus.bond",
    "https://www.javsee.cyou",
    "https://www.fanbus.bond",
    "https://www.busdmm.bond",
    "https://www.cdnbus.cyou",
    "https://www.dmmbus.bond",
]
_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6"}

# 每类最多用几个名字变体去试探（日文原名 / 繁中 / 用户输入）
_MAX_NAME_VARIANTS = 3
# 单个站点的翻页上限，防止异常页面导致无限翻页
_MAX_PAGES = 60


def _log(msg: str) -> None:
    log_console.log_text(msg)


# ---------------------------------------------------------------------------
# 软超时：让翻页循环到点自己收手，把已经拿到的番号带回来
# ---------------------------------------------------------------------------

_DEADLINE: ContextVar[float] = ContextVar("actor_source_deadline", default=0.0)


def _out_of_time() -> bool:
    """当前站点是否已用完时间预算（0 表示没有设置预算）。"""
    deadline = _DEADLINE.get()
    return bool(deadline) and time.monotonic() >= deadline


# ---------------------------------------------------------------------------
# 番号归一化
# ---------------------------------------------------------------------------

# 常见厂牌前缀（用于从标题/文件名里捞番号）
#
# 字母段与数字段之间**有分隔符**（`JN-4286`）或**无分隔符但数字 ≥3 位**（`SSIS006`）
# 才算番号：无分隔符又只有两位数字的，几乎都是「团体名 + 人数」——IQQTV 的
# 「SKE48的三上悠亚…」曾被抽成 `SKE-048` 这种假番号，故数字下限收到 3 位。
_NUMBER_IN_TEXT = re.compile(
    r"(?<![A-Z0-9])("
    r"FC2[-_ ]?(?:PPV)?[-_ ]?\d{5,8}"
    r"|[A-Z]{2,10}[-_ ]\d{2,6}(?:[-_]\d{1,4})?"
    r"|[A-Z]{2,10}\d{3,6}(?:[-_]\d{1,4})?"
    r"|1PONDO[-_ ]?\d{6}[-_ ]?\d{3}"
    r"|CARIBBEANCOM[-_ ]?\d{6}[-_ ]?\d{3}"
    r"|10MUSUME[-_ ]?\d{6}[-_ ]?\d{2}"
    r"|PACOPACOMAMA[-_ ]?\d{6}[-_ ]?\d{3}"
    r"|HEYZO[-_ ]?\d{3,4}"
    r"|HEYDOUGA[-_ ]?\d{4}[-_ ]?\d{3,4}"
    r")(?![0-9])",
    re.IGNORECASE,
)


def _pad_digits(digits: str) -> str:
    """编号段去前导零，但至少保留 3 位（DMM 的 00006 → 006）。"""
    stripped = digits.lstrip("0") or "0"
    return stripped.rjust(3, "0")


def normalize_key(number: str) -> str:
    """比较键：大写、去掉所有分隔符、FC2PPV 折叠成 FC2。

    本地 number_list 与各站点返回的番号都先过这里再比对，
    `SSIS-006` / `ssis006` / `SSIS 006` / `SSIS-00006` 视为同一个。
    """
    key = unicodedata.normalize("NFKC", str(number or "")).strip().upper()
    key = re.sub(r"[\s_\-\.]+", "", key)
    key = key.replace("FC2PPV", "FC2")
    # 纯字母 + 数字的编号段补零差异（SSIS00006 与 SSIS006）也折叠掉
    if m := re.fullmatch(r"([A-Z]{2,10})0*(\d{1,7})(\d{1,4})?", key):
        key = f"{m.group(1)}{m.group(2)}{m.group(3) or ''}"
    return key


def display_number(raw: str) -> str:
    """展示用番号：`ssis00006` / `ssis 6` / `SSIS_00006` 统一成 `SSIS-006`。

    认不出的形态原样大写返回，不猜——猜错比不猜更糟。
    """
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text).upper().replace("_", "-")
    text = re.sub(r"-{2,}", "-", text)
    if m := re.fullmatch(r"FC2-?(?:PPV-?)?(\d{4,8})", text):
        return f"FC2-{m.group(1)}"
    if m := re.fullmatch(r"([A-Z]{2,10})(\d{2,7})", text):
        return f"{m.group(1)}-{_pad_digits(m.group(2))}"
    if m := re.fullmatch(r"([A-Z]{2,10})-(\d{2,7})(-\d{1,4})?", text):
        return f"{m.group(1)}-{_pad_digits(m.group(2))}{m.group(3) or ''}"
    return text


def extract_numbers(text: str, *, require_separator: bool = False) -> list[str]:
    """从标题/文件名里捞出所有番号（已归一化为展示形态）。

    `require_separator=True` 时只认「字母 + 分隔符 + 数字」的标准写法（`TEK-067`），
    用于 IQQTV 这类标题里混着自造编号（`JN4286`）的站。
    """
    found: list[str] = []
    for raw in _NUMBER_IN_TEXT.findall(str(text or "")):
        if require_separator and not re.match(r"^[A-Z]{2,10}[-_ ]\d", raw, re.IGNORECASE):
            continue
        number = display_number(raw)
        if number and number not in found:
            found.append(number)
    return found


@dataclass(frozen=True, slots=True)
class NumberHit:
    """一条番号记录：番号 + 来自哪个站 + 该站的详情页地址 + 站点顺带给的元数据。

    actors / release / duration 只填站点列表页真的给出来的值（DMM_API 的演员表、
    JavDB 移动端的发行日与时长、AVSOX 的 releaseDate/length 等），拿不到就留空，
    由调用方决定要不要用「查询用的演员名」兜底。
    """

    number: str
    site: str
    url: str
    actors: str = ""  # 演员，多个用逗号分隔
    release: str = ""  # 发行日期 YYYY-MM-DD
    duration: str = ""  # 时长（分钟）


# ---------------------------------------------------------------------------
# HTTP 辅助（统一不重试，重试交给 collect_numbers 控制）
# ---------------------------------------------------------------------------


async def _http_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    encoding: str = "utf-8",
) -> str | None:
    try:
        async with manager.acquire_computed() as computed:
            html, _error = await computed.async_client.get_text(
                url,
                headers={**_HEADERS, **(headers or {})},
                cookies=cookies,
                encoding=encoding,
                retry_count=0,
            )
    except Exception:
        return None
    return html or None


async def _http_json(
    url: str, *, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None
) -> dict | None:
    try:
        async with manager.acquire_computed() as computed:
            data, _error = await computed.async_client.get_json(
                url, headers={**_HEADERS, **(headers or {})}, cookies=cookies, retry_count=0
            )
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def _http_post_json(
    url: str, payload: object, *, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None
) -> dict | None:
    try:
        async with manager.acquire_computed() as computed:
            data, _error = await computed.async_client.post_json(
                url,
                data=json.dumps(payload),
                headers={
                    **_HEADERS,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **(headers or {}),
                },
                cookies=cookies,
                retry_count=0,
            )
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _html_tree(html: str) -> etree._Element | None:
    try:
        return etree.fromstring(html, etree.HTMLParser())
    except Exception:
        return None


def _joined_text(node: etree._Element) -> str:
    return "".join(node.xpath(".//text()")).strip()


def _name_matches(target: str, candidate: str) -> bool:
    """宽松演员名匹配：归一化后相等、互为子串，或繁简/异体差异下前 N-1 字相同。"""

    def norm(value: str) -> str:
        value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        return re.sub(r"[\s\-・.。,，()（）\[\]【】]", "", value)

    t, c = norm(target), norm(candidate)
    if not t or not c:
        return False
    if t == c or t in c or c in t:
        return True
    return len(t) >= 3 and len(c) >= 3 and t[:-1] == c[:-1]


def _pick_name(names: Iterable[str], limit: int = _MAX_NAME_VARIANTS) -> list[str]:
    seen: list[str] = []
    for name in names:
        name = str(name or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen[:limit]


def _merge(
    hits: dict[str, NumberHit],
    number: str,
    site: str,
    url: str,
    *,
    actors: str = "",
    release: str = "",
    duration: str = "",
) -> None:
    """把一条记录塞进结果集。

    同番号只保留最先出现的站点（即优先级最高的站），但**元数据按字段补齐**：
    前一个站没给发行日/时长/演员，后一个站给了就补上，不因为「已有记录」而丢弃。
    """
    number = display_number(number)
    if not number:
        return
    key = normalize_key(number)
    if not key:
        return
    actors = _clean_meta(actors)
    release = _clean_date(release)
    duration = _clean_duration(duration)
    old = hits.get(key)
    if old is None:
        hits[key] = NumberHit(
            number=number,
            site=site,
            url=str(url or "").strip(),
            actors=actors,
            release=release,
            duration=duration,
        )
        return
    if not (actors or release or duration):
        return
    hits[key] = replace(
        old,
        actors=old.actors or actors,
        release=old.release or release,
        duration=old.duration or duration,
    )


def _clean_meta(value: object) -> str:
    """演员串归一：去空白、顿号/斜杠统一成英文逗号、去重保序。"""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[,，、/|]+", text)]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ",".join(seen)


def _clean_date(value: object) -> str:
    """发行日归一成 YYYY-MM-DD；认不出的日期返回空串（不猜）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _clean_duration(value: object) -> str:
    """时长归一成纯分钟数字（站点可能给 '96'、96、'96分钟'、'01:36:00'）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if m := re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2})", text):
        return str(int(m.group(1)) * 60 + int(m.group(2)))
    if m := re.search(r"\d+", text):
        return m.group(0)
    return ""


# ---------------------------------------------------------------------------
# JavBus：8 镜像轮询
# ---------------------------------------------------------------------------


class _JavbusRotator:
    """javbus 镜像轮询，连接失败自动切下一个域名。"""

    def __init__(self) -> None:
        custom = manager.config.get_site_url(Website.JAVBUS, "")
        self._rotator = DomainRotator(_JAVBUS_DOMAINS, custom_url=custom)

    @property
    def base(self) -> str:
        return self._rotator.current

    async def get_text(self, url: str) -> str | None:
        """带镜像轮询的 GET 请求，连接级失败切镜像，返回 HTML 或 None。"""
        headers = dict(_HEADERS)
        if manager.config.javbus:
            # 与 JavBusCrawler 一致：Cookie 串直接放请求头
            headers["cookie"] = manager.config.javbus
        for _ in range(len(self._rotator.domains)):
            async with manager.acquire_computed() as computed:
                html, error = await computed.async_client.get_text(url, headers=headers)
            if html is not None:
                return html
            # 404 是业务级错误（演员不存在），不轮询。必须匹配 "HTTP 404" 状态
            # 前缀：error 内嵌请求 URL，裸 "404" 子串会把 URL 含 404 的传输失败误判。
            if re.search(r"HTTP 404(?!\d)", str(error)):
                return None
            # 连接级失败：切镜像
            self._rotator.rotate()
            url = self._rotator.rebuild_url(url)
            _log(f"   javbus 镜像请求失败，切换: {self._rotator.current} ({error})")
        return None


async def _javbus_searchstar(rotator: _JavbusRotator, name: str, uncensored: bool) -> str | None:
    """javbus 按演员名搜索，返回 star 页 URL 或 None。"""
    prefix = "/uncensored" if uncensored else ""
    url = f"{rotator.base}{prefix}/searchstar/{quote(name)}"
    html = await rotator.get_text(url)
    if not html:
        return None
    root = _html_tree(html)
    if root is None:
        return None
    picked: str | None = None
    for a in root.xpath("//a[contains(@href,'/star/')]"):
        href = str(a.get("href") or "")
        if not href or "/searchstar/" in href:
            continue
        if uncensored != ("/uncensored/star/" in href):
            continue
        title = str(a.xpath(".//img/@title")[0]) if a.xpath(".//img/@title") else _joined_text(a)
        if _name_matches(name, title):
            picked = href
            break
        if picked is None:
            picked = href
    if not picked:
        return None
    return picked if picked.startswith("http") else f"{rotator.base}{picked}"


async def _fetch_javbus(names: list[str]) -> dict[str, NumberHit]:
    """有码：javbus searchstar → star 页分页。"""
    return await _javbus_numbers(names, uncensored=False)


async def _fetch_javbus_uncensored(names: list[str]) -> dict[str, NumberHit]:
    """无码：javbus 的 /uncensored/searchstar 通道，只列无码作品。"""
    return await _javbus_numbers(names, uncensored=True)


async def _javbus_numbers(names: list[str], *, uncensored: bool) -> dict[str, NumberHit]:
    rotator = _JavbusRotator()
    site = Website.JAVBUS.value
    for name in _pick_name(names):
        star_url = await _javbus_searchstar(rotator, name, uncensored=uncensored)
        if not star_url:
            continue
        hits: dict[str, NumberHit] = {}
        page = 1
        while not _out_of_time() and page <= _MAX_PAGES:
            url = star_url if page == 1 else f"{star_url}/{page}"
            html = await rotator.get_text(url)
            if not html:
                break
            root = _html_tree(html)
            if root is None:
                break
            boxes = root.xpath('//a[@class="movie-box"]')
            for box in boxes:
                href = str(box.get("href") or "")
                dates = box.xpath(".//date/text()")
                number = str(dates[0]).strip() if dates else ""
                # 演员页每个卡片两个 <date>：第一个是番号，第二个是发行日
                release = str(dates[1]).strip() if len(dates) > 1 else ""
                if not number and href:
                    number = href.rstrip("/").rsplit("/", 1)[-1]
                _merge(hits, number, site, href, release=release)
            next_pages = root.xpath(
                '//a[contains(text(),"下一頁") or contains(text(),"下一页") or contains(text(),"Next")]/@href'
            )
            if not next_pages or len(boxes) < 30:
                break
            page += 1
        if hits:
            return hits
    return {}


# ---------------------------------------------------------------------------
# JavDB 网页版 / JavDB_API
# ---------------------------------------------------------------------------


def _javdb_cookie() -> dict[str, str] | None:
    cookie = manager.config.javdb
    return {"cookie": cookie} if cookie else None


# JavDB 的「分类」入口，长得和演员主页一样（/actors/censored），不能当成演员
_JAVDB_NON_ACTOR_PATHS = frozenset({"censored", "uncensored", "western"})


async def _javdb_actor_path(base: str, name: str) -> str | None:
    """演员搜索页取演员主页路径 `/actors/xxxx`。"""
    for query in (f"/search?q={quote(name)}&f=actor", f"/search?q={quote(name)}"):
        html = await _http_text(base + query, headers=_javdb_cookie())
        if not html:
            continue
        if "banned your access" in html or "Due to copyright restrictions" in html:
            return None
        root = _html_tree(html)
        if root is None:
            continue
        # 演员卡片带 actor-box 类，优先按卡片取，避免抓到分类入口
        for a in root.xpath('//a[contains(@class,"actor-box")]'):
            href = str(a.get("href") or "")
            if re.fullmatch(r"/actors/[A-Za-z0-9]+", href):
                return href
        for href in root.xpath('//a[contains(@href,"/actors/")]/@href'):
            href = str(href)
            if not re.fullmatch(r"/actors/[A-Za-z0-9]+", href):
                continue
            if href.rsplit("/", 1)[-1].lower() in _JAVDB_NON_ACTOR_PATHS:
                continue
            return href
    return None


async def _javdb_actor_numbers(base: str, path: str) -> dict[str, NumberHit]:
    site = Website.JAVDB.value
    hits: dict[str, NumberHit] = {}
    page = 1
    while not _out_of_time() and page <= _MAX_PAGES:
        url = f"{base}{path}" if page == 1 else f"{base}{path}?page={page}"
        html = await _http_text(url, headers=_javdb_cookie())
        if not html:
            break
        root = _html_tree(html)
        if root is None:
            break
        boxes = root.xpath('//div[contains(@class,"movie-list")]//a[@class="box"]')
        if not boxes:
            break
        for box in boxes:
            href = str(box.get("href") or "")
            number = "".join(box.xpath('.//div[contains(@class,"video-title")]/strong/text()')).strip()
            # 列表卡片带发行日（<div class="meta">2026-09-29</div>），时长/演员列表页没有
            meta = "".join(box.xpath('.//div[contains(@class,"meta")]/text()')).strip()
            _merge(hits, number, site, urljoin(base, href), release=meta)
        if not root.xpath('//a[contains(@class,"pagination-next")]/@href'):
            break
        page += 1
    return hits


async def _javdb_site_numbers(names: list[str], *, site: Website, fallback: str) -> dict[str, NumberHit]:
    # 自定义网址只比默认地址多个 www. 时按默认地址走：`www.javdb580.com`
    # 是只回 1 字节的空壳（主站是 javdb580.com），留着它等于整站不可用。
    base = strip_redundant_www(manager.config.get_site_url(site, fallback), fallback).rstrip("/")
    for name in _pick_name(names):
        path = await _javdb_actor_path(base, name)
        if not path:
            continue
        hits = await _javdb_actor_numbers(base, path)
        if hits:
            # 站点名按各自站点标注（JavDB / JavDB_API 分开统计）
            return {k: replace(v, site=site.value) for k, v in hits.items()}
    return {}


async def _fetch_javdb(names: list[str]) -> dict[str, NumberHit]:
    return await _javdb_site_numbers(names, site=Website.JAVDB, fallback=_JAVDB_FALLBACK)


async def _fetch_javdb_api(names: list[str]) -> dict[str, NumberHit]:
    return await _javdb_site_numbers(names, site=Website.JAVDB_API, fallback=_JAVDB_FALLBACK)


def _only_fc2(hits: dict[str, NumberHit]) -> dict[str, NumberHit]:
    """FC2 类型只留 FC2- 番号，别把同一个演员的有码作品混进来。"""
    return {key: hit for key, hit in hits.items() if key.startswith("FC2")}


async def _fetch_javdb_fc2(names: list[str]) -> dict[str, NumberHit]:
    return _only_fc2(await _fetch_javdb(names))


async def _fetch_javdb_api_fc2(names: list[str]) -> dict[str, NumberHit]:
    return _only_fc2(await _fetch_javdb_api(names))


# ---------------------------------------------------------------------------
# JavDB_APP：移动端签名 API
# ---------------------------------------------------------------------------

_JAVDB_APP_LIMIT = 50
_JAVDB_APP_MAX_PAGES = 20  # 服务端把 page 截断在 20，20 页 × 50 = 最多 1000 条
_JAVDB_APP_INTERVAL = 0.3


async def _fetch_javdb_app(names: list[str], *, fc2_only: bool = False) -> dict[str, NumberHit]:
    """JavDB 移动端签名 API 关键字搜索（动漫 / FC2 也走这里）。"""
    from ..crawlers.javdb_app import (  # 局部导入：避免 crawlers 包的重量级导入链
        _API_BASE,
        _API_FALLBACKS,
        _build_api_params,
        _get_api_url,
        make_signature,
    )

    site = Website.JAVDB_APP.value
    hits: dict[str, NumberHit] = {}
    for name in _pick_name(names):
        for host in [_API_BASE, *_API_FALLBACKS]:
            headers = {"jdsignature": make_signature(), "accept-language": "zh", "User-Agent": "Dart/3.5 (dart:io)"}
            page = 1
            while not _out_of_time() and page <= _JAVDB_APP_MAX_PAGES:
                params = _build_api_params()
                params.update({"q": name, "page": str(page), "type": "movie", "limit": str(_JAVDB_APP_LIMIT)})
                data = await _http_json(_get_api_url(host, "/api/v2/search", params), headers=headers)
                if not data:
                    break
                movies = (data.get("data") or {}).get("movies") or []
                if not movies:
                    break
                for movie in movies:
                    number = str(movie.get("number") or "").strip()
                    if not number:
                        continue
                    if fc2_only and not normalize_key(number).startswith("FC2"):
                        continue
                    movie_id = str(movie.get("id") or "")
                    # 移动端搜索顺带给了发行日与时长（分钟）
                    _merge(
                        hits,
                        number,
                        site,
                        f"{_JAVDB_FALLBACK}/v/{movie_id}" if movie_id else "",
                        release=str(movie.get("release_date") or ""),
                        duration=str(movie.get("duration") or ""),
                    )
                if len(movies) < _JAVDB_APP_LIMIT:
                    break
                page += 1
                await asyncio.sleep(_JAVDB_APP_INTERVAL)
            if hits:
                return hits
    return hits


async def _fetch_javdb_app_all(names: list[str]) -> dict[str, NumberHit]:
    return await _fetch_javdb_app(names)


async def _fetch_javdb_app_fc2(names: list[str]) -> dict[str, NumberHit]:
    return await _fetch_javdb_app(names, fc2_only=True)


# ---------------------------------------------------------------------------
# JavLibrary / Javlibrary·镜像
# ---------------------------------------------------------------------------


async def _javlibrary_numbers(base: str, names: list[str], site: str) -> dict[str, NumberHit]:
    """JavLibrary：按名字搜演员 → vl_star 分页 → 取 code 链接。"""
    base = base.rstrip("/")
    for name in _pick_name(names):
        search_html = await _http_text(f"{base}/cn/vl_searchby_name.php?keyword={quote(name)}")
        if not search_html:
            continue
        root = _html_tree(search_html)
        if root is None:
            continue
        star_path = ""
        for a in root.xpath('//a[contains(@href,"vl_star.php?s=")]'):
            text = _joined_text(a)
            if _name_matches(name, text):
                star_path = str(a.get("href") or "")
                break
        if not star_path:
            continue
        hits: dict[str, NumberHit] = {}
        page = 1
        while not _out_of_time() and page <= _MAX_PAGES:
            sep = "&" if "?" in star_path else "?"
            url = (
                f"{base}/cn/{star_path.lstrip('/')}"
                if page == 1
                else f"{base}/cn/{star_path.lstrip('/')}{sep}page={page}"
            )
            html = await _http_text(url)
            if not html:
                break
            page_root = _html_tree(html)
            if page_root is None:
                break
            videos = page_root.xpath('//div[@class="video"]')
            for video in videos:
                code = video.xpath('.//span[@class="code"]/a')
                if not code:
                    continue
                number = _joined_text(code[0])
                href = str(code[0].get("href") or "")
                _merge(hits, number, site, urljoin(f"{base}/cn/", href))
            next_page = page_root.xpath('//a[contains(@class,"page") and contains(@class,"next")]/@href')
            if not next_page or not videos:
                break
            page += 1
        if hits:
            return hits
    return {}


def _javlibrary_base(url: str) -> str:
    """JavLibrary 站点根地址：去掉结尾斜杠与 `/cn` 语言段（路径里会自己拼 /cn）。"""
    base = str(url or "").strip().rstrip("/")
    if base.endswith("/cn"):
        base = base[: -len("/cn")]
    return base.rstrip("/")


async def _fetch_javlibrary(names: list[str]) -> dict[str, NumberHit]:
    custom = manager.config.get_site_url(Website.JAVLIBRARY, "")
    base = _javlibrary_base(custom) or _javlibrary_base(await get_javlibrary_domain())
    return await _javlibrary_numbers(base, names, Website.JAVLIBRARY.value)


async def _fetch_javlibrary_mirror(names: list[str]) -> dict[str, NumberHit]:
    custom = manager.config.get_site_url(Website.JAVLIBRARY_MIRROR, "")
    base = _javlibrary_base(custom) or _javlibrary_base(await get_javlibrary_mirror_domain())
    return await _javlibrary_numbers(base, names, Website.JAVLIBRARY_MIRROR.value)


# ---------------------------------------------------------------------------
# DMM（网页）
# ---------------------------------------------------------------------------


def _dmm_number_from_cid(cid: str) -> str:
    """DMM content_id → 展示番号（ssis00006 → SSIS-006，55t2800645 → T28-00645）。"""
    cid = str(cid or "").strip().lower()
    if not cid:
        return ""
    if m := re.fullmatch(r"([a-z]+)(\d+)", cid):
        return display_number(f"{m.group(1)}-{m.group(2)}")
    if m := re.fullmatch(r"\d+([a-z]+\d*?)(\d{5,})", cid):
        return display_number(f"{m.group(1)}-{m.group(2)}")
    if m := re.fullmatch(r"h_(\d+)([a-z]+)(\d+)", cid):
        return display_number(f"{m.group(2)}-{m.group(3)}")
    return display_number(cid)


async def _dmm_actress_id(name: str) -> str:
    html = await _http_text(f"{_DMM}/search/=/searchstr={quote(name)}/", cookies={"age_check_done": "1"})
    if not html or "not-available-in-your-region" in html:
        return ""
    ids = re.findall(r"actress/-/detail/=/id=(\d+)/", html) or re.findall(r"article=actress/id=(\d+)/", html)
    return ids[0] if ids else ""


async def _fetch_dmm(names: list[str]) -> dict[str, NumberHit]:
    """有码：DMM 网页版演员作品列表。"""
    site = Website.DMM.value
    actress_id = ""
    for name in _pick_name(names, 2):
        actress_id = await _dmm_actress_id(name)
        if actress_id:
            break
    if not actress_id:
        return {}
    hits: dict[str, NumberHit] = {}
    for page in range(1, _MAX_PAGES + 1):
        if _out_of_time():
            break
        url = f"{_DMM}/digital/videoa/-/list/=/article=actress/id={actress_id}/sort=date/page={page}/"
        html = await _http_text(url, cookies={"age_check_done": "1"})
        if not html:
            break
        cids = re.findall(r"/cid=([a-z0-9_]+)/", html)
        if not cids:
            cids = re.findall(r"content/\?id=([a-z0-9_]+)", html)
        new = 0
        for cid in dict.fromkeys(cids):
            before = len(hits)
            _merge(hits, _dmm_number_from_cid(cid), site, f"{_DMM}/digital/videoa/-/detail/=/cid={cid}/")
            new += len(hits) - before
        if new == 0:
            break
    return hits


# ---------------------------------------------------------------------------
# DMM_API（Affiliate API）
# ---------------------------------------------------------------------------


async def _dmm_api_actress_id(name: str) -> str:
    from ..crawlers.dmm_api import DmmApiCrawler

    url = (
        f"{_DMM_API}/affiliate/v3/ActressSearch?"
        f"api_id={DmmApiCrawler._api_id()}&affiliate_id={DmmApiCrawler._affiliate_id()}"
        f"&output=json&keyword={quote(name)}&hits=10"
    )
    data = await _http_json(url)
    if not data:
        return ""
    actresses = ((data.get("result") or {}).get("actress")) or []
    fallback = ""
    for actress in actresses:
        actress_id = str(actress.get("id") or "")
        actress_name = str(actress.get("name") or "")
        if not actress_id:
            continue
        if actress_name == name:
            return actress_id
        if not fallback and _name_matches(name, actress_name):
            fallback = actress_id
    return fallback


async def _fetch_dmm_api(names: list[str]) -> dict[str, NumberHit]:
    """有码：DMM Affiliate API（ActressSearch → ItemList 分页）。"""
    from ..crawlers.dmm_api import DmmApiCrawler

    site = Website.DMM_API.value
    actress_id = ""
    for name in _pick_name(names, 2):
        actress_id = await _dmm_api_actress_id(name)
        if actress_id:
            break
    if not actress_id:
        return {}
    hits: dict[str, NumberHit] = {}
    offset = 1
    while not _out_of_time() and offset <= 3000:
        url = (
            f"{_DMM_API}/affiliate/v3/ItemList?"
            f"api_id={DmmApiCrawler._api_id()}&affiliate_id={DmmApiCrawler._affiliate_id()}"
            f"&output=json&site=FANZA&service=digital&floor=videoa"
            f"&article=actress&article_id={actress_id}&hits=100&offset={offset}&sort=date"
        )
        data = await _http_json(url)
        if not data:
            break
        result = data.get("result") or {}
        items = result.get("items") or []
        if not items:
            break
        for item in items:
            cid = str(item.get("content_id") or item.get("product_id") or "")
            url_detail = str(item.get("URL") or "")
            if not cid:
                continue
            # ItemList 顺带给了发行日、时长（volume=分钟）与演员表，直接填进表格
            info = item.get("iteminfo") if isinstance(item.get("iteminfo"), dict) else {}
            actress_list = info.get("actress") or []
            actors = ",".join(
                str(a.get("name") or "").strip() for a in actress_list if isinstance(a, dict) and a.get("name")
            )
            _merge(
                hits,
                _dmm_number_from_cid(cid),
                site,
                url_detail or f"{_DMM}/digital/videoa/-/detail/=/cid={cid}/",
                actors=actors,
                release=str(item.get("date") or ""),
                duration=str(item.get("volume") or ""),
            )
        if len(items) < 100:
            break
        offset += 100
    return hits


# ---------------------------------------------------------------------------
# LibreDMM
# ---------------------------------------------------------------------------


async def _libredmm_fuzzy_search(name: str) -> str | None:
    """libredmm 演员模糊搜索，返回相对路径 /actresses/{id} 或 None。"""
    url = f"{_LIBREDMM}/actresses?order=New&fuzzy={quote(name)}&commit=Filter+by+name"
    html = await _http_text(url)
    if not html:
        return None
    root = _html_tree(html)
    if root is None:
        return None
    anchors = root.xpath('//a[contains(@href,"/actresses/")]')
    # 逐 <a> 成对取 href 与完整文本，避免跨 xpath 的 links/names zip 数量不等导致错位配对
    for a in anchors:
        link = str(a.get("href") or "")
        nm = _joined_text(a)
        if nm == name or name in nm or nm in name:
            return link
    return str(anchors[0].get("href") or "") if anchors else None


async def _libredmm_fetch_numbers(href: str) -> dict[str, NumberHit]:
    """拉取 libredmm 演员页全部作品，支持分页；番号取自 /movies/{num} 链接。"""
    site = Website.LIBREDMM.value
    full = href if href.startswith("http") else f"{_LIBREDMM}{href}"
    hits: dict[str, NumberHit] = {}
    page = 1
    while not _out_of_time() and page <= _MAX_PAGES:
        url = full if page == 1 else f"{full}?page={page}"
        html = await _http_text(url)
        if not html:
            break
        root = _html_tree(html)
        if root is None:
            break
        movies = root.xpath('//a[contains(@href,"/movies/")]/@href')
        for href_movie in movies:
            number = str(href_movie).split("/movies/")[-1].strip("/")
            if number:
                _merge(hits, number, site, urljoin(_LIBREDMM, str(href_movie)))
        next_text = "".join(root.xpath('//a[contains(@href,"?page=")]/text()'))
        if not movies or ("Next" not in next_text and "下一頁" not in next_text and "下一页" not in next_text):
            break
        if len(movies) < 60:
            break
        page += 1
    return hits


async def _fetch_libredmm(names: list[str]) -> dict[str, NumberHit]:
    """有码：LibreDMM（演员页优先用演员库已存地址，其次模糊搜索）。"""
    for name in _pick_name(names):
        href = ""
        try:
            from ..config.resources import resources

            href = resources.get_actor_data(name).get("href") or ""
        except Exception:
            href = ""
        if href and "libredmm.com" in href:
            hits = await _libredmm_fetch_numbers(href)
            if hits:
                return hits
        rel = await _libredmm_fuzzy_search(name)
        if rel:
            hits = await _libredmm_fetch_numbers(rel)
            if hits:
                return hits
    return {}


# ---------------------------------------------------------------------------
# AVSOX / AVheat（tellme.pw AIO 平台，JSON API）
# ---------------------------------------------------------------------------


async def _aio_warmup(root: str) -> dict[str, str]:
    """预热会话，拿 _csrf 之类 Cookie；无 Cookie 直接 POST 会被 WAF 403。"""
    try:
        async with manager.acquire_computed() as computed:
            resp, _error = await computed.async_client.request(
                "GET", root, headers=_HEADERS, retry_count=0, enable_cf_bypass=False
            )
    except Exception:
        return {}
    if resp is None:
        return {}
    try:
        jar = resp.cookies
        if hasattr(jar, "get_dict"):
            return dict(jar.get_dict())
        # 兜底分支: httpx 以外的 cookie jar。运行时迭代出的是带 name/value 的
        # Cookie 对象, 但 httpx 存根把 Cookies 的元素类型标错成 str, 故 cast。
        return {c.name: c.value for c in cast("Iterable[Any]", jar)}
    except Exception:
        return {}


async def _aio_locate_star_id(root: str, namespace: str, name: str, cookies: dict[str, str]) -> str:
    """搜索演员名 → 影片详情 → star 字段定位 starId。"""
    data = await _http_post_json(
        f"{root}/{namespace}/data/api/search", [{"search": name, "lang": "cn"}, 20, 1], cookies=cookies
    )
    if not data:
        return ""
    for item in (data.get("data") or [])[:8]:
        movie_id = item.get("movieId")
        if not movie_id:
            continue
        detail = await _http_post_json(f"{root}/{namespace}/data/api/getMovie", {"movieId": movie_id}, cookies=cookies)
        if not detail:
            continue
        for star in (detail.get("data") or {}).get("star") or []:
            star_name = str(star.get("starName_ja") or star.get("starName_en") or "").strip()
            if star_name and _name_matches(name, star_name):
                return str(star.get("starId") or "")
    return ""


async def _aio_numbers(site: str, namespace: str, names: list[str], site_label: Website) -> dict[str, NumberHit]:
    domain_site = site.lower()
    try:
        base = await get_aio_domain(domain_site)
    except Exception:
        base = f"https://{domain_site}.shop"
    root = base.rstrip("/")
    if root.endswith("/cn"):
        root = root[: -len("/cn")]
    cookies = await _aio_warmup(root)
    star_id = ""
    for name in _pick_name(names, 2):
        star_id = await _aio_locate_star_id(root, namespace, name, cookies)
        if star_id:
            break
    if not star_id:
        return {}
    site_name = site_label.value
    hits: dict[str, NumberHit] = {}
    page = 1
    while not _out_of_time() and page <= 30:
        data = await _http_post_json(
            f"{root}/{namespace}/data/api/getFilterMovies",
            ["star", star_id, "cn", 60, page],
            cookies=cookies,
        )
        if not data:
            break
        rows = data.get("data") or []
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            number = str(row.get("movieFanHao") or "").strip()
            movie_id = str(row.get("movieId") or "").strip()
            if not number:
                continue
            _merge(
                hits,
                number,
                site_name,
                f"{root}/cn/movie/{movie_id}" if movie_id else "",
                release=str(row.get("releaseDate") or ""),
                duration=str(row.get("length") or ""),
            )
        if len(rows) < 60:
            break
        page += 1
    return hits


async def _fetch_avsox(names: list[str]) -> dict[str, NumberHit]:
    return await _aio_numbers("avsox", "javu", names, Website.AVSOX)


async def _fetch_avheat(names: list[str]) -> dict[str, NumberHit]:
    return await _aio_numbers("avheat", "wav", names, Website.AVHEAT)


async def _fetch_avmoo(names: list[str]) -> dict[str, NumberHit]:
    """有码：AVMOO 与 avsox/avheat 同属 tellme.pw AIO 平台，只是命名空间是 jav（有码库）。"""
    return await _aio_numbers("avmoo", "jav", names, Website.AVMOO)


# ---------------------------------------------------------------------------
# IQQTV（国产）
# ---------------------------------------------------------------------------


async def _iqqtv_search_actor(name: str) -> tuple[str, str]:
    """iqqtv 搜索演员名，返回 (域名, s_tid)。"""
    for base in _IQQTV_DOMAINS:
        html = await _http_text(f"{base}/cn/search.php?kw={quote(name)}")
        if not html:
            continue
        root = _html_tree(html)
        if root is None:
            continue
        for a in root.xpath("//a[contains(@href,'s_type=actor')]"):
            nm = _joined_text(a)
            if not nm or "すべて" in nm or "全部" in nm or "表示" in nm:
                continue
            if _name_matches(name, nm):
                return base, str(a.get("href") or "").split("s_tid=")[-1].split("&")[0]
        return "", ""
    return "", ""


async def _fetch_iqqtv(names: list[str]) -> dict[str, NumberHit]:
    """国产：iqqtv 演员页分页，番号从作品标题里提取。"""
    site = Website.IQQTV.value
    for name in _pick_name(names, 2):
        base, tid = await _iqqtv_search_actor(name)
        if not tid:
            continue
        hits: dict[str, NumberHit] = {}
        page = 1
        while not _out_of_time() and page <= 30:
            html = await _http_text(f"{base}/cn/search.php?s_type=actor&s_tid={tid}&num={page}")
            if not html:
                break
            root = _html_tree(html)
            if root is None:
                break
            links = root.xpath('//a[contains(@href,"player.php")]')
            for link in links:
                title = str(link.get("title") or _joined_text(link))
                href = str(link.get("href") or "")
                # IQQTV 标题里常混自造编号（「马赛克破坏版 … JN4286」），只认标准
                # 「字母-数字」写法，避免把这类编号当成番号塞进缺失表
                for number in extract_numbers(title, require_separator=True):
                    _merge(hits, number, site, urljoin(base, href))
            if len(links) < 48:
                break
            page += 1
        if hits:
            return hits
    return {}


# ---------------------------------------------------------------------------
# 国产：Madou.club / Madouqu / JavDay
# ---------------------------------------------------------------------------


async def _wordpress_search_numbers(base: str, site: str, names: list[str]) -> dict[str, NumberHit]:
    """WordPress 站点（madou.club / madouqu）按 `?s=` 搜索演员名，标题里取番号。"""
    base = base.rstrip("/")
    for name in _pick_name(names, 2):
        html = await _http_text(f"{base}/?s={quote(name)}")
        if not html:
            continue
        root = _html_tree(html)
        if root is None:
            continue
        hits: dict[str, NumberHit] = {}
        for article in root.xpath("//article"):
            title = _joined_text(article.xpath(".//h2")[0]) if article.xpath(".//h2") else ""
            hrefs = article.xpath(".//h2//a/@href")
            href = str(hrefs[0]) if hrefs else ""
            if not title:
                continue
            for number in extract_numbers(title):
                _merge(hits, number, site, urljoin(base, href))
        if hits:
            return hits
    return {}


async def _fetch_madou_club(names: list[str]) -> dict[str, NumberHit]:
    base = manager.config.get_site_url(Website.MADOUCLUB, _MADOU_CLUB)
    return await _wordpress_search_numbers(base, Website.MADOUCLUB.value, names)


async def _fetch_madouqu(names: list[str]) -> dict[str, NumberHit]:
    base = manager.config.get_site_url(Website.MADOUQU, _MADOUQU_FALLBACK)
    return await _wordpress_search_numbers(base, Website.MADOUQU.value, names)


async def _fetch_javday(names: list[str]) -> dict[str, NumberHit]:
    """国产：JavDay 站内搜索页，从 videoBox 标题取番号。"""
    base = manager.config.get_site_url(Website.JAVDAY, _JAVDAY_FALLBACK).rstrip("/")
    site = Website.JAVDAY.value
    for name in _pick_name(names, 2):
        html = await _http_text(f"{base}/search?q={quote(name)}")
        if not html:
            continue
        root = _html_tree(html)
        if root is None:
            continue
        hits: dict[str, NumberHit] = {}
        for box in root.xpath('//a[contains(@class,"videoBox")]'):
            href = str(box.get("href") or "")
            title = (
                _joined_text(box.xpath('.//span[contains(@class,"title")]')[0])
                if box.xpath('.//span[contains(@class,"title")]')
                else _joined_text(box)
            )
            for number in extract_numbers(title):
                _merge(hits, number, site, urljoin(base, href))
        if hits:
            return hits
    return {}


# ---------------------------------------------------------------------------
# FC2 / FC2PPVDB
# ---------------------------------------------------------------------------


async def _fetch_fc2(names: list[str]) -> dict[str, NumberHit]:
    """FC2：站内搜索卖家 → 卖家页作品列表（需登录时返回空）。"""
    site = Website.FC2.value
    for name in _pick_name(names, 2):
        html = await _http_text(f"{_FC2_BASE}/search/?q={quote(name)}")
        # FC2 站内搜索要登录，未登录会整页返回登录页（标题「登录 FC2 …」）
        if not html or "登录 FC2" in html:
            return {}
        root = _html_tree(html)
        if root is None:
            return {}
        seller_ids = [
            m.group(1)
            for m in (
                re.search(r"/users/(\d+)", str(a.get("href") or ""))
                for a in root.xpath('//a[contains(@href,"/users/")]')
            )
            if m
        ]
        hits: dict[str, NumberHit] = {}
        for seller_id in dict.fromkeys(seller_ids[:3]):
            page = 1
            while not _out_of_time() and page <= 30:
                page_url = (
                    f"{_FC2_BASE}/users/{seller_id}" if page == 1 else f"{_FC2_BASE}/users/{seller_id}/page/{page}/"
                )
                page_html = await _http_text(page_url)
                if not page_html:
                    break
                article_ids = re.findall(r"/article/(\d{5,8})/", page_html)
                if not article_ids:
                    break
                for article_id in dict.fromkeys(article_ids):
                    _merge(hits, f"FC2-{article_id}", site, f"{_FC2_BASE}/article/{article_id}/")
                page += 1
        if hits:
            return hits
    return {}


async def _fc2ppvdb_actress_ids(base: str, name: str) -> list[str]:
    html = await _http_text(f"{base}/search?keyword={quote(name)}")
    if not html:
        return []
    ids: list[str] = []
    for m in re.finditer(r'href="[^"]*/actresses/(\d+)"[^>]*>(.{0,120}?)</a>', html, re.S):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        if _name_matches(name, text.strip()):
            ids.append(m.group(1))
    return ids


async def _fc2ppvdb_numbers(base: str, actress_id: str, site: str) -> dict[str, NumberHit]:
    hits: dict[str, NumberHit] = {}
    page = 1
    while not _out_of_time() and page <= 30:
        url = f"{base}/actresses/{actress_id}" if page == 1 else f"{base}/actresses/{actress_id}?page={page}"
        html = await _http_text(url)
        if not html:
            break
        article_ids = re.findall(r"/articles/(\d{5,8})", html)
        if not article_ids:
            break
        for article_id in dict.fromkeys(article_ids):
            _merge(hits, f"FC2-{article_id}", site, f"{_FC2PPVDB_BASE}/articles/{article_id}")
        page += 1
    return hits


async def _fetch_fc2ppvdb(names: list[str]) -> dict[str, NumberHit]:
    """FC2：FC2PPVDB 演员页（主域被 CF 拦时走 fc2cmadb 镜像）。"""
    site = Website.FC2PPVDB.value
    for name in _pick_name(names, 2):
        for base in (_FC2PPVDB_BASE, _FC2CMADB_BASE):
            ids = await _fc2ppvdb_actress_ids(base, name)
            for actress_id in ids[:2]:
                hits = await _fc2ppvdb_numbers(base, actress_id, site)
                if hits:
                    return hits
    return {}


# ---------------------------------------------------------------------------
# 欧美：ThepornDB
# ---------------------------------------------------------------------------


async def _fetch_theporndb(names: list[str]) -> dict[str, NumberHit]:
    """欧美：ThepornDB API 关键字搜索（movies + scenes）。"""
    from ..crawlers.theporndb import get_number

    token = str(getattr(manager.config, "theporndb_api_token", "") or "").strip()
    if not token:
        return {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    site = Website.THEPORNDB.value
    for name in _pick_name(names, 2):
        hits: dict[str, NumberHit] = {}
        for kind in ("movies", "scenes"):
            page = 1
            while not _out_of_time() and page <= 10:
                url = f"{_THEPORNDB_API}/{kind}?q={quote(name)}&per_page=100&page={page}"
                data = await _http_json(url, headers=headers)
                if not data:
                    break
                rows = data.get("data") or []
                if not rows:
                    break
                for row in rows:
                    title = str(row.get("title") or "")
                    site_info = row.get("site") if isinstance(row.get("site"), dict) else {}
                    date = str(row.get("date") or "")
                    number = get_number(str(site_info.get("short_name") or ""), date, title)
                    slug = str(row.get("slug") or "")
                    _merge(
                        hits,
                        number,
                        site,
                        f"{_THEPORNDB_WEB}/{kind}/{slug}" if slug else "",
                        release=date,
                        duration=str(row.get("duration") or ""),
                    )
                if len(rows) < 100:
                    break
                page += 1
        if hits:
            return hits
    return {}


# ---------------------------------------------------------------------------
# 动漫：Getchu
# ---------------------------------------------------------------------------


async def _fetch_getchu(names: list[str]) -> dict[str, NumberHit]:
    """动漫：Getchu 关键字搜索，标题里取番号（同人/游戏品番）。"""
    base = manager.config.get_site_url(Website.GETCHU, _GETCHU_FALLBACK).rstrip("/")
    site = Website.GETCHU.value
    for name in _pick_name(names, 2):
        keyword = quote(name, encoding="euc-jp", errors="ignore")
        html = await _http_text(f"{base}/php/search.phtml?genre=all&search_keyword={keyword}&gc=gc", encoding="euc-jp")
        if not html:
            continue
        root = _html_tree(html)
        if root is None:
            continue
        hits: dict[str, NumberHit] = {}
        for a in root.xpath("//a[@class='blueb']"):
            title = _joined_text(a)
            href = str(a.get("href") or "").replace("../", "/")
            for number in extract_numbers(title):
                _merge(hits, number, site, urljoin(base + "/", href))
        if hits:
            return hits
    return {}


# ---------------------------------------------------------------------------
# 站点注册表
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    site: str
    fetch: Callable[[list[str]], Awaitable[dict[str, NumberHit]]]
    # 同一个域名组的站点串行跑（避免同时打同一台站被封），不同组之间并发
    group: str = ""
    # 该站点的单次等待上限（秒）。JavLibrary 系走 CF 绕过，天然慢，给得短一些
    timeout: float = 120.0


# 内部演员类型 → 刮削类型（决定用「软件设置-类型刮削网站」里的哪一组站点）
_ACTOR_TYPE_TO_SCRAPING: dict[str, FixedScrapingType] = {
    "有码": FixedScrapingType.YOUMA,
    "无码": FixedScrapingType.WUMA,
    "FC2": FixedScrapingType.FC2,
    "欧美": FixedScrapingType.OUMEI,
    "国产": FixedScrapingType.GUOCHAN,
    "动漫": FixedScrapingType.DONGMAN,
}

ACTOR_TYPES: tuple[str, ...] = tuple(_ACTOR_TYPE_TO_SCRAPING)

# 「自动判断」时用的固定站点链（用户 2026-10-25 定稿，顺序即优先级）。
# 与「按类型取配置组」是两条路：自动判断不看软件设置里的站点组，
# 只有下拉框选了具体类型才走配置组（含组内被禁用的站点）。
_AUTO_SITE_ORDER: dict[str, tuple[Website, ...]] = {
    "有码": (
        Website.DMM,
        Website.DMM_API,
        Website.LIBREDMM,
        Website.JAVDB,
        Website.JAVDB_API,
        Website.JAVDB_APP,
        Website.JAVLIBRARY_MIRROR,
        Website.JAVLIBRARY,
        Website.JAVBUS,
        Website.IQQTV,
    ),
    "无码": (Website.AVSOX, Website.JAVDB, Website.JAVDB_API, Website.JAVDB_APP),
    "FC2": (
        Website.AVSOX,
        Website.FC2,
        Website.FC2PPVDB,
        Website.JAVDB,
        Website.JAVDB_API,
        Website.JAVDB_APP,
    ),
    "欧美": (Website.AVHEAT, Website.THEPORNDB, Website.JAVDB, Website.JAVDB_API, Website.JAVDB_APP),
    "国产": (Website.IQQTV, Website.MADOUCLUB, Website.MADOUQU, Website.JAVDAY),
    "动漫": (Website.JAVDB_APP, Website.GETCHU),
}

# 站点 → 「按演员/关键字列出全部作品」的实现。
# 只登记真有演员页/关键字搜索的站；配置里其余站点（厂牌官网、聚合站等）没有这种
# 入口，查缺时跳过并在日志里说明，不会静默当成「查过了、没有番号」。
_SITE_FETCHERS: dict[Website, Callable[[list[str]], Awaitable[dict[str, NumberHit]]]] = {
    Website.DMM: _fetch_dmm,
    Website.DMM_API: _fetch_dmm_api,
    Website.LIBREDMM: _fetch_libredmm,
    Website.AVMOO: _fetch_avmoo,
    Website.AVSOX: _fetch_avsox,
    Website.AVHEAT: _fetch_avheat,
    Website.FC2: _fetch_fc2,
    Website.FC2PPVDB: _fetch_fc2ppvdb,
    Website.THEPORNDB: _fetch_theporndb,
    Website.IQQTV: _fetch_iqqtv,
    Website.MADOUCLUB: _fetch_madou_club,
    Website.MADOUQU: _fetch_madouqu,
    Website.JAVDAY: _fetch_javday,
    Website.GETCHU: _fetch_getchu,
    Website.JAVDB: _fetch_javdb,
    Website.JAVDB_API: _fetch_javdb_api,
    Website.JAVDB_APP: _fetch_javdb_app_all,
    Website.JAVBUS: _fetch_javbus,
    Website.JAVLIBRARY: _fetch_javlibrary,
    Website.JAVLIBRARY_MIRROR: _fetch_javlibrary_mirror,
}

# FC2 类型下 JavDB 三站换成「只留 FC2- 番号」的版本：
# 否则同一个演员的有码作品会混进 FC2 的缺失表。
_SITE_FETCHERS_FC2: dict[Website, Callable[[list[str]], Awaitable[dict[str, NumberHit]]]] = {
    **_SITE_FETCHERS,
    Website.JAVDB: _fetch_javdb_fc2,
    Website.JAVDB_API: _fetch_javdb_api_fc2,
    Website.JAVDB_APP: _fetch_javdb_app_fc2,
}

# 无码类型下 JavBus 换成 uncensored 通道（JavBus 在有码/无码两个组里都有）
_SITE_FETCHERS_WUMA: dict[Website, Callable[[list[str]], Awaitable[dict[str, NumberHit]]]] = {
    **_SITE_FETCHERS,
    Website.JAVBUS: _fetch_javbus_uncensored,
}

# 同一台域名（或同一份数据）的站点串行跑，避免并发打同一站被封
_SITE_GROUPS: dict[Website, str] = {
    Website.DMM: "dmm",
    Website.DMM_API: "dmm",
    Website.JAVDB: "javdb",
    Website.JAVDB_API: "javdb",
    Website.JAVDB_APP: "javdb",
    Website.JAVLIBRARY: "javlibrary",
    Website.JAVLIBRARY_MIRROR: "javlibrary",
    Website.FC2: "fc2",
    Website.FC2PPVDB: "fc2",
}

# 各站点单次等待上限（秒）：DMM 网页可能被地区封锁、JavLibrary 系要过盾，给得短些
_SITE_TIMEOUTS: dict[Website, float] = {
    Website.DMM: 60,
    Website.JAVDB: 90,
    Website.JAVDB_API: 60,
    Website.JAVDB_APP: 60,
    Website.JAVLIBRARY: 60,
    Website.JAVLIBRARY_MIRROR: 60,
    Website.JAVBUS: 120,
}


def sites_for_type(actor_type: str) -> list[Website]:
    """按演员类型取「软件设置-类型刮削网站」里那一组站点（保持用户排的优先级顺序）。

    **不看 website_disabled**：用户口径是「编辑网站里被禁用的站点，在演员名检查
    缺失番号时不再禁用」——查缺是一次性手动工具，禁用只影响批量刮削。
    """
    scraping = _ACTOR_TYPE_TO_SCRAPING.get(actor_type, FixedScrapingType.YOUMA)
    field = SCRAPING_TYPE_SITE_FIELDS[scraping]
    return list(getattr(manager.config, field, None) or [])


def build_sources(actor_type: str, *, use_config_sites: bool) -> tuple[list[Source], list[str]]:
    """把该类型的站点清单变成可执行的 Source 列表，返回 (能查的, 跳过的站名)。

    `use_config_sites=False`（自动判断）用固定站点链；`True`（下拉框选了具体类型）
    用「软件设置-类型刮削网站」里那一组。
    """
    fetchers = _SITE_FETCHERS
    if actor_type == "FC2":
        fetchers = _SITE_FETCHERS_FC2
    elif actor_type == "无码":
        fetchers = _SITE_FETCHERS_WUMA
    if use_config_sites:
        sites = sites_for_type(actor_type)
    else:
        sites = list(_AUTO_SITE_ORDER.get(actor_type, _AUTO_SITE_ORDER["有码"]))

    sources: list[Source] = []
    skipped: list[str] = []
    for site in sites:
        fetch = fetchers.get(site)
        if fetch is None:
            skipped.append(site.value)
            continue
        sources.append(
            Source(
                site=site.value,
                fetch=fetch,
                group=_SITE_GROUPS.get(site, site.value),
                timeout=_SITE_TIMEOUTS.get(site, 120.0),
            )
        )
    return sources, skipped


# ---------------------------------------------------------------------------
# 演员名解析
# ---------------------------------------------------------------------------


async def resolve_actor_names(name: str) -> list[str]:
    """把用户填的名字扩展成各站能查到的写法（日文原名 / 繁中 / 别名）。

    日文站（DMM、JavBus、JavLibrary、libredmm）只认日文原名，用户填简体
    「三上悠亚」时这些站一个都查不到；JavDB 的演员库里同时存着原名与
    繁中/别名，用它解析一次，后续所有站点共用这组名字变体。
    """
    base_name = str(name or "").strip()
    if not base_name:
        return []
    names: list[str] = [base_name]

    def push(value: str) -> None:
        value = str(value or "").strip()
        if value and value not in names:
            names.append(value)

    # 1) JavDB 移动端演员搜索：一次请求拿到 name / name_zht / other_name
    try:
        from ..crawlers.javdb_app import _API_BASE, _build_api_params, _get_api_url, make_signature

        params = _build_api_params()
        params.update({"q": base_name, "page": "1", "type": "actor", "limit": "10"})
        data = await _http_json(
            _get_api_url(_API_BASE, "/api/v2/search", params),
            headers={"jdsignature": make_signature(), "accept-language": "zh", "User-Agent": "Dart/3.5 (dart:io)"},
        )
        for actor in ((data or {}).get("data") or {}).get("actors") or []:
            actor_name = str(actor.get("name") or "")
            if not _name_matches(base_name, actor_name):
                continue
            push(actor_name)
            push(str(actor.get("name_zht") or ""))
            for alias in re.split(r"[,，、/]", str(actor.get("other_name") or "")):
                push(alias)
    except Exception:
        pass

    # 2) JavDB 网页演员页标题：「三上悠亜, 三上悠亞」
    try:
        base = manager.config.get_site_url(Website.JAVDB, _JAVDB_FALLBACK).rstrip("/")
        path = await _javdb_actor_path(base, base_name)
        if path:
            html = await _http_text(f"{base}{path}", headers=_javdb_cookie())
            if html:
                root = _html_tree(html)
                if root is not None:
                    for node in root.xpath('//div[contains(@class,"actor-section-name")]'):
                        for part in re.split(r"[,，、/]", _joined_text(node)):
                            push(part)
    except Exception:
        pass

    # 3) 兜底：简转繁（「三上悠亚」→「三上悠亞」），至少让繁体站能查
    if len(names) == 1:
        try:
            from zhconv import convert as zhconv_convert

            push(zhconv_convert(base_name, "zh-hant"))
        except Exception:
            pass

    return names


async def _run_source(source: Source, names: list[str]) -> dict[str, NumberHit]:
    """单个站点：首次 + 一次重试，最多两次请求机会。

    到时间预算就由翻页循环自己收手（拿到的番号照常返回），不再重试；
    超时说明站点慢或被盾拦住，再来一次只是把等待翻倍。
    """
    for attempt in (1, 2):
        token = _DEADLINE.set(time.monotonic() + source.timeout)
        try:
            hits = await asyncio.wait_for(source.fetch(names), timeout=source.timeout + 15)
        except TimeoutError:
            return {}
        except Exception:
            hits = {}
        finally:
            _DEADLINE.reset(token)
        if hits:
            return hits
        if attempt == 2:
            break
    return {}


async def _run_group(sources: list[Source], names: list[str]) -> dict[str, dict[str, NumberHit]]:
    """同域名组内串行（先跑的站点优先级更高），组与组之间由调用方并发。"""
    results: dict[str, dict[str, NumberHit]] = {}
    for source in sources:
        results[source.site] = await _run_source(source, names)
    return results


async def collect_numbers(
    actor_type: str,
    names: list[str],
    *,
    use_config_sites: bool = False,
    log: Callable[[str], None] | None = None,
) -> dict[str, NumberHit]:
    """按类型汇总各站点番号；每个站点最多请求两次（首次 + 一次重试）。

    `use_config_sites=False`（自动判断）走固定站点链；`True`（下拉框选了具体类型）
    走「软件设置-类型刮削网站」里对应那一组，组内被禁用的站点照样参与。
    组内顺序即优先级。返回 `{归一化键: NumberHit}`，同番号只保留优先级最高的站点，
    元数据按字段补齐。不同域名的站点组并发跑，同域名组内串行，避免同时打同一台站被封。
    """
    emit = log or _log
    sources, skipped = build_sources(actor_type, use_config_sites=use_config_sites)
    if not sources:
        emit(f"   ⚠️ 「{actor_type}」没有可用于按演员查全量番号的站点")
        return {}
    source_desc = "类型刮削网站组" if use_config_sites else "固定站点链"
    emit(
        f"   按「{actor_type}」{source_desc}查缺：{len(sources)} 个站点参与"
        + (f"，{len(skipped)} 个站点无演员页已跳过（{'、'.join(skipped)}）" if skipped else "")
    )

    groups: dict[str, list[Source]] = {}
    for source in sources:
        groups.setdefault(source.group or source.site, []).append(source)
    emit(f"   并行查询 {len(groups)} 组站点，共 {len(sources)} 个站点...")
    group_results = await asyncio.gather(*[_run_group(items, names) for items in groups.values()])
    per_source: dict[str, dict[str, NumberHit]] = {}
    for result in group_results:
        per_source.update(result)

    merged: dict[str, NumberHit] = {}
    for source in sources:
        hits = per_source.get(source.site) or {}
        if not hits:
            emit(f"   {source.site}: 未取到番号")
            continue
        fresh = sum(1 for key in hits if key not in merged)
        for key, hit in hits.items():
            if key in merged:
                # 同番号：站点保留优先级最高的那个，元数据按字段补齐
                _merge(
                    merged,
                    hit.number,
                    merged[key].site,
                    merged[key].url,
                    actors=hit.actors,
                    release=hit.release,
                    duration=hit.duration,
                )
            else:
                merged[key] = hit
        emit(f"   {source.site}: {len(hits)} 部（新增 {fresh}）")
    return merged
