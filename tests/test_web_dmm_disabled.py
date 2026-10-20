"""DMM 被禁用时，图片兜底与 Amazon 参考图不再访问 DMM CDN。"""

from types import SimpleNamespace

import pytest

import mdcx.core.web as web
from mdcx.config.enums import Website
from mdcx.config.manager import manager


@pytest.fixture
def dmm_disabled():
    original = list(getattr(manager.config, "website_disabled", []) or [])
    manager.config.website_disabled = [Website.DMM]
    try:
        yield
    finally:
        manager.config.website_disabled = original


@pytest.mark.asyncio
async def test_build_dmm_poster_candidates_skips_when_dmm_disabled(dmm_disabled):
    result = SimpleNamespace(number="SSIS-001", poster="")
    assert await web._build_dmm_poster_candidates(result) == []


@pytest.mark.asyncio
async def test_load_dmm_official_reference_skips_when_dmm_disabled(dmm_disabled, monkeypatch):
    async def _must_not_download(*args, **kwargs):
        raise AssertionError("DMM 已禁用，不应下载 DMM 官方参考图")

    monkeypatch.setattr(web, "_download_image_to_memory", _must_not_download)
    assert await web._load_dmm_official_reference("SSIS-001", None) is None


@pytest.mark.asyncio
async def test_build_dmm_poster_candidates_works_when_dmm_enabled():
    manager.config.website_disabled = []
    result = SimpleNamespace(number="SSIS-001", poster="")
    candidates = await web._build_dmm_poster_candidates(result)

    assert len(candidates) == 1
    assert candidates[0].source == "dmm_direct"
    assert candidates[0].url.endswith("ps.jpg")
