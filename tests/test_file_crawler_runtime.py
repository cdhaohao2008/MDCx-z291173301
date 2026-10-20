from pathlib import Path

import pytest

from mdcx.config.enums import FixedScrapingType, Language, Website
from mdcx.config.models import (
    CONFIGURABLE_SCRAPING_TYPES,
    SCRAPING_TYPE_SITE_FIELDS,
    Config,
    FieldConfig,
    FieldPriorityConfig,
)
from mdcx.core.file_crawler import (
    FileScraper,
    _crawl_cache,
    _crawl_cache_key,
    _deal_res,
    classify_existing_scrape_result,
    classify_scrape_task,
)
from mdcx.core.translate import AVWIKI_SCRAPING_TYPES, _should_query_avwiki_actor
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.enums import FileMode
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.model_types import (
    CrawlerDebugInfo,
    CrawlerInput,
    CrawlerResponse,
    CrawlerResult,
    CrawlersResult,
    CrawlTask,
)


class _FakeCrawler:
    def __init__(self, data: CrawlerResult | None, error: Exception | None = None):
        self._data = data
        self._error = error

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01, error=self._error),
            data=self._data,
        )


class _FakeCrawlerProvider:
    def __init__(self, website_data: dict[Website, CrawlerResult | tuple[CrawlerResult | None, Exception | None]]):
        self._website_crawlers = {}
        for site, data in website_data.items():
            if isinstance(data, tuple):
                self._website_crawlers[site] = _FakeCrawler(data[0], data[1])
            else:
                self._website_crawlers[site] = _FakeCrawler(data)

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _RecordingCrawler:
    def __init__(self, site: Website, records: list[tuple[str, str]], should_raise: bool = False):
        self._site = site
        self._records = records
        self._should_raise = should_raise

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        self._records.append((self._site.value, task_input.number))
        if self._should_raise:
            raise RuntimeError("boom")

        data = CrawlerResult.empty()
        data.title = "ok"
        data.source = self._site.value
        data.external_id = f"{self._site.value}:id"
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01),
            data=data,
        )


class _RecordingCrawlerProvider:
    def __init__(self, crawlers: dict[Website, _RecordingCrawler]):
        self._website_crawlers = crawlers

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _ResultRecordingCrawler:
    def __init__(
        self,
        site: Website,
        records: list[Website],
        data: CrawlerResult | None,
        error: Exception | None = None,
    ):
        self._site = site
        self._records = records
        self._data = data
        self._error = error

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        self._records.append(self._site)
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01, error=self._error),
            data=self._data,
        )


class _ResultRecordingCrawlerProvider:
    def __init__(self, crawlers: dict[Website, _ResultRecordingCrawler]):
        self._website_crawlers = crawlers

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _FakeConfig:
    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.RUNTIME, CrawlerResultFields.RELEASE, CrawlerResultFields.YEAR):
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return FieldConfig(site_prority=[])


class _FailureReasonConfig(_FakeConfig):
    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field == CrawlerResultFields.TITLE:
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return super().get_field_config(field)


class _TypePriorityConfig(_FakeConfig):
    def get_type_field_config(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields
    ) -> FieldPriorityConfig:
        if scraping_type == FixedScrapingType.YOUMA and field == CrawlerResultFields.RUNTIME:
            return FieldPriorityConfig(site_prority=[Website.JAVDB, Website.AVBASE])
        return FieldPriorityConfig()


class _ImagePriorityConfig(_FakeConfig):
    scrape_like = "info"
    field_priority_try_all_images = True

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.POSTER, CrawlerResultFields.THUMB):
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return FieldConfig(site_prority=[])

    def get_type_field_config(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields
    ) -> FieldPriorityConfig:
        if field in (CrawlerResultFields.POSTER, CrawlerResultFields.THUMB):
            return FieldPriorityConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return FieldPriorityConfig()


