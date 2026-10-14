import pytest

from mdcx.crawlers.avheat import AvheatCrawler
from mdcx.crawlers.avmoo import AvmooCrawler
from mdcx.crawlers.avsox import AvsoxCrawler
from mdcx.models.model_types import CrawlerInput

SEARCH_RESPONSE = {
    "code": 200,
    "data": [
        {
            "movieId": "kgjavpj",
            "movieFanHao": "SSNI-804",
            "title": "Title",
        }
    ],
}

DETAIL_RESPONSE = {
    "code": 200,
    "data": {
        "movieId": "kgjavpj",
        "movieFanHao": "SSNI-804",
        "title": "巨乳上司と童貞部下",
        "title_ja": "巨乳上司と童貞部下",
        "releaseDate": "2020-06-14",
        "length": 119,
        "posterLarge": "https://img/pl.jpg",
        "posterSmall": "https://img/ps.jpg",
        "sampleLarge": ["https://img/s1.jpg", "https://img/s2.jpg"],
        "studio": {"studioName": "S1 NO.1 Style"},
        "series": {"seriesName": "Series"},
        "label": {"labelName": "S1 NO.1 STYLE"},
        "director": {"directorName": "苺原"},
        "star": [{"starName_en": "Aika Yumeno", "starName_ja": "夢乃あいか"}],
        "genre": [{"genreName": "ドラマ"}, {"genreName": "ギリモザ"}],
        "description_cn": "简介",
    },
}


class _FakeCookies:
    def get_dict(self):
        return {"_csrf": "test-csrf"}


class _FakeWarmupResp:
    status_code = 200
    cookies = _FakeCookies()


class FakeClient:
    """模拟 async_client，记录请求参数并按顺序返回预设响应。"""

    def __init__(self, search=None, detail=None):
        self.calls: list[tuple[str, dict]] = []
        self.warmup_calls: list[tuple[str, str]] = []
        self.search = search or SEARCH_RESPONSE
        self.detail = detail or DETAIL_RESPONSE

    async def request(self, method, url, **kwargs):
        self.warmup_calls.append((method, url))
        return _FakeWarmupResp(), ""

    async def post_json(self, url, *, data=None, json_data=None, headers=None, **kwargs):
        self.calls.append((url, {"data": data, "json_data": json_data, "headers": headers, "cookies": kwargs.get("cookies")}))
        if url.endswith("/search"):
            return self.search, ""
        return self.detail, ""


def _run(crawler_cls, number: str = "SSNI-804"):
    crawler = crawler_cls(client=FakeClient(), base_url="https://avmoo.shop")
    input_data = CrawlerInput.empty()
    input_data.number = number
    return crawler.run(input_data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("crawler_cls", "site_value", "mosaic"),
    [
        (AvmooCrawler, "AVMOO", "有码"),
        (AvsoxCrawler, "avsox", "无码"),
        (AvheatCrawler, "avheat", "欧美"),
    ],
)
async def test_run_search_then_get_movie(crawler_cls, site_value, mosaic):
    response = await _run(crawler_cls)
    assert response.data is not None
    assert response.data.source == site_value
    assert response.data.number == "SSNI-804"
    assert response.data.title == "巨乳上司と童貞部下"
    assert response.data.release == "2020-06-14"
    assert response.data.year == "2020"
    assert response.data.runtime == "119"
    assert response.data.studio == "S1 NO.1 Style"
    assert response.data.publisher == "S1 NO.1 STYLE"
    assert response.data.series == "Series"
    assert response.data.directors == ["苺原"]
    assert response.data.actors == ["夢乃あいか"]
    assert response.data.all_actors == ["夢乃あいか"]
    assert response.data.tags == ["ドラマ", "ギリモザ"]
    assert response.data.thumb == "https://img/pl.jpg"
    assert response.data.poster == "https://img/ps.jpg"
    assert response.data.extrafanart == ["https://img/s1.jpg", "https://img/s2.jpg"]
    assert response.data.mosaic == mosaic


@pytest.mark.asyncio
async def test_search_request_uses_json_array_body():
    crawler = AvmooCrawler(client=FakeClient(), base_url="https://avmoo.shop")
    input_data = CrawlerInput.empty()
    input_data.number = "SSNI-804"
    await crawler.run(input_data)

    search_call = crawler.async_client.calls[0]
    assert search_call[0] == "https://avmoo.shop/jav/data/api/search"
    assert search_call[1]["data"] == '[{"search": "SSNI-804", "lang": "cn"}, 60, 1]'
    assert search_call[1]["headers"]["Content-Type"] == "application/json"
    # 预热 Cookie 透传到 API 请求
    assert search_call[1]["cookies"] == {"_csrf": "test-csrf"}

    detail_call = crawler.async_client.calls[1]
    assert detail_call[0] == "https://avmoo.shop/jav/data/api/getMovie"
    assert detail_call[1]["data"] == {"movieId": "kgjavpj"}
    assert detail_call[1]["cookies"] == {"_csrf": "test-csrf"}


@pytest.mark.asyncio
async def test_warmup_called_before_search():
    client = FakeClient()
    crawler = AvsoxCrawler(client=client, base_url="https://avsox.click")
    input_data = CrawlerInput.empty()
    input_data.number = "MKBD-S39"
    await crawler.run(input_data)

    assert client.warmup_calls and client.warmup_calls[0] == ("GET", "https://avsox.click")


