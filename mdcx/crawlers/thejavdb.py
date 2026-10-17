import html as html_utils
import re
from typing import override
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.log_console import log_console
from mdcx.models.model_types import CrawlerResult
from mdcx.number import number_search_variants

from .base import CrawlerData, CrawlerException
from .dmm import DMMContext, DmmCrawler

# TheJavDB 网页版（thejavdb.net）是 React SPA + Cloudflare 挑战，静态抓取只会拿到
# `Just a moment...`；页面自己取数调的就是下面这个免 CF 直连的 JSON 接口，字段与页面一一对应，
# 所以按番号直接取 `/v1/movies/{universal_id}`。注意 `/v1/` 根路径已废弃，只会返回
# `This endpoint does not exist.`，只有 `/v1/movies...` 前缀不被 Cloudflare 挑战。
API_BASE = "https://api.thejavdb.net/v1"


class TheJavdbMovie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    public_id: str | None = None
    universal_id: str | None = None
    title: str | None = None
    description: str | None = None
    fullcover_url: str | None = None
    frontcover_url: str | None = None
    sample_movie_url: str | None = None
    release_date: str | None = None
    duration: int | str | None = None
    source_url: str | None = None
    maker: str | None = None
    label: str | None = None
    series: str | None = None
    actresses: list[str | None] | None = None
    directors: list[str | None] | None = None
    genres: list[str | None] | None = None
    samples: list[str | None] | None = None


