"""站点网址的 www 归一化（纯函数叶子模块）。

用户 2026-10-24 报的三个问题都出在同一处：自定义网址里留着早前版本自动补上的
`www.`，而目标站的 www 变体要么是空壳、要么 301 到主域。

- `www.javdb580.com` 是个只回 1 字节换行的空壳（真正的主站是 `javdb580.com`）：
  JavDB 的 Cookie 检测永远拿不到登录态、JavDB_API 的搜索页解析不出结果；
- `javbus.com` 301 到 `www.javbus.com`：跨主机跳转时请求头里的 Cookie 会被丢掉，
  有效的 JavBus Cookie 因此被判成「可能无效」（2026-10-19 的同类问题复现）。

这里只做纯字符串处理：判断「自定义网址是不是只比站点默认地址多了个 www」，
是就按默认地址走；不触网、不改用户配置。
"""

from urllib.parse import urlsplit, urlunsplit


def without_www(url: str) -> str:
    """去掉网址 host 的 `www.` 前缀（协议/端口/路径/查询原样保留）。

    本来就没有 `www.` 时返回空串，方便调用方用 `if alt := without_www(url)` 判断。
    """
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower()
    if not host.startswith("www."):
        return ""
    netloc = host[4:]
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def strip_redundant_www(url: str, default_url: str) -> str:
    """自定义网址只比站点默认地址多一个 `www.` 时，改用默认地址。

    只在这种「同一个站、只差 www」的情形下改写，其余自定义网址（换镜像域名、
    带路径、带端口）原样返回——不能把用户真正改过的地址悄悄换掉。
    """
    url = str(url or "").strip()
    default_url = str(default_url or "").strip()
    if not url or not default_url:
        return url
    parts = urlsplit(url)
    default_parts = urlsplit(default_url)
    host = (parts.hostname or "").lower()
    default_host = (default_parts.hostname or "").lower()
    if not host or not default_host or host == default_host or host != f"www.{default_host}":
        return url
    netloc = default_host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(
        (parts.scheme or default_parts.scheme or "https", netloc, parts.path, parts.query, parts.fragment)
    )
