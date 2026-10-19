"""软件设置-刮削网站「指定网站」下拉框既要 Official 本行、也要 Official 旗下 5 个无码官网。

用户反馈（两轮，2026-10-18）：

1. 「指定网站」下拉框只有一行笼统的 Official，五个无码官网站点一个都选不到。
2. 补上五个子站行后，Official 本行被一并撤掉，连「整批番号都交给 Official（有码+无码
   自动按番号前缀路由）」这个正常选项也选不到了。

本文件把两处口径钉死，并连带钉住三条不能漂的链路：

1. **五行都在**：站名 = `Official·{spec.studio}`，仍按 `spec` 的 key 排序（10musume / 1pondo /
   caribbeancom / heyzo / pacopacomama，即用户报缺失时的排列），显示文本带「无码：…」定位；
2. **Official 本行保留**（本轮改动）：`comboBox_website_all` 里 Official 值共 6 行（1 本行 +
   5 子站行），本行排在子站行之前；网络页「当前网站」`comboBox_custom_website` 维持原口径
   （本行撤下，只留 5 个子站行）——那里选的是执行刮削的站点，五个子站行都落到 official
   爬虫，同一份能力不必摆两遍；
3. **存取两端仍通**：行的 UserRole 存 `Official`（`save_config` 用 `currentData()` 转枚举、
   `load_config` 用 UserRole 列表反查下标），所以本行与五行任一行都能存进 `website_single`
   并被读回；读回落在本行（子站行都插在本行之后，`list.index` 取第一个 Official）。
"""

import inspect
import re
import sys

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication, QComboBox

from mdcx.config.enums import Website
from mdcx.controllers.main_window.init import (
    _SITE_CHECK_KEY_ROLE,
    _SITE_STATUS_DOT_PX,
    _SITE_URL_EXPLICIT_ROLE,
    _SITE_URL_ROLE,
    Init_Ui,
    _append_official_subsite_rows,
    _populate_site_combo,
    refresh_network_check_badges,
)
from mdcx.crawlers import get_registered_crawler_site_values
from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES

# 用户报缺失时给出的五行顺序（= spec key 排序结果）
_EXPECTED_LABELS = [
    "Official·10Musume",
    "Official·1Pondo",
    "Official·Caribbeancom",
    "Official·HEYZO",
    "Official·Pacopacomama",
]

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _row_values(combo: QComboBox) -> list[str]:
    return [str(combo.itemData(i, Qt.ItemDataRole.UserRole) or "") for i in range(combo.count())]


