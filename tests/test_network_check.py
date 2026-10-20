import sys
import threading
from types import SimpleNamespace

import pytest

from mdcx.config.enums import Website
from mdcx.core import network_check as nc
from mdcx.core.network_check import (
    NetworkCheckResult,
    NetworkCheckSpec,
    NetworkCheckStatus,
    _classify_http_result,
    _compute_used_proxy,
    _is_cloudflare_challenge,
    _probe_crawler_capability,
    _site_result_level,
    build_network_check_specs,
    format_result_line,
    load_site_check_cache,
    merge_site_check_cache,
    run_network_check,
    run_network_check_item,
)


def _patch_check_specs(monkeypatch: pytest.MonkeyPatch, specs: list[NetworkCheckSpec]) -> None:
    """把检测项构建的两处入口都替换成固定列表（按组拆开）。

    run_network_check 现在分两段拿检测项：静态项同步拿、先跑第一组「网络连通」，
    站点项丢后台并发构建、到后续分组再 join（原为 build_network_check_specs
    一次 await 全部拿齐）。要注入假检测项必须两处都打桩，否则真实检测项会混进来，
    结果数/总项数全对不上。「站点检测」组归站点项，其余组归静态项。
    """
    static_specs = [spec for spec in specs if spec.group != "站点检测"]
    site_specs = [spec for spec in specs if spec.group == "站点检测"]

    async def fake_site_specs() -> list[NetworkCheckSpec]:
        return list(site_specs)

    monkeypatch.setattr("mdcx.core.network_check._build_static_specs", lambda: list(static_specs))
    monkeypatch.setattr("mdcx.core.network_check._build_site_specs", fake_site_specs)


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok", url: str = "https://example.test"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = {}
        self.encoding = "utf-8"


class FakeClient:
    def __init__(self, *, fail_url_part: str = ""):
        self.fail_url_part = fail_url_part
        self.calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.fail_url_part and self.fail_url_part in url:
            raise RuntimeError("boom")
        return FakeResponse(url=url), ""


class FakeBypassClient:
    def __init__(self, *, bypass_ok: bool = True):
        self.bypass_ok = bypass_ok
        self.calls: list[dict] = []
        self.bypass_calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(
            text="<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>Cloudflare</html>",
            url=url,
        ), ""

    async def _try_bypass_cloudflare(self, **kwargs):
        self.bypass_calls.append(kwargs)
        if not self.bypass_ok:
            return None, "bypass failed"
        response = FakeResponse(text="<html>ok</html>", url=kwargs["target_url"])
        response.headers["x-mdcx-bypass-mode"] = "mirror"
        return response, ""


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
    website_disabled = []

    def proxy_hosts_list(self):
        return [s.strip() for s in (self.proxy_sites or "").split(",") if s.strip()]

    def direct_sites_list(self):
        return [s.strip() for s in (self.direct_sites or "").split(",") if s.strip()]

    def get_site_url(self, site, default=""):
        return default


class FakeManager:
    config = FakeConfig()
    computed = None


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fake_manager(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: FakeManager())


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_7mmtv_in_check_specs_and_probe_path(monkeypatch: pytest.MonkeyPatch):
    """7mmtv 已注册即自动进入检测清单；搜索探测链路走 _generate_search_url→搜索页匹配。"""

    from mdcx.config.models import Website as WebsiteEnum
    from mdcx.crawlers import get_registered_crawler_sites

    # 1) 注册爬虫清单含 7mmtv → 检测规格构建自动覆盖
    values = [s.value for s in get_registered_crawler_sites()]
    assert "7mmtv" in values

    # 2) 探测路径：搜索页 fixture 匹配探针番号 → OK
    from mdcx.core.network_check import (
        NetworkCheckSpec,
        NetworkCheckStatus,
        _probe_crawler_capability,
    )

    class FakeResponse:
        text = '<figure class="video-preview"><a href="/zh/x/SSNI-647.html"><img alt="SSNI-647 標題"></a></figure>'
        encoding = "utf-8"

    class FakeClient:
        async def request(self, method, url, **kwargs):
            return FakeResponse(), ""

    spec = NetworkCheckSpec(
        name="7mmtv",
        group="刮削站点",
        url="https://www.7mmtv.sx",
        site=WebsiteEnum.MMTV,
    )
    status, message = await _probe_crawler_capability(FakeClient(), spec)
    assert status is NetworkCheckStatus.OK, f"7mmtv 探测失败: {status} {message}"

    # 3) 搜索页无匹配番号时给 WARNING（未被收录提示），不炸整轮
    class FakeResponseMiss(FakeResponse):
        text = '<figure class="video-preview"><a href="/x.html"><img alt="OTHER-1"></a></figure>'

    class FakeClientMiss:
        async def request(self, method, url, **kwargs):
            return FakeResponseMiss(), ""

    # get_real_url 无匹配时 _parse_search_page 抛 CrawlerException → 转 WARNING
    status2, message2 = await _probe_crawler_capability(FakeClientMiss(), spec)
    assert status2 is NetworkCheckStatus.WARNING, f"未收录场景应 WARNING: {status2} {message2}"


@pytest.mark.anyio
async def test_build_network_check_specs_uses_registered_sites_without_key_error(monkeypatch: pytest.MonkeyPatch):
    class DynamicCrawler:
        @classmethod
        def base_url_(cls):
            return ""

    class CustomConfig(FakeConfig):
        def get_site_url(self, site, default=""):
            return "https://custom.example"

    class CustomManager:
        config = CustomConfig()
        computed = None

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.OFFICIAL],
        get_crawler=lambda site: DynamicCrawler,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: CustomManager())

    specs = await build_network_check_specs()

    assert any(spec.site == Website.OFFICIAL and spec.url == "https://custom.example" for spec in specs)


@pytest.mark.anyio
async def test_build_network_check_specs_skips_disabled_sites(monkeypatch: pytest.MonkeyPatch):
    """被禁用的站点不在检测清单里生成任何一行，连请求都不发。"""

    class DisabledConfig(FakeConfig):
        website_disabled = [Website.JAVDB]

    class DisabledManager:
        config = DisabledConfig()
        computed = None

    class DynamicCrawler:
        @classmethod
        def base_url_(cls):
            return "https://example.test"

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.AVBASE, Website.JAVDB],
        get_crawler=lambda site: DynamicCrawler,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: DisabledManager())

    specs = await build_network_check_specs()

    assert any(spec.site == Website.AVBASE for spec in specs)
    assert all(spec.site != Website.JAVDB for spec in specs)


@pytest.mark.anyio
async def test_build_network_check_specs_skips_disabled_official_only(monkeypatch: pytest.MonkeyPatch):
    """禁用 Official 只跳过 Official 本行，五个无码官网拆出的独立站点不受影响。"""

    five_sites = [
        Website.OFFICIAL_10MUSUME,
        Website.OFFICIAL_1PONDO,
        Website.OFFICIAL_CARIBBEANCOM,
        Website.OFFICIAL_HEYZO,
        Website.OFFICIAL_PACOPACOMAMA,
    ]

    class DisabledConfig(FakeConfig):
        website_disabled = [Website.OFFICIAL]

    class DisabledManager:
        config = DisabledConfig()
        computed = None

    from mdcx.crawlers import get_crawler as real_get_crawler

    monkeypatch.setattr(
        "mdcx.crawlers.get_registered_crawler_sites",
        lambda include_hidden=False: list(five_sites),
    )
    monkeypatch.setattr("mdcx.crawlers.get_crawler", real_get_crawler)
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: DisabledManager())

    specs = await build_network_check_specs()

    assert all(spec.site != Website.OFFICIAL for spec in specs)
    assert [spec.site for spec in specs if spec.site in five_sites] == five_sites


@pytest.mark.anyio
async def test_build_network_check_specs_skips_one_disabled_uncensored_site(monkeypatch: pytest.MonkeyPatch):
    """禁用某个无码官网只隐藏它自己，其余四站与 Official 本行照旧。"""

    class DisabledConfig(FakeConfig):
        website_disabled = [Website.OFFICIAL_HEYZO]

    class DisabledManager:
        config = DisabledConfig()
        computed = None

    from mdcx.crawlers import get_crawler as real_get_crawler

    monkeypatch.setattr(
        "mdcx.crawlers.get_registered_crawler_sites",
        lambda include_hidden=False: [Website.OFFICIAL, Website.OFFICIAL_10MUSUME, Website.OFFICIAL_HEYZO],
    )
    monkeypatch.setattr("mdcx.crawlers.get_crawler", real_get_crawler)
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: DisabledManager())

    specs = await build_network_check_specs()
    sites = [spec.site for spec in specs]

    assert Website.OFFICIAL_HEYZO not in sites
    assert Website.OFFICIAL_10MUSUME in sites
    assert Website.OFFICIAL in sites


@pytest.mark.anyio
async def test_run_network_check_retry_skips_sites_disabled_after_failure(monkeypatch: pytest.MonkeyPatch):
    """重试旧失败项时按当前禁用名单过滤，不再请求刚被禁用的站。"""

    class DisabledConfig(FakeConfig):
        website_disabled = [Website.JAVDB]

    class DisabledManager:
        config = DisabledConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: DisabledManager())
    spec = NetworkCheckSpec(name="JavDB", group="站点检测", url="https://javdb.com", site=Website.JAVDB)

    results = await run_network_check(
        specs=[spec],
        client=FakeClient(),
        emit_header=False,
        concurrency=1,
    )

    assert results == []


@pytest.mark.anyio
async def test_probe_crawler_strips_special_check_path_from_base_url(monkeypatch: pytest.MonkeyPatch):
    """议题 #77：spec.url 拼有 SPECIAL_CHECK_PATHS 探测路径时，探测构造爬虫必须剥回主站根 URL。

    实证：airav_cc 探测 URL 出现 https://airav.io/playon.aspx?hid=44733/cn/search_result?kw=... 畸形拼接；
    javdb（/v/D16Q5?locale=zh）、javbus（/FSDSS-660）同因导致「搜索失败/未匹配到番号」。
    """
    import mdcx.crawlers as crawlers_mod

    recorded: dict = {}

    class OriginCrawler:
        def __init__(self, client, base_url="", browser=None):
            self.base_url = base_url
            recorded["base_url"] = base_url

        def new_context(self, input_data):
            return SimpleNamespace(input=input_data)

        async def _generate_search_url(self, ctx):
            return f"{self.base_url}/search?q=TEST"

        async def _parse_search_page(self, ctx, html, search_url):
            return ["https://example.com/detail"]

        def _get_headers(self, ctx):
            return None

        def _get_cookies(self, ctx):
            return None

    monkeypatch.setattr(crawlers_mod, "get_crawler", lambda site: OriginCrawler)

    client = FakeClient()
    spec = NetworkCheckSpec(
        name="JavBus", group="刮削站点", url="https://www.javbus.com/FSDSS-660", site=Website.JAVBUS
    )

    status, _ = await _probe_crawler_capability(client, spec)

    assert status is NetworkCheckStatus.OK
    assert recorded["base_url"] == "https://www.javbus.com"
    assert client.calls[0]["url"] == "https://www.javbus.com/search?q=TEST"


@pytest.mark.anyio
async def test_mirror_sample_spec_runs_scrape_probe(monkeypatch: pytest.MonkeyPatch):
    """镜像项同样走刮削探测：通过时要说「连接正常，刮削正常」（用户 2026-10-19）。

    旧版（议题 #77）把镜像行整体豁免在探测之外，行尾永远只有一句「连接正常」——
    用户看不出镜像到底能不能刮。现存唯一的镜像项 `Javlibrary·镜像` 的爬虫是
    JavLibraryCrawler 的子类（页面结构同源、探测 URL 模式一致），当初豁免针对的
    「展示页域名型镜像」（xcity.jp 无 /api/search）已不存在于检测项里，故一并探测。
    """
    probe_called: list[str] = []

    async def fake(client, spec, probe_timeout=None):
        probe_called.append(spec.name)
        return NetworkCheckStatus.OK, "连接正常，刮削正常"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake)

    spec = NetworkCheckSpec(
        name="Javlibrary·镜像",
        group="站点检测",
        url="https://www.f101w.com/cn/?v=javme2j2tu",
        site=Website.JAVLIBRARY_MIRROR,
    )
    result = await run_network_check_item(spec, client=FakeClient())

    assert probe_called == ["Javlibrary·镜像"], "镜像项必须真的发起刮削探测"
    assert result.status == NetworkCheckStatus.OK
    assert result.message == "连接正常，刮削正常"


