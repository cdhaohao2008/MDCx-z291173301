"""旧配置自动升级：补齐缺失键 + 补齐新增列表项 + 落盘写回。

对应 2.6.2 的「配置结构变更后，程序运行时旧配置可自动升级」需求。
大配置框架未变，故 CURRENT_CONFIG_VERSION 保持不变，升级靠
「缺失键按出厂默认补齐 + 列表项幂等补齐」两步完成。
"""

import json

from mdcx.config.enums import DownloadableFile
from mdcx.config.migrations import CURRENT_CONFIG_VERSION, NEW_LIST_ITEMS, migrate_config_data
from mdcx.config.models import Config


def _v2_legacy_config() -> dict:
    """一份典型的旧配置：v2 版本号、legacy 小写站点名、缺大量新键。"""
    return {
        "config_version": 2,
        "main_mode": 4,
        "website_single": "airav_cc",
        "website_youma": ["dmm", "dmm_api"],
        "download_files": [DownloadableFile.NFO.value, DownloadableFile.POSTER_AUTO_BEST.value],
        "switch_on": ["auto_start"],
    }


def test_factory_defaults_covers_all_model_fields() -> None:
    """factory_defaults 必须覆盖全部模型字段，否则补齐会漏键。"""
    defaults = Config.factory_defaults()
    assert set(defaults) == set(Config.model_fields)
    assert defaults  # 非空
    # 必须可 JSON 序列化（写盘用的是 model_dump_json）
    json.dumps(defaults)


def test_factory_defaults_does_not_expand_type_field_configs() -> None:
    """不能用 Config().model_dump() 取默认值。

    model_post_init 会调 ensure_type_field_configs() 把空 dict 填成 7 组
    「按 website_* 推导」的站点优先级，若把它当默认值补进旧配置，会覆盖
    用户在旧界面里自定义的 type_field_configs 优先级。
    """
    defaults = Config.factory_defaults()
    assert defaults["type_field_configs"] == {}
    assert Config().model_dump()["type_field_configs"] != {}  # 反证：前者是「空」


def test_update_backfills_all_missing_top_level_keys() -> None:
    """旧配置跑一遍 Config.update 后，模型字段一个都不该再缺失。"""
    d = _v2_legacy_config()
    warnings = Config.update(d)

    defaults = Config.factory_defaults()
    assert [key for key in defaults if key not in d] == []
    assert d["config_version"] == CURRENT_CONFIG_VERSION
    # 迁移提示必须带 [迁移] 前缀，否则 load_config 会判为致命错误走 _failed.json（议题 #69）
    assert all(w.startswith(("[迁移]", "[V1]")) for w in warnings)
    Config.model_validate(d)  # 补齐后必须仍能通过强校验


def test_update_backfills_missing_keys_without_touching_existing_ones() -> None:
    """只补缺失键，不改动用户已有键的值。

    注意排除 website_*：legacy 小写站点名改品牌大小写是既有的站点迁移行为，
    与本次的「缺失键补齐」无关，不能拿来当断言基准。
    """
    d = _v2_legacy_config()
    d["ui_scale_factor"] = 1.5
    d["download_files"] = [DownloadableFile.NFO.value]

    Config.update(d)

    assert d["ui_scale_factor"] == 1.5
    # download_files 走的是「补新增项」而非覆盖：原有项必须仍在
    assert d["download_files"][0] == DownloadableFile.NFO.value
    assert len(d["download_files"]) > 1


def test_new_list_items_appended_to_legacy_config() -> None:
    """download_files 等已有值的列表，必须由迁移显式补上出厂默认勾选的新项。"""
    d = _v2_legacy_config()
    Config.update(d)

    for value in NEW_LIST_ITEMS["download_files"]:
        assert value in d["download_files"]
    assert d["download_files"][:2] == [
        DownloadableFile.NFO.value,
        DownloadableFile.POSTER_AUTO_BEST.value,
    ]  # 原有项保持原位与顺序


def test_backfill_keeps_separate_mode_inheritance_working() -> None:
    """补齐必须发生在 separate_* 继承之后，否则左侧开关会被提前填满而失去继承。

    separate_mode 打开时，separate_* 的开/关要从对应的主开关继承。
    """
    d = _v2_legacy_config()
    d["separate_mode"] = True
    d["separate_video"] = True
    d["separate_animate"] = True
    d["separate_movie"] = True

    Config.update(d)

    defaults = Config.factory_defaults()
    # separate_* 由主开关继承而来，取值应与主开关一致而非出厂默认
    assert d["separate_video"] == d["separate_mode"] == True  # noqa: E712
    for key, value in defaults.items():
        assert key in d, key


def test_update_is_idempotent() -> None:
    """重复升级不产生新的改动——否则每次启动都会重写配置文件。"""
    d = _v2_legacy_config()
    Config.update(d)
    once = json.loads(json.dumps(d, default=str))

    Config.update(d)
    assert json.loads(json.dumps(d, default=str)) == once


def test_legacy_main_mode_remapped_exactly_once():
    """旧编号里的「分离位」2 只迁移一次，第二次 Config.update 必须原地不动。

    锁的是「config_version 冻结为 2 后，迁移判据改为结构性判据」这条改动：
    若又退回拿版本号当判据，每次启动都会把 2 推成 3、3 推成 4、4 推成 5。
    """
    d = _v2_legacy_config()
    d["main_mode"] = 2  # 旧编号：2 = 视频

    Config.update(d)
    assert d["main_mode"] == 3  # 新编号：3 = 视频
    once = json.loads(json.dumps(d, default=str))

    Config.update(d)
    assert d["main_mode"] == 3
    assert json.loads(json.dumps(d, default=str)) == once


def test_migrate_list_items_does_not_create_absent_keys() -> None:
    """键整体缺失的列表项交给 pydantic default_factory，迁移不应凭空造键。"""
    d = _v2_legacy_config()
    del d["download_files"]
    migrate_config_data(d)
    assert "download_files" not in d
