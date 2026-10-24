"""站点默认地址规范：一律不带 `www.`（用户 2026-10-24 定规）。

用户原话：「所有网站的默认地址都不要加 www，加了有些网站反而有问题」。实测依据：
`www.madouqu.shop` / `www.thejavdb.net` 在 DNS 上就是 NXDOMAIN，`www.iqqq3.quest`、
`www.javfree.me` 的证书与域名不匹配（TLS 直接失败），iqqtv 的 www 还会被站内 302 到
`?fromsite=www`。

唯一例外是 MGStage：用户 2026-10-24 明确要求它保留 www（`https://www.mgstage.com`）。

另外「默认地址千万不要写成 www.www. 这样」——这里也一并校验。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from mdcx.base.web import site_root
from mdcx.config.enums import Website
from mdcx.config.manager import manager
from mdcx.config.models import Config, site_default_url
from mdcx.crawlers.base import crawler_registry

# 用户 2026-10-24 指定保留 www 的站点（其余站点一律不带 www）
WWW_ONLY_SITES = frozenset({Website.MGSTAGE})

# 没有固定入口地址的站点（base_url_() 返回空串）
EMPTY_URL_SITES = frozenset({Website.DMM, Website.OFFICIAL})

# 用户 2026-10-24 逐个点名的默认地址
EXPECTED_DEFAULTS = {
    Website.JAVLIBRARY: "https://javlibrary.com/cn",
    Website.IQQTV: "https://iqqr1.org/cn",
    Website.JAVFREE: "https://javfree.me",
    Website.MADOUQU: "https://madouqu.shop",
    Website.JAVDB: "https://javdb580.com",
    Website.MGSTAGE: "https://www.mgstage.com",
}


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch: pytest.MonkeyPatch):
    """默认地址不能被本机配置里的自定义网址顶掉（否则测试随开发机配置漂移）。"""
    monkeypatch.setattr(manager, "config", Config())


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/")[0] if "://" in url else ""


def test_no_www_in_any_site_default():
    offenders: list[str] = []
    for site in crawler_registry:
        url = site_default_url(site)
        if not url or site in WWW_ONLY_SITES:
            continue
        if _host(url).startswith("www."):
            offenders.append(f"{site.value}: {url}")
    assert offenders == [], "以下站点默认地址还带 www: " + "; ".join(offenders)


def test_www_only_site_keeps_www():
    """MGStage 是唯一保留 www 的站点（用户 2026-10-24 指定）。"""
    assert site_default_url(Website.MGSTAGE) == "https://www.mgstage.com"


def test_no_double_www_in_any_site_default():
    for site in crawler_registry:
        url = site_default_url(site)
        assert "www.www." not in url, f"{site.value} 的默认地址写成了重复 www: {url}"


def test_named_defaults():
    """用户点名的四个地址。"""
    for site, expected in EXPECTED_DEFAULTS.items():
        assert site_default_url(site) == expected, f"{site.value} 默认地址不对"


def test_every_site_has_default_except_known_empty():
    for site in crawler_registry:
        if site in EMPTY_URL_SITES:
            assert site_default_url(site) == ""
            continue
        assert site_default_url(site), f"{site.value} 默认地址为空"


def test_aio_sites_default_to_chinese_homepage():
    """AIO 三站（avmoo/avsox/avheat）默认地址带 /cn 中文首页，且不带 www。"""
    from mdcx.crawlers.avheat import AVheatCrawler
    from mdcx.crawlers.avmoo import AvmooCrawler
    from mdcx.crawlers.avsox import AVSOXCrawler

    expected = {
        AvmooCrawler: "https://avmoo.shop/cn",
        AVSOXCrawler: "https://avsox.click/cn",
        AVheatCrawler: "https://avheat.shop/cn",
    }
    for cls, url in expected.items():
        assert cls.base_url_() == url


def test_aio_api_base_drops_lang_path():
    """API 固定在站点根：带 /cn 的地址拼 API 前要去掉语言段，否则搜索会 404。"""
    from mdcx.crawlers.avsox import AVSOXCrawler

    crawler = AVSOXCrawler.__new__(AVSOXCrawler)
    assert crawler._api_base("https://avsox.click/cn") == "https://avsox.click"
    assert crawler._api_base("https://avsox.click/cn/") == "https://avsox.click"
    # 动态解析回来的根地址原样保留
    assert crawler._api_base("https://avsox.example") == "https://avsox.example"


def test_site_root_strips_language_path():
    """入口地址带语言段/首页路径时，拼搜索地址前要收敛成站点根。"""
    assert site_root("https://javlibrary.com/cn") == "https://javlibrary.com"
    assert site_root("https://javlibrary.com/cn/") == "https://javlibrary.com"
    assert site_root("https://javlibrary.com") == "https://javlibrary.com"
    assert site_root("https://f101w.com/cn/main.php") == "https://f101w.com"
    assert site_root("https://iqqr1.org/cn") == "https://iqqr1.org"


def test_language_path_not_doubled():
    """JavLibrary / IQQTV 的默认地址自带 /cn，刮削拼地址时不能变成 /cn/cn/。"""
    from mdcx.config.enums import Language
    from mdcx.crawlers.iqqtv import IQQTVCrawler
    from mdcx.crawlers.javlibrary import JavLibraryCrawler, language_path

    crawler = JavLibraryCrawler.__new__(JavLibraryCrawler)
    crawler.base_url = JavLibraryCrawler.base_url_()
    assert crawler.base_url.endswith("/cn")
    assert f"{site_root(crawler.base_url)}/{language_path(Language.ZH_CN)}" == "https://javlibrary.com/cn"

    iqq = IQQTVCrawler.__new__(IQQTVCrawler)
    iqq.base_url = IQQTVCrawler.base_url_()
    assert iqq._language_base_url("zh_cn") == "https://iqqr1.org/cn/"
    assert iqq._language_base_url("jp") == "https://iqqr1.org/jp/"


def test_site_url_column_keeps_full_address():
    """「当前网站」下拉右侧网址列显示完整地址（协议 + host + 路径）。"""
    from mdcx.controllers.main_window.init import _resolve_site_url

    assert _resolve_site_url("7mmtv") == "https://7mmtv.sx/"
    assert _resolve_site_url("JavDB") == "https://javdb580.com/"


def test_site_url_column_hides_www():
    """下拉网址列显示一律不带 www；点击跳转/刮削仍用真实地址（MGStage 带 www 才打得开）。"""
    from mdcx.controllers.main_window.init import _display_site_url, _resolve_site_url

    assert _resolve_site_url("MGStage") == "https://www.mgstage.com/"
    assert _display_site_url(_resolve_site_url("MGStage")) == "https://mgstage.com/"
    assert _display_site_url("https://javdb580.com/") == "https://javdb580.com/"
    assert _display_site_url("https://www.f101w.com/cn/") == "https://f101w.com/cn/"
