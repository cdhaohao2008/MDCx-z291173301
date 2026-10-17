"""同番号失败级联的日志降噪回归测试（field_log 站点级去重）。

背景（议题 #55 报告人日志实证，2026-08-29）：字段循环里对每个已失败
站点按【字段×站点】重复追加 "(已失败, 跳过)"——66 个失败文件的会话
产生 9400 行重复标记（每文件平均 142 行，"dmm 已失败"在同一文件内
重复 20+ 次，信息量趋近零），单次会话 5.5 万行日志中约 1.7 万行是
此类噪声 + 优先级装饰行。

修复：file_crawler 字段循环里失败站点标记改为站点级去重——每站点
的失败信息只记一次，后续字段静默跳过。
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


async def test_failed_site_marked_once_across_fields(monkeypatch: pytest.MonkeyPatch):
    """核心断言：javbus 失败后，4 个字段的循环里失败标记只出现 1 次。"""
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

    # javdb 只有 title/outline；series/studio 无值——这两个字段会轮询到
    # javbus 并触发"已失败跳过"路径（这正是噪声场景：字段轮到失败站点）
    javdb_data = CrawlerResult.empty()
    javdb_data.source = "JavDB"
    javdb_data.title = "标题"
    javdb_data.outline = "简介"

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: javdb_data,
            Website.JAVBUS: (None, RuntimeError("搜索结果: 未匹配到番号！")),
        }
    )
    scraper = FileScraper(_MixedFieldConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-55"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.JAVBUS})

    assert result is not None, "javdb 成功提供 4 字段，应部分成功"
    # 数失败标记行（"(已失败" 行），非字符串总出现——优先级行也含站名
    marks = result.field_log.count("(已失败")
    assert marks == 1, f"javbus 的失败标记应只记 1 次（站点级去重），实际 {marks} 次。\nfield_log:\n{result.field_log}"


async def test_failed_site_dedup_still_names_every_site(monkeypatch: pytest.MonkeyPatch):
    """去重不丢信息：两个失败站点各记一次，且新文案点明『本字段起逐字段重试』。"""
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
    # 每个失败站点恰好各 1 行，且带重试说明
    assert result.field_log.count("(已失败") == 2
    assert "JavBus" in result.field_log and "AVBase" in result.field_log
    assert "本字段起逐字段重试" in result.field_log
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


async def test_persistently_failing_site_retried_each_field_but_log_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
):
    """持续失败的站仍逐字段重试（不静默拉黑），但日志每站最多 2 行（议题 #55 不反弹）。"""
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
    task_input.number = "TEST-RETRY-2"

    result = await scraper._call_crawlers(task_input, {Website.JAVBUS, Website.AVBASE})

    assert result is not None, "存活站应让整体结果非 None，才能检查 field_log"
    # 预取 1 次 + 4 个字段各 1 次 = 5 次，证明每个字段都重试了
    assert len(calls) == 5, f"应逐字段重试（预取1+字段4），实际 {len(calls)} 次"
    # 日志有界：首败 1 行 + 「重试仍失败」1 行 = 2 行，不随字段数线性膨胀
    assert result.field_log.count("(已失败") == 1, result.field_log
    assert result.field_log.count("(重试仍失败") == 1, result.field_log


async def test_failed_site_mark_includes_cause(monkeypatch: pytest.MonkeyPatch):
    """议题 #101：失败标记必须区分失败类因——「请求超时/被拦截/解析失败/请求异常」。

    用户把「AVBase/TheJavDB_API/javdb_app 已失败，后续字段将跳过该站」误解为
    逻辑 bug，实际是这些站在其网络下请求级失败。标注原因后一眼可分辨。
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
    assert result.field_log.count("(已失败") == 2
    # 两个失败的类因明确标注
    assert "原因: 请求超时" in result.field_log
    assert "原因: 被站点拦截" in result.field_log
