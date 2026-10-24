"""lulubar 爬虫解析逻辑测试（纯函数，无网络依赖）."""

import importlib

from lxml import etree

lulubar = importlib.import_module("mdcx.crawlers.lulubar")


def _html(body: str) -> etree._Element:
    return etree.fromstring(f"<html><body>{body}</body></html>", etree.HTMLParser())


def test_probe_number_is_site_specific():
    """SSNI-647 该站未收录，探针改用实测存在的 IPZZ-547（人工验证）."""
    assert lulubar.LulubarCrawler.probe_number == "IPZZ-547"


def test_get_real_url_matches_uppercase_number():
    """搜索页 img@alt 为大写番号前缀时必须能命中（议题：SSNI-647 搜索不到）."""
    html = _html(
        '<a class="imgBoxW" href="/video/abc">'
        '<img alt="SSNI-647 女朋友不在的日子里被她的闺蜜勾引出轨" src="/images/a.jpg"></a>'
        '<a class="imgBoxW" href="/video/other"><img alt="SSNI-646 另一个" src="/images/b.jpg"></a>'
    )
    assert lulubar.get_real_url(html, "SSNI-647") == (
        "https://lulubar.co/video/abc",
        "https://lulubar.co/images/a.jpg",
    )


def test_get_real_url_matches_lowercase_number():
    html = _html('<a class="imgBoxW" href="/video/abc"><img alt="ssni-647 标题" src="/images/a.jpg"></a>')
    assert lulubar.get_real_url(html, "SSNI-647") == (
        "https://lulubar.co/video/abc",
        "https://lulubar.co/images/a.jpg",
    )


def test_get_real_url_no_match_returns_empty():
    html = _html('<a class="imgBoxW" href="/video/x"><img alt="IPX-535 标题" src="/images/x.jpg"></a>')
    assert lulubar.get_real_url(html, "SSNI-647") == ("", "")


def test_get_real_url_nested_img_frame_and_absolute_poster():
    """新版搜索页 img 被 div.img_frame 包裹，封面已是绝对地址时不能被二次拼接."""
    html = _html(
        '<a class="imgBoxW" href="/video/detail?id=446350">'
        '<div class="img_frame">'
        '<img class="img-fluid imgsize" alt="IPZZ-547 - 标题" '
        'src="https://image.lulubar.co/films/2025/05/10/5816845/ipzz00547pl.jpg">'
        "</div></a>"
    )
    assert lulubar.get_real_url(html, "IPZZ-547") == (
        "https://lulubar.co/video/detail?id=446350",
        "https://image.lulubar.co/films/2025/05/10/5816845/ipzz00547pl.jpg",
    )


def test_get_real_url_matches_number_not_at_start():
    """番号不在标题开头（如 [AI解码版] IPZZ-547）时也能命中."""
    html = _html(
        '<a class="imgBoxW" href="/video/abc">'
        '<div class="img_frame"><img alt="[AI解码版] IPZZ-547 标题" src="/images/a.jpg"></div></a>'
    )
    assert lulubar.get_real_url(html, "IPZZ-547")[0] == "https://lulubar.co/video/abc"


def test_get_real_url_does_not_match_longer_number():
    html = _html(
        '<a class="imgBoxW" href="/video/abc">'
        '<div class="img_frame"><img alt="IPZZ-5470 标题" src="/images/a.jpg"></div></a>'
    )
    assert lulubar.get_real_url(html, "IPZZ-547") == ("", "")


def test_get_cover_from_player_poster():
    """新版详情页封面在 plyr__poster 的 background-image 中."""
    html = _html(
        '<div class="plyr__poster" '
        'style="background-image: url(&quot;https://image.lulubar.co/films/2025/05/10/5816845/ipzz00547pl.jpg&quot;);">'
        "</div>"
    )
    assert lulubar.get_cover(html) == "https://image.lulubar.co/films/2025/05/10/5816845/ipzz00547pl.jpg"


def test_get_cover_falls_back_to_og_image():
    html = etree.fromstring(
        '<html><head><meta property="og:image" content="/films/2025/05/10/5816846/ipzz00547ps.jpg"></head></html>',
        etree.HTMLParser(),
    )
    assert lulubar.get_cover(html) == "https://lulubar.co/films/2025/05/10/5816846/ipzz00547ps.jpg"


def test_get_extrafanart_keeps_absolute_url():
    html = _html('<div id="stills"><div><img src="https://image.lulubar.co/still/1.jpg"></div></div>')
    assert lulubar.get_extrafanart(html) == ["https://image.lulubar.co/still/1.jpg"]