@pytest.mark.anyio
async def test_run_network_check_item_retries_probe_within_first_round(monkeypatch: pytest.MonkeyPatch):
    """议题 #118：首轮检测内部就自动递进重试（30s/45s），用户不必手动点「重试失败项」。"""
    seen: list[float | None] = []

    async def fake(client, spec, probe_timeout=None):
        seen.append(probe_timeout)
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake)
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    result = await run_network_check_item(spec, client=FakeClient())

    assert seen == [30.0, 45.0], "单项检测必须走满轮内阶梯"
    assert result.status == NetworkCheckStatus.WARNING
    assert result.message == "站点无效：刮削探测2次30s/45s均超时"


def test_message_for_error_tls_handshake():
    """SSL_ERROR_SYSCALL / UNEXPECTED_EOF 类的 TLS 握手中断要给出可执行指引（议题 #77 javdb_api/r18dev）。"""
    from mdcx.core.network_check import _message_for_error

    msg = _message_for_error("SSL_ERROR_SYSCALL; error queue empty: Failed to perform")
    assert msg == "TLS握手中断，常为HTTP/2指纹/SNI策略与目标站不兼容"

    msg2 = _message_for_error("UNEXPECTED_EOF_WHILE_READING")
    assert "TLS" in msg2 or "SSL" in msg2


def test_classify_403_cf_challenge_hint():
    """CF 403 要引导配 CF Bypass（议题 #77 lulubar/missav 批）。"""
    cf_body = "<html><title>Attention Required! | Cloudflare</title><body>cloudflare ray id</body></html>"

    spec = NetworkCheckSpec(name="missav", group="刮削站点", url="https://missav.ai")
    status, message = _classify_http_result(spec, 403, cf_body)

    assert status == NetworkCheckStatus.WARNING
    assert "Cloudflare" in message
    assert "CF Bypass" in message or "外部CF服务" in message


def test_classify_403_plain_block():
    """非 CF 的 403（出站 IP 被站点封）提示换节点，不提 CF Bypass。"""
    spec = NetworkCheckSpec(name="getchu", group="刮削站点", url="http://www.getchu.com")
    status, message = _classify_http_result(spec, 403, "<html>Forbidden</html>")

    assert status == NetworkCheckStatus.WARNING
    assert "节点" in message
    assert "CF Bypass" not in message


def test_classify_external_cf_service_503_warming_up():
    """TRAWL 预热期 GET /health 返回 503：报 WARNING（正在启动）而不是 FAILED，避免误导改配置。"""
    spec = NetworkCheckSpec(name="外部CF服务", group="辅助服务", url="http://127.0.0.1:8191/health")
    status, message = _classify_http_result(spec, 503, '{"status": "starting"}')

    assert status == NetworkCheckStatus.WARNING
    assert "正在启动" in message


def test_format_summary_groups_failure_causes():
    """失败/警告项按成因分组显示在总结里（议题 #77）。"""
    from mdcx.core.network_check import NetworkCheckResult, format_summary

    def r(name, status, message):
        return NetworkCheckResult(
            spec=NetworkCheckSpec(name=name, group="刮削站点", url="https://x.test"),
            status=status,
            message=message,
        )

    results = [
        r("missav", NetworkCheckStatus.WARNING, "站点可达但搜索页被 Cloudflare 拦截"),
        r(
            "javlibrary",
            NetworkCheckStatus.FAILED,
            "GET https://e100k.com 失败: 连接错误（bypass 兜底失败: mirror 返回 Cloudflare 挑战页）",
        ),
        r("getchu", NetworkCheckStatus.FAILED, "HTTP 403 请求被拒绝：当前节点出口 IP 可能被站点封禁"),
        r("javdb_api", NetworkCheckStatus.FAILED, "TLS 握手中断"),
        r("avbase", NetworkCheckStatus.WARNING, "站点无效：刮削探测2次30s/45s均超时"),
        r("ok", NetworkCheckStatus.OK, "连接正常"),
    ]
    lines = format_summary(results, elapsed=5.0, cancelled=False)

    text = "\n".join(lines)
    assert "根因分组" in text
    assert "Cloudflare" in text
    # 汇总文案已统一为无空格品牌写法「Cloudflare拦截×N」（与 format_summary 输出一致）
    assert "Cloudflare拦截×1" in text
    # bypass 已尝试但未解开：不再让人去配服务，单独成组
    assert "CF Bypass 已尝试但未解开 ×1" in text
    assert "节点" in text
    # 议题 #118：轮内重试仍超时的站点要单独成组，不能混进「其他异常」或「未收录」
    assert "刮削探测多次超时×1" in text
    assert "30s/45s" in text


def test_format_summary_bypass_failure_suffix_counts_as_unsolved():
    """直连传输失败兜底那一支的错误后缀（`CloudFlare Bypass失败：…`）也算「CF Bypass 已尝试但未解开」。

    该后缀去掉了「兜底」二字；直连错误里又带着 `Cloudflare`（web_async 的
    `遭遇Cloudflare挑战页且Bypass失败` 会和传输错误一起累积进同一条检测行），
    分组若只认旧文案，这类行会掉回「Cloudflare拦截×N：请配置外部CF服务」——
    服务明明已配好并实际跑过，正是加这个分组要避免的错误建议。
    """
    from mdcx.core.network_check import NetworkCheckResult, format_summary

    results = [
        NetworkCheckResult(
            spec=NetworkCheckSpec(name="getchu", group="刮削站点", url="https://www.getchu.com"),
            status=NetworkCheckStatus.FAILED,
            message=(
                "GET https://www.getchu.com 失败: 遭遇Cloudflare挑战页且Bypass失败: HTTP 403、"
                "Failed to perform CloudFlare Bypass失败：HTTP 502"
            ),
        )
    ]

    text = "\n".join(format_summary(results, elapsed=1.0, cancelled=False))

    assert "CF Bypass 已尝试但未解开 ×1" in text, text
    assert "Cloudflare拦截×" not in text, text


def test_format_summary_separator_width_follows_panel():
    """汇总区的「-」「=」两条分隔线必须同长，且跟随传入的面板可视宽。

    原来两处是各自硬编码的字面量（开头「-」、结尾「=」各写各的），与面板最上/最下
    那两条按可视宽自适应的横幅对不上，同一份报告里分隔线参差不齐。
    """
    from mdcx.core.network_check import (
        DEFAULT_SEPARATOR_WIDTH,
        NetworkCheckResult,
        format_summary,
    )

    def r(name, status, message):
        return NetworkCheckResult(
            spec=NetworkCheckSpec(name=name, group="刮削站点", url="https://x.test"),
            status=status,
            message=message,
        )

    results = [
        r("missav", NetworkCheckStatus.WARNING, "站点无效：刮削探测2次30s/45s均超时"),
        r("bad", NetworkCheckStatus.FAILED, "boom"),
    ]

    # 1. 传入面板量出的宽度：首尾两条分隔线都恰好该长
    lines = format_summary(results, elapsed=5.0, cancelled=False, separator_width=120)
    assert lines[0] == "-" * 120
    assert lines[-1] == "=" * 120

    # 2. 与面板横幅共用同一个收敛函数，故永远同长
    from mdcx.controllers.main_window.handlers import net_separator_width

    panel_chars = 137  # MyMAinWindow._net_separator_chars() 量到的原始字符数
    banner = net_separator_width(panel_chars)
    lines = format_summary(results, elapsed=5.0, cancelled=False, separator_width=banner)
    assert lines[0] == "-" * banner == lines[-1].replace("=", "-")

    # 3. 不传/传非法值时退回兜底宽度，不产生空行（量不到可视宽的降级路径）
    for bad in (None, 0, -5):
        lines = format_summary(results, elapsed=5.0, cancelled=False, separator_width=bad)
        assert len(lines[0]) == DEFAULT_SEPARATOR_WIDTH
        assert len(lines[-1]) == DEFAULT_SEPARATOR_WIDTH

    # 4. 头部的表格分隔线同样跟随（否则报告上半段与下半段宽度不一）
    from mdcx.core.network_check import _format_header

    header_seps = [line for line in _format_header(120) if line and set(line) == {"="}]
    assert len(header_seps) == 2
    assert all(len(line) == 120 for line in header_seps)


@pytest.mark.anyio
async def test_run_network_check_item_catches_single_item_exception():
    spec = NetworkCheckSpec(name="bad", group="刮削站点", url="https://bad.example")

    result = await run_network_check_item(spec, client=FakeClient(fail_url_part="bad"))

    assert result.status == NetworkCheckStatus.FAILED
    assert result.message == "检测异常"
    assert result.error == "boom"


@pytest.mark.anyio
async def test_run_network_check_survives_task_level_exception(monkeypatch: pytest.MonkeyPatch):
    """task.result() 层逃逸的异常（绕过 item 兜底）不应中断整轮检测（议题 #73）。

    实证：检测网络页跑到中途输出「网络检测出现异常：」（空消息）后整轮停止——
    主循环 task.result() 无兜底，单个 task 逃逸的异常中断整轮。空消息异常
    （如裸 TimeoutError，str() 为空）还导致用户看不到任何线索。
    """
    import mdcx.core.network_check as nc_module

    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="good", group="网络连通", url="https://good.example"),
            NetworkCheckSpec(name="boom", group="网络连通", url="https://boom.example"),
            NetworkCheckSpec(name="also_good", group="网络连通", url="https://also.example"),
        ],
    )

    real_item = nc_module.run_network_check_item

    async def flaky_item(spec, *, cancel_event=None, client=None):
        if spec.name == "boom":
            raise TimeoutError  # 空消息异常，复刻用户场景的形态
        return await real_item(spec, cancel_event=cancel_event, client=client)

    monkeypatch.setattr("mdcx.core.network_check.run_network_check_item", flaky_item)
    lines: list[str] = []

    results = await run_network_check(progress=lines.append, client=FakeClient(), concurrency=3, emit_header=False)

    assert len(results) == 3
    by_name = {r.spec.name: r for r in results}
    assert by_name["good"].status == NetworkCheckStatus.OK
    assert by_name["also_good"].status == NetworkCheckStatus.OK
    assert by_name["boom"].status == NetworkCheckStatus.FAILED
    # 空消息异常也必须带上类型名，否则用户又拿到「出现异常：」空行
    assert "TimeoutError" in by_name["boom"].error
    assert any("网络检测已完成" in line for line in lines)


@pytest.mark.anyio
async def test_run_network_check_cancelled_task_does_not_stop(monkeypatch: pytest.MonkeyPatch):
    """单个 task 内部抛 CancelledError 应软着陆（记 CANCELLED），不中断整轮（议题 #73）。

    用户截图实锤：CancelledError 从 future.result() 逃逸导致整轮停止。
    整轮取消由 cancel_event 分支统一处理，单项内部取消不应穿透。
    """
    import asyncio

    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="cancelled", group="网络连通", url="https://c.example"),
            NetworkCheckSpec(name="good", group="网络连通", url="https://g.example"),
        ],
    )

    real_item = nc.run_network_check_item

    async def flaky_item(spec, *, cancel_event=None, client=None):
        if spec.name == "cancelled":
            raise asyncio.CancelledError
        return await real_item(spec, cancel_event=cancel_event, client=client)

    monkeypatch.setattr("mdcx.core.network_check.run_network_check_item", flaky_item)
    lines: list[str] = []

    results = await run_network_check(progress=lines.append, client=FakeClient(), emit_header=False)

    assert len(results) == 2
    by_name = {r.spec.name: r for r in results}
    assert by_name["cancelled"].status == NetworkCheckStatus.CANCELLED
    assert by_name["good"].status == NetworkCheckStatus.OK
    assert any("网络检测已完成" in line for line in lines)


@pytest.mark.anyio
async def test_run_network_check_does_not_stop_on_single_item_exception(monkeypatch: pytest.MonkeyPatch):
    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="good", group="网络连通", url="https://good.example"),
            NetworkCheckSpec(name="bad", group="网络连通", url="https://bad.example"),
        ],
    )
    lines: list[str] = []

    results = await run_network_check(
        progress=lines.append, client=FakeClient(fail_url_part="bad"), concurrency=2, emit_header=False
    )

    assert len(results) == 2
    assert {result.spec.name: result.status for result in results} == {
        "good": NetworkCheckStatus.OK,
        "bad": NetworkCheckStatus.FAILED,
    }
    assert any("网络检测已完成" in line for line in lines)


