#!/usr/bin/env python3
import os.path
import re
from datetime import date as date_cls
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Literal, override
from urllib.parse import quote, urlencode

import oshash

from ..base.number import remove_escape_string
from ..config.enums import Switch, Website
from ..config.manager import manager
from ..number import long_name
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year

TheporndbKind = Literal["scenes", "movies"]


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_number(series, release, title):
    try:
        if series and release:
            return series.replace(" ", "") + "." + re.findall(r"\d{2}-\d{2}-\d{2}", release)[0].replace("-", ".")
    except Exception:
        pass
    return title


def read_data(data, kind: TheporndbKind):
    title = data.get("title") or ""
    outline = data.get("description") or ""
    # 描述里常见的 HTML 段落标签一并去掉；兼容旧接口返回的全角尖括号。
    outline = re.sub(r"</?p>|＜/?p＞", "", outline, flags=re.IGNORECASE)
    release = data.get("date") or ""
    trailer = data.get("trailer") or ""
    try:
        cover = data["background"]["large"]
    except Exception:
        cover = data.get("image")
    cover = cover or ""
    try:
        poster = data["posters"]["large"]
    except Exception:
        poster = data.get("poster")
    poster = poster or ""
    try:
        # duration 可能是 int，也可能是 "7200.0" 这类浮点字符串。
        runtime = str(int(float(data.get("duration") or 0) / 60))
    except TypeError, ValueError:
        runtime = ""
    try:
        series = data["site"]["name"] or ""
    except Exception:
        series = ""
    try:
        studio = data["site"]["network"]["name"] or ""
    except Exception:
        studio = ""
    publisher = studio
    try:
        director = data["director"]["name"] or ""
    except Exception:
        director = ""
    tag_list = []
    for each in data.get("tags") or []:
        name = each.get("name") if isinstance(each, dict) else None
        if name:
            tag_list.append(name)
    slug = data.get("slug") or ""
    real_url = f"https://api.theporndb.net/{kind}/{slug}" if slug else ""
    all_actor_list = []
    actor_list = []
    # 逐条解析：单个 performer 缺 parent/gender 不能让后面的演员全部丢失。
    for each in data.get("performers") or []:
        if not isinstance(each, dict):
            continue
        name = each.get("name")
        if not name:
            continue
        all_actor_list.append(name)
        try:
            if each["parent"]["extras"]["gender"] != "Male":
                actor_list.append(name)
        except KeyError, TypeError:
            pass
    number = get_number(series, release, title)
    return CrawlerData(
        number=number,
        title=title,
        originaltitle=title,
        actors=actor_list,
        all_actors=all_actor_list,
        outline=outline,
        originalplot=outline,
        tags=tag_list,
        release=release,
        year=get_year(release),
        runtime=runtime,
        score="",
        series=series,
        directors=[director] if director else [],
        studio=studio,
        publisher=publisher,
        thumb=cover,
        poster=poster,
        extrafanart=[],
        trailer=trailer,
        image_download=False,
        mosaic="无码",
        external_id=real_url,
        wanted="",
    )


def _normalize_date(value) -> str:
    """ThePornDB 的日期是 YYYY-MM-DD；容忍带时间或空值的候选。"""
    if not value:
        return ""
    return str(value).strip()[:10]


def _site_dict(data: dict) -> dict:
    """安全取出 site 对象；缺失或类型异常时返回空字典。"""
    site = data.get("site")
    return site if isinstance(site, dict) else {}


