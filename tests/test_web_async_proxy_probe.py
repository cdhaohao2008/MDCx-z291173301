"""配置代理端口无监听时的可诊断提示回归测试。

背景：代理不通时每个站点各报一次传输层错误（`WinError 10061` /
`curl: (7) Failed to connect`），十来个站点就是十几条一模一样的报错，没有一条指向
真正的原因——配置的端口上根本没有代理进程在监听。端口错配极常见：Clash 默认 7890，
而 clash-verge 的 mihomo 内核常改到 7897，用户照抄 7890 就是整片刮削失败，且从日志
看不出是配置问题（2026-10-19 排查 欧美组 站点时实测）。

约束：整个客户端只探测一次（成功/失败都算），避免刷屏；探测本身出错不得影响正常请求。
"""

import asyncio
import socket

import pytest

from mdcx.web_async import AsyncWebClient


def _closed_port() -> int:
    """占一个端口再立刻释放，得到一个几乎必定无人监听的端口号。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _client() -> AsyncWebClient:
    logs: list[str] = []
    client = AsyncWebClient(timeout=5, log_fn=logs.append)
    client._test_logs = logs  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_unreachable_proxy_logs_actionable_hint():
    client = _client()
    port = _closed_port()

    await client._warn_unreachable_proxy_once(f"http://127.0.0.1:{port}")

    logs = client._test_logs  # type: ignore[attr-defined]
    assert len(logs) == 1, f"应恰好一条结论日志，实际 {logs}"
    msg = logs[0]
    assert str(port) in msg, "必须点名配置的那个端口"
    assert "7890" in msg and "7897" in msg, "应给出常见取值供用户对照"
    assert "代理" in msg


@pytest.mark.asyncio
async def test_unreachable_proxy_warns_only_once():
    client = _client()
    port = _closed_port()

    await client._warn_unreachable_proxy_once(f"http://127.0.0.1:{port}")
    await client._warn_unreachable_proxy_once(f"http://127.0.0.1:{port}")
    await client._warn_unreachable_proxy_once(f"http://127.0.0.1:{port}")

    assert len(client._test_logs) == 1, "同一客户端只报一次，不能每站点各报一遍"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_reachable_proxy_stays_silent():
    """代理正常时不许啰嗦。"""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = _client()
    try:
        await client._warn_unreachable_proxy_once(f"http://127.0.0.1:{port}")
    finally:
        server.close()
        await server.wait_closed()

    assert client._test_logs == [], "代理可达时不应输出任何提示"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_malformed_proxy_string_does_not_raise():
    """代理串写坏了（端口不是数字）也属配置错误，但绝不能把异常抛到请求路径上。"""
    client = _client()

    await client._warn_unreachable_proxy_once("http://127.0.0.1:not-a-port")

    assert len(client._test_logs) == 1  # type: ignore[attr-defined]
