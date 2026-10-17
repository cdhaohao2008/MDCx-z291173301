"""`Javlibrary·镜像` 站点：zlibz.com 发布的镜像地址怎么解析、怎么用。

为什么单独一个站而不是给 JavLibrary 换个地址：原站对大陆 IP 有 CF 墙、镜像没有，
可达性不同，故拆成两个站点各自配置、各自缓存，用户可以只勾镜像（甚至只勾原站）。

镜像地址由 zlibz.com 首页**右上角的那张图**发布（`<img class="text" src="text.gif?101">`，
内容是 `f101w` + `www.f101w.com/cn`）。页面里没有可解析的文本链接、图里也没有 GIF 注释
扩展，所以只能**按图片内容的 sha256 认地址**；认不出就依次探测已知中文地址兜底。
这里把这三层分别钉死：解析图片地址 → 按哈希认地址 → 探测回退，再钉住爬虫本身的行为。
"""

import hashlib
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import mdcx.base.web as web  # noqa: E402
from mdcx.base.web import (  # noqa: E402
    _JAVLIBRARY_MIRROR_DOMAINS,
    _JAVLIBRARY_MIRROR_IMAGE_HASHES,
    _match_javlibrary_mirror_image,
    _parse_zlibz_address_image,
    get_javlibrary_mirror_domain,
)
from mdcx.config.enums import FixedScrapingType, Website  # noqa: E402
from mdcx.config.models import TYPE_DEFAULT_SITES  # noqa: E402
from mdcx.crawlers import get_crawler, get_registered_crawler_site_values  # noqa: E402
from mdcx.crawlers.javlibrary import JavLibraryCrawler  # noqa: E402
from mdcx.crawlers.javlibrary_mirror import JavLibraryMirrorCrawler, mirror_root  # noqa: E402

# zlibz.com 首页里右上角那张地址图的写法（class="text" 那张才是地址图，logo.gif 是二维码）
ZLIBZ_HTML = (
    '<div class="main"><img class="logo" src="logo.gif" width="150" height="150">'
    '<img class="text" src="text.gif?101" width="320" height="60"></div>'
)


def _crawler():
    return get_crawler(Website.JAVLIBRARY_MIRROR)


# --------------------------------------------------------------------------- 地址图解析


def test_parse_zlibz_address_image_finds_the_top_right_image():
    """只认 class="text" 的那张（logo.gif 是二维码，不是地址）。"""
    assert _parse_zlibz_address_image(ZLIBZ_HTML) == "https://zlibz.com/text.gif?101"


def test_parse_zlibz_address_image_accepts_absolute_and_relative_forms():
    """站点改版可能换成绝对地址 / 协议相对 / 其它属性顺序，都得能取到。"""
    assert (
        _parse_zlibz_address_image('<img class="text" src="https://zlibz.com/text.gif?9">')
        == "https://zlibz.com/text.gif?9"
    )
    assert (
        _parse_zlibz_address_image('<img class="text" src="//zlibz.com/text.gif?9">') == "https://zlibz.com/text.gif?9"
    )
    assert _parse_zlibz_address_image('<img class="text" src="pic/text.gif?9">') == "https://zlibz.com/pic/text.gif?9"
    # class 与 src 的先后顺序无关
    assert _parse_zlibz_address_image('<img src="text.gif?9" class="text">') == "https://zlibz.com/text.gif?9"


def test_parse_zlibz_address_image_without_the_image_returns_empty():
    """取不到就返回空串，让上层走探测兜底，而不是把页面当地址用。"""
    assert _parse_zlibz_address_image("") == ""
    assert _parse_zlibz_address_image("<html><body>维护中</body></html>") == ""
    assert _parse_zlibz_address_image('<img class="logo" src="logo.gif">') == ""


def test_mirror_image_hash_maps_to_the_published_address():
    """认地址靠哈希表；表里已有的那张图必须仍解析出当前中文地址。"""
    assert _JAVLIBRARY_MIRROR_IMAGE_HASHES["74b57aaf7d89868a0d43aa6ec180dcfc503b6668aca24c98bdfde78d4e294579"]
    assert (
        _match_javlibrary_mirror_image("74b57aaf7d89868a0d43aa6ec180dcfc503b6668aca24c98bdfde78d4e294579")
        == "https://www.f101w.com/cn"
    )


