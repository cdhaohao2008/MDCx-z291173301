import pytest

import mdcx.crawlers.dmm as dmm_module
from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.crawlers.thejavdb import TheJavDBCrawler, TheJavdbMovie
from mdcx.models.model_types import CrawlerInput

PAYLOAD = {
    "public_id": "4uKA43Ek",
    "universal_id": "SSIS-001",
    "title": "Title",
    "description": "Line 1<br>Line 2",
    "fullcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg",
    "frontcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg",
    "sample_movie_url": "https://cc3001.dmm.co.jp/pv/TOKEN/ssis00001_mhb_w.mp4",
    "release_date": "2021-02-18",
    "duration": 147,
    "source_url": "https://video.dmm.co.jp/av/content/?id=ssis00001",
    "maker": "エスワン ナンバーワンスタイル",
    "label": "S1 NO.1 STYLE",
    "series": None,
    "actresses": ["葵つかさ", "葵つかさ", "乙白さやか"],
    "directors": ["苺原"],
    "genres": ["ドラマ", "ギリモザ"],
    "samples": ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001jp-1.jpg"],
}


def test_site_url_points_at_web_version_not_dead_api_root():
    """站点地址是网页版首页，`/v1/` 根路径已废弃（会返回 This endpoint does not exist.）。"""
    assert TheJavDBCrawler.base_url_() == "https://thejavdb.net"
    assert TheJavDBCrawler.display_name() == "TheJavDB"
    assert TheJavDBCrawler.site() == Website.THEJAVDB


def test_api_url_uses_number_path_like_the_spa_does():
    assert TheJavDBCrawler.build_api_url("MKMP-765") == "https://api.thejavdb.net/v1/movies/MKMP-765"
    assert TheJavDBCrawler.build_api_url("ssis-001") == "https://api.thejavdb.net/v1/movies/ssis-001"


def test_detail_url_uses_public_id_segment():
    assert TheJavDBCrawler.build_detail_url("MKMP-765", "c6dGLzii") == "https://thejavdb.net/movies/MKMP-765/c6dGLzii"


def test_to_crawler_data_maps_api_response():
    crawler = TheJavDBCrawler(client=None)
    data = crawler._to_crawler_data(TheJavdbMovie.model_validate(PAYLOAD), fallback_number="SSIS-001")

    assert data.number == "SSIS-001"
    assert data.title == "Title"
    assert data.outline == "Line 1\nLine 2"
    assert data.runtime == "147"
    assert data.actors == ["葵つかさ", "乙白さやか"]
    assert data.all_actors == ["葵つかさ", "乙白さやか"]
    assert data.directors == ["苺原"]
    assert data.tags == ["ドラマ", "ギリモザ"]
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.mosaic == "有码"
    # 页面地址按 universal_id/public_id 拼（web 详情页），不再直接回退到 DMM 链接
    assert data.external_id == "https://thejavdb.net/movies/SSIS-001/4uKA43Ek"


def test_to_crawler_data_falls_back_to_source_url_without_public_id():
    payload = {key: value for key, value in PAYLOAD.items() if key != "public_id"}
    crawler = TheJavDBCrawler(client=None)
    data = crawler._to_crawler_data(TheJavdbMovie.model_validate(payload), fallback_number="SSIS-001")
    assert data.external_id == "https://video.dmm.co.jp/av/content/?id=ssis00001"


@pytest.mark.asyncio
async def test_run_calls_api_and_reuses_dmm_image_processing(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        async def get_json(self, url: str, **kwargs):
            assert url == "https://api.thejavdb.net/v1/movies/SSIS-001"
            assert kwargs == {"headers": {"Accept": "application/json"}}
            return (PAYLOAD, "")

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)
    monkeypatch.setattr(
        manager.config,
        "download_files",
        [DownloadableFile.POSTER, DownloadableFile.THUMB, DownloadableFile.EXTRAFANART],
    )

    crawler = TheJavDBCrawler(client=FakeClient())
    input_data = CrawlerInput.empty()
    input_data.number = "SSIS-001"

    response = await crawler.run(input_data)

    assert response.data is not None
    assert response.data.source == Website.THEJAVDB.value
    assert response.data.number == "SSIS-001"
    assert response.data.title == "Title"
    assert response.data.release == "2021-02-18"
    assert response.data.year == "2021"
    assert response.data.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg"
    assert response.data.poster == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg"
    assert response.data.extrafanart == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001jp-1.jpg"
    ]


@pytest.mark.asyncio
async def test_run_retries_without_dmm_z_suffix(monkeypatch: pytest.MonkeyPatch):
    """DMM 图床番号带 z 尾缀（IBW-786z）时站点只收录基础番号（IBW-786）。"""

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get_json(self, url: str, **kwargs):
            self.urls.append(url)
            if url.endswith("/IBW-786z"):
                return ({"error": "Movie not found."}, "")
            return (PAYLOAD, "")

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)
    client = FakeClient()
    crawler = TheJavDBCrawler(client=client)
    input_data = CrawlerInput.empty()
    input_data.number = "IBW-786z"

    response = await crawler.run(input_data)

    assert response.data is not None
    assert client.urls == [
        "https://api.thejavdb.net/v1/movies/IBW-786z",
        "https://api.thejavdb.net/v1/movies/IBW-786",
    ]


@pytest.mark.asyncio
async def test_run_reports_not_found_for_uncensored_number():
    class FakeClient:
        async def get_json(self, url: str, **kwargs):
            return ({"error": "Movie not found."}, "")

    crawler = TheJavDBCrawler(client=FakeClient())
    input_data = CrawlerInput.empty()
    input_data.number = "SIRO-4321"

    response = await crawler.run(input_data)

    assert response.data is None
    assert response.debug_info is not None
    assert "未收录" in str(response.debug_info.error or "")


@pytest.mark.asyncio
async def test_number_context_set_for_aws_thumb_upgrade():
    """_set_number_context 应正确设置 number_00/number_no_00 供 AWS 高清图升级使用。"""
    crawler = TheJavDBCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "SSIS-001"
    crawler._set_number_context(ctx)

    assert ctx.number_00 == "ssis00001"
    assert ctx.number_no_00 == "ssis001"


@pytest.mark.asyncio
async def test_number_context_handles_5digit_with_00_prefix():
    """4位数字（如 SNIS-0027）走 elif 分支，replace("-","0") -> snis00027。"""
    crawler = TheJavDBCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "SNIS-0027"
    crawler._set_number_context(ctx)

    assert ctx.number_00 == "snis00027"
    assert ctx.number_no_00 == "snis00027"