def get_real_url(res_search, file_path, series_ex, date, kind: TheporndbKind):
    search_data = res_search.get("data") if isinstance(res_search, dict) else None
    if not isinstance(search_data, list) or not search_data:
        return False
    file_name = os.path.split(file_path)[1].lower()
    new_file_name = re.findall(r"[\.-_]\d{2}\.\d{2}\.\d{2}(.+)", file_name)
    new_file_name = new_file_name[0] if new_file_name else file_name
    actor_number = len(new_file_name.replace(".and.", "&").split("&"))
    # 只拿文件名参与匹配：目录名（如「欧美转移」）只会引入噪声。
    temp_file_path_space = re.sub(r"[\W_]", " ", file_name).strip()
    temp_file_path_nospace = temp_file_path_space.replace(" ", "")
    # 多候选裁决的相似度基准用去扩展名的文件名（不含目录）——目录名只会引入噪声
    similarity_target = re.sub(r"[\W_]", " ", os.path.splitext(file_name)[0]).strip()

    res_date_list = []
    res_title_list = []
    res_actor_list = []
    for each in search_data:
        # 逐条解析并捕获异常：单条候选缺字段时不能让整批搜索结果一起作废。
        if not isinstance(each, dict):
            continue
        try:
            slug = each.get("slug")
            if not slug:
                continue
            res_id_url = f"https://api.theporndb.net/{kind}/{slug}"
            site = _site_dict(each)
            res_series = str(site.get("short_name") or "")
            # 站点 slug 里的连字符不参与比较（TeamSkeet -> team-skeet.com）。
            res_url = str(site.get("url") or "").lower().replace("-", "")
            res_date = _normalize_date(each.get("date"))
            res_title = str(each.get("title") or "")
            res_title_space = re.sub(r"[\W_]", " ", res_title.lower())
            res_title_nospace = res_title_space.replace(" ", "")
            actor_list_space = []
            actor_list_nospace = []
            performers = each.get("performers")
            if isinstance(performers, list):
                for a in performers:
                    if not isinstance(a, dict):
                        continue
                    name = a.get("name")
                    if not name:
                        continue
                    ac = re.sub(r"[\W_]", " ", str(name).lower())
                    actor_list_space.append(ac)
                    actor_list_nospace.append(ac.replace(" ", ""))
            res_actor_title_space = re.sub(r"\s+", " ", " ".join(actor_list_space) + " " + res_title_space).strip()
            # 番号里带的日期与候选条目日期矛盾时, 本候选一律不可用。
            # 只挡下面两条弱证据分支(站点名对不上的标题子串 / scenes 无条件兜底):
            # 搜索词退化成纯系列名时(如 "Deeper.26.06.17" 的第二关键词就是 "Deeper "),
            # ThePornDB 会把同名的其它作品捞回来, 标题去空格后正好是文件名归一化串的
            # 子串("deeper" in "deeper260617"), 于是 2016 年的 SketchySex.16.10.19
            # 「Deeper!」被当成 2026-06-17 的目标。日期矛盾是硬证据, 必须挡掉。
            date_conflict = bool(date) and bool(res_date) and res_date != date
            title_hit = bool(res_title_nospace) and res_title_nospace in temp_file_path_nospace
            series_match = bool(series_ex) and (series_ex == res_series.lower() or series_ex in res_url)

            if series_match:
                if title_hit:
                    res_title_list.append([res_id_url, res_actor_title_space])
                elif date and res_date == date:
                    res_date_list.append([res_id_url, res_actor_title_space])
                elif actor_list_nospace and len(actor_list_nospace) >= actor_number:
                    for a in actor_list_nospace:
                        if a not in temp_file_path_nospace:
                            break
                    else:
                        res_actor_list.append([res_id_url, res_actor_title_space])
            elif title_hit:
                # 站点名对不上但标题精确含在文件名里（如厂牌 slug 与实际站点归属不同，议题 #94）
                if not date_conflict:
                    res_title_list.append([res_id_url, res_actor_title_space])
            elif not series_ex and (kind == "scenes" or title_hit) and not date_conflict:
                res_title_list.append([res_id_url, res_actor_title_space])
        except Exception:
            continue

    # 采纳顺序：标题/演员精确命中 > 日期桶。日期桶证据最弱（同日多部作品常态，
    # 议题 #94 张冠李戴实证），须经相似度裁决，与文件名毫无重合时视为未命中，
    # 留给下一搜索词或其它站点，宁可未找到也不硬配
    for candidate_list in (res_title_list, res_actor_list, res_date_list):
        if not candidate_list:
            continue
        best = max(candidate_list, key=lambda each: similarity(each[1], similarity_target))
        if candidate_list is res_date_list and similarity(best[1], similarity_target) < 0.35:
            continue
        return best[0]
    return False


