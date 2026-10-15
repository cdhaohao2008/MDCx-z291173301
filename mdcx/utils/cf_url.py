"""CF 服务地址归一化（纯函数叶子模块）。

原先只有 mdcx/cf_bypass/trawl_adapter.py 里有这一个函数，但 config 迁移与 core 的
网络检测都要用它，于是 config 反向依赖 cf_bypass，并且在只读配置时也要把 httpx
拖进来。这里把它下沉到 utils：trawl_adapter 保留同名再导出，既有导入路径不变。
"""

from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def normalize_trawl_url(url: str | None) -> str:
    """归一化外部CF服务地址：回环地址的 https 降回 http。

    FlareSolverr / TRAWL 本地实例只 serving 纯 HTTP；配成 https://127.0.0.1:8191
    会导致适配层 POST /v1 TLS 握手失败（_wait_ready 探活永不等到 200，60s 后
    start() 失败并永久禁用），检测页 GET / 也超时红灯。非回环地址原样保留。
    """
    cleaned = (url or "").strip().rstrip("/")
    if cleaned.lower().startswith("https://"):
        try:
            host = (urlparse(cleaned).hostname or "").lower()
        except Exception:
            host = ""
        if host in _LOOPBACK_HOSTS:
            cleaned = "http://" + cleaned[len("https://") :]
    return cleaned
