"""软件设置-刮削网站「指定网站」下拉框里 Official 与五个无码官网各占一行。

历史（2026-10-18）：五个无码官网曾以 `Official·{厂牌}` 的「虚拟子行」补在下拉里，
UserRole 全写 `Official`，靠 `_append_official_subsite_rows` 在填充后二次拼接。
2026-10-20 起五个站成为真实注册站点（各自 `Website` 枚举、各自爬虫类），本文件
据此把这几条链路钉死：

1. **六行都在**：Official 本行 + `Official·10Musume` / `Official·1Pondo` /
   `Official·Caribbeancom` / `Official·HEYZO` / `Official·Pacopacomama`，两两相邻；
2. **身份真实**：每行 UserRole 是本站自己的枚举值，网址各取 `base_url_()`；
   `_SITE_CHECK_KEY_ROLE` 不再需要（检测键就是站点值本身）；
3. **存取两端仍通**：`website_single` 直接存/取对应站点值，选中哪行就落哪行；
4. **徽标各显各的**：缓存以站点值为键，一站红不染另外四站；没有自己那份缓存时
   不回退 Official 聚合值（独立站不该借用别人的检测结果）。
"""

import sys

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication, QComboBox

from mdcx.config.enums import Website
from mdcx.controllers.main_window.init import (
    _SITE_STATUS_DOT_PX,
    _SITE_URL_ROLE,
    Init_Ui,
    _populate_site_combo,
    refresh_network_check_badges,
)
from mdcx.crawlers import get_crawler, get_registered_crawler_site_values
from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES

# 用户报缺失时给出的顺序（与 `_site_types` / A-Z 排序一致）
_OFFICIAL_SUBSITE_VALUES = [
    Website.OFFICIAL_10MUSUME.value,
    Website.OFFICIAL_1PONDO.value,
    Website.OFFICIAL_CARIBBEANCOM.value,
    Website.OFFICIAL_HEYZO.value,
    Website.OFFICIAL_PACOPACOMAMA.value,
]
_EXPECTED_LABELS = [Website.OFFICIAL.value, *_OFFICIAL_SUBSITE_VALUES]

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


def _official_rows(combo: QComboBox) -> dict[str, int]:
    """行首站名 → 行下标（只收 Official 与五个无码站）。"""
    return {label: i for i, label in enumerate(_labels(combo)) if label in _EXPECTED_LABELS}


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _build_combo() -> QComboBox:
    """按 Init_Ui 的真实次序填一个下拉框：全部真实注册站点，无二次拼接。"""
    box = QComboBox()
    _populate_site_combo(box, sorted(get_registered_crawler_site_values()))
    return box


@pytest.fixture()
def combo(app) -> QComboBox:
    """刮削网站页「指定网站」框。"""
    box = _build_combo()
    yield box
    box.deleteLater()


@pytest.fixture()
def network_combo(app) -> QComboBox:
    """网络页「当前网站」框：与指定网站同源填充。"""
    box = _build_combo()
    yield box
    box.deleteLater()


def test_official_and_five_subsites_exist_once_in_combo(combo):
    labels = _labels(combo)
    for expected in _EXPECTED_LABELS:
        assert expected in labels, f"下拉缺少 {expected}"
    # 五站与 Official 相邻，不与其他站交错；每个值全局只出现一次（去掉旧虚拟拼接后不应重复）
    positions = [labels.index(expected) for expected in _EXPECTED_LABELS]
    assert positions == list(range(positions[0], positions[0] + len(_EXPECTED_LABELS)))
    values = _row_values(combo)
    for expected in _EXPECTED_LABELS:
        assert values.count(expected) == 1, f"{expected} 在真实站点下拉里应只出现一次"


def test_each_official_row_carries_its_own_caption(combo):
    texts = dict(zip(_labels(combo), _row_texts(combo), strict=True))
    assert texts[Website.OFFICIAL.value].endswith("官网：有码"), texts[Website.OFFICIAL.value]
    for label in _OFFICIAL_SUBSITE_VALUES:
        assert texts[label].endswith("官网：无码"), texts[label]