@pytest.mark.anyio
async def test_run_network_check_can_cancel_between_groups(monkeypatch: pytest.MonkeyPatch):
    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="first", group="网络连通", url="https://first.example"),
            NetworkCheckSpec(name="second", group="站点检测", url="https://second.example"),
        ],
    )
    cancel_event = threading.Event()
    lines: list[str] = []

    def progress(line: str):
        lines.append(line)
        if "first" in line:
            cancel_event.set()

    results = await run_network_check(
        progress=progress, cancel_event=cancel_event, client=FakeClient(), concurrency=1, emit_header=False
    )

    assert [result.spec.name for result in results] == ["first"]
    assert any("网络检测已取消" in line for line in lines)


@pytest.mark.anyio
async def test_dmm_api_spec_uses_real_query_url(monkeypatch: pytest.MonkeyPatch):
    class DmmApiCrawlerStub:
        @classmethod
        def base_url_(cls):
            return "https://api.dmm.com"

        @classmethod
        def _build_api_url(cls, **params):
            from urllib.parse import urlencode

            query = urlencode({"api_id": "test", "affiliate_id": "test", "output": "json", **params})
            return f"https://api.dmm.com/affiliate/v3/ItemList?{query}"

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.DMM_API],
        get_crawler=lambda site: DmmApiCrawlerStub,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await build_network_check_specs()

    dmm_api = next(spec for spec in specs if spec.site == Website.DMM_API)
    assert "api.dmm.com/affiliate/v3/ItemList" in dmm_api.url
    # v3 ItemList 必需参数缺失会 400 BAD REQUEST，keyword 用厂牌词验证搜索能力
    assert "site=FANZA" in dmm_api.url
    assert "service=digital" in dmm_api.url
    assert "floor=videoa" in dmm_api.url
    assert "keyword=SSIS" in dmm_api.url
    assert "keyword=SSIS-" not in dmm_api.url
    assert dmm_api.validator == "DMM_API"


@pytest.mark.anyio
async def test_missav_api_spec_uses_post_search(monkeypatch: pytest.MonkeyPatch):
    """Recombee search 端点只接受 POST（GET 405），检测须用真实搜索路径."""

    class MissavApiCrawlerStub:
        RECOMBEE_HOST = "client-rapi-missav.recombee.com"

        @classmethod
        def base_url_(cls):
            return "https://missav.ws"

        @classmethod
        def _sign_path(cls, path: str) -> str:
            return f"/missav-default{path}?frontend_timestamp=1&frontend_sign=sig"

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.MISSAV_API],
        get_crawler=lambda site: MissavApiCrawlerStub,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await build_network_check_specs()

    missav_api = next(spec for spec in specs if spec.site == Website.MISSAV_API)
    assert missav_api.method == "POST"
    assert "/search/users/anonymous/items/" in missav_api.url
    assert missav_api.json_data is not None and missav_api.json_data["searchQuery"] == "ssni-647"
    assert missav_api.validator == "Missav_API"


@pytest.mark.anyio
async def test_run_network_check_item_passes_json_body():
    spec = NetworkCheckSpec(
        name="missav_api",
        group="账号/API",
        url="https://client-rapi-missav.recombee.com/search",
        method="POST",
        json_data={"searchQuery": "ssni-647"},
    )
    client = FakeClient()

    await run_network_check_item(spec, client=client)

    assert client.calls[0]["json_data"] == {"searchQuery": "ssni-647"}


def test_format_result_line_does_not_duplicate_error():
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://example.test")
    from mdcx.core.network_check import NetworkCheckResult

    result = NetworkCheckResult(
        spec=spec,
        status=NetworkCheckStatus.FAILED,
        message="GET https://example.test 失败:HTTP 403",
        error="GET https://example.test 失败:HTTP 403",
    )

    line = format_result_line(result)

    assert line.count("GET https://example.test 失败:HTTP 403") == 1


def test_format_header_columns_align_with_result_lines():
    """诊断表头四列（状态码/耗时/路由/信息）与数据行对齐（真机实测校准列位）。

    表头用裸空格手拼、数据行用 _pad_left/_pad_right 拼，按 _disp_width 理论
    列位算出「严格相等」在真机（Microsoft YaHei UI 等宽渲染）上反而差半个到
    一个汉字——中日韩字实渲染宽略大于 2 个 ASCII 列，数据行行首 ✅ emoji 的
    实宽也有出入。故列位按用户屏上实测校准（docs/Changelog.md v2.6.3）：
    「状态码」37（= 数据行「200」所在列，使 200 居中于表头）、「耗时」49（居中于整串
    「1427 ms」）、「路由」63（与 代理/直连 右缘）、「信息」72（与说明文字左缘）。
    第九轮起「耗时/路由/信息」三列整体左移 1.281px（只缩「状态码→耗时」一处间隙，
    见 test_format_header_elapsed_gap_shifts_trailing_columns_left），显示列号不变。
    """
    from mdcx.core.network_check import _disp_width, _format_header

    header_line = next(line for line in _format_header() if "状态码" in line)
    spec = NetworkCheckSpec(name="AVBase", group="站点检测", url="https://avbase.example", use_proxy=True)
    result = NetworkCheckResult(
        spec=spec,
        status=NetworkCheckStatus.OK,
        status_code=200,
        elapsed_ms=153,
        message="连接正常，刮削正常",
    )
    line = format_result_line(result)

    def display_column(text: str, needle: str) -> int:
        return _disp_width(text[: text.index(needle)])

    # 数据列的理论列位（数字右对齐终点 39 / 耗时右缘 52 / 代理 61 / 说明文字 70）
    code_start = display_column(line, "200")
    assert code_start == 37

    # 校准后的表头列位（真机实测，见 _format_header 内注释）：
    # 「耗时」49 = 整串「1427 ms」的串中心（该串占 46–52）；「状态码」37 = 与数据行
    # 「200」同列（截图实测「200」需居中于表头，4 空格版两列墨迹中心差 0.000px）；
    # 其余两列按右/左对齐
    assert display_column(header_line, "状态码") == 37
    assert display_column(header_line, "耗时") == 49
    assert display_column(header_line, "路由") == 63
    assert display_column(header_line, "信息") == 72


def test_format_header_status_code_gap_is_four_ascii_spaces():
    """「状态码」表头前用 4 个普通空格，使 200 正好居中于表头。

    截图实测（2026-10-19）「状态码」墨迹中心 515.0、「200」墨迹中心 518.0，需右移
    3.0px；1 空格 = 7.141px，3 空格比 4 空格窄 7.141px，比 4 空格宽的候选里没有更近
    的纯 ASCII 方案，故取 4 空格（28.562px）。真实控件渲染复核：两列中心差 0.000px。

    早前用 U+2800 盲文空格做亚格位移的方案已弃用（刻度 8.453px 仍差 3.2px，且会往
    复制进剪贴板/粘贴进 issue 的文本里混进不可见字符），这里守住该 gap 保持纯 ASCII。
    （表头的另一处间隙「状态码→耗时」确实带一个 U+3000，见
    test_format_header_elapsed_gap_shifts_trailing_columns_left。）
    """
    from mdcx.core.network_check import _format_header

    header_line = next(line for line in _format_header() if "状态码" in line)
    head = header_line.index("状态码")
    gap = header_line[head - 4 : head]
    assert gap == "    "
    assert not set(header_line[:head]) & set("\u1680\u2800\uffa0\u3000"), (
        "「状态码」表头前不应混入不可见的填充字符（会被复制进剪贴板/issue）"
    )


def test_format_header_elapsed_gap_shifts_trailing_columns_left():
    """「耗时/路由/信息」三列整体左移 1.281px（用户 2026-10-19 要求左移 1px）。

    三列同量左移在结构上等价于只缩「状态码→耗时」这一处间隙 g1，g2/g3 不变。纯 ASCII
    里唯一的隐形刻度是空格 7.141px，做不到 1px；在零墨迹刻度 {空格 7.141, U+FFA0 6.5,
    U+2800 8.453, U+3000 13.0} 里穷举逼近 6 空格 −1.0px = 41.844px，最优为
    「4 空格 + U+3000」= 41.563px（位移 −1.281px、误差 0.28px；理论最优 0.25px 的组合要
    混三种特殊字符，不划算）。

    截图实测依据：表头「路由」墨迹中心 689.0 vs「代理」688.0、「信息」左缘 739 vs
    说明 738，两列各偏右 1.0px，左移 1px 即对齐。「耗时」表头中心 593.5 其实偏左
    1.5px（vs「1136 ms」串中心 595.0），已把数据摆给用户确认，用户明确选择照原话执行。

    U+3000 是 Unicode 类别 Zs 的正规空白、零墨迹、_disp_width 记 2 列（与 2 个空格
    等价），所以「耗时/路由/信息」的显示列仍是 49/63/72。代价是复制到剪贴板/粘贴进
    issue 的表头里会带一个不可见的表意空格——这是亚格对齐唯一的手段。
    """
    from mdcx.core.network_check import _HEADER_STATUS_TO_ELAPSED_GAP, _disp_width, _format_header

    header_line = next(line for line in _format_header() if "状态码" in line)
    head = header_line.index("状态码")
    tail = header_line[head + len("状态码") :]

    # 「状态码」与「耗时」之间的间隙被完整钉死：4 空格 + 1 个 U+3000
    assert _HEADER_STATUS_TO_ELAPSED_GAP == "    \u3000"
    assert tail.startswith(_HEADER_STATUS_TO_ELAPSED_GAP + "耗时")
    assert header_line[head + len("状态码") : head + len("状态码") + 5] == "    \u3000"

    # 零墨迹 + 显示列不变 ⇒ 三列显示列仍是 49/63/72
    assert _disp_width(_HEADER_STATUS_TO_ELAPSED_GAP) == 6

    def display_column(text: str, needle: str) -> int:
        return _disp_width(text[: text.index(needle)])

    assert display_column(header_line, "耗时") == 49
    assert display_column(header_line, "路由") == 63
    assert display_column(header_line, "信息") == 72


def test_format_result_line_tls_error_puts_url_first():
    """TLS 握手中断行：目标地址前置到行首，curl 英文尾巴译中文。"""
    from mdcx.core.network_check import _clean_error, _message_for_error

    spec = NetworkCheckSpec(name="AVSex", group="刮削站点", url="https://avsex.cc")
    error = _clean_error(
        "GET https://avsex.cc 失败: Failed to perform, curl: (35) BoringSSL SSL_connect: Connection closed abruptly"
    )
    result = NetworkCheckResult(
        spec=spec,
        status=NetworkCheckStatus.FAILED,
        message=_message_for_error(error),
        error=error,
    )

    line = format_result_line(result)

    assert line.endswith(
        "GET https://avsex.cc 失败：TLS握手中断，常为HTTP/2指纹/SNI策略与目标站不兼容，curl：连接被意外关闭"
    )


@pytest.mark.parametrize(
    ("raw", "expected_detail"),
    [
        (
            "Failed to perform, curl: (35) BoringSSL SSL_connect: Connection closed abruptly",
            "curl：连接被意外关闭",
        ),
        (
            "Failed to perform, curl: (35) OpenSSL SSL_read: UNEXPECTED_EOF_WHILE_READING",
            "curl：连接被意外中断",
        ),
        (
            "Failed to perform, curl: (35) TLS connect error: SSL routines: tlsv1 alert handshake failure",
            "curl：TLS握手失败",
        ),
        (
            "Failed to perform, curl: (35) SSL routines: wrong version number",
            "curl：TLS版本不匹配",
        ),
        # 非 TLS 家族对不上译表，原样留着仍是诊断线索
        ("Failed to perform, curl: (7) Failed to connect to 127.0.0.1 port 1080", None),
        # 多轮累积的其他原因不被译文吃掉
        (
            "HTTP 403、Failed to perform, curl: (35) BoringSSL SSL_connect: Connection closed abruptly",
            "HTTP 403、curl：连接被意外关闭",
        ),
    ],
)
def test_translate_error_detail(raw: str, expected_detail: str | None):
    from mdcx.core.network_check import _translate_error_detail

    detail = _translate_error_detail(raw)

    assert detail == (raw if expected_detail is None else expected_detail)


