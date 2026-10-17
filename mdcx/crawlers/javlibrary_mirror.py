"""JavLibrary 镜像站爬虫。

与 `javlibrary.py` 分成两个站点而不是同一个站的可切换地址，因为两者可达性不同：
`www.javlibrary.com` 对大陆 IP 有 CF 墙（要过挑战），镜像站（zlibz.com 发布、当前是
`www.f101w.com`）没有 CF 墙。混成一个站则取到哪个全看运气，用户也无法单独指定镜像。

地址来自 zlibz.com 首页右上角发布的那张图（见 `mdcx/base/web.py` 里
`_JAVLIBRARY_MIRROR_IMAGE_HASHES` 的说明），带 1 天缓存；刮削默认用中文页 `/cn`。
页面结构与原站一致，解析逻辑全部继承自 `JavLibraryCrawler`。
"""

import re
from typing import override

from ..base.web import (
    _JAVLIBRARY_MIRROR_DOMAINS,
    _JAVLIBRARY_MIRROR_PUBLISHER,
    _get_cached_javlibrary_mirror_domain,
    get_javlibrary_mirror_domain,
)
from ..config.enums import Language, Website
from ..config.manager import manager
from .javlibrary import JavLibraryCrawler

# 地址末尾可能带语言段（/cn、/ja、/tw），刮削时要按语言再拼一次，故先把根域名剥出来
_MIRROR_LANGUAGE_SUFFIX = re.compile(r"/(?:cn|ja|tw)/?$")


def mirror_root(url: str) -> str:
    """把镜像地址剥成根域名：`https://www.f101w.com/cn` → `https://www.f101w.com`。"""
    return _MIRROR_LANGUAGE_SUFFIX.sub("", str(url).rstrip("/"))


class JavLibraryMirrorCrawler(JavLibraryCrawler):
    description = "有码：仅限有码"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVLIBRARY_MIRROR

    @classmethod
    @override
    def display_name(cls) -> str:
        return Website.JAVLIBRARY_MIRROR.value

    @classmethod
    @override
    def base_url_(cls) -> str:
        # 同步接口（下拉框里的网址列、调网络检查都走这里），只能读缓存或用已知地址；
        # 真正刮削时 _run 会再异步解析一次最新地址。
        default = _get_cached_javlibrary_mirror_domain() or _JAVLIBRARY_MIRROR_DOMAINS[0]
        return manager.config.get_site_url(Website.JAVLIBRARY_MIRROR, default)

    @classmethod
    @override
    def known_hosts(cls) -> frozenset[str]:
        """镜像额外并入已知地址表与运行时解析到的当前地址。"""
        from urllib.parse import urlparse

        hosts = set(super().known_hosts())
        host = urlparse(_JAVLIBRARY_MIRROR_PUBLISHER).netloc.lower().split(":", 1)[0]
        if host:
            hosts.add(host)
        for url in [*_JAVLIBRARY_MIRROR_DOMAINS, _get_cached_javlibrary_mirror_domain()]:
            host = urlparse(str(url)).netloc.lower().split(":", 1)[0]
            if host:
                hosts.add(host)
                if host.startswith("www."):
                    hosts.add(host[4:])
        return frozenset(hosts)

    @classmethod
    @override
    async def check_urls(cls) -> list[str]:
        urls: list[str] = []
        try:
            latest = await get_javlibrary_mirror_domain()
            if latest and latest not in urls:
                urls.append(latest)
        except Exception:
            pass
        for candidate in _JAVLIBRARY_MIRROR_DOMAINS:
            if candidate not in urls:
                urls.append(candidate)
        return urls or [cls.base_url_()]

    @property
    @override
    def use_proxy(self) -> bool:
        # 父类这条属性写死了 Website.JAVLIBRARY，直接继承会去读原站的配置，故必须覆盖
        return not manager.config.get_site_config(Website.JAVLIBRARY_MIRROR).custom_url

    @override
    def _needs_localized_language(self) -> Language | None:
        """默认中文页：镜像就是给中文用户用的，刮削结果默认取 /cn 的标题、简介、分类。"""
        return super()._needs_localized_language() or Language.ZH_CN

    @override
    async def _run(self, ctx):
        # 未显式指定 base_url 且未配置自定义 URL 时，先解析 zlibz.com 当前发布的中文地址
        if not self._explicit_base_url and not manager.config.get_site_config(Website.JAVLIBRARY_MIRROR).custom_url:
            try:
                latest = await get_javlibrary_mirror_domain()
                if latest and latest != self.base_url:
                    ctx.debug(f"使用 javlibrary 镜像地址: {latest}")
                    self.base_url = latest
            except Exception as e:
                ctx.debug(f"获取 javlibrary 镜像地址失败，使用默认: {e}")
        # 解析出的地址带 /cn，语言段由 _scrape_language 按所选语言再拼，这里要的是根域名
        self.base_url = mirror_root(self.base_url)
        return await super()._run(ctx)
