"""Official 五个无码官网拆成独立站点后的抓取边界。

用户要求（2026-10-20）：`Official·10Musume`、`Official·1Pondo`、`Official·Caribbeancom`、
`Official·HEYZO`、`Official·Pacopacomama` 各自独立，互不影响。这里钉住三件事：

1. 五个类都注册到自己的 `Website` 枚举上，探测番号与官网地址取自同一份 spec；
2. 选中的站只抓自己的番号，不会按番号前缀“漂”到另一家官网；
3. 重定向到 `forced_site` 后，分派函数只调用本站的抓取实现。
"""

import pytest

from mdcx.config.enums import Website
from mdcx.crawlers import get_crawler
from mdcx.crawlers.official_uncensored import (
    UNCENSORED_OFFICIAL_SITES,
    Official1PondoCrawler,
    Official10MusumeCrawler,
    OfficialCaribbeancomCrawler,
    OfficialHeyzoCrawler,
    OfficialPacopacomamaCrawler,
    crawl_uncensored_official,
    route_uncensored_official,
)

_SITE_SOURCES = {
    Website.OFFICIAL_10MUSUME: ("10musume", Official10MusumeCrawler),
    Website.OFFICIAL_1PONDO: ("1pondo", Official1PondoCrawler),
    Website.OFFICIAL_CARIBBEANCOM: ("caribbeancom", OfficialCaribbeancomCrawler),
    Website.OFFICIAL_HEYZO: ("heyzo", OfficialHeyzoCrawler),
    Website.OFFICIAL_PACOPACOMAMA: ("pacopacomama", OfficialPacopacomamaCrawler),
}


class _Ctx:
    def debug(self, *_args, **_kwargs) -> None:
        pass


def test_five_sites_registered_with_their_own_source_and_probe():
    for site, (source, crawler_cls) in _SITE_SOURCES.items():
        assert get_crawler(site) is crawler_cls
        spec = UNCENSORED_OFFICIAL_SITES[source]
        assert crawler_cls.base_url_() == spec.base_url
        assert crawler_cls.probe_number == spec.probe_number
        assert route_uncensored_official(spec.probe_number) == source


@pytest.mark.asyncio
async def test_forced_site_rejects_another_sites_number():
    # Caribbeancom 的番号交给 HEYZO 爬虫：不抓、不猜、不回退到 Caribbeancom
    assert (
        await crawl_uncensored_official(
            _Ctx(),
            object(),
            "Caribbeancom-082226-001",
            forced_site="heyzo",
        )
        is None
    )


@pytest.mark.asyncio
async def test_forced_site_dispatches_only_its_own_crawler(monkeypatch):
    import mdcx.crawlers.official_uncensored as mod

    calls: list[tuple[str, str]] = []
    sentinel = object()

    async def fake_heyzo(ctx, client, movie_id):
        calls.append(("heyzo", movie_id))
        return sentinel

    async def fake_caribbean(ctx, client, movie_id):
        calls.append(("caribbeancom", movie_id))
        return sentinel

    monkeypatch.setattr(mod, "_crawl_heyzo", fake_heyzo)
    monkeypatch.setattr(mod, "_crawl_caribbeancom", fake_caribbean)

    data = await crawl_uncensored_official(_Ctx(), object(), "HEYZO-3935", forced_site="heyzo")

    assert data is sentinel
    assert calls == [("heyzo", "3935")]


@pytest.mark.asyncio
async def test_dedicated_crawler_reports_number_from_another_site():
    crawler = OfficialHeyzoCrawler(client=object())
    from mdcx.config.enums import Language
    from mdcx.models.model_types import CrawlerInput

    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="Caribbeancom-082226-001",
            short_number="Caribbeancom-082226-001",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.data is None
    assert res.debug_info.error is not None