def test_split_request_prefix():
    from mdcx.core.network_check import _split_request_prefix

    assert _split_request_prefix("GET https://avsex.cc 失败: curl: (35) TLS connect error") == (
        "GET https://avsex.cc 失败",
        "curl: (35) TLS connect error",
    )
    assert _split_request_prefix("POST https://x.cc 未知错误:  boom") == ("POST https://x.cc 未知错误", "boom")
    # 拆不出地址前缀时整串当细节（调用方退回旧格式）
    assert _split_request_prefix("Could not resolve host: x.cc") == ("", "Could not resolve host: x.cc")


def test_compose_failed_message_falls_back_without_prefix():
    """错误串没有「{方法} {url} 失败」段时维持旧的 `{提示}: {错误串}` 格式。"""
    from mdcx.core.network_check import _compose_failed_message

    assert _compose_failed_message("DNS 解析失败", "Could not resolve host: x.cc") == (
        "DNS 解析失败: Could not resolve host: x.cc"
    )


@pytest.mark.anyio
async def test_run_network_check_item_uses_default_retry_instead_of_single_attempt():
    spec = NetworkCheckSpec(name="avbase", group="刮削站点", url="https://www.avbase.net")
    client = FakeClient()

    await run_network_check_item(spec, client=client)

    assert len(client.calls) == 1
    assert "retry_count" not in client.calls[0], "检测不应强制单次请求，偶发连接错误应走默认重试"


def test_is_cloudflare_challenge_does_not_misjudge_passive_script_injection():
    normal_page = (
        "<html>LibreFanza</html>"
        "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script>"
        "<script src='https://static.cloudflareinsights.com/beacon.min.js'></script>"
    )

    assert _is_cloudflare_challenge(normal_page) is False


def test_is_cloudflare_challenge_detects_orchestrate_challenge_page():
    challenge_page = (
        "<html><title>Just a moment...</title>"
        "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/jsd/v1/x.js'></script>"
        "<span>Checking your browser before accessing libredmm.com</span>"
        "</html>"
    )

    assert _is_cloudflare_challenge(challenge_page) is True


def test_is_cloudflare_challenge_detects_verify_human_checkbox_page():
    """freejavbt 式复选框挑战页：无 just a moment/h/b 路径，仅验证文案 + cloudflare 字样命中。"""
    challenge_page = (
        "<html><head><title>freejavbt.com</title></head><body>"
        "<h1>Verify you are human. This may take a few seconds.</h1>"
        "<p>正在验证您是否是真人。这可能需要几秒钟时间。</p>"
        "<div>Ray ID: a4032cfd8ef257a7</div>"
        "<div>由 Cloudflare 提供性能和安全服务</div>"
        "</body></html>"
    )

    assert _is_cloudflare_challenge(challenge_page) is True


@pytest.mark.anyio
async def test_run_network_check_item_actively_uses_cf_bypass_on_challenge(monkeypatch: pytest.MonkeyPatch):
    class BypassConfig(FakeConfig):
        cf_bypass_url = "http://0.0.0.0:8000"

    class BypassManager:
        config = BypassConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: BypassManager())
    client = FakeBypassClient()
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
        headers={"cookie": "a=b"},
    )

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.OK
    # x-mdcx-bypass-mode 由适配层返回，用于告诉用户这次走的是 mirror 还是 html 通道
    assert result.message == "连接正常，通过挑战（mirror）"
    assert client.bypass_calls[0]["target_url"] == "https://cf.example"
    assert client.bypass_calls[0]["headers"] == {"cookie": "a=b"}
    assert client.bypass_calls[0]["timeout"] is None


@pytest.mark.anyio
async def test_run_network_check_item_uses_trawl_adapter_when_only_external_cf_service_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    """议题 #77：只配「外部CF服务」(cf_bypass_trawl_url)、cf_bypass_url 留空时，
    检测链路必须一样走 bypass——适配层是运行时自动启动、地址挂在 client 实例上的，
    不能用 config.cf_bypass_url 把关。
    """

    class TrawlConfig(FakeConfig):
        cf_bypass_url = ""
        cf_bypass_trawl_url = "http://127.0.0.1:8191"

    class TrawlManager:
        config = TrawlConfig()
        computed = None

    class TrawlBypassClient(FakeBypassClient):
        def __init__(self, *, adapter_ok: bool = True):
            super().__init__()
            self.adapter_ok = adapter_ok
            self.adapter_started = 0

        async def _ensure_local_bypass(self):
            self.adapter_started += 1
            return self.adapter_ok

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: TrawlManager())
    client = TrawlBypassClient()
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
    )

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.OK
    assert "通过挑战" in result.message
    assert client.bypass_calls, "bypass 一次都没被调用"


@pytest.mark.anyio
async def test_run_network_check_item_reports_cf_bypass_failure(monkeypatch: pytest.MonkeyPatch):
    class BypassConfig(FakeConfig):
        cf_bypass_url = "http://0.0.0.0:8000"

    class BypassManager:
        config = BypassConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: BypassManager())
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
    )

    result = await run_network_check_item(spec, client=FakeBypassClient(bypass_ok=False))

    assert result.status == NetworkCheckStatus.FAILED
    assert result.message == "Cloudflare Bypass 失败"
    assert result.error == "bypass failed"


@pytest.mark.anyio
async def test_run_network_check_item_names_unsolved_challenge_after_bypass(monkeypatch: pytest.MonkeyPatch):
    """bypass 跑过但返回仍是挑战页（FlareSolverr 未能解开）时，不得再提示
    “去配置外部CF服务”（它已配置且已运行），必须直接点名失败。"""

    class BypassConfig(FakeConfig):
        cf_bypass_url = "http://0.0.0.0:8000"

    class BypassManager:
        config = BypassConfig()
        computed = None

    class StillChallengeBypassClient(FakeBypassClient):
        async def _try_bypass_cloudflare(self, **kwargs):
            self.bypass_calls.append(kwargs)
            response = FakeResponse(
                text="<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>Cloudflare</html>",
                url=kwargs["target_url"],
            )
            response.headers["x-mdcx-bypass-mode"] = "html"
            return response, ""

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: BypassManager())
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
    )

    result = await run_network_check_item(spec, client=StillChallengeBypassClient())

    assert result.status == NetworkCheckStatus.WARNING
    assert "已尝试 CF Bypass" in result.message
    assert "仍是 Cloudflare 挑战页" in result.message
    assert "配置「外部CF服务」" not in result.message


class ProbeCrawler:
    def __init__(self, client, base_url="", browser=None):
        self.client = client
        self.base_url = base_url
        self.detail_urls: list[str] | None = ["https://example.test/works/1"]
        self.raise_not_implemented = False

    async def run(self, input_data):
        return SimpleNamespace(data=None, debug_info=SimpleNamespace(error=None))

    def new_context(self, input_data):
        return SimpleNamespace(input=input_data, debug=lambda msg: None)

    async def _generate_search_url(self, ctx):
        if self.raise_not_implemented:
            raise NotImplementedError
        return [f"{self.base_url}/works?q={ctx.input.number}"]

    def _get_headers(self, ctx):
        return None

    def _get_cookies(self, ctx):
        return None

    async def _parse_search_page(self, ctx, html, search_url):
        return self.detail_urls


class ProbeFakeClient:
    def __init__(self, text: str = "ok"):
        self.text = text
        self.calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = SimpleNamespace(status_code=200, text=self.text, url=url, headers={})
        response.encoding = "utf-8"
        return response, ""


def test_scrape_probe_attempt_timeout_ladder():
    """议题 #118：单站探测阶梯 30s → 45s，超出档数取最后一档。"""
    assert nc.SCRAPE_PROBE_TIMEOUT == 30.0
    assert nc.SCRAPE_PROBE_ATTEMPT_TIMEOUTS == (30.0, 45.0)
    assert nc.scrape_probe_attempt_timeout(0) == 30.0
    assert nc.scrape_probe_attempt_timeout(1) == 45.0
    assert nc.scrape_probe_attempt_timeout(2) == 45.0
    assert nc.scrape_probe_attempt_timeout(-1) == 30.0
    assert nc.scrape_probe_ladder_text() == "30s/45s"


def test_transient_probe_result_classification():
    """议题 #118：只有瞬时性结果值得轮内再试，确定性结论首次即定论。"""
    assert nc._is_transient_probe_result("站点可达但刮削探测超时")
    assert nc._is_transient_probe_result("站点可达但搜索页请求失败: timeout")
    assert nc._is_transient_probe_result("站点可达但刮削探测异常: boom")
    assert nc._is_transient_probe_result("站点可达但刮削探测失败: 500")
    # 确定性：重试必然同样结论
    assert not nc._is_transient_probe_result("站点可达，但测试番号 SSNI-647 未被该站点收录")
    assert not nc._is_transient_probe_result("站点可达但搜索页被 Cloudflare 拦截")
    assert not nc._is_transient_probe_result("站点可达但无法自动探测刮削，可用设置页指定网址实测")
    assert not nc._is_transient_probe_result("连接正常，刮削正常")
    # 爬虫主动抛出的「假 200」点名同样不该触发轮内重试
    assert not nc._is_transient_probe_result("站点可达但刮削探测失败: 搜索页返回 404（探测番号可能已下架或未收录）")
    assert not nc._is_transient_probe_result(
        "站点可达但刮削探测失败: 搜索页被 CloudFront 封锁（非日本出口 IP），请为 mgstage 单独走日本节点或关闭代理"
    )
    assert nc._is_transient_probe_result(
        "站点可达但刮削探测失败: 搜索失败: 搜索页未解析到结果（页面标题=..., 正文长度=1234）"
    )


@pytest.mark.anyio
async def test_probe_crawler_capability_passes_probe_timeout_to_search_request(monkeypatch: pytest.MonkeyPatch):
    """轮内递进重试的超时档必须落到搜索页请求上（否则第 2/3 次仍是 30s，重试无意义）。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    client = ProbeFakeClient()
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    await _probe_crawler_capability(client, spec, probe_timeout=45.0)

    assert client.calls
    assert client.calls[0]["timeout"] == 45.0


@pytest.mark.anyio
async def test_probe_crawler_capability_defaults_to_first_round_timeout(monkeypatch: pytest.MonkeyPatch):
    """未指定 probe_timeout 时用首轮 30s。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    client = ProbeFakeClient()
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    await _probe_crawler_capability(client, spec)

    assert client.calls[0]["timeout"] == nc.SCRAPE_PROBE_TIMEOUT == 30.0


@pytest.mark.anyio
async def test_probe_crawler_by_run_uses_passed_timeout(monkeypatch: pytest.MonkeyPatch):
    """重写 _run 的爬虫探测必须使用调用方传入的超时值。"""
    captured: dict = {}

    async def fake_wait_for(awaitable, timeout=None):
        captured["timeout"] = timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(nc.asyncio, "wait_for", fake_wait_for)

    class RunOnlyCrawler(ProbeCrawler):
        async def _generate_search_url(self, ctx):
            return None

    status, message = await nc._probe_crawler_by_run(
        RunOnlyCrawler(ProbeFakeClient()), SimpleNamespace(number="X-1"), 60.0
    )

    assert captured["timeout"] == 60.0
    assert status == NetworkCheckStatus.WARNING
    assert "超时" in message


def _stub_probe_attempts(monkeypatch: pytest.MonkeyPatch, results: list[tuple[NetworkCheckStatus | None, str]]):
    """替换单轮探测，按顺序吐出 results（用完重复最后一条），记录每次超时值。"""
    seen: list[float | None] = []

    async def fake(client, spec, probe_timeout=None):
        seen.append(probe_timeout)
        index = min(len(seen) - 1, len(results) - 1)
        return results[index]

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake)
    return seen


_PROBE_SPEC = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)


