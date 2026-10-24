"""站点默认地址规范：统一带 www，且绝不能出现 `www.www.`。

用户 2026-10-24：所有站点的默认地址都要带 www；`dmm_api`、`fc2`、`javdb_app`、
`theporndb`、`xcity` 因为地址格式特殊（api 子域、多级子域）不加，加了反而连不上。
另外「默认地址千万不要写成 www.www. 这样，有 www.www. 的一律改成 www」。

这里按注册表逐站校验，新增站点时忘了补 www 会直接失败。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from mdcx.config.enums import Website
from mdcx.config.manager import manager
from mdcx.config.models import Config, site_default_url
from mdcx.crawlers.base import crawler_registry

# 地址格式特殊、明确不加 www 的站点（用户 2026-10-24 指定）
NO_WWW_SITES = frozenset(
    {
        Website.DMM_API,
        Website.FC2,
        Website.JAVDB_APP,
        Website.THEPORNDB,
        Website.XCITY,
    }
)

# 明确不加 www 的站点：TheJavDB 的 www 无响应（用户 2026-10-24 浏览器实测），
# Madouqu 的 www.madouqu.shop 在 DNS 上就是 NXDOMAIN，主域浏览器访问正常。
NO_WWW_DNS_SITES = frozenset({Website.MADOUQU, Website.THEJAVDB})

# 没有固定入口地址的站点（base_url_() 返回空串）
EMPTY_URL_SITES = frozenset({Website.DMM, Website.OFFICIAL})


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch: pytest.MonkeyPatch):
    """默认地址不能被本机配置里的自定义网址顶掉（否则测试随开发机配置漂移）。"""
    monkeypatch.setattr(manager, "config", Config())


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/")[0] if "://" in url else ""


def _bare_domain(url: str) -> bool:
    """host 是「example.com」这种两段式裸域名（子域名不算）。"""
    return len(_host(url).split(".")) == 2


def test_no_double_www_in_any_site_default():
    for site in crawler_registry:
        url = site_default_url(site)
        assert "www.www." not in url, f"{site.value} 的默认地址写成了重复 www: {url}"


def test_bare_domain_defaults_carry_www():
    missing: list[str] = []
    for site in crawler_registry:
        if site in NO_WWW_SITES or site in NO_WWW_DNS_SITES:
            continue
        url = site_default_url(site)
        if not url:
            assert site in EMPTY_URL_SITES, f"{site.value} 默认地址为空，但不在已知无地址名单里"
            continue
        if _bare_domain(url) and not _host(url).startswith("www."):
            missing.append(f"{site.value}: {url}")
    assert missing == [], "以下站点默认地址缺 www: " + "; ".join(missing)


def test_excluded_sites_keep_their_own_host():
    """例外站点的默认地址保持原样（api 子域 / 多级子域，不能加 www）。"""
    for site in NO_WWW_SITES:
        url = site_default_url(site)
        assert url, f"{site.value} 应该有默认地址"
        assert not _host(url).startswith("www."), f"{site.value} 不该加 www: {url}"


def test_aio_sites_default_to_chinese_homepage():
    """AIO 三站（avmoo/avsox/avheat）默认地址带 /cn 中文首页。"""
    from mdcx.crawlers.avheat import AVheatCrawler
    from mdcx.crawlers.avmoo import AvmooCrawler
    from mdcx.crawlers.avsox import AVSOXCrawler

    expected = {
        AvmooCrawler: "https://www.avmoo.shop/cn",
        AVSOXCrawler: "https://www.avsox.click/cn",
        AVheatCrawler: "https://www.avheat.shop/cn",
    }
    for cls, url in expected.items():
        assert cls.base_url_() == url


def test_aio_api_base_drops_lang_path():
    """API 固定在站点根：带 /cn 的地址拼 API 前要去掉语言段，否则搜索会 404。"""
    from mdcx.crawlers.avsox import AVSOXCrawler

    crawler = AVSOXCrawler.__new__(AVSOXCrawler)
    assert crawler._api_base("https://www.avsox.click/cn") == "https://www.avsox.click"
    assert crawler._api_base("https://www.avsox.click/cn/") == "https://www.avsox.click"
    # 动态解析回来的根地址原样保留
    assert crawler._api_base("https://avsox.example") == "https://avsox.example"


def test_site_url_column_keeps_full_address():
    """「当前网站」下拉右侧网址列显示完整地址（含 https://www.）。"""
    from mdcx.controllers.main_window.init import _resolve_site_url

    assert _resolve_site_url("7mmtv") == "https://www.7mmtv.sx/"
    assert _resolve_site_url("JavDB") == "https://www.javdb.com/"
