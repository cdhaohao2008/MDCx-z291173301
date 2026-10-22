import re
from typing import Any

from .enums import DownloadableFile, FixedScrapingType, HDPicSource, Website

# 配置版本号固定为 2（用户 2026-10-19 定规）：以后无论新增配置项、新增列表
# 枚举值、给旧配置补缺键，还是真的动了大配置框架，都**不再**改它——版本号一格
# 一格往上叠，除了让人误以为「框架变了」没有任何实际作用。
# 本值与 resources/config/default_config.json 的 config_version、
# Config.config_version 的默认值必须三者一致。
#
# 连带后果：config_version 已不能当迁移判据（见 _migrate_main_mode 的结构性
# 判据）。版本号被冻结成 2 之后，任何 `_config_version(data) >= 3` 之类的判断
# 都恒为假，会让「只迁一次」的逻辑每次启动重跑一遍。
CURRENT_CONFIG_VERSION = 2

# v2.7.2: 两条 minnano 占位文案规则不再作为演员数据清洗的默认规则。
# 只清理「原始数值=占位文案、替换数值=空」的出厂形态；用户主动改过替换值的
# 同名规则保留，避免误删用户自定义内容。
_LEGACY_MINNANO_CLEAN_RULES = {
    ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
    ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
}


_ORGANIZE_INTERVAL_KEYS = ("organize_local_no_interval", "organize_netdisk_rest_interval")
"""整理模式「本地不限间隔 / 网盘按休息间隔」两个互斥开关的配置键。"""


def _migrate_organize_interval_keys(data: dict[str, Any]) -> None:
    """整理模式「本地存储不限间隔 / 网盘存储按自动休息间隔」互斥开关归一。

    旧配置文件里没有这两个键 → 补出厂默认（本地不限间隔 = True，网盘按休息间隔
    = False），保证老用户升级后行为与默认值一致。

    手改成「两开」或「全关」时归一：两开以「网盘按自动休息间隔」为准（等待是安全
    下限，网盘目录缓存没刷新就会整理失败）；全关则回到「本地不限间隔」（默认档）。
    界面层两枚复选框互斥（勾其一自动取消另一），这里只是手改配置的兜底。
    """
    if not any(key in data for key in _ORGANIZE_INTERVAL_KEYS):
        data["organize_local_no_interval"] = True
        data["organize_netdisk_rest_interval"] = False
        return
    local = bool(data.get("organize_local_no_interval", True))
    netdisk = bool(data.get("organize_netdisk_rest_interval", False))
    if local and netdisk:
        data["organize_local_no_interval"] = False
        data["organize_netdisk_rest_interval"] = True
    elif not local and not netdisk:
        data["organize_local_no_interval"] = True
        data["organize_netdisk_rest_interval"] = False


def _migrate_actor_clean_rules(data: dict[str, Any]) -> None:
    """从存量配置的生效规则/默认规则里摘掉两条已退役的 minnano 占位规则。"""
    for key in ("actor_clean_rules", "actor_clean_rules_default"):
        value = data.get(key)
        if not isinstance(value, list):
            continue
        kept: list[Any] = []
        for item in value:
            try:
                original, replacement = item
            except TypeError, ValueError:
                kept.append(item)
                continue
            if isinstance(original, str) and isinstance(replacement, str):
                if (original, replacement) in _LEGACY_MINNANO_CLEAN_RULES:
                    continue
            kept.append(item)
        if len(kept) != len(value):
            data[key] = kept


def _str_to_list(v: str | list[Any] | None, sep: str = ",", unique: bool = True) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        items = [str(item).strip() for item in v]
    else:
        items = [item.strip() for item in v.replace("，", sep).split(sep)]
    items = [item for item in items if item]
    if unique:
        return list(dict.fromkeys(items))
    return items


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


# 刮削模式编号（v3 调整）：分离模式插入为 2，视频/更新/读取顺延为 3/4/5。
_MAIN_MODE_REMAP_V3 = {2: 3, 3: 4, 4: 5}

