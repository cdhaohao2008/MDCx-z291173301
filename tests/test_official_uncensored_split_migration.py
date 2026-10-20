"""Official 五无码站拆分：旧配置迁移必须只跑一次且不改 config_version。

用户 2026-10-19 定规：config_version 永远保持 2。因此不能靠版本号判断迁移是否已做，
本文件钉住独立标记键 `official_uncensored_split_migrated` 的幂等行为。
"""

from copy import deepcopy

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.config.migrations import CURRENT_CONFIG_VERSION, migrate_config_data

_FIVE = [
    Website.OFFICIAL_10MUSUME.value,
    Website.OFFICIAL_1PONDO.value,
    Website.OFFICIAL_CARIBBEANCOM.value,
    Website.OFFICIAL_HEYZO.value,
    Website.OFFICIAL_PACOPACOMAMA.value,
]


def test_wuma_official_split_into_five_and_version_unchanged():
    data = {
        "config_version": CURRENT_CONFIG_VERSION,
        "website_wuma": ["AVSOX", "Official", "AVEntertainments"],
        "website_youma": ["Official", "DMM"],
        "website_disabled": ["Official"],
        "field_configs": {"title": {"site_prority": ["DMM", "Official", "LibreDMM"]}},
        "type_field_configs": {FixedScrapingType.WUMA.value: {"title": {"site_prority": ["Official"], "skip": False}}},
    }

    warnings = migrate_config_data(data)

    assert any("五个无码官网" in message for message in warnings)
    assert data["official_uncensored_split_migrated"] is True
    assert data["config_version"] == CURRENT_CONFIG_VERSION == 2
    # WUMA 的 Official 原位展开成五站，不留 Official
    assert data["website_wuma"] == ["AVSOX", *_FIVE, "AVEntertainments"]
    # YOUMA 的 Official 仍代表有码官网，不展开
    assert data["website_youma"] == ["Official", "DMM"]
    # 全局字段保留 Official（有码）并在其后补五站
    assert data["field_configs"]["title"]["site_prority"] == ["DMM", "Official", *_FIVE, "LibreDMM"]
    # WUMA 字段里的 Official 只代表无码，替换成五站
    assert data["type_field_configs"][FixedScrapingType.WUMA.value]["title"]["site_prority"] == _FIVE
    # 旧禁用 Official 时补禁五站，保持行为不回退
    assert data["website_disabled"] == ["Official", *_FIVE]


def test_migration_is_idempotent_after_marker_written():
    data = {
        "website_wuma": ["Official"],
        "field_configs": {"title": {"site_prority": ["Official"]}},
        "website_disabled": ["Official"],
    }
    migrate_config_data(data)
    once = deepcopy(data)

    warnings = migrate_config_data(data)

    assert warnings == []
    assert data == once


def test_lowercase_official_is_renamed_before_split():
    data = {"website_wuma": ["official", "AVSOX"]}

    migrate_config_data(data)

    assert data["website_wuma"] == [*_FIVE, "AVSOX"]
    assert data["official_uncensored_split_migrated"] is True


def test_already_split_config_is_not_expanded_again():
    data = {
        "website_wuma": [Website.OFFICIAL_10MUSUME.value, "AVSOX"],
        "field_configs": {"title": {"site_prority": ["Official", Website.OFFICIAL_HEYZO.value]}},
        "official_uncensored_split_migrated": True,
    }

    migrate_config_data(data)

    assert data["website_wuma"] == [Website.OFFICIAL_10MUSUME.value, "AVSOX"]
    assert data["field_configs"]["title"]["site_prority"] == ["Official", Website.OFFICIAL_HEYZO.value]