@pytest.mark.asyncio
async def test_search_prefers_exact_fanhao():
    """模糊搜索带回近似番号时优先精确匹配（MKBD-S39 不应拿成 MKBD-S72）。"""
    search = {
        "code": 200,
        "data": [
            {"movieId": "kplremk", "movieFanHao": "MKBD-S72", "title": "wrong"},
            {"movieId": "dnaapdn", "movieFanHao": "MKBD-S39", "title": "right"},
        ],
    }
    detail = {
        "code": 200,
        "data": {
            "movieId": "dnaapdn",
            "movieFanHao": "MKBD-S39",
            "title": "KIRARI 39",
            "releaseDate": "2012-12-06",
            "length": 180,
            "posterLarge": "https://img/pl.jpg",
            "posterSmall": "https://img/ps.jpg",
            "sampleLarge": [],
            "studio": {"studioName": "S"},
            "series": {"seriesName": "KIRARI (Blu-ray)"},
            "label": {"labelName": "L"},
            "director": {"directorName": "D"},
            "star": [],
            "genre": [],
        },
    }
    crawler = AvsoxCrawler(client=FakeClient(search=search, detail=detail), base_url="https://avsox.click")
    input_data = CrawlerInput.empty()
    input_data.number = "MKBD-S39"
    response = await crawler.run(input_data)
    assert response.data is not None
    assert response.data.number == "MKBD-S39"
    assert response.data.title == "KIRARI 39"
    detail_call = crawler.async_client.calls[1]
    assert detail_call[1]["data"] == {"movieId": "dnaapdn"}


@pytest.mark.asyncio
async def test_mojibake_fields_fall_back_to_clean_language():
    """MKBD-S39 实测：_ja 带 � 残码时回退干净值，标签优先 _cn 中文。"""
    detail = {
        "code": 200,
        "data": {
            "movieId": "dnaapdn",
            "movieFanHao": "MKBD-S39",
            "title": "KIRARI 39",
            "releaseDate": "2012-12-06",
            "length": 180,
            "posterLarge": "https://img/pl.jpg",
            "posterSmall": "https://img/ps.jpg",
            "sampleLarge": [],
            "studio": {"studioName_cn": "", "studioName_ja": "�ॲ�", "studioName_en": "MUGEN", "studioName": "�ॲ�"},
            "series": {"seriesName": "KIRARI (Blu-ray)"},
            "label": None,
            "director": None,
            "star": [{"starName_ja": "���g�ޤ���", "starName_en": "Maomi Nagasawa", "starName_cn": ""}],
            "genre": [
                {"genreName_cn": "美人", "genreName_ja": "美女", "genreName_en": "美女", "genreName": "美女"},
                {"genreName_cn": "美肌", "genreName_ja": "iPhone/iPad対応", "genreName_en": "Beautiful Skin", "genreName": "iPhone/iPad対応"},
                {"genreName_cn": "潮吹", "genreName_ja": "潮吹�?", "genreName_en": "Squirt", "genreName": "潮吹�?"},
            ],
        },
    }
    search = {"code": 200, "data": [{"movieId": "dnaapdn", "movieFanHao": "MKBD-S39"}]}
    crawler = AvsoxCrawler(client=FakeClient(search=search, detail=detail), base_url="https://avsox.click")
    input_data = CrawlerInput.empty()
    input_data.number = "MKBD-S39"
    response = await crawler.run(input_data)
    assert response.data is not None
    assert response.data.actors == ["Maomi Nagasawa"]
    assert response.data.studio == "MUGEN"
    assert response.data.tags == ["美人", "美肌", "潮吹"]


@pytest.mark.asyncio
async def test_dynamic_domain_miss_falls_back_to_default():
    """动态域名搜不到时改用默认域名重试（浏览器直连正常时的兜底）。"""

    class RoutingClient(FakeClient):
        async def post_json(self, url, *, data=None, json_data=None, headers=None, **kwargs):
            self.calls.append(
                (url, {"data": data, "json_data": json_data, "headers": headers, "cookies": kwargs.get("cookies")})
            )
            if url.startswith("https://stale.example") and url.endswith("/search"):
                return {"code": 200, "data": []}, ""
            if url.endswith("/search"):
                return self.search, ""
            return self.detail, ""

    crawler = AvsoxCrawler(client=RoutingClient(), base_url="https://stale.example")
    input_data = CrawlerInput.empty()
    input_data.number = "SSNI-804"
    response = await crawler.run(input_data)
    assert response.data is not None
    assert response.data.number == "SSNI-804"
    searched_hosts = [u for u, _ in crawler.async_client.calls if u.endswith("/search")]
    assert searched_hosts[0].startswith("https://stale.example")
    assert searched_hosts[-1] == "https://avsox.click/javu/data/api/search"


@pytest.mark.asyncio
async def test_namespace_and_fallback_domain():
    assert AvmooCrawler.namespace == "jav"
    assert AvmooCrawler.fallback_domain == "https://avmoo.shop"
    assert AvheatCrawler.namespace == "wav"
    assert AvheatCrawler.fallback_domain == "https://avheat.shop"
    assert AvsoxCrawler.namespace == "javu"
    assert AvsoxCrawler.fallback_domain == "https://avsox.click"


@pytest.mark.asyncio
async def test_with_outline_flags():
    assert AvmooCrawler.with_outline is False
    assert AvheatCrawler.with_outline is True
    assert AvsoxCrawler.with_outline is True


@pytest.mark.asyncio
async def test_outline_only_loaded_when_enabled(monkeypatch: pytest.MonkeyPatch):
    from mdcx.crawlers import aio_site as aio_module

    monkeypatch.setattr(aio_module, "get_aio_domain", lambda site: "https://avmoo.shop")

    response = await _run(AvmooCrawler)
    assert response.data is not None
    assert not response.data.outline

    avheat = AvheatCrawler(client=FakeClient(), base_url="https://avheat.shop")
    input_data = CrawlerInput.empty()
    input_data.number = "SSNI-804"
    response = await avheat.run(input_data)
    assert response.data is not None
    assert response.data.outline == "简介"