# 判别「本配置是否已在新编号下」的结构性依据：分离模式的四个开关与新编号同批
# 入列（2.2.3 起），新编号配置必然带这些键，旧编号配置必然一个都没有。
# 这四个键是真实模型字段，能随 save() 的 model_dump_json 落盘、也会被
# Config.update() 的 separate_* 继承分支补上。
#
# 为什么不能继续读 config_version：它已按用户定规冻结为 2，拿它当判据会让
# **每次启动**都把已经是新编号的配置再迁移一遍——分离模式(2) 会被推成视频(3)、
# 再被推成更新(4)、再被推成读取(5)，用户的刮削模式被悄悄改掉，且越用越偏。
_SEPARATE_MODE_KEYS = (
    "separate_success_file_move",
    "separate_failed_file_move",
    "separate_success_file_rename",
    "separate_del_empty_folder",
)


def _migrate_main_mode(data: dict[str, Any]) -> str | None:
    """旧编号（分离模式之前）→ 新编号，返回迁移提示或 None。

    判据是「`_SEPARATE_MODE_KEYS` 是否已在配置里」，与已冻结的 `config_version`
    无关。迁移后 `Config.update()` 会补上这四个键，故对同一份配置只生效一次。
    """
    if any(key in data for key in _SEPARATE_MODE_KEYS):
        return None
    mode = data.get("main_mode")
    if isinstance(mode, str) and mode.strip().isdigit():
        mode = int(mode.strip())
    if isinstance(mode, bool) or not isinstance(mode, int) or mode not in _MAIN_MODE_REMAP_V3:
        return None
    data["main_mode"] = _MAIN_MODE_REMAP_V3[mode]
    return "[迁移] 刮削模式编号已调整：视频模式2→3、更新模式3→4、读取模式4→5（新增分离模式2）"


def _migrate_download_file_option(value: Any) -> Any:
    value = _enum_value(value)
    if value == "youma_use_poster":
        return None
    if value == DownloadableFile.POSTER_AUTO_BEST.value:
        return DownloadableFile.POSTER_AUTO_BEST.value
    return value


def _is_removed_airav_site(site: object) -> bool:
    return site == Website.AIRAV or site == Website.AIRAV.value


_SITE_RENAMES = {
    "javdbapi": "DMM_API",
    "avmoo": "AVMOO",
    "dmm": "DMM",
    "dmm_api": "DMM_API",
    "freejavbt": "FreeJavBT",
    "getchu": "Getchu",
    "avbase": "AVBase",
    "aventertainments": "AVEntertainments",
    "airav.cc": "Airav.cc",
    "airav_cc": "Airav.cc",
    "avheat": "AVheat",
    "avsex": "AVSEX",
    "avsox": "AVSOX",
    # 大小写三代旧值都在：2026-08 下线前写入的全小写 faleno、恢复独立站点
    # 后写入的全大写 FALENO，均归一到品牌写法 Faleno。
    "faleno": "Faleno",
    "FALENO": "Faleno",
    "fc2": "FC2",
    "fc2ppvdb": "FC2PPVDB",
    "iqqtv": "IQQTV",
    "javbus": "JavBus",
    "javday": "JavDay",
    "javdb": "JavDB",
    # TheJavDB_API 已并入 TheJavDB。三个键都必须列出：`_rename_site` 是精确匹配
    # （无 `.lower()` 兜底），漏了旧值会让存量配置里的该站被 `_is_valid_site()` 当成
    # 非法值静默剔除（议题 #55 那条路径），等于升级即丢用户在用的 TheJavDB 源。
    "thejavdb": "TheJavDB",
    "thejavdb_api": "TheJavDB",
    "TheJavDB_API": "TheJavDB",
    "javdb_api": "JavDB_API",
    "javdb_app": "JavDB_APP",
    "javfree": "JavFree",
    "javlibrary": "JavLibrary",
    "libredmm": "LibreDMM",
    "lulubar": "Lulubar",
    "madouqu": "Madouqu",
    # 大小写两代旧值都在：改名前的全小写 madou_club，以及中间版本写入的 MADOU_CLUB
    "madou_club": "Madou.club",
    "MADOU_CLUB": "Madou.club",
    # 大小写两代旧值都在：改名前的全小写 missav，以及中间版本写入的品牌写法 MissAV，
    # 均归一到 Missav。此处必须逐字列出——`_rename_site` 是精确匹配（无 `.lower()`
    # 兜底），漏了 "MissAV" 会让存量配置里的该站被 `_is_valid_site()` 当成非法值
    # 静默剔除（议题 #55 那条路径），等于升级即丢用户在用的 Missav 源。
    "missav": "Missav",
    "MissAV": "Missav",
    "missav_api": "Missav_API",
    "MissAV_API": "Missav_API",
    "mgstage": "MGStage",
    "mywife": "MyWife",
    "prestige": "Prestige",
    "r18dev": "R18.dev",
    "theporndb": "ThepornDB",
    "xcity": "Xcity",
    "official": "Official",
}

