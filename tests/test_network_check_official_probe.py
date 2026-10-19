"""Official 无码官网五站的网络检测项（议题 #133）。

五站各自一行检测项，但 Official 爬虫是「按番号前缀路由」的统一入口：
不给带前缀的探测番号，它就会按 SSNI 落到 manager.computed.official_websites
里的别家官网（实测 SSNI → https://s1s1s1.com），那一家被挡时五行一起报失败，
而实际测的根本不是这五行对应的官网。这里钉住三件事：

1. 五个子检测项各自带 CF Bypass 与「本站专属探测番号」，探测番号能路由回本站；
2. 站点能连通、但探测番号在本站不存在时，走独立的「另行提示」文案；
3. 确定性失败不再被递进重试改写成「均超时」，也真的不再重试。
"""

from types import SimpleNamespace

import pytest

from mdcx.config.enums import Website
from mdcx.core import network_check as nc
from mdcx.core.network_check import (
    NetworkCheckSpec,
    NetworkCheckStatus,
    _is_transient_probe_result,
    _probe_crawler_by_run,
    _probe_crawler_capability,
    _probe_crawler_capability_with_retry,
)
from mdcx.crawlers.official_uncensored import (
    UNCENSORED_OFFICIAL_SITES,
    normalize_uncensored_official_id,
    route_uncensored_official,
)


class FakeConfig:
    use_proxy = False
    proxy = ""
    cf_bypass_url = ""
    cf_bypass_proxy = ""
    cf_bypass_trawl_url = ""
    cf_bypass_trawl_backend = "trawl"
    timeout = 5
    javdb = ""
    javbus = ""
    theporndb_api_token = ""
    proxy_sites = ""
    direct_sites = ""

    def proxy_hosts_list(self):
        return []

    def direct_sites_list(self):
        return []

    def get_site_url(self, site, default=""):
        return default


class FakeManager:
    config = FakeConfig()
    computed = None