def get_search_keyword(file_path):
    file_path = remove_escape_string(file_path)
    file_name = os.path.basename(file_path.replace("\\", "/")).replace(",", ".")
    file_name = os.path.splitext(file_name)[0]

    # 只看文件名，避免目录名里的番号被误当成目标；IGNORECASE 兼容小写文件名。
    temp_number = re.findall(
        r"(([A-Z0-9-\.]{2,})[-_\. ]{1}2?0?(\d{2}[-\.]\d{2}[-\.]\d{2}))",
        file_name,
        re.IGNORECASE,
    )
    keyword_list = []
    series_ex = ""
    date = ""
    if temp_number:
        full_number, series_ex, date = temp_number[0]
        series_ex = long_name(series_ex.lower().replace("-", "").replace(".", ""))
        date = "20" + date.replace(".", "-")
        # 第一个搜索词：系列 + 日期，精确召回。
        keyword_list.append(f"{series_ex} {date}".strip())
        # 第二个搜索词：系列 + 标题前两词；标题为空时退化为纯系列名（保留召回手段），
        # 但必须 strip，不能再拼出带尾空格的 "Deeper "。
        temp_title = re.sub(
            r"[-_&\.]", " ", re.sub(re.escape(full_number), "", file_name, count=1, flags=re.IGNORECASE)
        ).strip()
        temp_title_list = [i for i in temp_title.split(" ") if i and i.casefold() != series_ex.casefold()]
        keyword_list.append(" ".join([series_ex, *temp_title_list[:2]]).strip() or series_ex)
    else:
        keyword_list.append(" ".join(file_name.split(".")[:2]).replace("-", " ").strip())

    # 去重并按原顺序保留；空搜索词直接丢弃。
    deduped = []
    seen = set()
    for keyword in keyword_list:
        keyword = keyword.strip()
        if not keyword:
            continue
        key = keyword.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(keyword)
    return deduped, series_ex, date


