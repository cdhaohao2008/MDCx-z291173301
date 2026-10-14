"""重试各轮失败原因累积回归测试。

背景：`request()` 的 `error_msg` 每轮被整体覆盖，循环结束只保留最后一轮。直连先拿到
HTTP 403 挑战页、后续几轮变成 `curl: (35) TLS connect error` 时，末轮覆盖会把传输层
真因丢掉——检测报告只剩「GET http://www.getchu.com 失败: HTTP 403」，无法区分
「CF 拦截」与「链路层被 RST」。现改为累积各轮不重复的失败原因。

约束：响应体预览统一挂在最终错误串末尾。上层（`core/network_check.py`）按首个
` body=` 截断以剔除响应体，响应体若混在累积项中间会把后面的失败原因一并切掉。
"""

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

from mdcx.core.network_check import (
    NetworkCheckSpec,
    NetworkCheckStatus,
    run_network_check_item,
)
from mdcx.web_async import AsyncWebClient, _join_attempt_errors, _record_attempt_error


class _FakeResp:
    def __init__(self, status_code: int, text: str = "", url: str = "http://x.test/"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers: dict[str, str] = {}
        self.url = url


def _no_sleep(client: AsyncWebClient, monkeypatch) -> None:
    """重试间隔默认 2s/5s/…，测试里抹掉。"""
    monkeypatch.setattr(client, "_calc_retry_sleep_seconds", lambda *a, **k: 0.0)


def test_record_attempt_error_dedupes_and_splits_body():
    errors: list[str] = []

    body = _record_attempt_error(errors, "HTTP 403 body=<html>challenge</html>")
    body2 = _record_attempt_error(errors, "HTTP 403 body=<html>challenge again</html>")

    assert errors == ["HTTP 403"], "相同失败原因只保留一条，响应体差异不应各占一条"
    assert body == "<html>challenge</html>"
    assert body2 == "<html>challenge again</html>", "每轮响应体都交给调用方决定挂哪"


def test_record_attempt_error_keeps_order_across_kinds():
    errors: list[str] = []

    _record_attempt_error(errors, "HTTP 403 body=<html>x</html>")
    _record_attempt_error(errors, "Failed to perform, curl: (35) TLS connect error:")
    _record_attempt_error(errors, "连接超时")

    assert errors == [
        "HTTP 403",
        "Failed to perform, curl: (35) TLS connect error:",
        "连接超时",
    ]


def test_join_attempt_errors_appends_body_last():
    joined = _join_attempt_errors(
        ["HTTP 403", "Failed to perform, curl: (35) TLS connect error:"],
        "Failed to perform, curl: (35) TLS connect error:",
        "<html>challenge</html>",
    )

    assert joined == "HTTP 403、Failed to perform, curl: (35) TLS connect error: body=<html>challenge</html>"
    # 上层按首个 ` body=` 截断，累积项必须全在这一截之前
    assert joined.split(" body=", 1)[0] == "HTTP 403、Failed to perform, curl: (35) TLS connect error:"


def test_join_attempt_errors_without_body():
    assert _join_attempt_errors(["HTTP 403"], "HTTP 403", "") == "HTTP 403"
    # 累积列表为空（理论上不会发生）时退回末轮错误，不返回空串
    assert _join_attempt_errors([], "HTTP 500", "") == "HTTP 500"


@pytest.mark.asyncio
async def test_request_accumulates_transport_error_after_status(monkeypatch):
    """第一轮 403 挑战页、后续轮 TLS 握手失败：两种原因都要出现在错误串里。"""
    client = AsyncWebClient(timeout=10)
    _no_sleep(client, monkeypatch)
    calls = {"curl": 0}

    async def fake_curl_request(**kwargs):
        calls["curl"] += 1
        if calls["curl"] == 1:
            return _FakeResp(403, "<html>Just a moment...</html>")
        raise CurlConnectionError("Failed to perform, curl: (35) TLS connect error: SSL routines: ssl3_get_record")

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)

    _, err = await client.request(
        "GET",
        "http://www.getchu.com",
        use_proxy=False,
        enable_cf_bypass=False,
        retry_count=3,
    )

    head = err.split(" body=", 1)[0]
    assert "HTTP 403" in head, f"末轮覆盖吞掉了首轮状态码: {err!r}"
    assert "curl: (35) TLS connect error:" in head, f"传输层真因未进错误串: {err!r}"
    assert head.index("HTTP 403") < head.index("curl: (35) TLS connect error:"), "按发生顺序累积"
    assert err.endswith(" body=<html>Just a moment...</html>"), "响应体挂在末尾，供上层按 ` body=` 截断"