class FakeClient:
    """探测走 _run 路径时用不到连接器，留空壳即可。"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fake_manager(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: FakeManager())


def _official_spec(name: str, url: str, probe_number: str) -> NetworkCheckSpec:
    return NetworkCheckSpec(
        name=name,
        group="站点检测",
        url=url,
        site=Website.OFFICIAL,
        enable_cf_bypass=True,
        probe_number=probe_number,
    )


_SCRAPE_OK = object()


def _make_run_only_crawler(recorded: dict, *, error: str | None = None, data: object = _SCRAPE_OK):
    """没有搜索 URL 的爬虫（Official 正是这种），探测会回退真实刮削路径 _run。"""

    class RunOnlyCrawler:
        def __init__(self, client, base_url="", browser=None):
            recorded["base_url"] = base_url

        def new_context(self, input_data):
            return SimpleNamespace(input=input_data)

        async def _generate_search_url(self, ctx):
            return None

        async def run(self, input_data):
            recorded["number"] = input_data.number
            return SimpleNamespace(
                data=data,
                debug_info=SimpleNamespace(error=error),
            )

    return RunOnlyCrawler


# ---------- 1. 五站各自的探测番号与 CF Bypass ----------


def test_official_probe_numbers_route_back_to_their_own_site():
    """每个探测番号都必须被 route_uncensored_official 精确路由回它自己的站点。"""
    probe_numbers = []
    for source, official_spec in UNCENSORED_OFFICIAL_SITES.items():
        number = official_spec.probe_number
        assert number, f"{source} 缺探测番号"
        assert route_uncensored_official(number) == source, f"{source} 的探测番号路由到了别的站：{number}"
        assert normalize_uncensored_official_id(number), f"{source} 的探测番号取不出 movie id：{number}"
        probe_numbers.append(number)

    assert len(set(probe_numbers)) == len(UNCENSORED_OFFICIAL_SITES)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_official_subsite_specs_enable_cf_bypass_and_probe_own_site(monkeypatch: pytest.MonkeyPatch):
    """五个子检测项都要开 CF Bypass，并带上能路由回本站的探测番号。"""

    class DummyOfficialCrawler:
        @classmethod
        def base_url_(cls):
            return ""

    monkeypatch.setattr(
        "mdcx.crawlers.get_registered_crawler_sites",
        lambda include_hidden=False: [Website.OFFICIAL],
    )
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: DummyOfficialCrawler)

    specs = await nc._build_site_specs()

    assert specs, "应生成 Official 子检测项"
    assert len(specs) == len(UNCENSORED_OFFICIAL_SITES)
    for spec in specs:
        assert spec.site is Website.OFFICIAL
        assert spec.enable_cf_bypass is True, f"{spec.name} 未开 CF Bypass"
        assert spec.probe_number, f"{spec.name} 缺探测番号"
        source = route_uncensored_official(spec.probe_number)
        assert UNCENSORED_OFFICIAL_SITES[source].studio in spec.name


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_probe_uses_spec_probe_number_instead_of_global_default(monkeypatch: pytest.MonkeyPatch):
    """spec.probe_number 优先于爬虫类的 probe_number 与全局 SCRAPE_PROBE_NUMBER。"""
    recorded: dict = {}
    crawler_cls = _make_run_only_crawler(recorded, data=SimpleNamespace(number=""))
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: crawler_cls)

    spec = _official_spec("Official·HEYZO", "https://www.heyzo.com", "heyzo-3935")

    status, _ = await _probe_crawler_capability(FakeClient(), spec)

    assert status is NetworkCheckStatus.OK
    assert recorded["number"] == "heyzo-3935"
    assert recorded["base_url"] == "https://www.heyzo.com"


# ---------- 2. 站点能连通、番号不存在 → 另行提示 ----------


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "error",
    [
        "official uncensored request failed: HTTP 404",
        "不在官网番号前缀列表中",
        "搜索结果: 未匹配到番号！",
        "官网子爬虫未返回数据",
    ],
)
async def test_probe_number_missing_is_reported_separately(monkeypatch: pytest.MonkeyPatch, error: str):
    """站点可达但探测番号在本站不存在：单独提示，绝不能报成「站点无效/超时」。"""
    recorded: dict = {}
    crawler_cls = _make_run_only_crawler(recorded, error=error, data=None)
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: crawler_cls)

    spec = _official_spec("Official·Caribbeancom", "https://www.caribbeancom.com", "caribbeancom-082226-001")

    status, message = await _probe_crawler_capability(FakeClient(), spec)

    assert recorded["number"] == "caribbeancom-082226-001"
    assert status is NetworkCheckStatus.WARNING
    assert "未被该站点收录" in message
    assert "caribbeancom-082226-001" in message
    assert "站点无效" not in message
    assert "均超时" not in message
    # 提示文案里要带上真正原因，方便用户判断是番号过期还是站点改版
    assert "（" in message and "）" in message
    # 「未被该站点收录」是确定性结论，不该被拿去递进重试
    assert _is_transient_probe_result(message) is False


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_probe_number_missing_reason_is_specific():
    """不同确定性特征翻译出不同的原因短语（404 / 番号形态 / 搜索无匹配）。"""
    input_data = SimpleNamespace(number="1pondo-072625_001")

    def _crawler(error: str):
        class Crawler:
            async def run(self, data):
                return SimpleNamespace(data=None, debug_info=SimpleNamespace(error=error))

        return Crawler()

    _, http_404 = await _probe_crawler_by_run(_crawler("official uncensored request failed: HTTP 404"), input_data)
    _, not_routed = await _probe_crawler_by_run(_crawler("不在官网番号前缀列表中"), input_data)
    _, no_match = await _probe_crawler_by_run(_crawler("搜索结果: 未匹配到番号！"), input_data)

    assert "404" in http_404
    assert "官网前缀列表" in not_routed
    assert "未匹配" in no_match


# ---------- 3. 确定性失败不重试、不谎报超时 ----------


@pytest.mark.parametrize(
    "message",
    [
        "站点可达但刮削探测失败: 不在官网番号前缀列表中",
        "站点可达但刮削探测失败: 搜索结果: 未匹配到番号！",
        "站点可达但刮削探测失败: 官网子爬虫未返回数据",
        "站点可达但刮削探测失败: official uncensored json failed: not object",
        "站点可达但刮削探测失败: official uncensored data failed: title",
        "站点可达但刮削探测失败: 页面解析失败（解析结果为空，无法执行节点提取/xpath）",
        "站点可达但刮削探测失败: 获取失败: 没有获取到番号标题",
    ],
)
def test_deterministic_probe_results_are_not_retried(message: str):
    """页面已拿到、失败点已确定的结果：重试没有意义，不能再递进（议题 #133）。"""
    assert _is_transient_probe_result(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "站点可达但刮削探测超时",
        "站点可达但搜索页请求失败: ReadTimeout",
        "站点可达但刮削探测失败: official uncensored request failed: ConnectError",
        "站点可达但刮削探测异常: boom",
    ],
)
def test_transient_probe_results_still_retry(message: str):
    """连接/超时类瞬时错误仍按 30s→45s 阶梯重试。"""
    assert _is_transient_probe_result(message) is True


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_retry_ladder_reports_real_cause_when_not_timed_out(monkeypatch: pytest.MonkeyPatch):
    """两档都失败但都不是超时时，终局说明必须带真实原因，不能一律写「均超时」。"""
    calls: list[float | None] = []

    async def fake_probe(client, spec, timeout=None):
        calls.append(timeout)
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测失败: official uncensored request failed: ConnectError"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake_probe)
    spec = _official_spec("Official·1Pondo", "https://www.1pondo.tv", "1pondo-072625_001")

    status, message = await _probe_crawler_capability_with_retry(FakeClient(), spec)

    assert status is NetworkCheckStatus.WARNING
    assert len(calls) == len(nc.SCRAPE_PROBE_ATTEMPT_TIMEOUTS)
    assert "均失败" in message
    assert "均超时" not in message
    assert "official uncensored request failed: ConnectError" in message


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_retry_ladder_still_says_timeout_when_all_attempts_timed_out(monkeypatch: pytest.MonkeyPatch):
    async def fake_probe(client, spec, timeout=None):
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake_probe)
    spec = _official_spec("Official·10Musume", "https://www.10musume.com", "10musume-072625_01")

    status, message = await _probe_crawler_capability_with_retry(FakeClient(), spec)

    assert status is NetworkCheckStatus.WARNING
    assert "均超时" in message
    assert "均失败" not in message


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_deterministic_failure_short_circuits_retry_ladder(monkeypatch: pytest.MonkeyPatch):
    """确定性失败首次即定论：不再白等第二档，也就不会被改写成「均超时」。"""
    calls: list[int] = []

    async def fake_probe(client, spec, timeout=None):
        calls.append(1)
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测失败: 不在官网番号前缀列表中"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake_probe)
    spec = _official_spec("Official·Pacopacomama", "https://www.pacopacomama.com", "pacopacomama-072625_100")

    status, message = await _probe_crawler_capability_with_retry(FakeClient(), spec)

    assert status is NetworkCheckStatus.WARNING
    assert len(calls) == 1
    assert "不在官网番号前缀列表中" in message
    assert "站点无效" not in message


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_format_summary_separates_probe_failure_from_probe_timeout():
    """总结里的根因分组：确定性失败与多次超时分开成组（议题 #133）。"""
    results = [
        nc.NetworkCheckResult(
            spec=_official_spec("Official·1Pondo", "https://www.1pondo.tv", "1pondo-072625_001"),
            status=NetworkCheckStatus.WARNING,
            message="站点无效：刮削探测2次30s/45s均失败，official uncensored data failed: title",
        ),
        nc.NetworkCheckResult(
            spec=_official_spec("Official·HEYZO", "https://www.heyzo.com", "heyzo-3935"),
            status=NetworkCheckStatus.WARNING,
            message="站点无效：刮削探测2次30s/45s均超时",
        ),
    ]

    text = "\n".join(nc.format_summary(results, elapsed=5.0, cancelled=False))

    assert "刮削探测确定性失败×1" in text, text
    assert "刮削探测多次超时×1" in text, text
