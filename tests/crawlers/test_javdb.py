import pytest
from parsel import Selector

from mdcx.config.models import Website
from mdcx.crawlers.javdb import JavdbCrawler
from mdcx.models.model_types import CrawlerInput


def _load_html(name: str) -> Selector:
    path = f"tests/crawlers/data/javdb_api/{name}"
    with open(path, encoding="utf-8") as f:
        return Selector(text=f.read())


def test_site_enum():
    assert JavdbCrawler.site() == Website.JAVDB


@pytest.mark.asyncio
async def test_parse_search_page_matches_exact():
    crawler = JavdbCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "IPX-535"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is not None
    assert any("abc123" in url for url in result)


@pytest.mark.asyncio
async def test_parse_search_page_bf_not_matched_by_abf():
    crawler = JavdbCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "BF-030"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is None


@pytest.mark.asyncio
async def test_parse_search_page_abf_still_matches():
    crawler = JavdbCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "ABF-030"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is not None
    assert any("ghi789" in url for url in result)


def test_search_candidates_adds_base_for_dmm_z_suffix():
    # 议题 #106：DMM `z` 尾缀番号在 javdb 收录为基础番号，搜索候选应附带
    assert JavdbCrawler._search_candidates("IBW-786Z") == ["IBW-786Z", "IBW-786"]
    assert JavdbCrawler._search_candidates("BF-030") == ["BF-030"]


@pytest.mark.asyncio
async def test_parse_detail_page_maps_thumb_title_actors():
    from mdcx.crawlers.base.base_types import Context
    from mdcx.crawlers.javdb import Parser

    html = Selector(
        text="""
        <html><body>
          <a class="button is-white copy-to-clipboard" data-clipboard-text="SSIS-001"></a>
          <h2 class="title is-4"><strong class="current-title">Sample Title</strong><span class="origin-title">Origin Title</span></h2>
          <img class="video-cover" src="https://c0.jdbstatic.com/covers/ss/ssis-001.jpg" />
          <span><a>演员A</a><strong class="female"></strong></span>
          <div><strong>片商:</strong><span><a>制作商</a></span></div>
          <div><strong>日期:</strong><span>2024-01-01</span></div>
        </body></html>
        """
    )
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "SSIS-001"
    parser = Parser()

    assert await parser.number(ctx, html) == "SSIS-001"
    assert await parser.title(ctx, html) == "Sample Title"
    assert await parser.thumb(ctx, html) == "https://c0.jdbstatic.com/covers/ss/ssis-001.jpg"
    assert await parser.image_download(ctx, html) is False
