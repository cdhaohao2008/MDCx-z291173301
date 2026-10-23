"""简介占位值（发行日期 / 看更多）过滤的回归测试。

用户 2026-10-24 的需求：FC2 这类站点会把「販売日」当成简介、把「もっとみる」
当成原简介写进结果，界面上就成了 `简介：发行日期 2025-11-13` / `原简介：看更多`。
这类值零信息量，必须视为"没有简介"：先去其他站点取真正的简介，取不到就保持为空。
"""

import pytest

from mdcx.config.enums import Website
from mdcx.config.models import FieldConfig
from mdcx.core.file_crawler import FileScraper
from mdcx.core.outline_guard import (
    clear_placeholder_plots,
    is_placeholder_originalplot,
    is_placeholder_outline,
    is_placeholder_plot,
)
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.model_types import CrawlerInput, CrawlerResult, CrawlersResult
from tests.test_file_crawler_runtime import _FakeConfig, _FakeCrawlerProvider


@pytest.mark.parametrize(
    "value",
    [
        "发行日期 2025-11-13",
        "發行日期 2025/11/13",
        "发行日期：2025.11.13",
        "販売日 2025-11-13",
        "発売日 2025年11月13日",
        "配信日 2025/11/13",
        "Release date: 2025-11-13",
        "released 2025-11-13",
        "2025-11-13",
        "2025/11/13",
        "2025年11月13日",
        "发行日期 2025-11-13\n",
        "  发行日期   2025-11-13  ",
        "２０２５-１１-１３",
        # FC2 页面把「販売日」和「もっとみる」放在同一区块，抓下来就是这两行
        "发行日期 2025-11-13\n看更多",
        "発売日 2025/11/13\nもっとみる",
    ],
)
def test_release_date_outline_is_placeholder(value: str):
    assert is_placeholder_outline(value) is True
    assert is_placeholder_plot(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "这是一段真正的简介，讲述女主在夏日祭上的故事。",
        "2025-11-13 发售，故事从一场雨夜开始……",
        "FC2-PPV-4797400 素人作品，时长 51 分钟。",
        "",
        "   ",
    ],
)
def test_real_outline_is_not_placeholder(value: str):
    assert is_placeholder_outline(value) is False


@pytest.mark.parametrize(
    "value",
    ["看更多", "查看更多", "查看更多內容", "もっとみる", "続きを読む", "See more", "Read more…", " 看更多 "],
)
def test_read_more_originalplot_is_placeholder(value: str):
    assert is_placeholder_originalplot(value) is True


@pytest.mark.parametrize("value", ["本編のあらすじ。二人の出会いから始まる物語。", "", "   "])
def test_real_originalplot_is_not_placeholder(value: str):
    assert is_placeholder_originalplot(value) is False


def test_outline_also_rejects_read_more():
    """简介字段拿到「看更多」同样不算简介（站点偶尔把展开链接文本塞进简介）。"""
    assert is_placeholder_plot("看更多") is True
    assert is_placeholder_outline("真正的简介") is False


def test_clear_placeholder_plots_reports_cleared_fields():
    data = CrawlersResult.empty()
    data.outline = "发行日期 2025-11-13"
    data.originalplot = "看更多"

    cleared = clear_placeholder_plots(data)

    assert cleared == ["简介", "原简介"]
    assert data.outline == ""
    assert data.originalplot == ""


def test_clear_placeholder_plots_keeps_real_values():
    data = CrawlersResult.empty()
    data.outline = "真正的简介"
    data.originalplot = "本編のあらすじ"

    assert clear_placeholder_plots(data) == []
    assert data.outline == "真正的简介"
    assert data.originalplot == "本編のあらすじ"


class _OutlineConfig(_FakeConfig):
    """简介/原简介两字段的优先级都是 [FC2, JavDB]。"""

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.OUTLINE, CrawlerResultFields.ORIGINALPLOT):
            return FieldConfig(site_prority=[Website.FC2, Website.JAVDB])
        return FieldConfig(site_prority=[])


def _result(site: Website, *, outline: str = "", originalplot: str = "") -> CrawlerResult:
    data = CrawlerResult.empty()
    data.source = site.value
    data.external_id = f"{site.value}:id"
    data.title = f"{site.value} title"
    data.outline = outline
    data.originalplot = originalplot
    return data


class _TwoSiteProvider:
    """FC2 只给占位简介；JavDB 给真简介（或空值）。"""

    def __init__(self, javdb_outline: str = "", javdb_originalplot: str = ""):
        self._provider = _FakeCrawlerProvider(
            {
                Website.FC2: _result(Website.FC2, outline="发行日期 2025-11-13", originalplot="看更多"),
                Website.JAVDB: _result(Website.JAVDB, outline=javdb_outline, originalplot=javdb_originalplot),
            }
        )

    async def get(self, site: Website):
        return await self._provider.get(site)


@pytest.mark.asyncio
async def test_placeholder_outline_falls_back_to_next_site(monkeypatch: pytest.MonkeyPatch):
    """FC2 的「发行日期」简介被舍弃后，简介/原简介必须去下一站取到真值。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.OUTLINE, CrawlerResultFields.ORIGINALPLOT),
    )

    scraper = FileScraper(
        _OutlineConfig(),
        _TwoSiteProvider(javdb_outline="JavDB 的真简介", javdb_originalplot="JavDB 的原简介"),
    )
    task_input = CrawlerInput.empty()
    task_input.number = "FC2-4797400"

    result = await scraper._call_crawlers(task_input, {Website.FC2, Website.JAVDB})

    assert result is not None
    assert result.outline == "JavDB 的真简介", result.field_log
    assert result.originalplot == "JavDB 的原简介", result.field_log
    assert "占位" in result.field_log


@pytest.mark.asyncio
async def test_placeholder_outline_stays_empty_when_no_other_source(monkeypatch: pytest.MonkeyPatch):
    """其他站点也拿不到真简介时，简介/原简介保持为空（绝不回填发行日期/看更多）。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.OUTLINE, CrawlerResultFields.ORIGINALPLOT),
    )

    scraper = FileScraper(_OutlineConfig(), _TwoSiteProvider())
    task_input = CrawlerInput.empty()
    task_input.number = "FC2-4797401"

    result = await scraper._call_crawlers(task_input, {Website.FC2, Website.JAVDB})

    assert result is not None
    assert result.outline == ""
    assert result.originalplot == ""
