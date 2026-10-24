"""失败站点逐字段重试的回归测试。

核心主张：**失败不否定整个站点**。一次请求失败（超时/被拦截/响应解析失败/
请求异常）只说明【那一次】请求失败，不说明该站对后续字段也不可用——超时、
限流、CDN 抖动都是瞬时的。故命中 failed 的站点在每个字段照常重试，重试成功
即恢复供后续字段使用；每次重试也如实记一行，静默只会把用户引向错误结论。

但重试有预算（2026-10-24 用户定规）：同一番号对同一站点最多重试 2 次，用尽后
本番号不再请求该站，只留一行「不再请求该站」。19 个字段各重试一次 = 19 次超时
等待，纯属浪费——既不可能在第 13 次突然恢复，也让整批刮削慢到不可用。

历史背景（保留以说明为何曾有过相反设计）：2026-08 曾把失败标记做成站点级
去重 + 后续字段静默跳过，理由是「同一文件内 140+ 行重复标记」。该权衡现已
被用户明确否决——日志冗余的代价远小于整站字段被一次抖动打掉。
"""

import contextlib

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


async def test_retry_capped_per_site(monkeypatch: pytest.MonkeyPatch):
    """请求上限：普通站点一个番号最多请求 3 次，之后不再发请求也不再刷日志。

    用户诉求（2026-10-24）：「一个番号对一个站点默认最多请求三次，重试请求十几次
    人都要疯掉，不仅耗时间还没卵用」。此前每个字段各重试一次，19 个字段就是 19 次
    超时等待；这里断言预算用尽后彻底停手，并只留一行「不再请求该站」。
    """
    fields = (
        CrawlerResultFields.TITLE,
        CrawlerResultFields.OUTLINE,
        CrawlerResultFields.SERIES,
        CrawlerResultFields.STUDIO,
        CrawlerResultFields.PUBLISHER,
        CrawlerResultFields.TRAILER,
    )
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", fields)

    calls: list[Website] = []
    ok_data = _build_result(Website.JAVDB, "存活站的标题")

    class _OneFlakyOneAlive:
        """AVBASE 持续超时；JAVDB 正常返回（让整体结果非 None，才能检查 field_log）。"""

        async def get(self, site: Website):
            if site is Website.JAVDB:
                return _StaticCrawler(ok_data)
            return _FlakyCrawler(Website.AVBASE, calls, None, fail_times=999)

    scraper = FileScraper(_RetryConfig([Website.AVBASE, Website.JAVDB]), _OneFlakyOneAlive())
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-55"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None, "存活站应让整体结果非 None，才能检查 field_log"
    # 预取 1 次 + 重试 2 次 = 3 次；第 3 个字段起直接跳过，不再产生请求
    assert len(calls) == 3, f"单站请求应封顶 3 次（预取1+重试2），实际 {len(calls)} 次。\ncalls: {calls}"
    assert "重试第 1 次仍失败" in result.field_log, result.field_log
    assert "重试第 2 次仍失败" in result.field_log, result.field_log
    assert "重试第 3 次" not in result.field_log, result.field_log
    # 放弃只记一行，后续字段静默跳过（不刷屏）
    assert result.field_log.count("本番号后续字段不再请求该站") == 1, result.field_log


class _MirrorAwareCrawler:
    """记录每次请求实际打到的地址；恒定超时。

    `use_base_url` 模拟 BaseCrawler 的钉地址行为（聚合层按源/镜像交替时调用）。
    `base_url` 模拟 CrawlerProvider 初始化时传入的自定义地址：没有钉地址时就用它。
    """

    def __init__(self, site: Website, records: list[tuple[Website, str]], base_url: str = ""):
        self._site = site
        self._records = records
        self._base_url = base_url
        self._pinned = ""

    @contextlib.contextmanager
    def use_base_url(self, url: str):
        self._pinned = url
        try:
            yield
        finally:
            self._pinned = ""

    async def run(self, task_input):
        self._records.append((self._site, self._pinned or self._base_url))
        raise TimeoutError("read timed out")


def _mirror_provider(records: list[tuple[Website, str]], alive_site: Website, alive_data):
    class _Provider:
        async def get(self, site: Website):
            if site is alive_site:
                return _StaticCrawler(alive_data)
            return _MirrorAwareCrawler(site, records)

    return _Provider()