class _Fc2PosterPriorityConfig(_FakeConfig):
    scrape_like = "info"
    field_priority_try_all_images = True

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field == CrawlerResultFields.TITLE:
            return FieldConfig(site_prority=[Website.FC2])
        if field == CrawlerResultFields.POSTER:
            return FieldConfig(site_prority=[Website.FC2PPVDB])
        if field == CrawlerResultFields.THUMB:
            return FieldConfig(site_prority=[Website.FC2PPVDB, Website.FC2])
        return FieldConfig(site_prority=[])

    def get_type_field_config(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields
    ) -> FieldPriorityConfig:
        if scraping_type == FixedScrapingType.FC2 and field == CrawlerResultFields.TITLE:
            return FieldPriorityConfig(site_prority=[Website.FC2])
        if scraping_type == FixedScrapingType.FC2 and field == CrawlerResultFields.POSTER:
            return FieldPriorityConfig(site_prority=[Website.FC2PPVDB])
        if scraping_type == FixedScrapingType.FC2 and field == CrawlerResultFields.THUMB:
            return FieldPriorityConfig(site_prority=[Website.FC2PPVDB, Website.FC2])
        return FieldPriorityConfig()


class _ClassificationConfig:
    fixed_scraping_type = FixedScrapingType.AUTO
    website_youma = {Website.DMM}
    website_wuma = {Website.JAVBUS}
    website_suren = {Website.JAVDAY}
    website_fc2 = {Website.FC2}
    website_oumei = {Website.THEPORNDB}
    website_guochan = {Website.MADOUQU}
    website_dongman = {Website.GETCHU}


def _build_result(site: Website, runtime: str = "", release: str = "", year: str = "") -> CrawlerResult:
    result = CrawlerResult.empty()
    result.source = site.value
    result.external_id = f"{site.value}:id"
    result.title = f"{site.value} title"
    result.runtime = runtime
    result.release = release
    result.year = year
    return result


def _build_image_result(site: Website, poster: str = "", thumb: str = "", image_download: bool = True) -> CrawlerResult:
    result = _build_result(site)
    result.poster = poster
    result.thumb = thumb
    result.image_download = image_download
    return result


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", True),
        ("00", True),
        ("0.0", True),
        ("0.00", True),
        ("55", False),
        ("", False),
    ],
)
def test_is_invalid_runtime(value: str, expected: bool):
    assert FileScraper._is_invalid_runtime(value) is expected


def test_deal_res_normalize_iso_release():
    result = CrawlersResult.empty()
    result.release = "2023-07-14T01:00:00Z"

    normalized = _deal_res(result)

    assert normalized.release == "2023-07-14"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("0", ""),
        ("0.0", ""),
        ("0.00", ""),
        ("8.50", "8.5"),
        ("4.25", "4.2"),
        ("abc", ""),
    ],
)
def test_deal_res_score_empty_and_zero_stay_empty(value: str, expected: str):
    """评分缺失或 0 分(站点未评价)留空,不写 0.0 污染 NFO/命名模板."""
    result = CrawlersResult.empty()
    result.score = value

    assert _deal_res(result).score == expected


@pytest.mark.parametrize(
    ("value", "site_value", "expected"),
    [
        ("8.50", "javlibrary", "8.5(Javlibrary)"),
        ("4.25", "javdb", "4.2(Javdb)"),
        ("4.5", "DMM", "4.5(Dmm)"),
        ("8.50", "", "8.5"),
    ],
)
def test_deal_res_score_appends_source_site(value: str, site_value: str, expected: str):
    """非零评分追加来源站点后缀以区分各站量纲;无来源信息时不追加."""
    from mdcx.gen.field_enums import CrawlerResultFields

    result = CrawlersResult.empty()
    result.score = value
    if site_value:
        result.field_sources[CrawlerResultFields.SCORE] = site_value

    assert _deal_res(result).score == expected