@pytest.mark.anyio
async def test_probe_retry_stops_when_a_later_attempt_passes(monkeypatch: pytest.MonkeyPatch):
    """议题 #118：首探超时后自动第 2 次并放宽到 45s，成功即定论，不再重试。"""
    _stub_probe_attempts(
        monkeypatch,
        [
            (NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"),
            (NetworkCheckStatus.OK, "连接正常，刮削正常"),
        ],
    )

    status, message = await nc._probe_crawler_capability_with_retry(ProbeFakeClient(), _PROBE_SPEC)

    assert status == NetworkCheckStatus.OK
    assert "刮削正常" in message


@pytest.mark.anyio
async def test_probe_retry_two_timeouts_declares_probe_invalid(monkeypatch: pytest.MonkeyPatch):
    """两次都超时 → 给出「站点无效：刮削探测…均超时」终局说明，并列出实际用过的阶梯。"""
    seen = _stub_probe_attempts(monkeypatch, [(NetworkCheckStatus.WARNING, "站点可达但刮削探测超时")])

    status, message = await nc._probe_crawler_capability_with_retry(ProbeFakeClient(), _PROBE_SPEC)

    assert seen == [30.0, 45.0]
    assert status == NetworkCheckStatus.WARNING
    assert "站点无效：刮削探测2次30s/45s均超时" in message


@pytest.mark.anyio
async def test_probe_retry_skips_deterministic_result(monkeypatch: pytest.MonkeyPatch):
    """「测试番号未被收录」是确定性结论：只探一次，不白等 45s。"""
    seen = _stub_probe_attempts(
        monkeypatch,
        [(NetworkCheckStatus.WARNING, "站点可达，但测试番号 SSNI-647 未被该站点收录（属正常情况）")],
    )

    status, message = await nc._probe_crawler_capability_with_retry(ProbeFakeClient(), _PROBE_SPEC)

    assert seen == [30.0]
    assert status == NetworkCheckStatus.WARNING
    assert "未被该站点收录" in message


@pytest.mark.anyio
async def test_probe_retry_emits_no_intermediate_progress_lines(monkeypatch: pytest.MonkeyPatch):
    """重试逐档进度行已下线：检测页每站只留一条最终结论，「↳ 站点第2/2次…」曾被误读成独立检测项。"""

    async def fake(client, spec, probe_timeout=None):
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake)
    emitted: list[str] = []

    spec = NetworkCheckSpec(name="AVBase", group="站点检测", url="https://www.avbase.net", site=Website.AVBASE)
    results = await run_network_check(
        specs=[spec],
        client=ProbeFakeClient(),
        progress=emitted.append,
        emit_header=False,
    )

    assert not any("次刮削探测" in line for line in emitted), emitted
    assert results[0].message == "站点无效：刮削探测2次30s/45s均超时"


@pytest.mark.anyio
async def test_probe_retry_stops_when_cancelled(monkeypatch: pytest.MonkeyPatch):
    """点「停止」后不再继续下一档探测。"""
    cancel_event = threading.Event()
    seen: list[float | None] = []

    async def fake(client, spec, probe_timeout=None):
        seen.append(probe_timeout)
        cancel_event.set()
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"

    monkeypatch.setattr(nc, "_probe_crawler_capability", fake)

    status, message = await nc._probe_crawler_capability_with_retry(
        ProbeFakeClient(), _PROBE_SPEC, cancel_event=cancel_event
    )

    assert seen == [30.0]
    assert status == NetworkCheckStatus.WARNING
    assert "超时" in message


@pytest.mark.anyio
async def test_probe_retry_mixed_transient_keeps_last_reason(monkeypatch: pytest.MonkeyPatch):
    """非全超时（请求失败/异常混合）时终局说明保留最后一次原因，避免误报「均超时」。"""
    _stub_probe_attempts(
        monkeypatch,
        [
            (NetworkCheckStatus.WARNING, "站点可达但搜索页请求失败: conn reset"),
            (NetworkCheckStatus.WARNING, "站点可达但刮削探测失败: 500"),
        ],
    )

    status, message = await nc._probe_crawler_capability_with_retry(ProbeFakeClient(), _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    assert message == "站点无效：刮削探测2次30s/45s均失败，500"
    assert "均超时" not in message


# 用户 2026-10-19 实测 faleno.jp：搜索页 403，错误串带着整页响应体进检测行
_FALENO_403_ERROR = (
    "GET https://faleno.jp/top/?s=fns%20165 失败: HTTP 403 "
    'body=<!DOCTYPE html> <html lang="ja"> <head> <meta charset="EUC-JP" /> '
    '<title>403 Forbidden</title> <meta name="copyright" content="Copyright XSERVER Inc.">'
)


class ProbeBodyErrorClient:
    """搜索页请求恒定失败，且错误串带整页响应体（`web_async.request` 的真实格式）。"""

    def __init__(self, error: str):
        self.error = error
        self.calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return None, self.error


def test_strip_response_body_keeps_status_only():
    """按首个 ` body=` 截断：无 body 的原样返回，多轮累积原因不被误切。"""
    assert nc._strip_response_body(_FALENO_403_ERROR) == "GET https://faleno.jp/top/?s=fns%20165 失败: HTTP 403"
    assert nc._strip_response_body("HTTP 403") == "HTTP 403"
    assert nc._strip_response_body("") == ""
    # 多轮重试累积的失败原因必须全在 ` body=` 之前，截断后一条都不丢
    assert nc._strip_response_body("HTTP 403、curl: (35) TLS connect error: body=<html>x</html>") == (
        "HTTP 403、curl: (35) TLS connect error:"
    )


def test_clean_error_drops_response_body():
    """连通性检测行：TRAWL 返回的 JSON 响应体同样不带进报告。"""
    raw = (
        "GET https://www.g102q.com 失败: 遭遇Cloudflare挑战页且Bypass失败: HTTP 502; "
        'GET http://127.0.0.1:6757/html 失败: HTTP 502 body={"error": "TRAWL 返回 HTTP 502"}'
    )

    cleaned = nc._clean_error(raw)

    assert "body=" not in cleaned
    assert cleaned == (
        "GET https://www.g102q.com 失败: 遭遇Cloudflare挑战页且Bypass失败: HTTP 502; "
        "GET http://127.0.0.1:6757/html 失败: HTTP 502"
    )
    # 响应体挂在末尾会挡住 curl 尾巴正则（锚在 $），截断后必须恢复翻译
    assert (
        nc._clean_error(
            "GET https://x.test 失败: Failed to perform, curl: (35) BoringSSL SSL_connect: "
            "Connection closed abruptly (SSL_ERROR_SYSCALL; error queue empty) in connection to x:443 "
            "body=<html>403</html>"
        )
        == "GET https://x.test 失败: Failed to perform, curl: (35) BoringSSL SSL_connect: Connection closed abruptly"
    )


@pytest.mark.anyio
async def test_dynamic_domain_fallback_message_drops_response_body(monkeypatch: pytest.MonkeyPatch):
    """「代码网址与动态域名均无法联通」这条也不该带 body= 响应体。"""
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: FakeManager())

    class AlwaysFailingClient:
        def __init__(self):
            self.urls: list[str] = []

        async def request(self, method, url, **kwargs):
            self.urls.append(url)
            return None, 'GET https://x.test 失败: HTTP 502 body={"error": "TRAWL 返回 HTTP 502"}'

    async def fake_get_aio_domain(name: str) -> str:
        return "https://dynamic.example"

    monkeypatch.setattr("mdcx.base.web.get_aio_domain", fake_get_aio_domain)
    client = AlwaysFailingClient()
    spec = NetworkCheckSpec(name="avmoo", group="刮削站点", url="https://hardcoded.example", site=Website.AVMOO)

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.FAILED
    assert client.urls == ["https://hardcoded.example", "https://dynamic.example"]
    assert "body=" not in result.message and "body=" not in (result.error or "")
    assert result.message == ("代码网址与动态域名均无法联通：GET https://x.test 失败: HTTP 502")


