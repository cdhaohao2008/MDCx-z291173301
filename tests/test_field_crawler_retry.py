"""失败站点逐字段重试的回归测试。

核心主张：**失败不否定整个站点**。一次请求失败（超时/被拦截/响应解析失败/
请求异常）只说明【那一次】请求失败，不说明该站对后续字段也不可用——超时、
限流、CDN 抖动都是瞬时的。故命中 failed 的站点在每个字段照常重试，重试成功
即恢复供后续字段使用；每次重试也如实记一行，静默只会把用户引向错误结论。

历史背景（保留以说明为何曾有过相反设计）：2026-08 曾把失败标记做成站点级
去重 + 后续字段静默跳过，理由是「同一文件内 140+ 行重复标记」。该权衡现已
被用户明确否决——日志冗余的代价远小于整站字段被一次抖动打掉。
"""

import pytest

from mdcx.config.enums import Website
from mdcx.config.models import FieldConfig
from mdcx.core.file_crawler import FileScraper
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.model_types import (
    CrawlerDebugInfo,
    CrawlerInput,
    CrawlerResponse,
    CrawlerResult,
)
from tests.test_file_crawler_runtime import (
    _build_result,
    _FakeConfig,
    _FakeCrawlerProvider,
)

pytestmark = pytest.mark.asyncio


class _MixedFieldConfig(_FakeConfig):
    """title/outline/series/studio 四字段都有 [javdb(成功), javbus(失败)] 优先级。"""

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
            CrawlerResultFields.SERIES,
            CrawlerResultFields.STUDIO,
        ):
            return FieldConfig(site_prority=[Website.JAVDB, Website.JAVBUS])
        return FieldConfig(site_prority=[])


class _RetryConfig(_FakeConfig):
    """四字段都用同一站，考察该站失败后的逐字段重试行为。"""

    def __init__(self, sites: list[Website] | None = None):
        self._sites = sites or [Website.JAVBUS]

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        return FieldConfig(site_prority=list(self._sites))


class _FlakyCrawler:
    """前 fail_times 次抛瞬时异常，之后返回 data（用于验证重试可恢复）。"""

    def __init__(self, site: Website, records: list[Website], data, fail_times: int):
        self._site = site
        self._records = records
        self._data = data
        self._fail_times = fail_times

    async def run(self, task_input):
        self._records.append(self._site)
        if len(self._records) <= self._fail_times:
            raise TimeoutError("read timed out")
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01),
            data=self._data,
        )


class _StaticCrawler:
    """恒定返回同一份数据、不记录调用。"""

    def __init__(self, data):
        self._data = data

    async def run(self, task_input):
        return CrawlerResponse(debug_info=CrawlerDebugInfo(execution_time=0.01), data=self._data)


class _FlakyCrawlerProvider:
    def __init__(self, site: Website, records: list[Website], data, fail_times: int):
        self._crawler = _FlakyCrawler(site, records, data, fail_times)

    async def get(self, site: Website):
        return self._crawler


