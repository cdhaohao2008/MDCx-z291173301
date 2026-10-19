import pytest

from mdcx.config.enums import Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.missav_api import MissavApiCrawler
from mdcx.models.model_types import CrawlerInput


def _recombee_item(uncensored=False):
    return {
        "id": "ssis-001",
        "values": {
            "title_cn": "简中标题",
            "title": "Original Title",
            "actresses": ["女优A"],
            "directors": ["导演A"],
            "genres": ["剧情"],
            "series": ["系列A"],
            "labels": ["厂牌A"],
            "released_at": 1672531200,
            "duration": 7200,
            "is_uncensored_leak": uncensored,
        },
    }


def _mock_dmm_upgrade(monkeypatch):
    async def fake_upgrade(ctx, number, cover, poster):
        return cover, poster

    monkeypatch.setattr("mdcx.crawlers.dmm_direct.upgrade_dmm_cover", fake_upgrade)


class FakeRecombeeClient:
    def __init__(self, item):
        self._item = item

    async def post_json(self, url, **kwargs):
        assert "client-rapi-missav.recombee.com" in url
        return {"recomms": [self._item]}, ""


@pytest.mark.asyncio
async def test_missav_api_run_maps_fields_and_images(monkeypatch):
    _mock_dmm_upgrade(monkeypatch)
    crawler = MissavApiCrawler(client=FakeRecombeeClient(_recombee_item()))
    data_input = CrawlerInput.empty()
    data_input.number = "SSIS-001"

    res = await crawler.run(data_input)

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "Missav_API"
    assert res.data.number == "SSIS-001"
    assert res.data.title == "简中标题"
    assert res.data.actors == ["女优A"]
    assert res.data.release == "2023-01-01"
    assert res.data.runtime == "120"
    assert res.data.thumb == "https://fourhoi.com/ssis-001/cover-n.jpg"
    assert res.data.poster == "https://fourhoi.com/ssis-001/cover.jpg"
    assert res.data.image_download is True
    assert res.data.mosaic == ""


@pytest.mark.asyncio
async def test_missav_api_run_uncensored_sets_mosaic(monkeypatch):
    _mock_dmm_upgrade(monkeypatch)
    crawler = MissavApiCrawler(client=FakeRecombeeClient(_recombee_item(uncensored=True)))
    data_input = CrawlerInput.empty()
    data_input.number = "SSIS-001"

    res = await crawler.run(data_input)

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.mosaic == "无码"


def test_missav_api_pure_helpers():
    assert MissavApiCrawler._normalize_number("SSIS-001") == "ssis-001"
    assert MissavApiCrawler._normalize_number_case("ssis-001") == "SSIS-001"
    assert MissavApiCrawler._number_from_url("https://missav.ws/ssis-001/cn") == "ssis-001"
    assert MissavApiCrawler._ts_to_date(1672531200) == "2023-01-01"

    crawler = MissavApiCrawler(client=None)
    data = crawler._build_data(_recombee_item(), "SSIS-001")
    assert data.thumb == "https://fourhoi.com/ssis-001/cover-n.jpg"
    assert data.poster == "https://fourhoi.com/ssis-001/cover.jpg"
    assert data.image_download is True


def test_missav_api_crawler_is_registered():
    assert get_crawler(Website.MISSAV_API) is MissavApiCrawler


class FakeRecombeeUnrelatedClient:
    """Recombee 搜不到目标番号时返回的是一批语义相近的无关条目（2026-10-19 实测）。"""

    UNRELATED_IDS = [
        "sdfk-001",
        "agemix-403",
        "ppx-004",
        "hnd-843-uncensored-leak",
        "miab-596-uncensored-leak",
    ]

    async def post_json(self, url, **kwargs):
        return {"recomms": [{"id": i, "values": {"title_cn": f"无关条目 {i}"}} for i in self.UNRELATED_IDS]}, ""


@pytest.mark.asyncio
async def test_missav_api_recombee_fuzzy_hits_never_become_a_result(monkeypatch):
    """搜不到就报「未找到」，绝不能把 Recombee 首条无关条目当成目标番号的结果。

    旧实现 `return recomms[0]` 让搜 `Deeper.26.06.17` 返回 sdfk-001（SODrijf，2019），
    而 `data.number` 取的是 input_number，用户看到「番号对得上、元数据全错」。
    """
    _mock_dmm_upgrade(monkeypatch)
    crawler = MissavApiCrawler(client=FakeRecombeeUnrelatedClient())
    data_input = CrawlerInput.empty()
    data_input.number = "Deeper.26.06.17"

    res = await crawler.run(data_input)

    assert res.data is None, "Recombee 无番号匹配时不得产出结果"
    assert res.debug_info.error is not None
    assert "未找到" in str(res.debug_info.error)


@pytest.mark.asyncio
async def test_missav_api_recombee_search_returns_none_on_fuzzy_only(monkeypatch):
    """直接钉住 `_recombee_search` 的返回值契约。"""
    crawler = MissavApiCrawler(client=FakeRecombeeUnrelatedClient())
    ctx = type("Ctx", (), {"debug": lambda self, _msg: None})()

    assert await crawler._recombee_search(ctx, "Deeper.26.06.17") is None


@pytest.mark.asyncio
async def test_missav_api_prefix_match_still_accepted(monkeypatch):
    """前缀匹配仍要放行（miab-596 -> miab-596-uncensored-leak 这类派生条目）。"""
    _mock_dmm_upgrade(monkeypatch)
    crawler = MissavApiCrawler(
        client=FakeRecombeeClient({"id": "miab-596-uncensored-leak", "values": {"title_cn": "前缀命中"}})
    )
    data_input = CrawlerInput.empty()
    data_input.number = "MIAB-596"

    res = await crawler.run(data_input)

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "MIAB-596"
    assert res.data.external_id == "miab-596-uncensored-leak"