def _row_texts(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _labels(combo: QComboBox) -> list[str]:
    """行首站名（显示文本第一段，剥掉「（区域标签）」与后续能力文案）。"""
    return [text.split(" ")[0].split("（")[0].strip() for text in _row_texts(combo)]


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _build_combo(*, remove_base_row: bool) -> QComboBox:
    """按 Init_Ui 的真实次序填一个下拉框：先站点清单，再补 Official 五个子行。"""
    box = QComboBox()
    _populate_site_combo(box, sorted(get_registered_crawler_site_values()))
    _append_official_subsite_rows(box, remove_base_row=remove_base_row)
    return box


@pytest.fixture()
def combo(app) -> QComboBox:
    """刮削网站页「指定网站」框：官方本行保留（Init_Ui 传 remove_base_row=False）。"""
    box = _build_combo(remove_base_row=False)
    yield box
    box.deleteLater()


@pytest.fixture()
def network_combo(app) -> QComboBox:
    """网络页「当前网站」框：官方本行撤下，只留五个子站行。"""
    box = _build_combo(remove_base_row=True)
    yield box
    box.deleteLater()


def test_five_official_uncensored_rows_exist_in_single_website_combo(combo):
    labels = _labels(combo)
    for expected in _EXPECTED_LABELS:
        assert expected in labels, f"指定网站下拉缺少 {expected}"
    # 顺序与网络页一致（spec key 排序），五行相邻
    positions = [labels.index(expected) for expected in _EXPECTED_LABELS]
    assert positions == list(range(positions[0], positions[0] + len(_EXPECTED_LABELS)))


def test_each_row_carries_its_own_uncensored_caption(combo):
    texts = _row_texts(combo)
    display = dict(zip(_labels(combo), texts, strict=True))
    # 展示名沿用网络页那份映射（加勒比/一本道/Paco），未列出的原样显示厂牌名
    assert display["Official·Caribbeancom"] == "Official·Caribbeancom 无码：加勒比"
    assert display["Official·1Pondo"] == "Official·1Pondo 无码：一本道"
    assert display["Official·Pacopacomama"] == "Official·Pacopacomama 无码：Paco"
    assert display["Official·HEYZO"] == "Official·HEYZO 无码：HEYZO"
    assert display["Official·10Musume"] == "Official·10Musume 无码：10Musume"


def test_rows_store_official_as_value_with_own_url(combo):
    """UserRole 存 Official（存取两端的 Website 防护不受影响），网址存各自官网地址。"""
    urls = {}
    for i, label in enumerate(_labels(combo)):
        if not label.startswith("Official·"):
            continue
        assert combo.itemData(i, Qt.ItemDataRole.UserRole) == Website.OFFICIAL.value
        assert Website(combo.itemData(i, Qt.ItemDataRole.UserRole)) is Website.OFFICIAL
        urls[label] = str(combo.itemData(i, _SITE_URL_ROLE) or "")
        # 刷新检测徽章时网址不被重算覆盖（否则会被 official 的空地址冲掉）
        assert combo.itemData(i, _SITE_URL_EXPLICIT_ROLE) == urls[label]
    assert urls == {
        f"Official·{spec.studio}": spec.base_url.rstrip("/") + "/" for spec in UNCENSORED_OFFICIAL_SITES.values()
    }


def test_bare_official_row_kept_before_the_five_subsites(combo):
    """本轮改动：指定网站框里 Official 本行要留着，且排在五个子站行之前。"""
    labels = _labels(combo)
    values = _row_values(combo)
    assert values.count(Website.OFFICIAL.value) == 6, "Official 应当由本行 + 五个子行代表"
    assert labels.count(Website.OFFICIAL.value) == 1, "其中不带「·厂牌」的只有本行一行"
    assert labels.index(Website.OFFICIAL.value) < labels.index(_EXPECTED_LABELS[0]), "本行应排在子站行之前"
    # 其它站点一个不多一个不少
    registered = set(get_registered_crawler_site_values()) - {Website.OFFICIAL.value}
    assert set(values) == registered | {Website.OFFICIAL.value}


def test_bare_official_row_still_hidden_in_network_page_combo(network_combo):
    """网络页「当前网站」框维持原口径：五个子站行已经代表 official，本行撤下。"""
    labels = _labels(network_combo)
    assert _row_values(network_combo).count(Website.OFFICIAL.value) == 5, "网络页应恰好由五个子行代表 Official"
    assert not any(label == Website.OFFICIAL.value for label in labels)


def test_selected_row_round_trips_through_website_single(combo):
    """选定本行或任一子行 → 存进 config 的值都是 Official → 读回落回本行。"""
    labels = _labels(combo)
    for i, label in enumerate(labels):
        if label != Website.OFFICIAL.value and not label.startswith("Official·"):
            continue
        combo.setCurrentIndex(i)
        saved = Website(combo.currentData())  # save_config 的写法
        assert saved is Website.OFFICIAL
        assert saved in _row_values(combo), "读回时找不到对应行（会落进 UI 列表之外的兜底分支）"
        index = _row_values(combo).index(saved.value)  # load_config 的写法
        # 子站行都插在本行之后，index() 取到的第一个 Official 即本行
        assert labels[index] == Website.OFFICIAL.value


def test_init_ui_calls_append_official_subsite_rows_for_both_combos():
    """运行期接线：Init_Ui 必须对「指定网站」「当前网站」两框都调，且两处口径不同。

    口径钉死：指定网站传 remove_base_row=False（留 Official 本行），当前网站用默认
    True（撤本行）。写成源码级断言，是防将来有人「顺手统一」两处又改回去。
    """
    calls = re.findall(r"_append_official_subsite_rows\(([^)]*)\)", inspect.getsource(Init_Ui))
    assert len(calls) == 2, f"Init_Ui 应恰好有两处调用，实际 {len(calls)} 处"
    assert "self.Ui.comboBox_website_all" in calls[0], "指定网站框未补 Official 子行"
    assert "remove_base_row=False" in calls[0], "指定网站框应保留 Official 本行"
    assert "self.Ui.comboBox_custom_website" in calls[1], "当前网站框未补 Official 子行"
    assert "remove_base_row" not in calls[1], "当前网站框应撤下 Official 本行（用默认值即可）"


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    """真实主窗口（沿用 tests/test_site_pref_row_order.py 的打桩：关掉启动自检与四个定时器）。"""
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def test_real_main_window_single_website_combo_has_the_five_rows(win):
    """真实主窗口里「指定网站」框确实摆着本行 + 五个子行（上面几项验的是函数层，这里验接线结果）。"""
    box = win.Ui.comboBox_website_all
    labels = _labels(box)
    assert all(expected in labels for expected in _EXPECTED_LABELS), f"实际下拉里缺行：{labels}"
    assert _row_values(box).count("Official") == 6, "指定网站框应保留 Official 本行（1 本行 + 5 子行）"
    # 网络页「当前网站」框同口径列子站行、本行撤下：子站行数量与顺序两边必须一致
    network_combo = win.Ui.comboBox_custom_website
    network_labels = _labels(network_combo)
    assert [label for label in network_labels if label.startswith("Official·")] == [
        label for label in labels if label.startswith("Official·")
    ]
    assert "Official" not in network_labels


# ---- 检测徽标（状态圆点 + 悬停提示）：五个子行各显各的那站 ----
#   用户 2026-10-19 实测「Official·10Musume 等五行的网络检测全部通过，红点却不变」。
#   两层原因各有回归：① 缓存合并（merge_site_check_cache，见 tests/test_network_check.py）
#   把某轮 fail 当成历史值参与比较，后续全绿的轮次翻不回来；② 五个子行共用 Official 的
#   聚合徽标，一站失败五行一起红、用户看不出是哪家。下面这组盯第 ② 层。


def _cache_with_one_bad_subsite() -> dict:
    """五站里只有 HEYZO 不通，其余全绿（HEYZO 挡风控，真实跑测里最常见的那一种）。"""
    cache = {
        "Official": {"status": "fail", "route": "proxy", "checked_at": "2026-10-19T21:00:00"},
    }
    for studio, status in (
        ("10Musume", "ok"),
        ("1Pondo", "ok"),
        ("Caribbeancom", "ok"),
        ("HEYZO", "fail"),
        ("Pacopacomama", "ok"),
    ):
        cache[f"Official·{studio}"] = {"status": status, "route": "proxy", "checked_at": "2026-10-19T21:00:00"}
    return cache


def _install_cache(monkeypatch, cache: dict) -> None:
    """把检测缓存换成给定的内容（真改读端，让 invalidate_check_cache() 后重新读到它）。"""
    import mdcx.controllers.main_window.init as init_mod
    import mdcx.core.network_check as nc_mod

    monkeypatch.setattr(nc_mod, "load_site_check_cache", lambda: dict(cache))
    init_mod.invalidate_check_cache()


def _subsite_rows(combo: QComboBox) -> dict[str, int]:
    """行首站名 → 行下标（只收五个子站行）。"""
    return {label: i for i, label in enumerate(_labels(combo)) if label.startswith("Official·")}


def _dot_rgb(box: QComboBox, row: int) -> tuple[int, ...]:
    """把该行状态圆点图标栅格化后取中心像素的 RGB（空图标返回空元组）。"""
    icon = box.itemIcon(row)
    if icon.isNull():
        return ()
    sizes = icon.availableSizes()
    image = icon.pixmap(sizes[0] if sizes else QSize(_SITE_STATUS_DOT_PX, _SITE_STATUS_DOT_PX)).toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).getRgb()[:3]


