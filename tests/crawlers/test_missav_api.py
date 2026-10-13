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
    assert res.data.source == "missav_api"
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