async def test_mirrored_site_alternates_source_and_mirror(monkeypatch: pytest.MonkeyPatch):
    """JavDB/JavBus/JavLibrary：一个番号最多请求 4 次，按「源 → 镜像 → 源 → 镜像」交替。

    用户 2026-10-24：「第一次源地址，第二次镜像地址，第三次源地址，第四次镜像地址，
    四次还没获取到数据就 pass 掉」。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE, CrawlerResultFields.SERIES),
    )

    records: list[tuple[Website, str]] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")
    provider = _mirror_provider(records, Website.AVBASE, ok_data)
    scraper = FileScraper(_RetryConfig([Website.JAVDB, Website.AVBASE]), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-MIRROR"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.AVBASE})

    assert result is not None
    javdb_requests = [url for site, url in records if site is Website.JAVDB]
    assert javdb_requests == [
        "",  # 第 1 次：源地址（默认 javdb580.com）
        "https://javdb.com",  # 第 2 次：镜像地址（原站）
        "",  # 第 3 次：源地址
        "https://javdb.com",  # 第 4 次：镜像地址
    ], javdb_requests
    assert "已请求 4 次仍失败" in result.field_log, result.field_log
    assert "改用地址" in result.field_log, result.field_log


async def test_javbus_tries_four_addresses_one_each(monkeypatch: pytest.MonkeyPatch):
    """JavBus 四条线路：一个番号 4 次请求，分别用 www.javbus.com / www.dmmsee.casa /
    www.javsee.cyou / www.cdnbus.bond，正好一个地址一次（用户 2026-10-24 定规）。

    一律带 www：四个裸域都会 301 到 www，跨主机跳转会丢掉请求头里的 Cookie。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE, CrawlerResultFields.SERIES),
    )

    records: list[tuple[Website, str]] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")
    provider = _mirror_provider(records, Website.AVBASE, ok_data)
    scraper = FileScraper(_RetryConfig([Website.JAVBUS, Website.AVBASE]), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-JAVBUS"

    result = await scraper._call_crawlers(task_input, {Website.JAVBUS, Website.AVBASE})

    assert result is not None
    javbus_requests = [url for site, url in records if site is Website.JAVBUS]
    assert javbus_requests == [
        "",  # 第 1 次：默认地址（www.javbus.com）
        "https://www.dmmsee.casa",  # 第 2 次
        "https://www.javsee.cyou",  # 第 3 次
        "https://www.cdnbus.bond",  # 第 4 次
    ], javbus_requests
    assert "已请求 4 次仍失败" in result.field_log, result.field_log


async def test_javlibrary_mirror_uses_mirror_crawler(monkeypatch: pytest.MonkeyPatch):
    """JavLibrary 的镜像由独立爬虫提供：偶数次请求走 JavLibraryMirror。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE, CrawlerResultFields.SERIES),
    )

    records: list[tuple[Website, str]] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")
    provider = _mirror_provider(records, Website.AVBASE, ok_data)
    scraper = FileScraper(_RetryConfig([Website.JAVLIBRARY, Website.AVBASE]), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-JAVLIB"

    result = await scraper._call_crawlers(task_input, {Website.JAVLIBRARY, Website.AVBASE})

    assert result is not None
    javlib_requests = [(site, url) for site, url in records if site is not Website.AVBASE]
    assert javlib_requests == [
        (Website.JAVLIBRARY, ""),
        (Website.JAVLIBRARY_MIRROR, "https://f101w.com/cn"),
        (Website.JAVLIBRARY, ""),
        (Website.JAVLIBRARY_MIRROR, "https://f101w.com/cn"),
    ], javlib_requests


async def test_custom_url_disables_source_mirror_alternation(monkeypatch: pytest.MonkeyPatch):
    """用户给源站配置了自定义网址后，所有重试都打自定义地址，绝不切回内置镜像。

    用户诉求（2026-10-24）：当前网站下拉项改了网址并保存后，刮削必须一直用改后的
    网址，不能第一次用自定义地址、第二次又跑回 javdb580.com 之类的默认镜像。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE, CrawlerResultFields.SERIES),
    )

    class _CustomUrlConfig(_RetryConfig):
        def get_site_url(self, site: Website, default: str = "") -> str:
            if site is Website.JAVDB:
                return "https://my-javdb.example"
            return default

    records: list[tuple[Website, str]] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")

    class _Provider:
        async def get(self, site: Website):
            if site is Website.JAVDB:
                return _MirrorAwareCrawler(site, records, base_url="https://my-javdb.example")
            return _StaticCrawler(ok_data)

    scraper = FileScraper(_CustomUrlConfig([Website.JAVDB, Website.AVBASE]), _Provider())
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-CUSTOM-URL"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.AVBASE})

    assert result is not None
    javdb_requests = [url for site, url in records if site is Website.JAVDB]
    assert javdb_requests == ["https://my-javdb.example"] * 4, javdb_requests
    assert "改用镜像地址" not in result.field_log, result.field_log


async def test_custom_url_on_mirror_site_is_used_instead_of_builtin_mirror(monkeypatch: pytest.MonkeyPatch):
    """JavLibrary 镜像站自己配置了自定义网址时，偶数次请求用它而不是写死的 f101w 地址。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE, CrawlerResultFields.SERIES),
    )

    class _CustomMirrorConfig(_RetryConfig):
        def get_site_url(self, site: Website, default: str = "") -> str:
            if site is Website.JAVLIBRARY_MIRROR:
                return "https://my-javlib-mirror.example"
            return default

    records: list[tuple[Website, str]] = []
    ok_data = _build_result(Website.AVBASE, "存活站的标题")

    class _Provider:
        async def get(self, site: Website):
            if site is Website.JAVLIBRARY:
                return _MirrorAwareCrawler(site, records)
            if site is Website.JAVLIBRARY_MIRROR:
                return _MirrorAwareCrawler(site, records, base_url="https://my-javlib-mirror.example")
            return _StaticCrawler(ok_data)

    scraper = FileScraper(_CustomMirrorConfig([Website.JAVLIBRARY, Website.AVBASE]), _Provider())
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-CUSTOM-MIRROR"

    result = await scraper._call_crawlers(task_input, {Website.JAVLIBRARY, Website.AVBASE})

    assert result is not None
    javlib_requests = [(site, url) for site, url in records if site is not Website.AVBASE]
    assert javlib_requests == [
        (Website.JAVLIBRARY, ""),
        (Website.JAVLIBRARY_MIRROR, "https://my-javlib-mirror.example"),
        (Website.JAVLIBRARY, ""),
        (Website.JAVLIBRARY_MIRROR, "https://my-javlib-mirror.example"),
    ], javlib_requests
    assert "https://f101w.com/cn" not in str(javlib_requests)


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

    用户曾把「AVBase/TheJavDB/javdb_app 已失败」误解为逻辑 bug，实际是这些站
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