_VALID_SITE_VALUES = frozenset(site.value for site in Website)


def _rename_site(site: str) -> str:
    return _SITE_RENAMES.get(site, site)


def _is_valid_site(site: object) -> bool:
    """站点值是否仍存在于当前 `Website` 枚举中。

    2026-08 精简了 15 个失效/重复爬虫（cnmdb/hdouban/mdtv/love6/kin8/giga/cableav/
    hscangku/fc2club/fc2hub/jav321/fantastica/dahlia/faleno），旧配置里残留的
    站点值会让 pydantic 校验整体失败，进而使配置被写入 `_failed.json`
    且界面回写被跳过（表现为「保存不生效」，议题 #55）。故在此静默剔除。
    7mmtv 曾在同一批被移除，2026-09 以聚合站爬虫形式回归（移植自 Hazard804/mdcx），
    旧配置中残留的 7mmtv 值因此自动恢复有效。
    dahlia/faleno 曾在同一批被移除，2026-10 恢复独立站点身份（厂牌官网重新
    从 Official 拆出），旧配置中残留的 dahlia/faleno 值同样自动恢复有效。
    """
    value = _enum_value(site)
    return isinstance(value, str) and value in _VALID_SITE_VALUES


def _clean_sites(sites: list[Any]) -> list[str]:
    """重命名 + 剔除已移除站点，保持原有顺序。"""
    return [
        renamed
        for site in sites
        if not _is_removed_airav_site(site) and _is_valid_site(renamed := _rename_site(str(_enum_value(site))))
    ]