def test_unknown_image_hash_yields_empty():
    """换地址 = 换图，哈希对不上时返回空串（上层据此走探测，不是当成地址）。"""
    assert _match_javlibrary_mirror_image("0" * 64) == ""
    assert _match_javlibrary_mirror_image("") == ""


def test_known_addresses_are_chinese_pages():
    """兜底列表必须是中文页地址——用户要的就是「默认使用中文地址」。"""
    assert all(domain.endswith("/cn") for domain in _JAVLIBRARY_MIRROR_DOMAINS)
    assert _JAVLIBRARY_MIRROR_DOMAINS[0] == "https://www.f101w.com/cn"


# --------------------------------------------------------------------------- 抓取地址


class _FakeResponse:
    def __init__(self, content: bytes = b""):
        self.content = content


def _patch_manager(monkeypatch, handler):
    """把 manager.acquire_computed 换成假的：handler 收到 (kind, url) 返回内容或 None。"""

    class FakeAsyncClient:
        async def get_text(self, url, **kwargs):
            result = handler("text", url)
            return (result, "") if result is not None else (None, "err")

        async def request(self, method, url, **kwargs):
            result = handler("bytes", url)
            return (result, "") if result is not None else (None, "err")

    class FakeComputed:
        async def __aenter__(self):
            return SimpleNamespace(async_client=FakeAsyncClient())

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(web.manager, "acquire_computed", lambda: FakeComputed())


@pytest.fixture
def clear_mirror_cache():
    web._JAVLIBRARY_MIRROR_DOMAIN_CACHE.clear()
    yield
    web._JAVLIBRARY_MIRROR_DOMAIN_CACHE.clear()


@pytest.mark.asyncio
async def test_resolve_domain_recognizes_the_published_image(monkeypatch, clear_mirror_cache):
    """流程走通：取首页 → 取地址图 → 按图认地址，并写进缓存（第二次不再请求）。"""
    payload = b"GIF89a-fake-address-image"
    calls: list[str] = []

    def handler(kind: str, url: str):
        calls.append(url)
        if kind == "text":
            return ZLIBZ_HTML
        return _FakeResponse(payload)

    # 造一张内容落在哈希表里的图：直接把 payload 的 sha256 塞进表
    monkeypatch.setitem(
        _JAVLIBRARY_MIRROR_IMAGE_HASHES, hashlib.sha256(payload).hexdigest(), "https://www.example.test/cn"
    )
    _patch_manager(monkeypatch, handler)

    assert await get_javlibrary_mirror_domain() == "https://www.example.test/cn"
    assert calls == ["https://zlibz.com/", "https://zlibz.com/text.gif?101"]
    # 缓存命中，第二次不重新请求
    calls.clear()
    assert await get_javlibrary_mirror_domain() == "https://www.example.test/cn"
    assert calls == []


@pytest.mark.asyncio
async def test_resolve_domain_falls_back_to_probing_when_image_is_unknown(monkeypatch, clear_mirror_cache):
    """换了新图（哈希对不上）：不报错，改为依次探测已知中文地址，返回首个可用的。"""
    probed: list[str] = []

    def handler(kind: str, url: str):
        if kind == "text":
            return ZLIBZ_HTML
        if url.endswith("text.gif?101"):
            return _FakeResponse(b"brand-new-image")
        probed.append(url)
        return _FakeResponse(b"ok") if url.startswith("https://www.c97k.com") else None

    _patch_manager(monkeypatch, handler)

    assert await get_javlibrary_mirror_domain() == "https://www.c97k.com/cn"
    assert probed == _JAVLIBRARY_MIRROR_DOMAINS


@pytest.mark.asyncio
async def test_resolve_domain_survives_a_dead_publisher(monkeypatch, clear_mirror_cache):
    """zlibz.com 整个挂了：仍然要给出可用地址，不能让整站失败。"""

    def handler(kind: str, url: str):
        if kind == "text":
            raise RuntimeError("connection reset")
        return _FakeResponse(b"ok")

    _patch_manager(monkeypatch, handler)
    assert await get_javlibrary_mirror_domain() == _JAVLIBRARY_MIRROR_DOMAINS[0]


# --------------------------------------------------------------------------- 爬虫