class ThepornDBCrawler(BaseCrawler):
    description = "欧美：欧美番号"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.THEPORNDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://api.theporndb.net"

    @classmethod
    @override
    def display_name(cls) -> str:
        return "ThepornDB"

    def _headers(self, ctx: Context):
        api_token = manager.config.theporndb_api_token
        if api_token:
            return {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.202 Safari/537.36",
            }
        # ThePornDB 公开的「按 slug 直查详情」端点（/scenes|movies/{slug}）不需要 Token；
        # 用户指定网页地址时走该端点，不能因为没配 Token 直接拒绝（议题 #81）。
        if ctx.input.appoint_url:
            return {
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.202 Safari/537.36",
            }
        raise CrawlerException("请添加 API Token 后刮削！（「软件设置」-「网络」-「API Token」）")

    async def _nearest_site_candidates(
        self,
        ctx: Context,
        kind: TheporndbKind,
        series_ex: str,
        date: str,
        headers: dict,
    ) -> list[str]:
        """裸番号失败时查同站点相邻日期，只用于把「最近有什么」告诉用户。

        结果只进错误提示，不参与匹配：裸番号没有标题/演员证据，跨日自动采纳
        仍可能张冠李戴。这里限定系列 slug 为纯字母数字，避免把带空格的系列名
        当成站点参数。
        """
        if not series_ex or not date or not re.fullmatch(r"[a-z0-9]+", series_ex):
            return []
        try:
            center = date_cls.fromisoformat(date)
        except ValueError:
            return []
        start = (center - timedelta(days=1)).isoformat()
        params = {
            "site": series_ex,
            "date": start,
            "date_operation": ">=",
            "orderBy": "former_released",
            "per_page": 100,
        }
        url = f"{self.base_url}/{kind}?{urlencode(params, quote_via=quote)}"
        ctx.debug(f"未命中，查询同站点相邻日期: {url}")
        ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), url]
        res, error = await self.async_client.get_json(url, headers=headers)
        if not isinstance(res, dict):
            if error:
                ctx.debug(f"相邻日期查询失败: {error}")
            return []
        allowed = {(center + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)}
        labels = []
        seen = set()
        for each in res.get("data") or []:
            if not isinstance(each, dict):
                continue
            slug = each.get("slug")
            if not slug or slug in seen:
                continue
            site = _site_dict(each)
            site_name = str(site.get("short_name") or "").lower()
            site_url = str(site.get("url") or "").lower()
            # 同样忽略站点名/域名里的连字符，避免 TeamSkeet 与 team-skeet.com 对不上。
            site_match = series_ex in f"{site_name} {site_url}".replace("-", "")
            if not site_match:
                continue
            res_date = _normalize_date(each.get("date"))
            if res_date not in allowed:
                continue
            seen.add(slug)
            title = str(each.get("title") or slug)
            labels.append(f"{res_date}《{title}》")
            if len(labels) >= 3:
                break
        return labels

    @override
    async def _run(self, ctx: Context):
        errors = []
        # 指定网址已经写明了 scenes/movies 时只走对应类型，避免先向另一类型
        # 发一个注定 404 的请求（旧逻辑会把 /movies/ 强行替换成 /scenes/）。
        kinds: tuple[TheporndbKind, ...] = ("scenes", "movies")
        appoint_url = (ctx.input.appoint_url or "").lower()
        if "/movies/" in appoint_url:
            kinds = ("movies",)
        elif "/scenes/" in appoint_url:
            kinds = ("scenes",)
        # Token 只校验一次，避免缺失时把同一条提示在 scenes/movies 各报一遍。
        self._headers(ctx)
        for kind in kinds:
            try:
                data = await self._scrape_kind(ctx, kind)
                result = data.to_result()
                result.source = self.site().value
                ctx.debug("数据获取成功！")
                return result
            except Exception as e:
                errors.append(f"{kind}: {e}")
                ctx.debug(f"{kind} 获取失败，尝试下一类型: {e}")
        raise CrawlerException("；".join(errors))

    async def _scrape_kind(self, ctx: Context, kind: TheporndbKind) -> CrawlerData:
        headers = self._headers(ctx)
        file_path = str(ctx.input.file_path or f"{ctx.input.number}.mp4")
        real_url = ctx.input.appoint_url or ""
        if real_url:
            # 同时兼容 theporndb.net / www.theporndb.net，且只替换一次路径类型。
            real_url = re.sub(r"//(?:www\.)?theporndb\.net/", "//api.theporndb.net/", real_url)
            real_url = re.sub(r"/(?:scenes|movies)/", f"/{kind}/", real_url, count=1)
        hash_data = None

        if not real_url:
            use_hash = kind == "movies" or Switch.THEPORNDB_NO_HASH not in manager.config.switch_on
            if use_hash:
                try:
                    file_hash = oshash.oshash(file_path)
                    hash_url = f"{self.base_url}/{kind}/hash/{file_hash}"
                    ctx.debug(f"请求地址: {hash_url}")
                    ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), hash_url]
                    hash_search, error = await self.async_client.get_json(hash_url, headers=headers)
                    if hash_search is None:
                        if "HTTP 401" in str(error):
                            raise CrawlerException("ThePornDB 返回 401，请检查 API Token 是否正确（设置-网络中填写）")
                        ctx.debug(f"Hash 请求失败，继续文件名搜索: {error}")
                        hash_search = {}
                    hash_data = hash_search.get("data") if isinstance(hash_search, dict) else None
                    if hash_data:
                        return read_data(hash_data, kind)
                except CrawlerException:
                    raise
                except Exception:
                    pass

            search_keyword_list, series_ex, date = get_search_keyword(file_path)
            if not search_keyword_list:
                raise CrawlerException("未生成搜索关键词")
            last_search_url = ""
            matched = False
            for search_keyword in search_keyword_list:
                # scenes/movies 都支持 parse（官方 Jellyfin 插件同样用 parse），
                # 查询参数统一百分号转义：空格 %20、& %26，日志里看到的即实际发出的 URL。
                params = {"parse": search_keyword, "per_page": 100}
                last_search_url = f"{self.base_url}/{kind}?{urlencode(params, quote_via=quote)}"
                ctx.debug(f"请求地址: {last_search_url}")
                ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), last_search_url]
                res_search, error = await self.async_client.get_json(last_search_url, headers=headers)
                if res_search is None:
                    if "HTTP 401" in str(error):
                        raise CrawlerException("ThePornDB 返回 401，请检查 API Token 是否正确（设置-网络中填写）")
                    raise CrawlerException(f"请求错误:{error}")

                real_url = get_real_url(res_search, file_path, series_ex, date, kind)
                if real_url:
                    matched = True
                    break
            if not matched:
                hint = ""
                # 裸番号（第二个搜索词退化成纯系列名）才查相邻日期；有标题/演员
                # 证据的文件不应被这条诊断带偏。
                bare_number = len(search_keyword_list) == 1 or (
                    search_keyword_list[1].casefold() == series_ex.casefold()
                )
                if bare_number:
                    nearest = await self._nearest_site_candidates(ctx, kind, series_ex, date, headers)
                    if nearest:
                        hint = f"；同站点相邻日期候选: {'；'.join(nearest)}（未自动采用）"
                raise CrawlerException(f"未找到匹配的内容: {last_search_url}{hint}")

        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [*(ctx.debug_info.detail_urls or []), real_url]
        res_real, error = await self.async_client.get_json(real_url, headers=headers)
        if res_real is None:
            if "HTTP 401" in str(error):
                raise CrawlerException("ThePornDB 返回 401，请检查 API Token 是否正确（设置-网络中填写）")
            raise CrawlerException(f"请求错误:{error}")

        real_data = res_real.get("data") if isinstance(res_real, dict) else None
        if not real_data:
            raise CrawlerException(f"未获取正确数据: {real_url}")
        return read_data(real_data, kind)

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
