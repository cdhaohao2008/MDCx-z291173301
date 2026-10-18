import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.javday import (
    MIN_TITLE_MATCH_SCORE,
    JavDayCrawler,
    clean_title_keyword,
    get_cover,
    get_some_info,
    get_title,
    title_match_score,
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


# ---------- 国产短剧：条目无番号，改走站内搜索页按标题找页面 ----------

# 真实页面结构（/search/?q=继母与女儿）：每个结果一个 <a class="videoBox">，
# 标题在 .videoBox-info .title 里，链接是站内随机 ID（/videos/Gb5WuoJw/）。
SEARCH_HTML = """
<html><body>
  <div class="col-style d-4 m-2 lazy loaded">
    <a href="/videos/Gb5WuoJw/" target="_blank" class="videoBox">
      <div class="videoBox_wrap"></div>
      <div class="videoBox-info"><span class="title">女儿同爸</span></div>
    </a>
  </div>
  <div class="col-style d-4 m-2 lazy loaded">
    <a href="/videos/uzRTu1MR/" target="_blank" class="videoBox">
      <div class="videoBox_wrap"></div>
      <div class="videoBox-info"><span class="title">继母与女儿</span></div>
    </a>
  </div>
  <div class="col-style d-4 m-2 lazy loaded">
    <a href="/videos/BtjCR1uv/" target="_blank" class="videoBox">
      <div class="videoBox_wrap"></div>
      <div class="videoBox-info"><span class="title">办公室的秘密</span></div>
    </a>
  </div>
  <a href="/tags/国产/">国产标签页不是视频结果</a>
</body></html>
"""


def _duanju_input() -> CrawlerInput:
    data_input = CrawlerInput.empty()
    data_input.number = ""
    data_input.file_path = r"D:\短剧\继母与女儿.国语.mp4"
    return data_input


@pytest.mark.asyncio
async def test_javday_no_number_falls_back_to_title_search_url():
    """短剧条目没有番号：取不到番号时应改拼站内搜索页 URL，而不是 /videos//。"""
    crawler = JavDayCrawler(client=None, base_url="https://javday.app")
    ctx = crawler.new_context(_duanju_input())

    urls = await crawler._generate_search_url(ctx)

    assert urls
    assert all("/search/?q=" in url for url in urls), urls
    assert urls[0] == "https://javday.app/search/?q=%E7%BB%A7%E6%AF%8D%E4%B8%8E%E5%A5%B3%E5%84%BF"


@pytest.mark.asyncio
async def test_javday_numbered_file_still_uses_direct_video_url():
    """有番号的老流程不受影响：仍走 /videos/<番号>/ 直连，不进搜索页。"""
    crawler = JavDayCrawler(client=None, base_url="https://javday.app")
    data_input = CrawlerInput.empty()
    data_input.number = "MXGS-319"
    ctx = crawler.new_context(data_input)

    urls = await crawler._generate_search_url(ctx)

    assert urls
    assert all("/videos/" in url and "/search/" not in url for url in urls), urls


@pytest.mark.asyncio
async def test_javday_title_search_ranks_best_match_first():
    """搜索是模糊匹配，必须按标题相似度排序并丢掉不沾边的那条。"""
    crawler = JavDayCrawler(client=None, base_url="https://javday.app")
    ctx = crawler.new_context(_duanju_input())
    html = Selector(text=SEARCH_HTML)
    search_url = "https://javday.app/search/?q=%E7%BB%A7%E6%AF%8D%E4%B8%8E%E5%A5%B3%E5%84%BF"

    detail_urls = await crawler._parse_search_page(ctx, html, search_url)

    assert detail_urls == [
        "https://javday.app/videos/uzRTu1MR/",
        "https://javday.app/videos/Gb5WuoJw/",
    ]


@pytest.mark.asyncio
async def test_javday_title_search_returns_none_when_all_unrelated():
    """标题完全对不上时不返回任何详情页，宁可报搜索失败也不乱抓一部。"""
    crawler = JavDayCrawler(client=None, base_url="https://javday.app")
    ctx = crawler.new_context(_duanju_input())
    html = Selector(text=SEARCH_HTML)
    search_url = "https://javday.app/search/?q=%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E4%BA%BA%E7%89%A9"

    assert await crawler._parse_search_page(ctx, html, search_url) is None


def test_title_match_score_prefers_exact_then_containment():
    assert title_match_score("继母与女儿", "继母与女儿") == 100.0
    assert title_match_score("继母与女儿", "继母与女儿 国语") > 80
    assert title_match_score("继母与女儿", "继母与女儿") > title_match_score("继母与女儿", "女儿同爸")
    # 只共用「的」这种字的不算沾边，得低于阈值被丢掉
    assert title_match_score("继母与女儿", "办公室的秘密") < MIN_TITLE_MATCH_SCORE
    # 繁简与标点差异不影响匹配（站点标题是繁体、文件名可能是简体）
    assert title_match_score("继母与女儿", "繼母與女兒") == 100.0


def test_clean_title_keyword_drops_resolution_and_language():
    assert clean_title_keyword("继母与女儿.国语.1080P") == "继母与女儿"
    assert clean_title_keyword("【完整版】继母与女儿 国语 高清") == "继母与女儿"
    # 整串都是噪声时清洗不出东西，返回空串让调用方回退用原名
    assert clean_title_keyword("1080P 国语") == ""


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
