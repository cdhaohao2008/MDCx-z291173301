import pytest
from parsel import Selector

from mdcx.crawlers.missav import MissavCrawler


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        # 无语言段：语言码插到 slug 之前
        ("https://missav.ws/SSNI-647", "https://missav.ws/cn/SSNI-647"),
        ("https://missav.ws/dm79/SSNI-647", "https://missav.ws/dm79/cn/SSNI-647"),
        # 旧末尾式：纠正为规范式
        ("https://missav.ws/SSNI-647/cn", "https://missav.ws/cn/SSNI-647"),
        ("https://missav.ws/dm79/SSNI-647/cn", "https://missav.ws/dm79/cn/SSNI-647"),
        # 已是规范式：幂等不变
        ("https://missav.ws/cn/SSNI-647", "https://missav.ws/cn/SSNI-647"),
        ("https://missav.ws/dm79/cn/SSNI-647", "https://missav.ws/dm79/cn/SSNI-647"),
    ],
)
def test_ensure_cn_detail_url_uses_canonical_lang_prefix(raw_url: str, expected: str):
    assert MissavCrawler._ensure_cn_detail_url(raw_url) == expected


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("MIDV-999-U", "midv-999"),
        ("MIDV-0999-UC", "midv-999"),
        ("MIDV999U", "midv-999"),
        ("010101-123-U", "010101-123"),
        ("100225_100", "100225-100"),
        ("10musume_031426_01", "031426-01"),
        ("caribbeancom-031426-001", "031426-001"),
    ],
)
def test_normalize_number_for_uncensored_judge(number: str, expected: str):
    assert MissavCrawler._normalize_number_for_uncensored_judge(number) == expected


@pytest.mark.parametrize(
    ("number", "mosaic", "expected"),
    [
        ("MIDV-999-U", "无码破解", False),
        ("MIDV-999-UC", "无码", False),
        ("MIDV-999", "无码", False),
        ("HEYZO-1234-U", "有码", True),
        ("010101-123-U", "有码", True),
        ("100225_100", "有码", True),
        ("10musume_031426_01", "有码", True),
        ("caribbeancom-031426-001", "有码", True),
    ],
)
def test_should_use_uncensored_search_by_original_number(number: str, mosaic: str, expected: bool):
    assert MissavCrawler._should_use_uncensored_search(number, mosaic) is expected


def test_is_soft_404_page_detects_not_found_template():
    html = Selector(
        text="""
        <html>
            <head>
                <meta property="og:title" content="MissAV | 免費高清AV在線看" />
                <meta property="og:image" content="https://missav.ws/missav/logo-square.png" />
                <title>MissAV | 免費高清AV在線看</title>
            </head>
            <body>
                <p>404</p>
                <h1>找不到頁面</h1>
            </body>
        </html>
        """
    )

    assert MissavCrawler._is_soft_404_page(html) is True


def test_is_soft_404_page_ignores_normal_detail_page():
    html = Selector(
        text="""
        <html>
            <head>
                <meta property="og:title" content="SNOS-004 絶頂快感 - MissAV" />
                <meta property="og:image" content="https://fourhoi.com/snos-004/cover-n.jpg" />
                <title>SNOS-004 絶頂快感 - MissAV</title>
            </head>
            <body>
                <h1>SNOS-004 絶頂快感</h1>
                <p>發行日期：2024-01-01</p>
            </body>
        </html>
        """
    )

    assert MissavCrawler._is_soft_404_page(html) is False


class _FakeMissavClient:
    async def get_text(self, url, **kwargs):
        assert "missav" in url
        assert "SSNI-647" in url
        return (
            """
            <html>
              <head>
                <meta property="og:title" content="SSNI-647 Sample Title - MissAV" />
                <meta property="og:image" content="https://fourhoi.com/ssni-647/cover-n.jpg" />
                <meta property="og:url" content="https://missav.ws/cn/SSNI-647" />
                <meta property="og:description" content="Sample outline" />
              </head>
              <body>
                <div class="text-secondary"><span>番號</span><span class="font-medium">SSNI-647</span></div>
                <div class="text-secondary"><span>標題</span><span class="font-medium">Sample Title</span></div>
                <div class="text-secondary"><span>女優</span><span class="font-medium"><a>演员A</a></span></div>
                <div class="text-secondary"><span>發行日期</span><span class="font-medium">2024-01-01</span></div>
                <div class="text-secondary"><span>時長</span><span class="font-medium">120分鐘</span></div>
                <div class="text-secondary"><span>類型</span><span class="font-medium"><a>剧情</a></span></div>
                <div class="text-secondary"><span>系列</span><span class="font-medium"><a>系列A</a></span></div>
                <div class="text-secondary"><span>發行商</span><span class="font-medium"><a>制作商</a></span></div>
              </body>
            </html>
            """,
            "",
        )


@pytest.mark.asyncio
async def test_missav_run_maps_fields_and_thumb():
    from mdcx.config.enums import Language
    from mdcx.models.model_types import CrawlerInput

    crawler = MissavCrawler(client=_FakeMissavClient(), base_url="https://missav.ws")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSNI-647",
            short_number="SSNI-647",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "missav"
    assert res.data.number == "SSNI-647"
    assert res.data.title == "Sample Title"
    assert res.data.actors == ["演员A"]
    assert res.data.release == "2024-01-01"
    assert res.data.thumb == "https://fourhoi.com/ssni-647/cover-n.jpg"