class TheJavDBCrawler(DmmCrawler):
    description = "有码：仅能有码"

    @staticmethod
    def _log(message: str):
        log_console.add_log(f"[TheJavDB] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.THEJAVDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        # 占位站点地址（网页版首页），实际取数走 API_BASE，与 Missav_API 同思路：
        # 站点地址只用于拼详情页与「打开网站」，改它不影响免 CF 直连的取数通道。
        return manager.config.get_site_url(Website.THEJAVDB, "https://thejavdb.net")

    @classmethod
    @override
    def display_name(cls) -> str:
        return "TheJavDB"

    @classmethod
    def build_api_url(cls, number: str) -> str:
        """按番号取详情：与网页版自己调用的 `/v1/movies/{universal_id}` 一致，免 CF 直连。"""
        return f"{API_BASE}/movies/{quote(str(number or '').strip(), safe='')}"

    @classmethod
    def build_detail_url(cls, universal_id: str, public_id: str) -> str:
        """网页详情页：`{站点地址}/movies/{番号}/{public_id}`，如 `/movies/MKMP-765/c6dGLzii`。"""
        return f"{cls.base_url_()}/movies/{quote(str(universal_id or '').strip(), safe='')}/{quote(str(public_id or '').strip(), safe='')}"

    @staticmethod
    def _clean_text(value: object) -> str:
        text = html_utils.unescape(str(value or "").strip())
        if not text:
            return ""
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _clean_list(cls, values: list[str | None] | None) -> list[str]:
        return list(dict.fromkeys(item for value in (values or []) if (item := cls._clean_text(value))))

    @staticmethod
    def _runtime(value: int | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            return str(value) if value > 0 else ""
        if matched := re.search(r"\d+", str(value)):
            return matched.group()
        return ""

    @staticmethod
    def _is_movie_payload(response: object) -> bool:
        """未收录时接口返回 `{"error": "Movie not found."}`，字段全空，按未收录处理。"""
        if not isinstance(response, dict):
            return False
        return any(response.get(key) for key in ("universal_id", "title", "fullcover_url"))

    def _set_number_context(self, ctx: DMMContext) -> None:
        """设置 number_00 / number_no_00，供 DmmCrawler 高清图升级使用。"""
        number = ctx.input.number.lower()
        if x := re.findall(r"[A-Za-z]+-?(\d+)", number):
            digits = x[0]
            if len(digits) >= 5 and digits.startswith("00"):
                number = number.replace(digits, digits[2:])
            elif len(digits) == 4:
                number = number.replace("-", "0")
        ctx.number_00 = number.replace("-", "00")
        ctx.number_no_00 = number.replace("-", "")

    async def _fetch_movie(self, ctx: DMMContext, number: str) -> TheJavdbMovie | None:
        """按番号候依次探测，首个收录即返回；全部未收录返回 None。

        候选来自 `number_search_variants`：DMM 图床番号带 `z` 尾缀（如 `IBW-786z`）而
        TheJavDB 收录基础番号（`IBW-786`），直搜带尾缀的番号会「未收录」。
        """
        candidates = number_search_variants(number) or [number]
        last_error = ""
        for candidate in candidates:
            api_url = self.build_api_url(candidate)
            ctx.debug(f"API URL: {api_url}")
            ctx.debug_info.search_urls = [*ctx.debug_info.search_urls, api_url]
            response, error = await self.async_client.get_json(api_url, headers={"Accept": "application/json"})
            if response is None:
                last_error = error
                ctx.debug(f"API 请求失败: {error}")
                continue
            if not self._is_movie_payload(response):
                ctx.debug(f"API 未收录该番号: {candidate}")
                continue
            try:
                return TheJavdbMovie.model_validate(response)
            except Exception as e:
                ctx.debug(f"API 响应解析失败: {e} {response=}")
                raise CrawlerException(f"API 响应解析失败: {e}") from e
        if last_error:
            self._log(f"请求失败: {last_error}")
        return None

    def _detail_url(self, movie: TheJavdbMovie, fallback_number: str) -> str:
        """拼网页详情页；`public_id` 缺失时留空，由调用方回退到接口自带 source_url。"""
        public_id = self._clean_text(movie.public_id)
        if not public_id:
            return ""
        universal_id = self._clean_text(movie.universal_id) or fallback_number
        return self.build_detail_url(universal_id, public_id)

    @override
    async def _run(self, ctx: DMMContext) -> CrawlerResult:
        number = ctx.input.number.strip()
        if not number:
            raise CrawlerException("番号为空")

        self._set_number_context(ctx)

        movie = await self._fetch_movie(ctx, number)
        if movie is None:
            tried = "、".join(ctx.debug_info.search_urls)
            raise CrawlerException(f"TheJavDB 未收录该番号，已探测: {tried}")

        data = self._to_crawler_data(movie, fallback_number=number)
        if not data.title and not data.thumb:
            raise CrawlerException("API 返回空内容")

        if detail_url := self._detail_url(movie, number):
            self._log(f"详情页: {detail_url}")

        # DMM 高清直链升级（横版+竖版，无码番号内部跳过）
        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        data.thumb, data.poster = await upgrade_dmm_cover(
            ctx, str(data.number or ""), str(data.thumb or ""), str(data.poster or "")
        )

        if data.external_id:
            ctx.debug_info.detail_urls = [str(data.external_id)]

        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    def _to_crawler_data(self, movie: TheJavdbMovie, *, fallback_number: str) -> CrawlerData:
        title = self._clean_text(movie.title)
        outline = self._clean_text(movie.description)
        source_url = self._clean_text(movie.source_url)
        number = self._clean_text(movie.universal_id) or fallback_number
        thumb = self._with_https(str(movie.fullcover_url or "").strip())
        poster = self._with_https(str(movie.frontcover_url or "").strip())

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline=outline,
            originalplot=outline,
            number=number,
            thumb=thumb,
            poster=poster,
            trailer=self._with_https(str(movie.sample_movie_url or "").strip()),
            release=self._clean_text(movie.release_date),
            runtime=self._runtime(movie.duration),
            studio=self._clean_text(movie.maker),
            publisher=self._clean_text(movie.label),
            series=self._clean_text(movie.series),
            actors=self._clean_list(movie.actresses),
            all_actors=self._clean_list(movie.actresses),
            directors=self._clean_list(movie.directors),
            tags=self._clean_list(movie.genres),
            extrafanart=[self._with_https(str(url or "").strip()) for url in (movie.samples or []) if url],
            external_id=self._detail_url(movie, number) or source_url or number,
            mosaic="有码",
        )

    @override
    async def post_process(self, ctx: DMMContext, res: CrawlerResult) -> CrawlerResult:
        if res.trailer:
            res.trailer = self._pick_best_unvalidated_trailer("", [res.trailer])
        if not res.publisher:
            res.publisher = res.studio
        if res.extrafanart and DownloadableFile.EXTRAFANART not in manager.config.download_files:
            res.extrafanart = self._dedupe_urls(res.extrafanart)
        return await super().post_process(ctx, res)