def test_rows_store_their_own_site_value_with_own_url(combo):
    """每行 UserRole 是本站枚举值；五个无码站各自带自己的官网地址。"""
    urls = {}
    for i, label in enumerate(_labels(combo)):
        if label not in _EXPECTED_LABELS:
            continue
        value = Website(combo.itemData(i, Qt.ItemDataRole.UserRole))
        assert value.value == label
        if label != Website.OFFICIAL.value:
            urls[label] = str(combo.itemData(i, _SITE_URL_ROLE) or "")
    assert urls == {
        f"Official·{spec.studio}": spec.base_url.rstrip("/") + "/" for spec in UNCENSORED_OFFICIAL_SITES.values()
    }


def test_five_subsites_are_registered_with_own_crawler():
    registered = set(get_registered_crawler_site_values())
    assert set(_EXPECTED_LABELS) <= registered
    from mdcx.crawlers.official_uncensored import (
        Official1PondoCrawler,
        Official10MusumeCrawler,
        OfficialCaribbeancomCrawler,
        OfficialHeyzoCrawler,
        OfficialPacopacomamaCrawler,
    )

    assert get_crawler(Website.OFFICIAL_10MUSUME) is Official10MusumeCrawler
    assert get_crawler(Website.OFFICIAL_1PONDO) is Official1PondoCrawler
    assert get_crawler(Website.OFFICIAL_CARIBBEANCOM) is OfficialCaribbeancomCrawler
    assert get_crawler(Website.OFFICIAL_HEYZO) is OfficialHeyzoCrawler
    assert get_crawler(Website.OFFICIAL_PACOPACOMAMA) is OfficialPacopacomamaCrawler


def test_selected_row_round_trips_through_website_single(combo):
    """选中哪站 → 存进 config 的就是哪站 → 读回仍落在同一行。"""
    labels = _labels(combo)
    for label in _EXPECTED_LABELS:
        index = labels.index(label)
        combo.setCurrentIndex(index)
        saved = Website(combo.currentData())  # save_config 的写法
        assert saved.value == label
        assert saved.value in _row_values(combo), "读回时找不到对应行（会落进 UI 列表之外的兜底分支）"
        assert labels[_row_values(combo).index(saved.value)] == label


def test_init_ui_no_longer_appends_virtual_official_rows():
    """运行期接线：旧虚拟拼接函数已删除，Init_Ui 不再二次插行。"""
    source = __import__("inspect").getsource(Init_Ui)
    assert "_append_official_subsite_rows" not in source
    assert "_OFFICIAL_STUDIO_DISPLAY" not in source


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


def test_real_main_window_both_combos_have_official_and_five_subsites(win):
    """真实主窗口两个站点下拉都直接摆着六个真实条目，且各自只出现一次。"""
    for box in (win.Ui.comboBox_website_all, win.Ui.comboBox_custom_website):
        values = _row_values(box)
        for expected in _EXPECTED_LABELS:
            assert values.count(expected) == 1, f"{expected} 在真实下拉里应只出现一次，实际 {values.count(expected)}"
        labels = _labels(box)
        positions = [labels.index(expected) for expected in _EXPECTED_LABELS]
        assert positions == list(range(positions[0], positions[0] + len(_EXPECTED_LABELS)))


# ---- 检测徽标（状态圆点 + 悬停提示）：六行各显各的那站 ----
#   用户 2026-10-19 实测「Official·10Musume 等五行的网络检测全部通过，红点却不变」。
#   旧实现五行共用 Official 的聚合徽标，一站失败五行一起红；现在每行的键就是本站值。


def _cache_with_one_bad_subsite() -> dict:
    """五站里只有 HEYZO 不通，其余全绿（HEYZO 挡风控，真实跑测里最常见的那一种）。"""
    cache = {
        "Official": {"status": "ok", "route": "proxy", "checked_at": "2026-10-19T21:00:00"},
    }
    for label in _OFFICIAL_SUBSITE_VALUES:
        status = "fail" if label == Website.OFFICIAL_HEYZO.value else "ok"
        cache[label] = {"status": status, "route": "proxy", "checked_at": "2026-10-19T21:00:00"}
    return cache