@pytest.mark.parametrize(
    ("number", "mosaic", "short_number", "expected_type", "expected_sites"),
    [
        # 素人番号（259LUXU-1488 / SIRO-5533）一律按有码走：短剧没有番号，
        # 短剧组也就无从自动判断，只有锁定刮削类型选「短剧」时才会用到它。
        ("259LUXU-1488", "", "LUXU-1488", FixedScrapingType.YOUMA, {Website.DMM}),
        ("SIRO-5533", "", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("FC2-123456", "", "", FixedScrapingType.FC2, {Website.FC2}),
        ("100225_100", "无码", "", FixedScrapingType.WUMA, {Website.JAVBUS}),
        ("100225_101", "無修正", "", FixedScrapingType.WUMA, {Website.JAVBUS}),
        ("ABF-131", "无码破解", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-132", "无码流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-133", "流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-134", "無碼破解", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-135", "無碼流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-136", "无码流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("HEYZO-3843", "", "", FixedScrapingType.WUMA, {Website.JAVBUS}),
        ("MD-1234", "", "", FixedScrapingType.GUOCHAN, {Website.MADOUQU}),
        ("DANDY-732", "", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("SSNI00321", "", "", FixedScrapingType.YOUMA, {Website.DMM}),
    ],
)
def test_classify_scrape_task_keeps_existing_type_branches(
    number: str,
    mosaic: str,
    short_number: str,
    expected_type: FixedScrapingType,
    expected_sites: set[Website],
):
    task = CrawlTask.empty()
    task.number = number
    task.mosaic = mosaic
    task.short_number = short_number

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == expected_type
    assert classification.scraping_type_source == "auto"
    assert classification.sites == expected_sites


@pytest.mark.parametrize(
    ("number", "file_path", "expected_website"),
    [
        ("MYWIFE-1500", "D:/test/mywife/MYWIFE-1500.mp4", Website.MYWIFE),
        # 厂牌官网独立成站后，前缀直接锁定单站（classification.sites 只是白名单，
        # 真正保证官网优先的是 website= 强制单站分支）
        ("DLDSS-539", "", Website.DAHLIA),
        ("FNS-165", "", Website.FALENO),
        ("FLN-001", "", Website.FALENO),
        ("JIMMY-003", "", Website.FALENO),
    ],
)
def test_classify_scrape_task_marks_youma_specific_crawlers(number: str, file_path: str, expected_website: Website):
    task = CrawlTask.empty()
    task.number = number
    if file_path:
        task.file_path = Path(file_path)

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.YOUMA
    assert classification.website == expected_website


def test_classify_existing_scrape_result_uses_nfo_mosaic_without_substring_wuma_match():
    task = CrawlTask.empty()
    task.number = "ABF-131"

    result = CrawlersResult.empty()
    result.number = "ABF-131"
    result.mosaic = "无码破解"

    classification = classify_existing_scrape_result(task, result, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.YOUMA
    assert result.scraping_type == FixedScrapingType.YOUMA
    assert result.scraping_type_source == "auto"


def test_classify_scrape_task_fixed_type_overrides_auto_detection():
    class FixedDuanjuConfig(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.SUREN

    task = CrawlTask.empty()
    task.number = "DANDY-732"

    classification = classify_scrape_task(task, FixedDuanjuConfig())

    assert classification.scraping_type == FixedScrapingType.SUREN
    assert classification.scraping_type_source == "fixed"
    assert classification.sites == {Website.JAVDAY}


@pytest.mark.parametrize(
    ("number", "file_path", "mosaic"),
    [
        ("DLID123", "", ""),
        ("xxx", "D:/test/getchu/abc.mp4", ""),
        ("xxx", "D:/test/里番/abc.mp4", ""),
        ("xxx", "D:/test/动漫/abc.mp4", ""),
        ("xxx", "", "动漫"),
        ("xxx", "", "里番"),
    ],
)
def test_classify_scrape_task_routes_dongman(number: str, file_path: str, mosaic: str):
    task = CrawlTask.empty()
    task.number = number
    if file_path:
        task.file_path = Path(file_path)
    task.mosaic = mosaic

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.DONGMAN
    assert classification.scraping_type_source == "auto"


def test_classify_scrape_task_fixed_dongman_uses_dongman_sites():
    class FixedDongmanConfig(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.DONGMAN

    task = CrawlTask.empty()
    task.number = "ABP-123"

    classification = classify_scrape_task(task, FixedDongmanConfig())

    assert classification.scraping_type == FixedScrapingType.DONGMAN
    assert classification.scraping_type_source == "fixed"
    assert classification.sites == {Website.GETCHU}


@pytest.mark.parametrize("number", ["FC2-abc", "FC2-123"])
def test_classify_invalid_fc2_number_in_auto_mode_falls_through(number: str):
    """自动判断下文件名含 FC2 但无 5 位以上数字时，不应误标 fixed 并返回空站点。"""
    task = CrawlTask.empty()
    task.number = number

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.YOUMA
    assert classification.scraping_type_source == "auto"
    assert classification.sites


def test_classify_invalid_fc2_number_in_fixed_fc2_mode_uses_fc2_sites():
    """锁定 FC2 时不受番号格式影响，直接使用 FC2 站点列表（开头 early-return 分支）。"""

    class FixedFc2Config(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.FC2

    task = CrawlTask.empty()
    task.number = "FC2-abc"

    classification = classify_scrape_task(task, FixedFc2Config())

    assert classification.scraping_type == FixedScrapingType.FC2
    assert classification.scraping_type_source == "fixed"
    assert classification.sites == {Website.FC2}


@pytest.mark.parametrize(
    ("scraping_type", "expected_field"),
    [
        (FixedScrapingType.YOUMA, "website_youma"),
        (FixedScrapingType.WUMA, "website_wuma"),
        (FixedScrapingType.SUREN, "website_suren"),
        (FixedScrapingType.FC2, "website_fc2"),
        (FixedScrapingType.OUMEI, "website_oumei"),
        (FixedScrapingType.GUOCHAN, "website_guochan"),
        (FixedScrapingType.DONGMAN, "website_dongman"),
    ],
)
def test_classify_scrape_task_fixed_every_type_uses_its_own_site_list(scraping_type, expected_field):
    """下拉七档逐一锁定都必须路由到自己的网站名单（不看番号格式）。"""

    class _Fixed(_ClassificationConfig):
        fixed_scraping_type = scraping_type

    task = CrawlTask.empty()
    task.number = "ABP-123"

    classification = classify_scrape_task(task, _Fixed())

    assert classification.scraping_type == scraping_type
    assert classification.scraping_type_source == "fixed"
    assert classification.sites == getattr(_ClassificationConfig, expected_field)


@pytest.mark.parametrize(
    "scraping_type",
    [
        FixedScrapingType.YOUMA,
        FixedScrapingType.WUMA,
        FixedScrapingType.SUREN,
        FixedScrapingType.FC2,
        FixedScrapingType.OUMEI,
        FixedScrapingType.GUOCHAN,
        FixedScrapingType.DONGMAN,
    ],
)
def test_locked_types_cover_every_configurable_type(scraping_type):
    """锁定分支查表必须覆盖 CONFIGURABLE_SCRAPING_TYPES 全集。

    回归 2.6.2：classify_scrape_task 曾自带一份硬编码的「类型→website_* 字段」映射，
    与 models.SCRAPING_TYPE_SITE_FIELDS 是两份同源真相。以后新增类型只改 models 时，
    锁定分支会静默拿到 sites=None，最终报「站点名单为空」。改为共用同一张表后，
    本用例即可拦住这类漏改。
    """
    assert set(SCRAPING_TYPE_SITE_FIELDS) == set(CONFIGURABLE_SCRAPING_TYPES)
    assert scraping_type in SCRAPING_TYPE_SITE_FIELDS


def test_classify_scrape_task_fixed_guochan_keeps_guochan_mosaic():
    """锁定国产传媒时马赛克口径必须与自动模式一致（MD- 番号两种模式都是「国产」）。"""

    class FixedGuochanConfig(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.GUOCHAN

    task = CrawlTask.empty()
    task.number = "MD-1234"

    fixed = classify_scrape_task(task, FixedGuochanConfig())
    auto = classify_scrape_task(task, _ClassificationConfig())

    assert fixed.scraping_type == FixedScrapingType.GUOCHAN
    assert fixed.scraping_type_source == "fixed"
    assert fixed.mosaic == "国产"
    assert fixed.mosaic == auto.mosaic


def test_classify_scrape_task_fixed_non_guochan_has_no_forced_mosaic():
    """除国产外，锁定分支不硬塞马赛克：无码/有码仍由番号与文件信息判定，避免误伤。"""

    class FixedWumaConfig(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.WUMA

    task = CrawlTask.empty()
    task.number = "ABP-123"

    assert classify_scrape_task(task, FixedWumaConfig()).mosaic == ""


def test_avwiki_uses_unified_scraping_types():
    assert AVWIKI_SCRAPING_TYPES == {
        FixedScrapingType.YOUMA,
        FixedScrapingType.SUREN,
        FixedScrapingType.FC2,
    }


@pytest.mark.parametrize(
    ("website", "expected_language", "expected_org_language"),
    [
        (Website.AIRAV_CC, Language.ZH_CN, Language.ZH_CN),
        (Website.IQQTV, Language.ZH_CN, Language.ZH_CN),
        (Website.JAVLIBRARY, Language.ZH_CN, Language.ZH_CN),
        (Website.MADOUQU, Language.ZH_CN, Language.ZH_CN),
        (Website.DMM, Language.JP, Language.ZH_CN),
    ],
)
def test_specific_crawler_language_uses_website_enum_members(
    website: Website, expected_language: Language, expected_org_language: Language
):
    config = Config()
    config.set_field_language(CrawlerResultFields.TITLE, Language.ZH_CN)
    scraper = FileScraper(config, _FakeCrawlerProvider({}))

    assert scraper._get_specific_crawler_language(website) == (expected_language, expected_org_language)


@pytest.mark.parametrize(
    ("scraping_type", "actors", "expected"),
    [
        (FixedScrapingType.YOUMA, [], True),
        (FixedScrapingType.YOUMA, ["未知演员"], True),
        (FixedScrapingType.YOUMA, ["葵つかさ"], False),
        (FixedScrapingType.SUREN, ["素人"], True),
        (FixedScrapingType.FC2, ["販売者"], True),
        (FixedScrapingType.WUMA, [], False),
    ],
)
def test_avwiki_youma_only_queries_when_actor_unknown_or_empty(
    scraping_type: FixedScrapingType, actors: list[str], expected: bool
):
    result = CrawlersResult.empty()
    result.scraping_type = scraping_type
    result.actors = actors

    assert _should_query_avwiki_actor(result) is expected


@pytest.mark.asyncio
async def test_call_crawlers_runtime_skip_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, "0"),
            Website.JAVDB: _build_result(Website.JAVDB, "55"),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.runtime == "55"
    assert result.field_sources[CrawlerResultFields.RUNTIME] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawlers_skips_disabled_sites(monkeypatch: pytest.MonkeyPatch):
    """禁用站点既不请求、也不进入字段候选；启用站点照常完成刮削。"""
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME,))

    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.AVBASE: _RecordingCrawler(Website.AVBASE, records),
            Website.JAVDB: _RecordingCrawler(Website.JAVDB, records),
        }
    )
    config = Config(website_youma=[Website.AVBASE, Website.JAVDB], website_disabled=[Website.JAVDB])
    config.set_field_sites(CrawlerResultFields.RUNTIME, [Website.JAVDB, Website.AVBASE])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert records == [("AVBase", "SCUTE-1354")]
    assert "AVBase" in result.site_log
    assert "JavDB" not in result.site_log


@pytest.mark.asyncio
async def test_call_crawlers_all_sites_disabled_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.TITLE,))
    LogBuffer.log().clear()

    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.AVBASE: _RecordingCrawler(Website.AVBASE, records),
            Website.JAVDB: _RecordingCrawler(Website.JAVDB, records),
        }
    )
    config = Config(website_disabled=[Website.AVBASE, Website.JAVDB])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is None
    assert records == []
    assert "全部站点均已禁用" in LogBuffer.log().get()