@pytest.mark.anyio
async def test_probe_search_page_failure_drops_response_body(monkeypatch: pytest.MonkeyPatch):
    """单轮探测：403 响应体不该整页进说明行。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)

    status, message = await _probe_crawler_capability(ProbeBodyErrorClient(_FALENO_403_ERROR), _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    # `?s=fns%20165` 的转义在成文时已还原（`decode_url_escapes`），报告里是 `fns 165`
    assert message == "站点可达但搜索页请求失败: GET https://faleno.jp/top/?s=fns 165 失败: HTTP 403"


@pytest.mark.anyio
async def test_probe_retry_final_message_drops_response_body(monkeypatch: pytest.MonkeyPatch):
    """两档重试跑完的终局说明同样不带响应体（用户实测的原文案形态）。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    client = ProbeBodyErrorClient(_FALENO_403_ERROR)

    status, message = await nc._probe_crawler_capability_with_retry(client, _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    assert message == ("站点无效：刮削探测2次30s/45s均失败，GET https://faleno.jp/top/?s=fns 165 失败: HTTP 403")
    assert len(client.calls) == 2


def test_probe_root_cause_strips_reachable_wrapper():
    """终局说明里「站点可达但xxx: 」是同一句话念两遍，只剥这一层包装。"""
    # 剥：带冒号的外层包装
    assert nc._probe_root_cause("站点可达但刮削探测失败: 搜索失败: 搜索页未解析到结果，页面标题=x") == (
        "搜索失败: 搜索页未解析到结果，页面标题=x"
    )
    assert nc._probe_root_cause("站点可达但搜索页请求失败: GET https://x.test 失败: HTTP 403") == (
        "GET https://x.test 失败: HTTP 403"
    )
    # 不剥：无冒号的结论句自带完整语义，剥掉前缀反而读不懂
    assert nc._probe_root_cause("站点可达但搜索页被 Cloudflare 拦截") == "站点可达但搜索页被 Cloudflare 拦截"
    # 不剥：根因里自带冒号，不能被当成外层包装剥掉第二层
    assert nc._probe_root_cause("official uncensored data failed: title") == "official uncensored data failed: title"
    assert nc._probe_root_cause("") == ""


@pytest.mark.anyio
async def test_probe_retry_final_message_drops_wrapper_and_body(monkeypatch: pytest.MonkeyPatch):
    """两档重试的终局说明只留根因：既不带「最后一次原因：」，也不带响应体。"""
    monkeypatch.setattr(
        "mdcx.crawlers.get_crawler",
        lambda site: ProbeCrawler,
    )

    class AggregatedErrorClient(ProbeBodyErrorClient):
        async def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return None, (
                "搜索失败: 搜索页未解析到结果，"
                "页面标题=このページはお住まいの地域からご利用になれません。-FANZA, 正文长度=3134 "
                "body=<html>403</html>"
            )

    status, message = await nc._probe_crawler_capability_with_retry(AggregatedErrorClient(""), _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    assert message == (
        "站点无效：刮削探测2次30s/45s均失败，搜索失败: 搜索页未解析到结果，"
        "页面标题=このページはお住まいの地域からご利用になれません。-FANZA, 正文长度=3134"
    )


@pytest.mark.anyio
async def test_probe_crawler_by_run_drops_response_body():
    """回退 `_run` 探测：聚合串里逐 URL 的响应体同样不进说明行。"""
    error = "搜索失败: 请求失败: GET https://faleno.jp/top/?s=fns%20165 失败: HTTP 403 body=<html>403</html>"

    class RunOnlyBodyCrawler(ProbeCrawler):
        async def _generate_search_url(self, ctx):
            return None

        async def run(self, input_data):
            return SimpleNamespace(data=None, debug_info=SimpleNamespace(error=error))

    status, message = await nc._probe_crawler_by_run(
        RunOnlyBodyCrawler(ProbeFakeClient()), SimpleNamespace(number="X-1"), 30.0
    )

    assert status == NetworkCheckStatus.WARNING
    assert "body=" not in message
    assert message.endswith("GET https://faleno.jp/top/?s=fns 165 失败: HTTP 403")


# 用户 2026-10-19 实测 lulubar.co：TLS 连接被掐，原始 curl 串整段进检测行
_LULUBAR_TLS_ERROR = (
    "GET https://lulubar.co/video/bysearch?search=IPZZ-547&page=1 失败: Failed to perform, "
    "curl: (35) BoringSSL SSL_connect: Connection closed abruptly (SSL_ERROR_SYSCALL; "
    "error queue empty) in connection to lulubar.co:443. "
    "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
)

_LULUBAR_TLS_CLEAN = "GET https://lulubar.co/video/bysearch?search=IPZZ-547&page=1 失败: 执行失败，curl：连接被意外关闭"


def test_clean_probe_error_translates_curl_tail():
    """探测行的 curl 尾巴要按联网检测行同一套译表翻译，地址前缀与半角分隔符保持原样。"""
    assert nc._clean_probe_error(_LULUBAR_TLS_ERROR) == _LULUBAR_TLS_CLEAN
    # 没有「{方法} {url} 失败」段时整串当细节翻译，剥不出前缀不硬拼
    assert nc._clean_probe_error(
        "Failed to perform, curl: (35) TLS connect error: SSL routines: handshake failure"
    ) == ("执行失败，curl：TLS握手失败")
    # 对不上译表的 curl 形态原样留着（只把引导词译掉），仍是诊断线索
    assert nc._clean_probe_error(
        "GET https://x.test 失败: Failed to perform, curl: (7) Failed to connect to 127.0.0.1"
    ) == ("GET https://x.test 失败: 执行失败，curl: (7) Failed to connect to 127.0.0.1")
    # 响应体照样截掉；细节为空时不留下 `失败: ` 尾巴
    assert nc._clean_probe_error("GET https://x.test 失败: HTTP 403 body=<html>403</html>") == (
        "GET https://x.test 失败: HTTP 403"
    )


@pytest.mark.anyio
async def test_probe_search_page_failure_translates_curl_tail(monkeypatch: pytest.MonkeyPatch):
    """单轮探测：搜索页请求失败行里的 curl 串同样中文化。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)

    status, message = await _probe_crawler_capability(ProbeBodyErrorClient(_LULUBAR_TLS_ERROR), _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    assert message == f"站点可达但搜索页请求失败: {_LULUBAR_TLS_CLEAN}"


@pytest.mark.anyio
async def test_probe_retry_final_message_translates_curl_tail(monkeypatch: pytest.MonkeyPatch):
    """两档重试跑完的终局说明：剥包装 + 译 curl 尾巴一步到位。"""
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    client = ProbeBodyErrorClient(_LULUBAR_TLS_ERROR)

    status, message = await nc._probe_crawler_capability_with_retry(client, _PROBE_SPEC)

    assert status == NetworkCheckStatus.WARNING
    assert message == f"站点无效：刮削探测2次30s/45s均失败，{_LULUBAR_TLS_CLEAN}"
    assert len(client.calls) == 2


@pytest.mark.anyio
async def test_probe_crawler_by_run_translates_curl_tail():
    """回退 `_run` 探测：聚合串里的 curl 尾巴同样中文化。"""

    class RunOnlyTlsCrawler(ProbeCrawler):
        async def _generate_search_url(self, ctx):
            return None

        async def run(self, input_data):
            return SimpleNamespace(data=None, debug_info=SimpleNamespace(error=f"搜索失败: {_LULUBAR_TLS_ERROR}"))

    status, message = await nc._probe_crawler_by_run(
        RunOnlyTlsCrawler(ProbeFakeClient()), SimpleNamespace(number="X-1"), 30.0
    )

    assert status == NetworkCheckStatus.WARNING
    assert message == f"站点可达但刮削探测失败: 搜索失败: {_LULUBAR_TLS_CLEAN}"


def test_translate_error_detail_keep_failed_to_perform():
    """联网检测行照旧丢掉引导词；探测行（keep_failed_to_perform）译成「执行失败」。"""
    from mdcx.core.network_check import _translate_error_detail

    raw = "Failed to perform, curl: (35) BoringSSL SSL_connect: Connection closed abruptly"

    assert _translate_error_detail(raw) == "curl：连接被意外关闭"
    assert _translate_error_detail(raw, keep_failed_to_perform=True) == "执行失败，curl：连接被意外关闭"
    # 引导词紧贴 curl 尾巴首位时照译，前面累积的其他失败原因不受影响
    assert _translate_error_detail(f"HTTP 403、{raw}", keep_failed_to_perform=True) == (
        "HTTP 403、执行失败，curl：连接被意外关闭"
    )
    # 没有引导词时不硬加「执行失败」
    assert (
        _translate_error_detail(
            "curl: (35) TLS connect error: SSL routines: tlsv1 alert handshake failure",
            keep_failed_to_perform=True,
        )
        == "curl：TLS握手失败"
    )


@pytest.mark.anyio
async def test_probe_crawler_capability_ok_when_search_finds_detail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.OK
    assert "刮削正常" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_warns_on_cloudflare_challenge(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: ProbeCrawler)
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    status, message = await _probe_crawler_capability(
        ProbeFakeClient(
            text="<html><script src='/cdn-cgi/challenge-platform/h/b/orchestrate/jsd/v1/x.js'></script>Cloudflare</html>"
        ),
        spec,
    )

    assert status == NetworkCheckStatus.WARNING
    assert "Cloudflare" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_warns_when_no_search_result(monkeypatch: pytest.MonkeyPatch):
    class NoResultCrawler(ProbeCrawler):
        def __init__(self, client, base_url="", browser=None):
            super().__init__(client, base_url, browser)
            self.detail_urls = None

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: NoResultCrawler)
    spec = NetworkCheckSpec(name="AVBase", group="刮削站点", url="https://www.avbase.net", site=Website.AVBASE)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.WARNING
    assert "未被该站点收录" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_warns_when_search_url_unavailable(monkeypatch: pytest.MonkeyPatch):
    class NoUrlCrawler(ProbeCrawler):
        async def _generate_search_url(self, ctx):
            return None

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: NoUrlCrawler)
    spec = NetworkCheckSpec(name="FC2PPVDB", group="刮削站点", url="https://fc2cmadb.com", site=Website.FC2PPVDB)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.WARNING
    assert "未被该站点收录" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_falls_back_to_run_when_search_url_missing(monkeypatch: pytest.MonkeyPatch):
    """重写 _run 的爬虫（fc2/cnmdb 等）_generate_search_url 返回 None 时回退真实刮削探测."""

    class RunOnlyCrawler(ProbeCrawler):
        async def _generate_search_url(self, ctx):
            return None

        async def run(self, input_data):
            return SimpleNamespace(data=SimpleNamespace(), debug_info=SimpleNamespace(error=None))

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: RunOnlyCrawler)
    spec = NetworkCheckSpec(name="FC2PPVDB", group="刮削站点", url="https://fc2cmadb.com", site=Website.FC2PPVDB)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.OK
    assert "刮削正常" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_falls_back_to_run_when_parse_empty(monkeypatch: pytest.MonkeyPatch):
    """重写 _search（POST 搜索）的爬虫 GET 探测解析为空时回退真实刮削探测."""

    class PostSearchCrawler(ProbeCrawler):
        def __init__(self, client, base_url="", browser=None):
            super().__init__(client, base_url, browser)
            self.detail_urls = None

        async def run(self, input_data):
            return SimpleNamespace(data=SimpleNamespace(), debug_info=SimpleNamespace(error=None))

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: PostSearchCrawler)
    spec = NetworkCheckSpec(name="Madouqu", group="刮削站点", url="https://madouqu.shop", site=Website.MADOUQU)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.OK
    assert "刮削正常" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_uses_probe_number_attribute(monkeypatch: pytest.MonkeyPatch):
    """爬虫类自定义 probe_number 时探测使用专属番号."""

    captured = {}

    class BrandedCrawler(ProbeCrawler):
        probe_number = "FNS-165"

        async def _generate_search_url(self, ctx):
            captured["number"] = ctx.input.number
            return [f"{self.base_url}/works?q={ctx.input.number}"]

        async def _parse_search_page(self, ctx, html, search_url):
            return ["https://example.test/works/1"]

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: BrandedCrawler)
    spec = NetworkCheckSpec(name="Xcity", group="刮削站点", url="https://xcity.jp", site=Website.XCITY)

    status, _message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.OK
    assert captured["number"] == "FNS-165"


@pytest.mark.anyio
async def test_probe_crawler_capability_warns_when_run_rewritten_and_succeeds(monkeypatch: pytest.MonkeyPatch):
    """重写 _run 的 API 类爬虫走真实刮削探测, run() 成功时返回 OK."""

    class RewrittenCrawler(ProbeCrawler):
        def __init__(self, client, base_url="", browser=None):
            super().__init__(client, base_url, browser)
            self.raise_not_implemented = True

        async def run(self, input_data):
            return SimpleNamespace(data=SimpleNamespace(), debug_info=SimpleNamespace(error=None))

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: RewrittenCrawler)
    spec = NetworkCheckSpec(name="AVMOO", group="刮削站点", url="https://avmoo.shop", site=Website.AVMOO)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.OK
    assert "刮削正常" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_warns_when_run_rewritten_and_fails(monkeypatch: pytest.MonkeyPatch):
    """重写 _run 的爬虫 run() 失败时返回 WARNING."""

    class RewrittenCrawler(ProbeCrawler):
        def __init__(self, client, base_url="", browser=None):
            super().__init__(client, base_url, browser)
            self.raise_not_implemented = True

        async def run(self, input_data):
            return SimpleNamespace(data=None, debug_info=SimpleNamespace(error="未找到匹配"))

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: RewrittenCrawler)
    spec = NetworkCheckSpec(name="FC2PPVDB", group="刮削站点", url="https://fc2cmadb.com", site=Website.FC2PPVDB)

    status, message = await _probe_crawler_capability(ProbeFakeClient(), spec)

    assert status == NetworkCheckStatus.WARNING
    assert "刮削探测失败" in message


@pytest.mark.anyio
async def test_probe_crawler_capability_skipped_without_site():
    spec = NetworkCheckSpec(name="GitHub Raw", group="网络连通", url="https://raw.githubusercontent.com")

    status, message = await _probe_crawler_capability(None, spec)

    assert status is None
    assert message == ""


def test_compute_used_proxy_false_when_proxy_disabled():
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://libredmm.com", use_proxy=True)

    assert _compute_used_proxy(spec) is False


def test_compute_used_proxy_true_when_host_in_proxy_sites(monkeypatch: pytest.MonkeyPatch):
    class ProxyConfig(FakeConfig):
        use_proxy = True
        proxy = "http://127.0.0.1:7890"
        proxy_sites = "libredmm.com,javdb.com"
        direct_sites = ""

    class ProxyManager:
        config = ProxyConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: ProxyManager())
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://libredmm.com", use_proxy=True)

    assert _compute_used_proxy(spec) is True


def test_compute_used_proxy_false_when_host_not_in_proxy_sites(monkeypatch: pytest.MonkeyPatch):
    class ProxyConfig(FakeConfig):
        use_proxy = True
        proxy = "http://127.0.0.1:7890"
        proxy_sites = "javdb.com"
        direct_sites = ""

    class ProxyManager:
        config = ProxyConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: ProxyManager())
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://libredmm.com", use_proxy=True)

    assert _compute_used_proxy(spec) is False


def test_compute_used_proxy_false_when_spec_forbids_proxy(monkeypatch: pytest.MonkeyPatch):
    class ProxyConfig(FakeConfig):
        use_proxy = True
        proxy = "http://127.0.0.1:7890"
        proxy_sites = "libredmm.com"
        direct_sites = ""

    class ProxyManager:
        config = ProxyConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: ProxyManager())
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://libredmm.com", use_proxy=False)

    assert _compute_used_proxy(spec) is False


def test_compute_used_proxy_false_when_host_in_direct_sites(monkeypatch: pytest.MonkeyPatch):
    """直连白名单优先：即使 host 在 proxy_sites 中，命中 direct_sites 也不走代理。"""

    class ProxyConfig(FakeConfig):
        use_proxy = True
        proxy = "http://127.0.0.1:7890"
        proxy_sites = "google.com,javdb.com"
        direct_sites = "google.com"

    class ProxyManager:
        config = ProxyConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: ProxyManager())
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://google.com", use_proxy=True)

    assert _compute_used_proxy(spec) is False


def test_format_result_line_shows_direct_when_not_using_proxy(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core.network_check import NetworkCheckResult

    result = NetworkCheckResult(
        spec=NetworkCheckSpec(name="site", group="刮削站点", url="https://libredmm.com", use_proxy=True),
        status=NetworkCheckStatus.OK,
        message="连接正常，刮削正常",
        used_proxy=False,
    )

    line = format_result_line(result)

    assert "直连" in line


# ---- 站点检测缓存（持久化 & 合并，供站点选择列表回显）----


def _mk_cache_result(site, status, *, group="刮削站点", used_proxy=True):
    spec = NetworkCheckSpec(name=str(site), group=group, url="https://example.test", site=site)
    return NetworkCheckResult(spec=spec, status=status, message="", used_proxy=used_proxy)


def test_site_result_level_mapping():
    assert _site_result_level(NetworkCheckStatus.OK) == "ok"
    assert _site_result_level(NetworkCheckStatus.WARNING) == "warn"
    assert _site_result_level(NetworkCheckStatus.FAILED) == "fail"
    assert _site_result_level(NetworkCheckStatus.SKIPPED) == "skip"
    assert _site_result_level(NetworkCheckStatus.CANCELLED) == "skip"


def test_merge_and_load_cache_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(nc, "_site_cache_path", lambda: cache)

    merge_site_check_cache([_mk_cache_result(Website.JAVDB, NetworkCheckStatus.OK, used_proxy=True)])

    loaded = load_site_check_cache()
    assert loaded["JavDB"]["status"] == "ok"
    assert loaded["JavDB"]["route"] == "proxy"
    assert loaded["JavDB"]["checked_at"]


def test_merge_cache_includes_any_site_attributed_group(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """议题 #129 语义反转: 缓存收集以"有无 site 归属"为准, 不再按组过滤——
    账号/API 组要标注; 无 site 归属项(基础连通性等)仍排除。"""
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(nc, "_site_cache_path", lambda: cache)

    merge_site_check_cache(
        [
            _mk_cache_result(Website.JAVDB, NetworkCheckStatus.OK, group="账号/API"),
            NetworkCheckResult(
                spec=NetworkCheckSpec(name="通用 HTTPS", group="基础环境", url="https://x.test"),
                status=NetworkCheckStatus.OK,
                message="m",
            ),
        ]
    )

    loaded = load_site_check_cache()
    assert loaded["JavDB"]["status"] == "ok"
    assert len(loaded) == 1


def test_merge_cache_partial_overwrite_preserves_history(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(nc, "_site_cache_path", lambda: cache)

    merge_site_check_cache([_mk_cache_result(Website.JAVDB, NetworkCheckStatus.FAILED, used_proxy=False)])
    # 重试失败项场景：只重测部分站点，其余历史保留
    merge_site_check_cache([_mk_cache_result(Website.DMM, NetworkCheckStatus.OK)])

    loaded = load_site_check_cache()
    assert loaded["JavDB"]["status"] == "fail"
    assert loaded["JavDB"]["route"] == "direct"
    assert loaded["DMM"]["status"] == "ok"


def test_merge_cache_new_run_overwrites_same_site(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(nc, "_site_cache_path", lambda: cache)

    merge_site_check_cache([_mk_cache_result(Website.JAVDB, NetworkCheckStatus.FAILED)])
    merge_site_check_cache([_mk_cache_result(Website.JAVDB, NetworkCheckStatus.OK)])

    assert load_site_check_cache()["JavDB"]["status"] == "ok"


def test_load_cache_bad_or_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(nc, "_site_cache_path", lambda: cache)
    assert load_site_check_cache() == {}
    cache.write_text("not-json", encoding="utf-8")
    assert load_site_check_cache() == {}
    cache.write_text('{"version":1,"sites":"oops"}', encoding="utf-8")
    assert load_site_check_cache() == {}


def test_region_tags_reference_valid_websites():
    # 地域标签数据源防漂移：键必须是真实存在的站点值
    from mdcx.manual import ManualConfig

    valid = {w.value for w in Website}
    assert set(ManualConfig.SITE_REGION_TAGS) <= valid
    assert set(ManualConfig.SITE_REGION_TAGS) == set()


@pytest.mark.anyio
async def test_run_network_check_reports_structured_progress(monkeypatch: pytest.MonkeyPatch):
    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="env", group="基础环境", url="https://env.example"),
            NetworkCheckSpec(name="a", group="网络连通", url="https://a.example"),
            NetworkCheckSpec(name="b", group="站点检测", url="https://b.example"),
            NetworkCheckSpec(name="c", group="站点检测", url="https://c.example"),
        ],
    )
    seen: list[tuple[int, int]] = []

    results = await run_network_check(
        on_item_done=lambda done, total: seen.append((done, total)),
        client=FakeClient(),
        concurrency=3,
        emit_header=False,
    )

    # "基础环境"组不参与计数：total=3，done 单调递增到 3。
    # done 含首组那项 "a"：它在后台站点 specs 并入前就跑完了，那时总项数还未知
    # （total=0），按契约不回调（UI 也按 total>0 才刷新按钮），故首个回调是 2/3。
    assert seen == [(2, 3), (3, 3)]
    assert len(results) == 3  # "基础环境"组是输出横幅非实际检测项，不执行也不计进度


@pytest.mark.anyio
async def test_run_network_check_reports_each_item_result(monkeypatch: pytest.MonkeyPatch):
    """每完成一项就回调该结果本身：UI 靠它逐站刷新徽标，不必等整轮跑完。

    用户 2026-10-20 实测：整轮检测里慢站/探测超时拖到 30+ 分钟，站点列表
    却一直保持上次的旧状态，直到全部跑完才一次性更新。回调必须覆盖所有分组
    （并发「网络连通」与串行「站点检测」「账号/API」两条执行路径）。
    """
    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="net", group="网络连通", url="https://net.example"),
            NetworkCheckSpec(name="site", group="站点检测", url="https://site.example", site=Website.DMM),
            NetworkCheckSpec(name="api", group="账号/API", url="https://api.example", site=Website.THEJAVDB),
        ],
    )
    emitted: list[NetworkCheckResult] = []

    results = await run_network_check(
        on_item_result=emitted.append,
        client=FakeClient(),
        concurrency=3,
        emit_header=False,
    )

    assert sorted(result.spec.name for result in emitted) == ["api", "net", "site"]
    assert [result.spec.name for result in results] == ["net", "site", "api"]
    # 回调出去的就是最终结果本身（不是摘要行/占位行），状态与返回值逐项一致
    assert {result.spec.name: result.status for result in emitted} == {
        result.spec.name: result.status for result in results
    }


@pytest.mark.anyio
async def test_on_item_result_exception_does_not_abort_run(monkeypatch: pytest.MonkeyPatch):
    """单项结果回调是界面副作用，抛异常不能让整轮检测中止。"""
    _patch_check_specs(
        monkeypatch,
        [
            NetworkCheckSpec(name="net", group="网络连通", url="https://net.example"),
            NetworkCheckSpec(name="site", group="站点检测", url="https://site.example", site=Website.DMM),
        ],
    )
    calls: list[str] = []

    def explode(result: NetworkCheckResult):
        calls.append(result.spec.name)
        raise RuntimeError("UI 刷新失败")

    results = await run_network_check(
        on_item_result=explode,
        client=FakeClient(),
        emit_header=False,
    )

    assert [result.spec.name for result in results] == ["net", "site"]
    assert sorted(calls) == ["net", "site"]


# ==================== 检测起步延迟：动态域名解析不得挡住「网络连通」首组 ====================


@pytest.mark.anyio
async def test_network_group_runs_before_site_specs_ready(monkeypatch: pytest.MonkeyPatch):
    """「网络连通」必须在站点检测项构建完成之前就出结果（实测挡住十几分钟）。

    根因：run_network_check 原先先 await build_network_check_specs() 才开始跑，
    而站点 specs 要逐站串行解析动态域名（javlibrary 抓 GitHub、avmoo/avsox/
    avheat 抓 tellme.pw、madouqu 抓发布页），被墙环境下各站耗时相加可达十几分钟，
    用户点「开始检测」后连 GitHub Raw / 通用HTTPS 都看不到。现静态项先跑、站点
    specs 后台构建。这里用「站点 specs 等静态项跑完才放行」的门闩锁死该顺序：
    若实现退回首段阻塞构建，站点 specs 永远等不到门闩，整轮超时失败。
    """
    import asyncio

    monkeypatch.setattr(
        "mdcx.core.network_check._build_static_specs",
        lambda: [NetworkCheckSpec(name="net", group="网络连通", url="https://net.example")],
    )
    gate = asyncio.Event()

    async def gated_site_specs() -> list[NetworkCheckSpec]:
        # 只有「网络连通」那项真的跑起来（下面 flaky_item 会开门闩）才放行
        await gate.wait()
        return [NetworkCheckSpec(name="site", group="站点检测", url="https://site.example")]

    real_item = nc.run_network_check_item

    async def flaky_item(spec, *, cancel_event=None, client=None):
        gate.set()
        return await real_item(spec, cancel_event=cancel_event, client=client)

    monkeypatch.setattr("mdcx.core.network_check._build_site_specs", gated_site_specs)
    monkeypatch.setattr("mdcx.core.network_check.run_network_check_item", flaky_item)
    lines: list[str] = []

    # 超时兜底：真退化成首段阻塞构建时这里是死锁，靠 wait_for 变成失败而非挂死
    results = await asyncio.wait_for(
        run_network_check(progress=lines.append, client=FakeClient(), emit_header=False),
        timeout=10,
    )

    assert [result.spec.name for result in results] == ["net", "site"]
    # 首组结果行在站点 specs 放行前就已打印（progress 先于 join）
    assert any("net" in line for line in lines)


@pytest.mark.anyio
async def test_site_specs_merged_once_for_later_groups(monkeypatch: pytest.MonkeyPatch):
    """站点 specs 全程只构建/并入一次：账号/API 组不能出现重复检测行。

    根因：join_site_specs() 把 site_specs_task 置回 None，而「账号/API」「辅助服务」
    同样不是 STATIC_ONLY_GROUPS，原先只看 task is None 的话每进一组就重建并再并入
    一份站点 specs —— DMM_API/Missav_API/TheJavDB（账号/API 组的三项）于是各被
    检测两次、报告里打印两行，进度分母也跟着虚高。
    """
    calls: list[int] = []

    monkeypatch.setattr(
        "mdcx.core.network_check._build_static_specs",
        lambda: [
            NetworkCheckSpec(name="net", group="网络连通", url="https://net.example"),
            NetworkCheckSpec(name="cf", group="辅助服务", url="https://cf.example"),
        ],
    )

    async def counted_site_specs() -> list[NetworkCheckSpec]:
        calls.append(1)
        return [
            NetworkCheckSpec(name="site", group="站点检测", url="https://site.example"),
            # 与真实实现一致：API 类站点 specs 的 group 就是「账号/API」，
            # 因此在「账号/API」组被 join 进来（重复时正是它被多跑一次）。
            NetworkCheckSpec(name="DMM_API", group="账号/API", url="https://dmm.example"),
        ]

    monkeypatch.setattr("mdcx.core.network_check._build_site_specs", counted_site_specs)
    lines: list[str] = []

    results = await run_network_check(progress=lines.append, client=FakeClient(), emit_header=False)

    assert len(calls) == 1
    assert sorted(result.spec.name for result in results) == ["DMM_API", "cf", "net", "site"]
    dmm_lines = [line for line in lines if "DMM_API" in line]
    assert len(dmm_lines) == 1, dmm_lines


@pytest.mark.anyio
async def test_build_site_specs_uses_hardcoded_url_not_dynamic(monkeypatch: pytest.MonkeyPatch):
    """检测前先使用代码里的网址（默认域名），不覆盖为动态解析结果（议题 #132）；
    动态域名解析仅在检测失败时作为兜底重试执行（见 run_network_check_item）。"""
    import asyncio

    class FakeCrawler:
        @classmethod
        def base_url_(cls):
            return "https://hardcoded.example"

        @classmethod
        async def check_urls(cls):
            await asyncio.sleep(3600)  # 故意挂起：若构建时仍调用则超时失败
            return ["https://dynamic.example"]

    monkeypatch.setitem(
        sys.modules,
        "mdcx.crawlers",
        SimpleNamespace(
            get_registered_crawler_sites=lambda include_hidden=False: [Website.MMTV],
            get_crawler=lambda site: FakeCrawler,
        ),
    )

    specs = await asyncio.wait_for(nc.build_network_check_specs(), timeout=5)
    # 构建阶段不调用 check_urls，直接用代码里的网址
    assert [spec.url for spec in specs if spec.site == Website.MMTV] == ["https://hardcoded.example"]


@pytest.mark.anyio
async def test_build_site_specs_uses_default_url_even_if_dynamic_hangs(monkeypatch: pytest.MonkeyPatch):
    """构建阶段不调用 check_urls，即使动态解析会卡死也不影响构建速度（议题 #132）；
    检测时若代码里的网址无法联通，再通过函数获取新网址重试。"""
    import asyncio

    class HangingCrawler:
        @classmethod
        def base_url_(cls):
            return "https://hanging.example"

        @classmethod
        async def check_urls(cls):
            await asyncio.sleep(3600)
            return ["https://never.example"]

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.MMTV],
        get_crawler=lambda site: HangingCrawler,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await asyncio.wait_for(nc.build_network_check_specs(), timeout=5)
    # 构建阶段不触发动态解析，直接用代码里的默认域名
    assert [spec.url for spec in specs if spec.site == Website.MMTV] == ["https://hanging.example"]


# ==================== 议题 #129: API 组入缓存 + official 五站子检测/最差聚合 ====================


def _result(site: Website, status: NetworkCheckStatus, group: str = "刮削站点", name: str = "") -> NetworkCheckResult:
    spec = NetworkCheckSpec(name=name or site.value, group=group, url="https://x.test", site=site)
    return NetworkCheckResult(spec=spec, status=status, message="m", used_proxy=True)


def test_merge_cache_includes_api_group_sites(monkeypatch, tmp_path):
    """账号/API 组(带 site 归属)的检测结果须写入站点缓存→网站设置下拉有标注 (#129)。"""
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    merge_site_check_cache(
        [
            _result(Website.DMM_API, NetworkCheckStatus.OK, group="账号/API"),
            _result(Website.THEJAVDB, NetworkCheckStatus.WARNING, group="账号/API"),
            _result(Website.MISSAV_API, NetworkCheckStatus.FAILED, group="账号/API"),
            _result(None or Website.THEPORNDB, NetworkCheckStatus.OK, group="账号/API"),
            # 无站点归属项(基础环境等)不入库
            NetworkCheckResult(
                spec=NetworkCheckSpec(name="通用 HTTPS", group="网络连通", url="https://x.test"),
                status=NetworkCheckStatus.OK,
                message="m",
            ),
        ]
    )
    cache = load_site_check_cache()
    assert cache["DMM_API"]["status"] == "ok"
    assert cache["TheJavDB"]["status"] == "warn"
    assert cache["Missav_API"]["status"] == "fail"
    assert cache["ThepornDB"]["status"] == "ok"
    assert "通用 HTTPS" not in cache and all(v.get("status") for v in cache.values())


def test_merge_cache_official_aggregates_worst(monkeypatch, tmp_path):
    """official 五站子结果按"取最差"聚合: 同一轮内任一 fail 整条链路标红, 与结果顺序无关。"""
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    merge_site_check_cache(
        [
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official·1Pondo"),
            _result(Website.OFFICIAL, NetworkCheckStatus.FAILED, name="Official·HEYZO"),
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official·Caribbeancom"),
        ]
    )
    assert load_site_check_cache()["Official"]["status"] == "fail"

    # 反序: 先 fail 后 ok 也必须保持 fail
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache2.json")
    merge_site_check_cache(
        [
            _result(Website.OFFICIAL, NetworkCheckStatus.FAILED, name="Official·1Pondo"),
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official·HEYZO"),
        ]
    )
    assert load_site_check_cache()["Official"]["status"] == "fail"


def test_merge_cache_official_new_run_clears_stale_fail(monkeypatch, tmp_path):
    """一轮 fail 不能把后续全绿的轮次永久钉死（用户 2026-10-19：五站全通过但状态不变）。

    取最差只在本轮之内做，历史值不参与比较；否则 Official 一旦记过 fail，
    之后任何更成功的轮次都会被判成「不如历史」丢弃，红点永远不翻绿。
    """
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    merge_site_check_cache(
        [
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official·1Pondo"),
            _result(Website.OFFICIAL, NetworkCheckStatus.FAILED, name="Official·HEYZO"),
        ]
    )
    assert load_site_check_cache()["Official"]["status"] == "fail"

    # 下一轮五站全绿 → 聚合翻绿（历史 fail 不得参与比较）
    merge_site_check_cache(
        [
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name=f"Official·{studio}")
            for studio in ("10Musume", "1Pondo", "Caribbeancom", "HEYZO", "Pacopacomama")
        ]
    )
    assert load_site_check_cache()["Official"]["status"] == "ok"


def test_merge_cache_official_writes_per_subsite_keys(monkeypatch, tmp_path):
    """五站子检测各存一份 `Official·厂牌` 记录，下拉里每行回显自己那站的状态。"""
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    merge_site_check_cache(
        [
            _result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official·10Musume"),
            _result(Website.OFFICIAL, NetworkCheckStatus.FAILED, name="Official·HEYZO"),
            _result(Website.OFFICIAL, NetworkCheckStatus.WARNING, name="Official·1Pondo"),
        ]
    )
    cache = load_site_check_cache()
    assert cache["Official·10Musume"]["status"] == "ok"
    assert cache["Official·HEYZO"]["status"] == "fail"
    assert cache["Official·1Pondo"]["status"] == "warn"
    assert cache["Official"]["status"] == "fail"  # 本行仍取本轮最差
    assert all(cache[k]["route"] == "proxy" for k in ("Official·10Musume", "Official·HEYZO", "Official·1Pondo"))


def test_merge_cache_official_subsite_keys_follow_site_value_only_for_subsites(monkeypatch, tmp_path):
    """非子站名的 Official 检测项（用户自定义 URL 时的本行）不写子键，只更新聚合。"""
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    merge_site_check_cache([_result(Website.OFFICIAL, NetworkCheckStatus.OK, name="Official")])
    cache = load_site_check_cache()
    assert cache["Official"]["status"] == "ok"
    assert list(cache) == ["Official"]


def test_official_subsite_prefix_keys_cover_five_sites():
    """逐站缓存键由检测项名 `Official·厂牌` 拼成，五站互不重名（子站行按同名取徽标）。"""
    from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES

    assert nc.OFFICIAL_SUBSITE_PREFIX == "Official·"
    keys = [f"{nc.OFFICIAL_SUBSITE_PREFIX}{spec.studio}" for spec in UNCENSORED_OFFICIAL_SITES.values()]
    assert len(keys) == 5
    assert len(set(keys)) == 5
    assert all(key.startswith(nc.OFFICIAL_SUBSITE_PREFIX) for key in keys)


@pytest.mark.anyio
async def test_official_generates_five_independent_site_specs(monkeypatch):
    """official 五个无码官网拆成独立站点后，检测报告每站各一行、各用自己官网地址。"""
    from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES

    site_to_source = {
        Website.OFFICIAL_10MUSUME: "10musume",
        Website.OFFICIAL_1PONDO: "1pondo",
        Website.OFFICIAL_CARIBBEANCOM: "caribbeancom",
        Website.OFFICIAL_HEYZO: "heyzo",
        Website.OFFICIAL_PACOPACOMAMA: "pacopacomama",
    }

    specs = await build_network_check_specs()
    official_specs = [s for s in specs if s.site in site_to_source]

    assert len(official_specs) == len(UNCENSORED_OFFICIAL_SITES) == 5
    for spec in official_specs:
        official_spec = UNCENSORED_OFFICIAL_SITES[site_to_source[spec.site]]
        assert spec.name == spec.site.value
        assert spec.url == official_spec.base_url
        assert spec.probe_number == official_spec.probe_number


def test_theporndb_token_spec_binds_site_without_token():
    """未填 Token 时 ThePornDB 检测项也必须带 site，才能回标网站设置下拉（#174）。"""
    spec = next(s for s in nc._build_static_specs() if s.name == "ThePornDB Token")
    assert spec.site == Website.THEPORNDB
    assert spec.group == "账号/API"
    assert spec.warning_if_missing


def test_theporndb_token_spec_binds_site_with_token(monkeypatch):
    """已填 Token 时检测项同样带 site=theporndb（#174）。"""

    class Cfg(FakeConfig):
        theporndb_api_token = "tok"

    class Mgr:
        config = Cfg()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: Mgr())
    spec = next(s for s in nc._build_static_specs() if s.name == "ThePornDB Token")
    assert spec.site == Website.THEPORNDB
    assert spec.validator == "theporndb_token"
    assert "api.theporndb.net" in spec.url


def test_merge_cache_uses_theporndb_token_production_spec(monkeypatch, tmp_path):
    """用生产形态的 ThePornDB Token spec（name 不是站点值）合并缓存，键必须是 theporndb。"""
    monkeypatch.setattr(nc, "_site_cache_path", lambda: tmp_path / "cache.json")
    spec = NetworkCheckSpec(
        name="ThePornDB Token",
        group="账号/API",
        url="https://api.theporndb.net/scenes/hash/x",
        site=Website.THEPORNDB,
        validator="theporndb_token",
    )
    merge_site_check_cache(
        [NetworkCheckResult(spec=spec, status=NetworkCheckStatus.OK, message="API 查询正常", used_proxy=True)]
    )
    cache = load_site_check_cache()
    assert cache["ThepornDB"]["status"] == "ok"


@pytest.mark.anyio
async def test_thejavdb_spec_has_site_for_badge(monkeypatch: pytest.MonkeyPatch):
    """TheJavDB 生产检测项带 site 归属，网站设置下拉能回标（#129/#174）。"""

    class ThejavdbCrawlerStub:
        @classmethod
        def base_url_(cls):
            return "https://thejavdb.net"

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.THEJAVDB],
        get_crawler=lambda site: ThejavdbCrawlerStub,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await build_network_check_specs()
    spec = next(s for s in specs if s.site == Website.THEJAVDB)
    assert spec.name == "TheJavDB"
    assert spec.group == "账号/API"
    assert spec.validator == "TheJavDB"
    # 网页版是 SPA + CF 挑战，检测走它自己的免 CF 直连接口按番号取
    assert spec.url == "https://api.thejavdb.net/v1/movies/ssni-200"


