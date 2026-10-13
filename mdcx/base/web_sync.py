from concurrent.futures import CancelledError, TimeoutError

from ..config.manager import manager
from ..utils import executor

# 同步包装在工作线程里阻塞等后台 loop；网络僵死时不能无限等，
# 否则该工作线程永久泄漏、UI 状态永远卡在“检测中”。
_SYNC_TIMEOUT = 120.0


def get_text_sync(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    use_proxy=True,
    encoding: str = "utf-8",
):
    try:
        with manager.acquire_computed() as computed:
            return executor.run(
                computed.async_client.get_text(
                    url, headers=headers, cookies=cookies, encoding=encoding, use_proxy=use_proxy
                ),
                timeout=_SYNC_TIMEOUT,
            )
    except CancelledError:
        return None, "任务已取消"
    except TimeoutError:
        # 注意：文案不得含 "Cookie" 字样——调用方（javdb/javbus 检查）无 response
        # 时只读 error 字符串做状态展示，含该字样会被误判为 Cookie 有效。
        return None, "请求超时（120s），请检查网络或代理后重试"


def get_json_sync(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    use_proxy=True,
):
    try:
        with manager.acquire_computed() as computed:
            return executor.run(
                computed.async_client.get_json(url, headers=headers, cookies=cookies, use_proxy=use_proxy),
                timeout=_SYNC_TIMEOUT,
            )
    except CancelledError:
        return None, "任务已取消"
    except TimeoutError:
        return None, "请求超时（120s），请检查网络或代理后重试"
