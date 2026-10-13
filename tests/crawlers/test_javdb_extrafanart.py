import pytest
from parsel import Selector

from mdcx.base.web import is_bare_host_url
from mdcx.core.media_resource import MediaResourceContext
from mdcx.crawlers.base.base_types import Context
from mdcx.crawlers.javdb import Parser as JavdbParser
from mdcx.crawlers.javdb_api import Parser as JavdbApiParser
from mdcx.models.model_types import CrawlerInput

# javdb 样图画廊真实结构（/v/eprkM 实测）：a.tile-item 的 href 为裸 CDN 根占位，
# 真图在内层 img src。
_FANCYBOX_HTML = """
<div class="tile-images preview-images">
  <a class="tile-item" href="https://c0.jdbstatic.com/" data-fancybox="gallery" data-caption="1">
    <img src="https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg" alt="1" loading="lazy" />
  </a>
  <a class="tile-item" href="https://c0.jdbstatic.com/" data-fancybox="gallery" data-caption="2">
    <img src="https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg" alt="2" loading="lazy" />
  </a>
</div>
"""

# 混合结构：第一个锚点 href 是原图（优先取 href），第二个 href 是裸占位（回退 img）。
_MIXED_HTML = """
<div class="tile-images preview-images">
  <a class="tile-item" href="https://c0.jdbstatic.com/samples/xz/XzkY4_1.jpg">
    <img src="https://c0.jdbstatic.com/thumbs/xz/XzkY4_1.jpg" />
  </a>
  <a class="tile-item" href="https://c0.jdbstatic.com/">
    <img src="https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg" />
  </a>
</div>
"""
_HREF_ONLY_HTML = """
<div class="tile-images preview-images">
  <a class="tile-item" href="https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg">x</a>
  <a class="tile-item" href="https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg">x</a>
</div>
"""


def _ctx():
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "MKBD-S39"
    return ctx


@pytest.mark.asyncio
async def test_javdb_extrafanart_prefers_img_src_over_bare_href():
    html = Selector(text=_FANCYBOX_HTML)
    result = await JavdbParser().extrafanart(_ctx(), html)
    assert result == [
        "https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg",
        "https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg",
    ]
    assert not any(is_bare_host_url(u) for u in result)


@pytest.mark.asyncio
async def test_javdb_api_extrafanart_prefers_img_src_over_bare_href():
    html = Selector(text=_FANCYBOX_HTML)
    result = await JavdbApiParser().extrafanart(_ctx(), html)
    assert result == [
        "https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg",
        "https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg",
    ]


@pytest.mark.asyncio
async def test_extrafanart_falls_back_to_href_without_img():
    html = Selector(text=_HREF_ONLY_HTML)
    for parser in (JavdbParser(), JavdbApiParser()):
        result = await parser.extrafanart(_ctx(), html)
        assert result == [
            "https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg",
            "https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg",
        ]


@pytest.mark.asyncio
async def test_extrafanart_href_first_img_fallback_per_anchor():
    html = Selector(text=_MIXED_HTML)
    for parser in (JavdbParser(), JavdbApiParser()):
        result = await parser.extrafanart(_ctx(), html)
        assert result == [
            "https://c0.jdbstatic.com/samples/xz/XzkY4_1.jpg",
            "https://c0.jdbstatic.com/samples/ep/eprkM_s_1.jpg",
        ]


def test_is_bare_host_url():
    assert is_bare_host_url("https://c0.jdbstatic.com/")
    assert is_bare_host_url("https://c0.jdbstatic.com")
    assert is_bare_host_url("//c0.jdbstatic.com/")
    assert not is_bare_host_url("https://c0.jdbstatic.com/covers/ep/eprkM.jpg")
    assert not is_bare_host_url("https://c0.jdbstatic.com/samples/ep/eprkM_s_0.jpg")
    assert not is_bare_host_url("")
    assert not is_bare_host_url("not a url")


def test_media_context_normalize_url_drops_bare_host():
    assert MediaResourceContext.normalize_url("https://c0.jdbstatic.com/") == ""
    assert MediaResourceContext.normalize_url("https://c0.jdbstatic.com") == ""
    assert (
        MediaResourceContext.normalize_url("https://c0.jdbstatic.com/covers/ep/eprkM.jpg")
        == "https://c0.jdbstatic.com/covers/ep/eprkM.jpg"
    )


@pytest.mark.asyncio
async def test_media_context_probe_size_never_requests_bare_host():
    # normalize 已视为空，_probe_size 应直接返回 (0, 0) 而不发起任何请求。
    ctx = MediaResourceContext()
    assert await ctx.probe_size("https://c0.jdbstatic.com/") == (0, 0)
    assert await ctx.fetch_image("https://c0.jdbstatic.com/") is None