@pytest.mark.asyncio
async def test_call_specific_crawler_skips_disabled_site():
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider({Website.JAVDB: _RecordingCrawler(Website.JAVDB, records)})
    config = Config(website_disabled=[Website.JAVDB])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_specific_crawler(task_input, Website.JAVDB)

    assert result is None
    assert records == []


@pytest.mark.asyncio
async def test_call_crawlers_records_failure_reasons_when_all_sites_fail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.TITLE,))
    LogBuffer.error().clear()

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: (None, RuntimeError("搜索结果未匹配")),
            Website.JAVDB: (None, TimeoutError()),
        }
    )
    scraper = FileScraper(_FailureReasonConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "JIMMY-003"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is None
    error_text = LogBuffer.error().get()
    assert "所有刮削来源均未返回可用数据" in error_text
    assert "AVBase: 搜索结果未匹配" in error_text
    assert "JavDB: 请求超时" in error_text


@pytest.mark.asyncio
async def test_call_crawlers_release_skip_invalid_and_fill_year(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RELEASE,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, release="0000-00-00"),
            Website.JAVDB: _build_result(Website.JAVDB, release="2024-1-2"),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SIRO-5533"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.release == "2024-01-02"
    assert result.year == "2024"
    assert result.field_sources[CrawlerResultFields.RELEASE] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawlers_uses_type_field_priority(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, "120"),
            Website.JAVDB: _build_result(Website.JAVDB, "55"),
        }
    )
    scraper = FileScraper(_TypePriorityConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(
        task_input,
        classification=classify_scrape_task(task_input, Config(website_youma=[Website.AVBASE, Website.JAVDB])),
    )

    assert result is not None
    assert result.runtime == "55"
    assert result.field_sources[CrawlerResultFields.RUNTIME] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawlers_legacy_site_list_uses_global_field_priority(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, "120"),
            Website.JAVDB: _build_result(Website.JAVDB, "55"),
        }
    )
    config = Config(website_youma=[Website.AVBASE, Website.JAVDB])
    config.set_field_sites(CrawlerResultFields.RUNTIME, [Website.JAVDB, Website.AVBASE])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.runtime == "55"
    assert result.field_sources[CrawlerResultFields.RUNTIME] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawlers_collects_all_image_candidates_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.POSTER, CrawlerResultFields.THUMB))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_image_result(
                Website.AVBASE,
                poster="https://example.test/avbase-poster.jpg",
                thumb="https://example.test/avbase-thumb.jpg",
                image_download=False,
            ),
            Website.JAVDB: _build_image_result(
                Website.JAVDB,
                poster="https://example.test/javdb-poster.jpg",
                thumb="https://example.test/javdb-thumb.jpg",
                image_download=True,
            ),
        }
    )
    scraper = FileScraper(_ImagePriorityConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(
        task_input,
        classification=classify_scrape_task(task_input, Config(website_youma=[Website.AVBASE, Website.JAVDB])),
    )

    assert result is not None
    assert result.poster == "https://example.test/avbase-poster.jpg"
    assert result.poster_from == Website.AVBASE.value
    assert result.poster_list == [
        (Website.AVBASE.value, "https://example.test/avbase-poster.jpg", False),
        (Website.JAVDB.value, "https://example.test/javdb-poster.jpg", True),
    ]
    assert result.thumb_list == [
        (Website.AVBASE.value, "https://example.test/avbase-thumb.jpg"),
        (Website.JAVDB.value, "https://example.test/javdb-thumb.jpg"),
    ]


@pytest.mark.asyncio
async def test_call_crawlers_collects_poster_candidates_only_from_type_poster_priority(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.TITLE, CrawlerResultFields.POSTER))

    provider = _FakeCrawlerProvider(
        {
            Website.FC2: _build_image_result(
                Website.FC2,
                poster="https://example.test/fc2-poster.jpg",
                image_download=False,
            ),
            Website.FC2PPVDB: _build_image_result(
                Website.FC2PPVDB,
                poster="https://example.test/fcppvdb-poster.jpg",
                image_download=True,
            ),
        }
    )
    scraper = FileScraper(_Fc2PosterPriorityConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "FC2-1234567"

    result = await scraper._call_crawlers(
        task_input,
        classification=classify_scrape_task(task_input, Config(website_fc2=[Website.FC2, Website.FC2PPVDB])),
    )

    assert result is not None
    assert result.title == "FC2 title"
    assert result.poster == "https://example.test/fcppvdb-poster.jpg"
    assert result.poster_from == Website.FC2PPVDB.value
    assert result.poster_list == [
        (Website.FC2PPVDB.value, "https://example.test/fcppvdb-poster.jpg", True),
    ]


@pytest.mark.asyncio
async def test_speed_mode_uses_first_successful_type_site_without_field_merge():
    records: list[Website] = []
    provider = _ResultRecordingCrawlerProvider(
        {
            Website.AVBASE: _ResultRecordingCrawler(
                Website.AVBASE, records, _build_result(Website.AVBASE, runtime="120")
            ),
            Website.JAVDB: _ResultRecordingCrawler(Website.JAVDB, records, _build_result(Website.JAVDB, runtime="55")),
        }
    )
    config = Config(scrape_like="speed", website_youma=[Website.AVBASE, Website.JAVDB])
    config.set_field_sites(CrawlerResultFields.RUNTIME, [Website.JAVDB, Website.AVBASE])
    scraper = FileScraper(config, provider)
    task_input = CrawlTask.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper.run(task_input, FileMode.Default)

    assert result is not None
    assert result.runtime == "120"
    assert result.field_sources[CrawlerResultFields.TITLE] == Website.AVBASE.value
    assert records == [Website.AVBASE]


@pytest.mark.asyncio
async def test_speed_mode_falls_back_to_next_site_after_empty_result():
    records: list[Website] = []
    provider = _ResultRecordingCrawlerProvider(
        {
            Website.AVBASE: _ResultRecordingCrawler(Website.AVBASE, records, None),
            Website.JAVDB: _ResultRecordingCrawler(Website.JAVDB, records, _build_result(Website.JAVDB, runtime="55")),
        }
    )
    config = Config(scrape_like="speed", website_youma=[Website.AVBASE, Website.JAVDB])
    scraper = FileScraper(config, provider)
    task_input = CrawlTask.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper.run(task_input, FileMode.Default)

    assert result is not None
    assert result.runtime == "55"
    assert result.field_sources[CrawlerResultFields.TITLE] == Website.JAVDB.value
    assert records == [Website.AVBASE, Website.JAVDB]


@pytest.mark.asyncio
async def test_call_crawler_restore_number_for_mgstage():
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.DMM: _RecordingCrawler(Website.DMM, records),
            Website.MGSTAGE: _RecordingCrawler(Website.MGSTAGE, records),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "200GANA-3327"
    task_input.short_number = "GANA-3327"

    await scraper._call_crawler(task_input, Website.DMM)
    assert task_input.number == "200GANA-3327"

    await scraper._call_crawler(task_input, Website.MGSTAGE)
    assert task_input.number == "200GANA-3327"

    assert records == [
        (Website.DMM.value, "GANA-3327"),
        (Website.MGSTAGE.value, "200GANA-3327"),
    ]


@pytest.mark.asyncio
async def test_call_crawler_restore_number_when_exception():
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.DMM: _RecordingCrawler(Website.DMM, records, should_raise=True),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "200GANA-3327"
    task_input.short_number = "GANA-3327"

    with pytest.raises(RuntimeError, match="boom"):
        await scraper._call_crawler(task_input, Website.DMM)

    assert task_input.number == "200GANA-3327"
    assert records == [(Website.DMM.value, "GANA-3327")]


@pytest.mark.asyncio
async def test_call_specific_crawler_writes_debug_error_to_log_buffer():
    LogBuffer.error().clear()
    provider = _FakeCrawlerProvider({Website.THEPORNDB: (None, RuntimeError("请添加 API Token 后刮削！"))})
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "Nurumassage.26.02.23"

    result = await scraper._call_specific_crawler(task_input, Website.THEPORNDB)

    assert result is None
    assert "请添加 API Token 后刮削！" in LogBuffer.error().get()
    LogBuffer.error().clear()


class _AllFieldsPriorityConfig(_FakeConfig):
    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.TITLE, CrawlerResultFields.ACTORS):
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return super().get_field_config(field)