def _install_cache(monkeypatch, cache: dict) -> None:
    """把检测缓存换成给定的内容（真改读端，让 invalidate_check_cache() 后重新读到它）。"""
    import mdcx.controllers.main_window.init as init_mod
    import mdcx.core.network_check as nc_mod

    monkeypatch.setattr(nc_mod, "load_site_check_cache", lambda: dict(cache))
    init_mod.invalidate_check_cache()


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
_OK_SUBSITES = [label for label in _OFFICIAL_SUBSITE_VALUES if label != Website.OFFICIAL_HEYZO.value]


@pytest.fixture()
def cached_combo(app, monkeypatch) -> QComboBox:
    """带检测缓存的「当前网站」框：六行各带自己那站的检测结果。"""
    _install_cache(monkeypatch, _cache_with_one_bad_subsite())
    return _build_combo()


def test_subsite_rows_take_badge_from_their_own_site_value(cached_combo):
    rows = _official_rows(cached_combo)
    assert sorted(rows) == sorted(_EXPECTED_LABELS)
    assert _dot_rgb(cached_combo, rows[Website.OFFICIAL.value]) == _GREEN
    assert _dot_rgb(cached_combo, rows[Website.OFFICIAL_HEYZO.value]) == _RED
    for label in _OK_SUBSITES:
        assert _dot_rgb(cached_combo, rows[label]) == _GREEN, f"{label} 不该跟着 HEYZO 一起变红"


def test_subsite_tooltip_reports_own_site_result(cached_combo):
    rows = _official_rows(cached_combo)
    tips = {label: str(cached_combo.itemData(row, Qt.ItemDataRole.ToolTipRole) or "") for label, row in rows.items()}
    assert tips[Website.OFFICIAL_HEYZO.value].startswith("上次检测：2026-10-19 21:00")
    assert "❌连不通" in tips[Website.OFFICIAL_HEYZO.value]
    for label in _OK_SUBSITES:
        assert "✅可连通" in tips[label], f"{label} 的提示被 HEYZO 的失败结果污染了：{tips[label]}"


def test_subsites_do_not_fall_back_to_official_aggregate(app, monkeypatch):
    """只有 Official 有缓存时，五个独立站不借它的结果：没有自己那份就保持空白圆点。"""
    _install_cache(monkeypatch, {"Official": {"status": "ok", "route": "proxy", "checked_at": "2026-10-19T21:00:00"}})
    box = _build_combo()
    rows = _official_rows(box)
    assert _dot_rgb(box, rows[Website.OFFICIAL.value]) == _GREEN
    for label in _OFFICIAL_SUBSITE_VALUES:
        assert box.itemIcon(rows[label]).isNull(), f"{label} 不应回退 Official 聚合状态"


def test_refresh_badges_recolors_each_site_independently(app, monkeypatch):
    """检测完成后刷新徽标：按各站自己的键取色，HEYZO 红、其余绿，不被 Official 聚合值覆盖。"""
    box = _build_combo()
    other = QComboBox()
    _populate_site_combo(other, sorted(get_registered_crawler_site_values()))
    win = type("_Win", (), {})()
    win.Ui = type("_Ui", (), {})()
    win.Ui.comboBox_website_all = box
    win.Ui.comboBox_custom_website = box
    win.Ui.comboBox_no_proxy_sites = other

    # 先用「全红」缓存填出六行红点
    all_red = {
        Website.OFFICIAL.value: {"status": "fail", "route": "proxy", "checked_at": "2026-10-19T20:00:00"},
        **{
            label: {"status": "fail", "route": "proxy", "checked_at": "2026-10-19T20:00:00"}
            for label in _OFFICIAL_SUBSITE_VALUES
        },
    }
    _install_cache(monkeypatch, all_red)
    refresh_network_check_badges(win)
    assert all(_dot_rgb(box, row) == _RED for row in _official_rows(box).values())

    # 刷新成「只有 HEYZO 红」：这正是检测通过后用户看到的那一幕
    _install_cache(monkeypatch, _cache_with_one_bad_subsite())
    refresh_network_check_badges(win)
    rows = _official_rows(box)
    assert _dot_rgb(box, rows[Website.OFFICIAL.value]) == _GREEN
    assert _dot_rgb(box, rows[Website.OFFICIAL_HEYZO.value]) == _RED
    for label in _OK_SUBSITES:
        assert _dot_rgb(box, rows[label]) == _GREEN, f"{label} 刷新后仍未翻绿"
