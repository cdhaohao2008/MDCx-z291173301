import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.javday import (
    JavDayCrawler,
    get_cover,
    get_some_info,
    get_title,
)
from mdcx.models.model_types import CrawlerInput

DETAIL_HTML = """
<html>
  <head><meta property="og:image" content="https://cdn.example.test/cover.jpg" /></head>
  <body>
    <div id="videoInfo"><div>
      <h1>MXGS-319-L 初！強制イカセ洗礼 矢野沙紀（無碼流出版）</h1>
      <div>
        <p><span>类别</span><span><a>国产</a><a>剧情</a></span></p>
        <p><span>其他</span><span>xxx</span></p>
        <p><span>系列</span><span><a>麻豆</a></span></p>
      </div>
    </div></div>
  </body>
</html>
"""


def _mock_dmm_upgrade(monkeypatch):
    async def fake_upgrade(ctx, number, cover, poster):
        return cover, poster

    monkeypatch.setattr("mdcx.crawlers.dmm_direct.upgrade_dmm_cover", fake_upgrade)


class FakeJavdayClient:
    async def get_text(self, url, **kwargs):
        assert "/videos/" in url
        return DETAIL_HTML, ""


@pytest.mark.asyncio
async def test_javday_run_maps_fields_and_thumb(monkeypatch):
    _mock_dmm_upgrade(monkeypatch)
    crawler = JavDayCrawler(client=FakeJavdayClient(), base_url="https://javday.app")
    data_input = CrawlerInput.empty()
    data_input.number = "MXGS-319"

    res = await crawler.run(data_input)

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "JavDay"
    assert "MXGS" in (res.data.number or "")
    assert "矢野沙紀" in (res.data.title or "")
    assert res.data.thumb == "https://cdn.example.test/cover.jpg"
    assert res.data.mosaic == "国产"
    assert res.data.image_download is False
    assert res.data.extrafanart == []


@pytest.mark.asyncio
async def test_javday_search_miss_returns_none():
    crawler = JavDayCrawler(client=None, base_url="https://javday.app")
    ctx = crawler.new_context(CrawlerInput.empty())
    html = Selector(text="<html><body>你似乎來到了沒有視頻存在的荒原</body></html>")

    assert await crawler._parse_search_page(ctx, html, "https://javday.app/videos/NOTEXIST/") is None


def test_javday_pure_helpers():
    from lxml import etree

    html = etree.fromstring(DETAIL_HTML, etree.HTMLParser())
    assert "MXGS-319" in get_title(html)
    series, tag, actor = get_some_info(html, "MXGS-319-L 初！強制イカセ洗礼 矢野沙紀（無碼流出版）", "")
    assert series == "麻豆"
    assert "国产" in tag
    assert get_cover(html, "https://javday.app") == "https://cdn.example.test/cover.jpg"


def test_javday_crawler_is_registered():
    assert get_crawler(Website.JAVDAY) is JavDayCrawler