_GREEN = (67, 160, 71)
_RED = (229, 57, 53)
_OK_SUBSITES = ("Official·10Musume", "Official·1Pondo", "Official·Caribbeancom", "Official·Pacopacomama")


@pytest.fixture()
def cached_combo(app, monkeypatch) -> QComboBox:
    """带检测缓存的「当前网站」框：五行子站行各带自己的检测键与状态。"""
    _install_cache(monkeypatch, _cache_with_one_bad_subsite())
    return _build_combo(remove_base_row=True)


def test_subsite_rows_carry_own_check_key_equal_to_their_label(cached_combo):
    """检测键必须逐字等于检测报告里那一行的名字（= 行首站名），否则徽标取不到自己那站的结果。"""
    rows = _subsite_rows(cached_combo)
    assert sorted(rows) == sorted(_EXPECTED_LABELS)
    for label, row in rows.items():
        assert cached_combo.itemData(row, _SITE_CHECK_KEY_ROLE) == label
        # UserRole 仍是 Official（选中语义不变），检测键另存角色
        assert cached_combo.itemData(row, Qt.ItemDataRole.UserRole) == Website.OFFICIAL.value


def test_one_bad_subsite_does_not_paint_the_other_four_rows_red(cached_combo):
    """只有 HEYZO 那一行是红点，另外四行必须是绿点（聚合徽标会把五行一起染红）。"""
    rows = _subsite_rows(cached_combo)
    assert _dot_rgb(cached_combo, rows["Official·HEYZO"]) == _RED
    for label in _OK_SUBSITES:
        assert _dot_rgb(cached_combo, rows[label]) == _GREEN, f"{label} 不该跟着 HEYZO 一起变红"