def _migrate_site_list(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_sites(_str_to_list(value, ","))
    if isinstance(value, list | set):
        return _clean_sites(list(value))
    return value


# Official 五个无码官网从 Official 拆出后的独立站点值。
_OFFICIAL_UNCENSORED_SITES = (
    Website.OFFICIAL_10MUSUME.value,
    Website.OFFICIAL_1PONDO.value,
    Website.OFFICIAL_CARIBBEANCOM.value,
    Website.OFFICIAL_HEYZO.value,
    Website.OFFICIAL_PACOPACOMAMA.value,
)


def _is_official_value(value: Any) -> bool:
    """旧配置里可能还是小写 official：先按迁移表改名再比较。"""
    return _rename_site(str(_enum_value(value))) == Website.OFFICIAL.value


def _replace_official_with_uncensored(sites: list[Any]) -> list[str]:
    """把列表里的 Official 展开成五个无码站；已含任一独立站时不重复展开。"""
    values = [str(_enum_value(site)) for site in sites]
    if any(value in _OFFICIAL_UNCENSORED_SITES for value in values):
        return values
    expanded: list[str] = []
    for value in values:
        if _is_official_value(value):
            expanded.extend(_OFFICIAL_UNCENSORED_SITES)
        else:
            expanded.append(value)
    return list(dict.fromkeys(expanded))


def _add_uncensored_after_official(sites: list[Any]) -> list[str]:
    """字段优先级里保留 Official，并在其后补五个无码站（已有则不动）。"""
    values = [str(_enum_value(site)) for site in sites]
    if any(value in _OFFICIAL_UNCENSORED_SITES for value in values):
        return values
    expanded: list[str] = []
    for value in values:
        expanded.append(value)
        if _is_official_value(value):
            expanded.extend(_OFFICIAL_UNCENSORED_SITES)
    return list(dict.fromkeys(expanded))


def _migrate_official_uncensored_split(data: dict[str, Any]) -> str | None:
    """旧配置迁移：WUMA 的 Official 拆成五个独立无码站。

    config_version 固定为 2，不能用版本号判断，故用独立标记键。
    只迁移 WUMA：YOUMA 的 Official 仍代表有码官网。
    """
    if data.get("official_uncensored_split_migrated") is True:
        return None

    changed = False

    wuma = data.get("website_wuma")
    if isinstance(wuma, str):
        values = _str_to_list(wuma, ",")
        new_values = _replace_official_with_uncensored(values)
        if new_values != values:
            data["website_wuma"] = new_values
            changed = True
    elif isinstance(wuma, list | set | tuple):
        new_values = _replace_official_with_uncensored(list(wuma))
        if new_values != [str(_enum_value(site)) for site in wuma]:
            data["website_wuma"] = new_values
            changed = True

    if isinstance(field_configs := data.get("field_configs"), dict):
        for value in field_configs.values():
            if not isinstance(value, dict):
                continue
            sites = value.get("site_prority")
            if isinstance(sites, list):
                new_sites = _add_uncensored_after_official(sites)
                if new_sites != [str(_enum_value(site)) for site in sites]:
                    value["site_prority"] = new_sites
                    changed = True

    if isinstance(type_field_configs := data.get("type_field_configs"), dict):
        wuma_fields = type_field_configs.get(FixedScrapingType.WUMA.value)
        if isinstance(wuma_fields, dict):
            for value in wuma_fields.values():
                if not isinstance(value, dict):
                    continue
                sites = value.get("site_prority")
                if isinstance(sites, list):
                    new_sites = _replace_official_with_uncensored(sites)
                    if new_sites != [str(_enum_value(site)) for site in sites]:
                        value["site_prority"] = new_sites
                        changed = True

    disabled = data.get("website_disabled")
    if isinstance(disabled, str):
        disabled_values = _str_to_list(disabled, ",")
        if any(_is_official_value(value) for value in disabled_values):
            data["website_disabled"] = list(dict.fromkeys([*disabled_values, *_OFFICIAL_UNCENSORED_SITES]))
            changed = True
    elif isinstance(disabled, list | set | tuple):
        disabled_values = [str(_enum_value(site)) for site in disabled]
        if any(_is_official_value(value) for value in disabled_values):
            new_values = list(dict.fromkeys([*disabled_values, *_OFFICIAL_UNCENSORED_SITES]))
            if new_values != disabled_values:
                data["website_disabled"] = new_values
                changed = True

    data["official_uncensored_split_migrated"] = True
    if not changed:
        return None
    return "[迁移] Official 五个无码官网已拆成独立站点：WUMA 的 Official 已替换为五个独立站，可分别启用/禁用"


def _migrate_field_config_sites(value: Any) -> None:
    if not isinstance(value, dict):
        return
    sites = value.get("site_prority")
    if isinstance(sites, list):
        value["site_prority"] = _clean_sites(sites)


def _migrate_site_configs(data: dict[str, Any]) -> None:
    """剔除 site_configs 中键为已移除站点的条目（先改名，旧小写键归一化为新值）。"""
    site_configs = data.get("site_configs")
    if not isinstance(site_configs, dict):
        return
    renamed: dict[str, Any] = {}
    for key, value in site_configs.items():
        new_key = _rename_site(str(_enum_value(key)))
        if _is_valid_site(new_key):
            renamed.setdefault(new_key, value)
    data["site_configs"] = renamed


def _migrate_removed_hd_pic_sources(data: dict[str, Any]) -> None:
    valid_values = {HDPicSource.AMAZON.value}
    hd_pics = data.get("download_hd_pics")
    if isinstance(hd_pics, str):
        items: list[Any] = _str_to_list(hd_pics, ",")
    elif isinstance(hd_pics, list | set):
        items = list(hd_pics)
    else:
        return
    data["download_hd_pics"] = [item for item in items if str(_enum_value(item)) in valid_values]


def _migrate_builtin_naming_templates(data: dict[str, Any]) -> None:
    """将旧版内置命名模板迁移为 Jinja2 写法。"""

    mapping = {
        "actor": "{{ actor }}",
        "number actor": "{{ number }} {{ actor }}",
        "number": "{{ number }}",
        "number title": "{{ number }} {{ title }}",
        "[number]title": "[{{ number }}]{% if title and title != number %}{{ title }}{% endif %}",
        "letters/number": "{{ letters }}/{{ number }}",
        "actor/number actor": "{{ actor }}/{{ number }} {{ actor }}",
        "{actor}": "{{ actor }}",
        "{number} {actor}": "{{ number }} {{ actor }}",
        "{number}": "{{ number }}",
        "{number} {title}": "{{ number }} {{ title }}",
        "[{number}]{title}": "[{{ number }}]{% if title and title != number %}{{ title }}{% endif %}",
        "{letters}/{number}": "{{ letters }}/{{ number }}",
        "{actor}/{number} {actor}": "{{ actor }}/{{ number }} {{ actor }}",
    }

    def convert_braced_template(template: str) -> str:
        if "{{" in template or "{%" in template:
            return template

        def replace_field(text: str) -> str:
            return re.sub(r"\{([A-Za-z0-9_]+)\}", r"{{ \1 }}", text)

        while "{?" in template:
            start = template.find("{?")
            colon = template.find(":", start + 2)
            if colon < 0:
                break
            depth = 0
            end = -1
            for index in range(colon + 1, len(template)):
                if template[index] == "{":
                    depth += 1
                elif template[index] == "}":
                    if depth == 0:
                        end = index
                        break
                    depth -= 1
            if end < 0:
                break
            field = template[start + 2 : colon].strip()
            content = replace_field(template[colon + 1 : end])
            optional = f"{{% if {field} %}}{content}{{% endif %}}"
            template = template[:start] + optional + template[end + 1 :]
        return replace_field(template)

    for key in (
        "folder_name",
        "naming_file",
        "naming_media",
        "update_a_folder",
        "update_b_folder",
        "update_c_filetemplate",
        "update_d_folder",
        "update_titletemplate",
    ):
        value = data.get(key)
        if not isinstance(value, str):
            continue
        data[key] = mapping.get(value, convert_braced_template(value))


def _ensure_switch(data: dict[str, Any], value: str) -> None:
    """老配置缺新开关时默认补上（默认勾选语义）。

    switch_on 在 v2 json 里是 list，兼容 str（逗号分隔）形态。
    """
    current = data.get("switch_on")
    if isinstance(current, str):
        items = _str_to_list(current, ",")
        if value not in items:
            items.append(value)
            data["switch_on"] = ",".join(items)
    elif isinstance(current, list | set | tuple):
        values = [str(_enum_value(item)) for item in current]
        if value not in values:
            data["switch_on"] = [*current, value]
    # switch_on 缺失（全新默认配置）时不动：走 pydantic default_factory，本身已默认勾选


def _ensure_switch_exclusive(data: dict[str, Any], keep: str, drop: str) -> None:
    """两个互斥开关同时出现时只保留 keep（老配置升级用）。

    switch_on 在 v2 json 里是 list，兼容 str（逗号分隔）形态。
    """
    current = data.get("switch_on")
    if isinstance(current, str):
        items = _str_to_list(current, ",")
        if keep in items and drop in items:
            data["switch_on"] = ",".join(item for item in items if item != drop)
    elif isinstance(current, list | set | tuple):
        values = [str(_enum_value(item)) for item in current]
        if keep in values and drop in values:
            data["switch_on"] = [item for item in current if str(_enum_value(item)) != drop]


def migrate_config_data(data: dict[str, Any]) -> list[str]:
    """
    统一处理配置结构变更.

    所有可恢复的旧配置差异都应在这里归一化，再交给 Pydantic 做强校验。
    """
    warnings: list[str] = []

    data.pop("google_used", None)
    data.pop("google_exclude", None)
    # 严格校验开关移除（读零校验架构下语义为空）：旧配置残留键静默清洗
    # 注意: 本函数返回的所有消息均为「迁移警告」而非校验错误, 必须带 [迁移] 前缀——
    # load_config 只把无前缀消息视为致命错误并触发 _failed.json 保护分支,
    # 漏加前缀会让正常迁移的用户配置被误判为「读取配置文件出错」且无法切回(议题 #69)。
    if data.pop("amazon_strict_pic_verify", None) is not None:
        warnings.append("[迁移] 已移除配置项「严格校验 Amazon 图片」：ASIN 库命中即信任，软校验仅用于新 ASIN 入库")
    _migrate_builtin_naming_templates(data)
    _migrate_removed_hd_pic_sources(data)
    _migrate_actor_clean_rules(data)
    if message := _migrate_official_uncensored_split(data):
        warnings.append(message)

    single = data.get("website_single")
    if isinstance(single, str):
        renamed_single = _rename_site(str(_enum_value(single)))
        if renamed_single != single:
            data["website_single"] = renamed_single
            single = renamed_single
    if _is_removed_airav_site(single) or not _is_valid_site(single):
        data["website_single"] = Website.AIRAV_CC.value
    for key, value in list(data.items()):
        if key.startswith("website_") and key != "website_single":
            data[key] = _migrate_site_list(value)

    if isinstance(field_configs := data.get("field_configs"), dict):
        for value in field_configs.values():
            _migrate_field_config_sites(value)
    if isinstance(type_field_configs := data.get("type_field_configs"), dict):
        for field_configs in type_field_configs.values():
            if not isinstance(field_configs, dict):
                continue
            for value in field_configs.values():
                _migrate_field_config_sites(value)
    _migrate_site_configs(data)

    if "proxy_type" in data:
        data["use_proxy"] = data["proxy_type"] != "no"
    if isinstance(r := data.get("proxy"), str):
        r = r.strip()
        if all(schema not in r for schema in ["http://", "https://", "socks5://", "socks5h://"]):
            data["proxy"] = "http://" + r
    # 默认 proxy_sites 曾把 seesaawiki.jp 误拼为 seesawiki.jp（mywife 爬虫实际请求域名带双 a），
    # 存量用户配置静默修正（seesaawiki 中不含 seesawiki 子串，replace 不会误伤已正确值）
    if isinstance(ps := data.get("proxy_sites"), str) and "seesawiki" in ps:
        data["proxy_sites"] = ps.replace("seesawiki.jp", "seesaawiki.jp")
    if isinstance(r := data.get("cf_bypass_url"), str):
        r = r.strip().rstrip("/")
        if r and all(schema not in r for schema in ["http://", "https://"]):
            r = "http://" + r
        data["cf_bypass_url"] = r
    if isinstance(r := data.get("cf_bypass_proxy"), str):
        r = r.strip()
        if r and all(schema not in r for schema in ["http://", "https://", "socks4://", "socks5://", "socks5h://"]):
            r = "http://" + r
        data["cf_bypass_proxy"] = r
    if isinstance(r := data.get("cf_bypass_trawl_url"), str):
        r = r.strip().rstrip("/")
        if r and all(schema not in r for schema in ["http://", "https://"]):
            r = "http://" + r
        # 回环 https 降回 http：FlareSolverr/TRAWL 本地实例只 serving 纯 HTTP，
        # 保留 https 会导致适配层与检测全部 TLS 超时（normalize_trawl_url）。
        try:
            from ..utils.cf_url import normalize_trawl_url

            r = normalize_trawl_url(r)
        except Exception:
            pass
        data["cf_bypass_trawl_url"] = r
    if isinstance(r := data.get("cf_bypass_trawl_backend"), str):
        r = r.strip().lower()
        data["cf_bypass_trawl_backend"] = r if r in ("trawl", "flaresolverr") else "trawl"

    if isinstance(r := data.get("use_database"), int):
        data["use_database"] = bool(r)
    if isinstance(r := data.get("local_library"), str):
        data["local_library"] = _str_to_list(r, ",")

    if isinstance(download_files := data.get("download_files"), str):
        data["download_files"] = [
            item
            for value in _str_to_list(download_files, ",")
            if (item := _migrate_download_file_option(value)) is not None
        ]
    elif isinstance(download_files, list | set):
        data["download_files"] = [
            item for value in download_files if (item := _migrate_download_file_option(value)) is not None
        ]

    if isinstance(translate_config := data.get("translate_config"), dict):
        old_prompt = translate_config.pop("llm_prompt", None)
        if isinstance(old_prompt, str):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)
        if isinstance(translate_by := translate_config.get("translate_by"), list):
            translate_config["translate_by"] = [item for item in translate_by if item != "youdao"]
    if isinstance(old_prompt := data.get("llm_prompt"), str):
        translate_config = data.setdefault("translate_config", {})
        if isinstance(translate_config, dict):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)

    if note := _migrate_main_mode(data):
        warnings.append(note)

    # 无限次刮削开关（高级 → 保留任务右侧）：默认勾选，老配置缺键时自动补上
    # 不带 [迁移] 前缀即会被视为致命错误触发 _failed.json 保护分支，故此处静默补齐不告警
    _ensure_switch(data, "infinite_scrape")

    # 视频模式：「删除本地已下载的图片和信息文件」与「移动已下载图片和文件到新目录」
    # 互斥（同一时刻只能选中一个）。老配置只可能有 sort_del；手改配置若两个都勾上，
    # 保留原有的 sort_del（不改变旧行为），去掉新开关 sort_move。
    _ensure_switch_exclusive(data, "sort_del", "sort_move")

    data["config_version"] = CURRENT_CONFIG_VERSION
    return warnings