@pytest.mark.asyncio
async def test_request_dedupes_repeated_identical_errors(monkeypatch):
    """三轮同一原因只出一条，避免错误串被重复原因撑长。"""
    client = AsyncWebClient(timeout=10)
    _no_sleep(client, monkeypatch)

    async def fake_curl_request(**kwargs):
        raise CurlConnectionError("Failed to perform, curl: (35) TLS connect error:")

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)

    _, err = await client.request(
        "GET",
        "http://www.getchu.com",
        use_proxy=False,
        enable_cf_bypass=False,
        retry_count=3,
    )

    assert err == "GET http://www.getchu.com 失败: Failed to perform, curl: (35) TLS connect error:"


@pytest.mark.asyncio
async def test_request_single_attempt_error_unchanged(monkeypatch):
    """单轮失败（retry_count=1）格式与改动前一致，状态码前缀保留。"""
    client = AsyncWebClient(timeout=10)
    _no_sleep(client, monkeypatch)

    async def fake_curl_request(**kwargs):
        return _FakeResp(400, '{"ValidationErrors": {"ProductionYear": ["year out of range"]}}')

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)

    _, err = await client.request(
        "POST",
        "http://example.test/Items/1",
        use_proxy=False,
        enable_cf_bypass=False,
        retry_count=1,
    )

    assert err == (
        "POST http://example.test/Items/1 失败: HTTP 400"
        ' body={"ValidationErrors": {"ProductionYear": ["year out of range"]}}'
    )


class _AccumulatedErrorClient:
    """检测链路桩：直连返回累积后的错误串（模拟 web_async 的新格式），bypass 失败。"""

    def __init__(self):
        self.bypass_calls = 0

    async def request(self, method, url, **kwargs):
        return None, (
            "GET http://www.getchu.com 失败: HTTP 403、"
            "Failed to perform, curl: (35) TLS connect error: body=<html>Just a moment...</html>"
        )

    async def _try_bypass_cloudflare(self, **kwargs):
        self.bypass_calls += 1
        return None, "HTTP 502、GET http://127.0.0.1:7372/html 失败: HTTP 502"


class _StubConfig:
    use_proxy = False
    proxy = ""
    cf_bypass_url = "http://127.0.0.1:7372"
    cf_bypass_proxy = ""
    cf_bypass_trawl_url = ""
    cf_bypass_trawl_backend = "flaresolverr"
    timeout = 5
    proxy_sites = ""
    direct_sites = ""

    def proxy_hosts_list(self):
        return []

    def direct_sites_list(self):
        return []


class _StubManager:
    config = _StubConfig()
    computed = None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_check_keeps_accumulated_errors_after_body_truncation(monkeypatch):
    """检测行按首个 ` body=` 截断响应体时，累积的失败原因不能被一并切掉。"""
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: _StubManager())
    client = _AccumulatedErrorClient()
    spec = NetworkCheckSpec(name="getchu", group="刮削站点", url="http://www.getchu.com", enable_cf_bypass=True)

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.FAILED
    message = result.error or result.message
    assert client.bypass_calls == 1
    assert "HTTP 403、Failed to perform, curl: (35) TLS connect error:" in message, message
    assert "body=" not in message, "响应体不应进检测行"
    assert "CloudFlare Bypass兜底失败：HTTP 502、GET http://127.0.0.1:7372/html 失败: HTTP 502" in message, message
