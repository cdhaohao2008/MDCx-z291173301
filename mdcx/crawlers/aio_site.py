#!/usr/bin/env python3
import json
from typing import override

from ..base.web import get_aio_domain
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year
from .base.base_types import NOT_SUPPORT


class AioSiteCrawler(BaseCrawler):
    """
    tellme.pw AIO 系列站点（avmoo/avsox/avheat）爬虫基类.

    这些站点是 Vue SPA，页面 HTML 只是壳，数据全部走 JSON API:

      - search:    POST {base}/{namespace}/data/api/search
                   body 为 JSON 数组 `[{"search": 番号, "lang": lang}, 60, 1]`
                   返回 `{"code": 200, "data": [{movieId, movieFanHao, title, ...}]}`
      - getMovie:  POST {base}/{namespace}/data/api/getMovie
                   body 为表单 `{"movieId": "..."}`
                   返回完整影片详情(嵌套 star/studio/genre/series/label/director 等)

    站点入口域名为动态地址，通过 tellme.pw 导航页实时获取（见 base/web.get_aio_domain）。
    子类只需指定命名空间、动态域名键、马赛克类型与语言即可。
    """

    namespace: str = ""
    domain_site: str = ""
    mosaic: str = ""

    # 默认域名（动态获取失败时回退）
    fallback_domain: str = ""

    @classmethod
    def supports_custom_url(cls) -> bool:
        return True

    @classmethod
    def _default_url(cls) -> str:
        return cls.fallback_domain or f"https://{cls.domain_site}.shop"

    @classmethod
    @override
    def base_url_(cls) -> str:
        return cls._default_url()

    @classmethod
    @override
    async def check_urls(cls) -> list[str]:
        """网络检测用动态地址（含默认 fallback）."""
        try:
            domain = await get_aio_domain(cls.domain_site)
            return [domain, cls._default_url()]
        except Exception:
            return [cls._default_url()]

    async def _resolve_domain(self, ctx: Context) -> str:
        """解析站点入口域名：优先用户自定义 URL，其次动态获取，最后回退默认域名。"""
        if self.base_url:
            return self.base_url.rstrip("/")
        try:
            domain = await get_aio_domain(self.domain_site)
            ctx.debug(f"动态域名: {domain}")
            return domain
        except Exception as e:
            ctx.debug(f"动态域名获取失败, 使用默认域名: {e}")
            return self._default_url()

    async def _warmup_cookies(self, ctx: Context, base: str) -> dict[str, str]:
        """预热本站会话：GET 一次站点首页，把 Set-Cookie（如 _csrf）取回，
        后续 API POST 显式携带才能通过 WAF 校验（无 Cookie 直接 POST 会被 403）。
        预热失败返回空 dict，主流程按原逻辑继续，不构成回归。"""
        try:
            resp, _ = await self.async_client.request("GET", base, retry_count=1, enable_cf_bypass=False)
        except Exception as e:
            ctx.debug(f"会话预热失败: {e}")
            return {}
        if resp is None:
            return {}
        try:
            jar = resp.cookies
            if hasattr(jar, "get_dict"):
                return dict(jar.get_dict())
            return {c.name: c.value for c in jar}
        except Exception as e:
            ctx.debug(f"预热 Cookie 提取失败: {e}")
            return {}

    @staticmethod
    def _pick_clean(*values: object) -> str:
        """多语言字段优选：跳过空值与含 U+FFFD（�）的故障值，取首个干净值。

        avsox 搜索固定 `lang=cn`，老番（如 MKBD-S39）的 _ja 常带 � 残码，
        而 _cn 是干净中文（浏览器标签页同源）。逐级回退保证干净优先。
        """
        for value in values:
            text = str(value or "").strip()
            if text and "�" not in text:
                return text
        return ""

    async def _api_search(
        self, ctx: Context, base: str, number: str, cookies: dict[str, str] | None = None
    ) -> dict | None:
        url = f"{base}/{self.namespace}/data/api/search"
        body = json.dumps([{"search": number, "lang": "cn"}, 60, 1])
        json_data, error = await self.async_client.post_json(
            url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            cookies=cookies,
        )
        if error or json_data is None:
            ctx.debug(f"搜索请求失败: {error}")
            return None
        items = json_data.get("data") or []
        if not items:
            ctx.debug("搜索结果为空")
            return None
        # 模糊搜索常带回近似番号（如搜 MKBD-S39 带回 MKBD-S72），优先精确番号。
        want = "".join(number.upper().split())
        for item in items:
            if isinstance(item, dict) and "".join(str(item.get("movieFanHao") or "").upper().split()) == want:
                return item
        first = items[0]
        return first if isinstance(first, dict) else None

    async def _api_get_movie(
        self, ctx: Context, base: str, movie_id: str, cookies: dict[str, str] | None = None
    ) -> dict | None:
        url = f"{base}/{self.namespace}/data/api/getMovie"
        json_data, error = await self.async_client.post_json(
            url,
            data={"movieId": movie_id},
            headers={"Accept": "application/json"},
            cookies=cookies,
        )
        if error or json_data is None:
            ctx.debug(f"详情请求失败: {error}")
            return None
        data = json_data.get("data")
        return data if isinstance(data, dict) else None

    def _build_data(self, movie: dict, input_number: str) -> CrawlerData:
        title = str(movie.get("title") or "").strip()
        if not title:
            title = str(movie.get("title_ja") or "").strip()
        fanhao = str(movie.get("movieFanHao") or input_number or "").strip()

        actors = list(
            dict.fromkeys(
                picked
                for star in (movie.get("star") or [])
                if isinstance(star, dict)
                for picked in [
                    self._pick_clean(
                        star.get("starName_ja"),
                        star.get("starName_en"),
                        star.get("starName_cn"),
                        star.get("starName_tw"),
                        star.get("starName"),
                    )
                ]
                if picked
            )
        )

        tags = list(
            dict.fromkeys(
                picked
                for genre in (movie.get("genre") or [])
                if isinstance(genre, dict)
                for picked in [
                    self._pick_clean(
                        genre.get("genreName_cn"),
                        genre.get("genreName_ja"),
                        genre.get("genreName_en"),
                        genre.get("genreName_tw"),
                        genre.get("genreName"),
                    )
                ]
                if picked
            )
        )

        studio_obj = movie.get("studio") or {}
        series_obj = movie.get("series") or {}
        label_obj = movie.get("label") or {}
        director_obj = movie.get("director") or {}
        studio = self._pick_clean(
            studio_obj.get("studioName_cn"),
            studio_obj.get("studioName_ja"),
            studio_obj.get("studioName_en"),
            studio_obj.get("studioName"),
        )
        series = self._pick_clean(
            series_obj.get("seriesName_cn"),
            series_obj.get("seriesName_ja"),
            series_obj.get("seriesName_en"),
            series_obj.get("seriesName"),
        )
        label = self._pick_clean(
            label_obj.get("labelName_cn"),
            label_obj.get("labelName_ja"),
            label_obj.get("labelName_en"),
            label_obj.get("labelName"),
        )
        director = self._pick_clean(
            director_obj.get("directorName_cn"),
            director_obj.get("directorName_ja"),
            director_obj.get("directorName_en"),
            director_obj.get("directorName"),
        )

        release = str(movie.get("releaseDate") or "").strip()
        length = str(movie.get("length") or "").strip()

        outline = (
            str(movie.get("description_cn") or movie.get("description_zh") or movie.get("description_en") or "").strip()
            if self.with_outline
            else ""
        )

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline=outline or NOT_SUPPORT,
            originalplot=outline or NOT_SUPPORT,
            number=fanhao or input_number,
            release=release,
            year=get_year(release),
            runtime=length,
            studio=studio,
            publisher=label or studio,
            series=series,
            directors=[director] if director else NOT_SUPPORT,
            actors=actors,
            all_actors=actors,
            tags=tags,
            thumb=str(movie.get("posterLarge") or "").strip() or NOT_SUPPORT,
            poster=str(movie.get("posterSmall") or "").strip() or NOT_SUPPORT,
            extrafanart=[str(url or "").strip() for url in (movie.get("sampleLarge") or []) if url and str(url).strip()]
            or NOT_SUPPORT,
            image_download=bool(movie.get("posterSmall") or movie.get("posterLarge")),
            mosaic=self.mosaic,
            external_id=fanhao,
        )

    with_outline: bool = False

    @override
    async def _run(self, ctx: Context):
        number = (ctx.input.number or "").strip()
        if not number:
            raise CrawlerException("番号为空")

        base = await self._resolve_domain(ctx)
        ctx.debug(f"API 基础地址: {base}")

        cookies = await self._warmup_cookies(ctx, base)

        movie = await self._api_search(ctx, base, number, cookies)
        if not movie:
            # 动态域名可能过期/被墙（浏览器直连默认域名却正常），回退默认域名重试一次。
            fallback = self._default_url()
            if fallback != base:
                ctx.debug(f"动态域名搜索无结果，改用默认域名重试: {fallback}")
                cookies = await self._warmup_cookies(ctx, fallback)
                movie = await self._api_search(ctx, fallback, number, cookies)
                if movie:
                    base = fallback
        if not movie:
            raise CrawlerException(f"未找到匹配: {number}")

        movie_id = str(movie.get("movieId") or "").strip()
        ctx.debug(f"搜索命中 movieId: {movie_id}")
        detail = await self._api_get_movie(ctx, base, movie_id, cookies)
        if not detail:
            raise CrawlerException("获取详情失败")

        data = self._build_data(detail, number)
        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    # 三个抽象方法本爬虫用不到（已重写 _run 完全自定义流程），仅需提供实现方可实例化。
    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError
