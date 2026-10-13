"""respx 接入示例：httpx 轻量直连路径（``_emby_request``）改走真实传输层 mock。

对比 tests/test_emby_actor_manager_http.py 里手写的 FakeAsyncClient：
路由按真实 URL 注册，还能断言实际发出的 method/headers，不用再伪造
``httpx.Response`` 子集。

缺 respx 时整文件跳过（importorskip），不影响 CI 最小依赖集。
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("respx")

pytestmark = pytest.mark.asyncio


@pytest.fixture
def emby_configured(monkeypatch):
    """填必需的 api_key/emby_url/server_type。"""
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "api_key", "test-token")
    monkeypatch.setattr(manager.config, "emby_url", "http://test:8096")
    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "user_id", "user-1")


async def test_emby_request_500_via_respx(emby_configured, respx_mock):
    """500 按 (None, "HTTP 500...") 返回，且真实请求带了 token 认证头。"""
    from mdcx.tools import emby_shared

    route = respx_mock.get("http://test:8096/System/Info").mock(
        return_value=httpx.Response(500, text="boom")
    )

    resp, err = await emby_shared._emby_request("GET", "/System/Info", token="secret-token")

    assert resp is None
    assert err.startswith("HTTP 500")
    assert route.called
    sent_auth = route.calls[0].request.headers.get("Authorization", "")
    assert "secret-token" in sent_auth


async def test_emby_get_json_200_via_respx(emby_configured, respx_mock):
    """200 JSON 正常解析返回字典。"""
    from mdcx.tools import emby_shared

    respx_mock.get("http://test:8096/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "4.8"})
    )

    data, err = await emby_shared._emby_get_json("/System/Info")

    assert err == ""
    assert data == {"Version": "4.8"}


async def test_emby_request_connection_error_via_respx(emby_configured, respx_mock):
    """连接异常按 (None, 错误名) 返回，不抛异常。"""
    from mdcx.tools import emby_shared

    respx_mock.get("http://test:8096/System/Info").mock(
        side_effect=httpx.ConnectError("refused")
    )

    resp, err = await emby_shared._emby_request("GET", "/System/Info")

    assert resp is None
    assert "ConnectError" in err