async def test_failed_site_retried_and_logged_for_every_field(monkeypatch: pytest.MonkeyPatch):
    """核心断言：javbus 失败后 4 个字段各重试一次，且每次都如实记一行（不再静默跳过）。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
            CrawlerResultFields.SERIES,
            CrawlerResultFields.STUDIO,
        ),
    )

    calls: list[Website] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")

    class _OneFlakyOneAlive:
        """JAVBUS 持续超时；AVBASE 正常返回（让整体结果非 None，才能检查 field_log）。"""

        async def get(self, site: Website):
            if site is Website.AVBASE:
                return _StaticCrawler(ok_data)
            return _FlakyCrawler(Website.JAVBUS, calls, None, fail_times=999)

    scraper = FileScraper(_RetryConfig([Website.JAVBUS, Website.AVBASE]), _OneFlakyOneAlive())
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-55"

    result = await scraper._call_crawlers(task_input, {Website.JAVBUS, Website.AVBASE})

    assert result is not None, "存活站应让整体结果非 None，才能检查 field_log"
    # 预取 1 次 + 4 个字段各 1 次 = 5 次，证明每个字段都重试了（未被永久跳过）
    assert len(calls) == 5, f"应逐字段重试（预取1+字段4），实际 {len(calls)} 次。\ncalls: {calls}"
    # 每次重试都记一行，序号递增——重试是被要求看见的行为
    for n in range(1, 5):
        assert f"重试第 {n} 次仍失败" in result.field_log, f"第 {n} 次重试未记日志。\n{result.field_log}"
    assert result.field_log.count("重试第") == 4, result.field_log


async def test_every_failed_site_is_retried_and_named(monkeypatch: pytest.MonkeyPatch):
    """两个失败站点都被重试、都被点名，且旧的『后续字段将跳过该站』文案已消失。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE),
    )

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: _build_result(Website.JAVDB, "成功标题"),
            Website.JAVBUS: (None, RuntimeError("javbus 失败原因A")),
            Website.AVBASE: (None, RuntimeError("AVBase 失败原因B")),
        }
    )

    class _ThreeSiteConfig(_MixedFieldConfig):
        def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
            if field in (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE):
                return FieldConfig(site_prority=[Website.JAVDB, Website.JAVBUS, Website.AVBASE])
            return FieldConfig(site_prority=[])

    scraper = FileScraper(_ThreeSiteConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-56"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.JAVBUS, Website.AVBASE})

    assert result is not None
    # TITLE 由 JAVDB 命中即 break；OUTLINE 时 JAVDB 无值，才轮到两个失败站各重试一次
    assert result.field_log.count("重试第") == 2, result.field_log
    assert "JavBus" in result.field_log and "AVBase" in result.field_log
    # 旧文案「后续字段将跳过该站」必须彻底消失，否则用户会以为站点被永久拉黑
    assert "后续字段将跳过" not in result.field_log


async def test_retried_site_recovered_after_transient_failure(monkeypatch: pytest.MonkeyPatch):
    """核心回归：站点首败后必须被重试，重试成功即恢复，不得因一次失败永久失声。

    用户诉求（2026-10-17）：「一次失败又不是次次会失败」——超时/被拦截/解析失败
    都是瞬时的，旧实现把 failed 站点在所有后续字段一律跳过，一字段偶发失败就让
    该站对所有字段彻底失声。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.ACTORS),
    )

    calls: list[Website] = []
    # 第 1 次（预取并发批）失败，第 2 次（TITLE 字段重试）成功
    flaky_data = CrawlerResult.empty()
    flaky_data.title = "恢复后的标题"
    flaky_data.actors = ["恢复后的演员"]

    provider = _FlakyCrawlerProvider(Website.JAVBUS, calls, flaky_data, fail_times=1)
    scraper = FileScraper(_RetryConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-RETRY"

    result = await scraper._call_crawlers(task_input, {Website.JAVBUS})

    assert result is not None
    # 预取失败后又请求了 1 次 = 该站没有被「一次失败即永久跳过」
    assert len(calls) == 2, f"失败站点未按字段重试: {calls}"
    # 重试成功后恢复：该站补上的 title 被采用，后续 ACTORS 字段命中缓存
    assert result.title == "恢复后的标题"
    assert result.actors == ["恢复后的演员"]
    assert "重试成功" in result.field_log


async def test_failed_site_mark_includes_cause(monkeypatch: pytest.MonkeyPatch):
    """议题 #101：失败标记必须区分失败类因——「请求超时/被拦截/解析失败/请求异常」。

    用户曾把「AVBase/TheJavDB_API/javdb_app 已失败」误解为逻辑 bug，实际是这些站
    在其网络下请求级失败。标注原因后一眼可分辨，且重试行也必须带上原因。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
        ),
    )

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: (None, TimeoutError("read timed out")),
            Website.JAVBUS: (None, RuntimeError("cloudflare 403 blocked")),
            Website.AVBASE: _build_result(Website.AVBASE, "成功标题"),
        }
    )

    class _TimeoutConfig(_MixedFieldConfig):
        def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB, Website.JAVBUS])

    scraper = FileScraper(_TimeoutConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-101"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB, Website.JAVBUS})
    assert result is not None
    # AVBASE 排在最前且 TITLE 命中即 break，故只有 OUTLINE 字段会轮到两个失败站重试
    assert result.field_log.count("重试第") == 2, result.field_log
    # 两个失败的类因明确标注
    assert "原因: 请求超时" in result.field_log
    assert "原因: 被站点拦截" in result.field_log