@pytest.mark.asyncio
async def test_unrecorded_site_retried_for_later_fields(monkeypatch: pytest.MonkeyPatch):
    """议题 #90 方案A：站点连通但未收录该条目（无请求错误）不进 failed，后续字段仍回该站重试。

    旧行为：预收集与字段合并把「未收录」站点加入 failed，后续字段直接跳过该站；
    新行为：未收录站按字段重复请求，仅超时/请求异常才永久跳过。
    """
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.TITLE, CrawlerResultFields.ACTORS))
    LogBuffer.error().clear()

    avbase_calls: list[Website] = []
    javdb_calls: list[Website] = []
    javdb_data = CrawlerResult.empty()
    javdb_data.title = "t"
    javdb_data.actors = ["a"]
    provider = _ResultRecordingCrawlerProvider(
        {
            Website.AVBASE: _ResultRecordingCrawler(Website.AVBASE, avbase_calls, data=None, error=None),
            Website.JAVDB: _ResultRecordingCrawler(Website.JAVDB, javdb_calls, data=javdb_data, error=None),
        }
    )
    scraper = FileScraper(_AllFieldsPriorityConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "JIMMY-003"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    # AVBASE 未收录：预收集 1 次 + 每个字段合并各 1 次（TITLE/ACTORS），证明未被 failed 永久跳过
    assert avbase_calls.count(Website.AVBASE) >= 3, f"未收录站未按字段重复请求: {avbase_calls}"
    # JAVDB 有数据：预收集 1 次后缓存复用，不被重复请求
    assert javdb_calls.count(Website.JAVDB) == 1, f"有数据站被重复请求: {javdb_calls}"
    assert result is not None
    assert result.title == "t"
    assert result.actors == ["a"]


def test_crawl_cache_key_separates_sites_mode_and_type():
    task_input = CrawlerInput.empty()
    task_input.file_path = Path("/tmp/mdcx-cache-key.mp4")
    task_input.number = "SCUTE-1354"
    common = {"sites": [Website.AVBASE, Website.JAVDB], "mode": "full", "scraping_type": FixedScrapingType.YOUMA}
    key = _crawl_cache_key(task_input, **common)
    assert key is not None
    assert key == _crawl_cache_key(task_input, **common)

    assert key != _crawl_cache_key(task_input, **{**common, "sites": [Website.AVBASE]})
    assert key != _crawl_cache_key(task_input, **{**common, "mode": "speed"})
    assert key != _crawl_cache_key(task_input, **{**common, "scraping_type": FixedScrapingType.GUOCHAN})


@pytest.mark.asyncio
async def test_crawl_cache_not_reused_after_site_disabled():
    """禁用站点后不能命中禁用前的缓存，否则会继续使用该站字段和图片候选。"""
    _crawl_cache.clear()
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.AVBASE: _RecordingCrawler(Website.AVBASE, records),
            Website.JAVDB: _RecordingCrawler(Website.JAVDB, records),
        }
    )
    config = Config(website_youma=[Website.AVBASE, Website.JAVDB], website_disabled=[])
    config.set_field_sites(CrawlerResultFields.RUNTIME, [Website.JAVDB, Website.AVBASE])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.file_path = Path("/tmp/mdcx-cache-disabled.mp4")
    task_input.number = "SCUTE-1354"

    try:
        first = await scraper._call_crawlers(task_input, [Website.AVBASE, Website.JAVDB])
        assert first is not None
        assert {site for site, _ in records} == {Website.AVBASE.value, Website.JAVDB.value}

        config.website_disabled = [Website.JAVDB]
        records.clear()
        second = await scraper._call_crawlers(task_input, [Website.AVBASE, Website.JAVDB])

        assert second is not None
        assert records
        assert {site for site, _ in records} == {Website.AVBASE.value}
    finally:
        _crawl_cache.clear()