def test_mirror_root_strips_the_language_suffix():
    """镜像站的 base_url 允许带 /cn，解析最新地址时要把语言后缀摘掉。"""
    assert mirror_root("https://www.f101w.com/cn") == "https://www.f101w.com"
    assert mirror_root("https://www.c97k.com/tw/") == "https://www.c97k.com"
    assert mirror_root("https://www.f101w.com") == "https://www.f101w.com"
    assert mirror_root("https://www.f101w.com/ja") == "https://www.f101w.com"


def test_mirror_crawler_is_registered():
    assert get_crawler(Website.JAVLIBRARY_MIRROR) is JavLibraryMirrorCrawler
    assert Website.JAVLIBRARY_MIRROR.value in get_registered_crawler_site_values()
    # 与原站各自独立：不能把镜像爬到原站的类上，反之亦然
    assert get_crawler(Website.JAVLIBRARY) is JavLibraryCrawler


def test_mirror_crawler_reuses_the_javlibrary_parsing():
    """镜像站页面结构与原站同源，解析流程直接继承——故它是 JavLibraryCrawler 的子类。"""
    assert issubclass(JavLibraryMirrorCrawler, JavLibraryCrawler)
    for name in (
        "_scrape_language",
        "_browser_bypass",
        "post_process",
        "_generate_search_url",
        "_parse_search_page",
        "_parse_detail_page",
    ):
        assert getattr(JavLibraryMirrorCrawler, name) is getattr(JavLibraryCrawler, name), name


def test_mirror_crawler_identity():
    """站点值、展示名、说明都要是镜像自己的，不能串到原站上。

    说明与原站同为「有码：仅限有码」——定位说明只说它能刮什么类型，不夹带「镜像站」
    「无 CF 墙」这类额外措辞（用户明确要求过不要在说明里加戏）。
    """
    crawler = _crawler()
    assert crawler.site() == Website.JAVLIBRARY_MIRROR
    assert crawler.display_name() == "Javlibrary\u00b7\u955c\u50cf"
    assert crawler.description == "有码：仅限有码"


def test_mirror_crawler_default_base_url_is_the_chinese_page():
    """下拉框与刮削默认都用中文地址（未配置自定义网址时）。"""
    assert _crawler().base_url_() == "https://www.f101w.com/cn"
    assert _crawler().base_url_().endswith("/cn")


def test_mirror_crawler_knows_all_published_hosts():
    """CF 判定/换域名要认得镜像的域名，以及发布地址的站点本身。"""
    hosts = _crawler().known_hosts()
    assert any("f101w.com" in host for host in hosts)
    assert any("c97k.com" in host for host in hosts)
    assert any("zlibz.com" in host for host in hosts)


def test_mirror_crawler_defaults_to_the_chinese_language():
    """默认中文页：父类只在需要时才叠本地化页，镜像必须默认要。"""
    from mdcx.config.enums import Language

    crawler = JavLibraryMirrorCrawler(client=None)
    assert crawler._needs_localized_language() == Language.ZH_CN
    # 父类那条「按需本地化」在镜像上不成立，故必须覆盖而不是继承
    assert JavLibraryMirrorCrawler._needs_localized_language is not JavLibraryCrawler._needs_localized_language


def test_mirror_site_sits_right_after_javlibrary_in_coded_types():
    """用户指定的位置：有码与素人两组里镜像紧跟在原站后面。"""
    for scraping_type in (FixedScrapingType.YOUMA, FixedScrapingType.SUREN):
        sites = list(TYPE_DEFAULT_SITES[scraping_type])
        assert sites.index(Website.JAVLIBRARY_MIRROR) == sites.index(Website.JAVLIBRARY) + 1


def test_mirror_site_only_joins_the_coded_types():
    """只加进有码/素人两组，其余四组不含它。"""
    for scraping_type in (
        FixedScrapingType.WUMA,
        FixedScrapingType.FC2,
        FixedScrapingType.OUMEI,
        FixedScrapingType.GUOCHAN,
    ):
        assert Website.JAVLIBRARY_MIRROR not in TYPE_DEFAULT_SITES[scraping_type], scraping_type.name


def test_mirror_site_value_accepts_legacy_spellings():
    """配置里手写的几种写法都归一到同一个站点值，不至于变成「非法站点」被静默剔除。"""
    for spelling in (
        "javlibrary\u00b7\u955c\u50cf",
        "javlibrary_mirror",
        "javlibrarymirror",
        "Javlibrary\u00b7\u955c\u50cf",
    ):
        assert Website(spelling) is Website.JAVLIBRARY_MIRROR