@pytest.mark.anyio
async def test_getchu_spec_enables_cf_bypass(monkeypatch: pytest.MonkeyPatch):
    """GETCHU 曾被 special-case 漏掉 enable_cf_bypass：直连 RST（curl 56）时
    请求层与检测层两处传输兜底都进不去，检测直接红且无 bypass 标注。"""

    class GetchuCrawlerStub:
        @classmethod
        def base_url_(cls):
            return "http://www.getchu.com"

        @classmethod
        async def check_urls(cls):
            return ["http://www.getchu.com"]

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.GETCHU],
        get_crawler=lambda site: GetchuCrawlerStub,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await build_network_check_specs()
    spec = next(s for s in specs if s.site == Website.GETCHU)
    assert spec.enable_cf_bypass is True


@pytest.mark.anyio
async def test_run_network_check_holds_computed_lease(monkeypatch: pytest.MonkeyPatch):
    """整轮检测持有 computed 租约：检测期间点"保存"替换 computed 时，
    旧客户端因租约未归零不会被关闭，排队/重试中的项不再报"网络客户端已关闭"。

    实证：检测裸用共享客户端（无租约），13 分钟长轮尾部 avsex/javlibrary/
    xcity/missav 全报"网络客户端已关闭"——旧客户端在连接池空闲瞬间被
    close_when_idle 关闭，串行 bypass 排队者零占用、死得最先。"""

    class LeaseManager:
        def __init__(self):
            self.config = FakeConfig()
            self.events: list[str] = []
            self.client = FakeClient()
            self.computed = SimpleNamespace(async_client=self.client)

        def acquire_computed(self):
            mgr = self

            class Lease:
                async def __aenter__(self):
                    mgr.events.append("enter")
                    return mgr.computed

                async def __aexit__(self, *exc):
                    mgr.events.append("exit")
                    return False

            self.events.append("acquire")
            return Lease()

    mgr = LeaseManager()
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: mgr)

    results = await run_network_check(
        specs=[NetworkCheckSpec(name="good", group="网络连通", url="https://good.example")],
        progress=lambda line: None,
        emit_header=False,
    )

    # 租约：取、用、还，顺序正确
    assert mgr.events == ["acquire", "enter", "exit"]
    # 跑的就是租约里的客户端
    assert mgr.client.calls, "run 未使用租约客户端请求"
    assert all("good.example" in c["url"] for c in mgr.client.calls)
    assert len(results) == 1
    assert results[0].status == NetworkCheckStatus.OK
    # 串行锁已摘，不残留
    assert getattr(mgr.client, "_bypass_serial_lock", None) is None