def test_subsite_tooltip_reports_own_site_result(cached_combo):
    """悬停提示同样各报各的：HEYZO 那行写「❌连不通」，其余四行写「✅可连通」。"""
    rows = _subsite_rows(cached_combo)
    tips = {label: str(cached_combo.itemData(row, Qt.ItemDataRole.ToolTipRole) or "") for label, row in rows.items()}
    assert tips["Official·HEYZO"].startswith("上次检测：2026-10-19 21:00")
    assert "❌连不通" in tips["Official·HEYZO"]
    for label in _OK_SUBSITES:
        assert "✅可连通" in tips[label], f"{label} 的提示被 HEYZO 的失败结果污染了：{tips[label]}"


def test_subsite_rows_fall_back_to_official_aggregate_without_sub_keys(app, monkeypatch):
    """缓存里没有子键（旧缓存/自定义过 Official URL）时回退 Official 聚合值，不退回空白圆点。"""
    _install_cache(monkeypatch, {"Official": {"status": "ok", "route": "proxy", "checked_at": "2026-10-19T21:00:00"}})
    box = _build_combo(remove_base_row=True)
    for label, row in _subsite_rows(box).items():
        assert _dot_rgb(box, row) == _GREEN, f"{label} 没有回退到 Official 聚合状态"
        assert "✅可连通" in str(box.itemData(row, Qt.ItemDataRole.ToolTipRole) or "")


def test_refresh_badges_recolors_subsite_rows_per_site(app, monkeypatch):
    """检测完成后刷新徽标：仍按子站行的检测键取色，HEYZO 红、其余绿，不被 Official 聚合值覆盖。"""
    box = _build_combo(remove_base_row=True)
    other = QComboBox()
    _populate_site_combo(other, sorted(get_registered_crawler_site_values()))  # 无子站行的普通框
    win = type("_Win", (), {})()
    win.Ui = type("_Ui", (), {})()
    win.Ui.comboBox_website_all = box
    win.Ui.comboBox_custom_website = box
    win.Ui.comboBox_no_proxy_sites = other

    # 先用「全红」缓存填出五行红点（只有 Official 聚合值，子站行回退到它）
    _install_cache(monkeypatch, {"Official": {"status": "fail", "route": "proxy", "checked_at": "2026-10-19T20:00:00"}})
    refresh_network_check_badges(win)
    assert all(_dot_rgb(box, row) == _RED for row in _subsite_rows(box).values())

    # 刷新成「只有 HEYZO 红」：这正是检测通过后用户看到的那一幕
    _install_cache(monkeypatch, _cache_with_one_bad_subsite())
    refresh_network_check_badges(win)
    rows = _subsite_rows(box)
    assert _dot_rgb(box, rows["Official·HEYZO"]) == _RED
    for label in _OK_SUBSITES:
        assert _dot_rgb(box, rows[label]) == _GREEN, f"{label} 刷新后仍未翻绿"
