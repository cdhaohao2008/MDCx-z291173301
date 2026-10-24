"""自定义网址的保存格式与界面展示回归测试。

用户诉求（2026-10-24）：设置页「自定义网址」只展示真正改过的网址，格式统一为
`https://javdb580.com/`；没改过的站点保持空白。保存后再次读取配置也必须能显示出来。
同一轮追加：裸域名自动补 `www.`、重复 www 不叠加、格式不合要求不保存、
与站点默认地址相同的输入按「没自定义」处理（不写配置、输入框也不显示）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit

from mdcx.config.enums import Website
from mdcx.config.manager import manager
from mdcx.config.models import (
    Config,
    SiteConfig,
    normalize_custom_url,
    resolve_custom_url,
    site_default_url,
)
from mdcx.controllers.main_window.init import _resolve_site_url
from mdcx.controllers.main_window.settings_actions import SettingsActionsMixin

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 不自动补 www（用户 2026-10-24：加了 www 有些站点反而打不开），host 按填的来
        ("javdb580.com", "https://javdb580.com"),
        ("javdb580.com/", "https://javdb580.com"),
        ("www.javdb580.com", "https://www.javdb580.com"),
        ("https://javdb580.com/", "https://javdb580.com"),
        (" https://javdb580.com/ ", "https://javdb580.com"),
        # 误写两个 www 收成一个
        ("https://www.www.javdb580.com/", "https://www.javdb580.com"),
        # 带路径：保留路径、不留尾斜杠
        ("https://example.com/cn/", "https://example.com/cn"),
        # 子域名、IP、带端口的地址原样保留
        ("api.example.com", "https://api.example.com"),
        ("192.168.1.5:8080", "https://192.168.1.5:8080"),
        ("http://www.javbus.com/", "http://www.javbus.com"),
        # 空值 = 清除
        ("", ""),
        ("   ", ""),
        # 格式不合基本网址要求：一律不通过
        ("javdb", ""),
        ("not a url", ""),
        ("https://", ""),
        ("ftp://javdb.com", ""),
        ("https://javdb.com:99999", ""),
        ("https://-bad-.com", ""),
        ("https://user:pass@javdb.com", ""),
    ],
)
def test_normalize_custom_url(raw: str, expected: str):
    assert normalize_custom_url(raw) == expected


def test_resolve_custom_url_ignores_default_address():
    """填的就是站点默认地址时按「没自定义」处理（只差一个 www 也算同一个站）。"""
    default = "https://javbus.com"
    assert resolve_custom_url("https://javbus.com/", default) == ""
    assert resolve_custom_url("javbus.com", default) == ""
    assert resolve_custom_url("https://www.javbus.com/", default) == ""
    assert resolve_custom_url("https://javbus.com/other", default) == "https://javbus.com/other"
    assert resolve_custom_url("", default) == ""
    assert resolve_custom_url("javdb580.com", "") == "https://javdb580.com"

    # 默认地址本身没有 www（JavDB 就是 javdb.com）：补出来的 www 视为同一个站
    assert resolve_custom_url("javdb.com", "https://javdb.com") == ""
    assert resolve_custom_url("www.javdb.com", "https://javdb.com") == ""
    # 换的是另一个域名，照旧保存
    assert resolve_custom_url("javdb580.com", "https://javdb.com") == "https://javdb580.com"


def test_site_default_url_ignores_configured_custom_url(monkeypatch: pytest.MonkeyPatch):
    """取站点默认地址时不受当前自定义网址影响，取完不改变配置。"""
    config = Config()
    config.site_configs[Website.JAVBUS] = SiteConfig(custom_url="https://my-javbus.example/")
    monkeypatch.setattr(manager, "config", config)

    assert site_default_url(Website.JAVBUS) == "https://javbus.com"
    # 临时置空后必须原样还原，否则用户的自定义网址会被这次判断吃掉
    assert config.get_site_url(Website.JAVBUS) == "https://my-javbus.example"


def test_custom_url_display_only_when_modified():
    config = Config()

    # 没改过的站点不显示默认地址，输入框保持空白
    assert config.get_site_url_display(Website.JAVDB) == ""

    # 改过的站点按统一格式展示：结尾带斜杠
    config.site_configs[Website.JAVDB] = SiteConfig(custom_url="https://javdb580.com/")
    assert config.get_site_url_display(Website.JAVDB) == "https://javdb580.com/"

    # 带路径的自定义网址同样只补结尾斜杠，不丢路径
    config.site_configs[Website.JAVLIBRARY] = SiteConfig(custom_url="https://www.f101w.com/cn/")
    assert config.get_site_url_display(Website.JAVLIBRARY) == "https://www.f101w.com/cn/"

    # 带查询串的网址：斜杠只补在 path 上，不会拼到 query 后面
    config.site_configs[Website.JAVBUS] = SiteConfig(custom_url="https://javbus.example/?lang=zh")
    assert config.get_site_url_display(Website.JAVBUS) == "https://javbus.example/?lang=zh"


def test_custom_url_survives_config_roundtrip():
    """保存到配置文件的网址再读回来仍要显示（重启软件后也不能丢）。"""
    config = Config()
    config.site_configs[Website.JAVDB] = SiteConfig(custom_url="https://javdb580.com/")

    restored = Config.model_validate_json(config.model_dump_json())

    assert restored.get_site_url_display(Website.JAVDB) == "https://javdb580.com/"
    # 刮削用的是无尾斜杠形式（爬虫 base_url 约定）
    assert restored.get_site_url(Website.JAVDB) == "https://javdb580.com"
    # 没配置过的站点依旧空白，不会被默认地址顶上来
    assert restored.get_site_url_display(Website.JAVBUS) == ""


def test_switch_site_shows_only_modified_custom_url(monkeypatch: pytest.MonkeyPatch):
    """切换「当前网站」下拉：改过网址的站点回显自定义地址，没改过的保持空白。"""
    _ensure_app()
    config = Config()
    config.site_configs[Website.JAVDB] = SiteConfig(custom_url="https://javdb580.com/")
    monkeypatch.setattr(manager, "config", config)

    ui = SimpleNamespace(lineEdit_site_custom_url=QLineEdit())
    window = SimpleNamespace(Ui=ui)

    SettingsActionsMixin.switch_custom_website_change(window, "JavDB（综合） 综合：有码/无码/欧美/传媒")
    assert ui.lineEdit_site_custom_url.text() == "https://javdb580.com/"

    SettingsActionsMixin.switch_custom_website_change(window, "JavBus（综合） 综合：有码/无码")
    assert ui.lineEdit_site_custom_url.text() == ""


def test_site_combo_url_follows_custom_url(monkeypatch: pytest.MonkeyPatch):
    """下拉框右侧「当前网址」列跟着自定义网址走（保存后刷新用的就是这个解析）。"""
    _ensure_app()
    config = Config()
    config.site_configs[Website.JAVDB] = SiteConfig(custom_url="https://javdb580.com/")
    monkeypatch.setattr(manager, "config", config)

    assert _resolve_site_url("JavDB") == "https://javdb580.com/"
    # 没改过的站点仍显示自己的默认地址
    assert _resolve_site_url("JavBus") == "https://javbus.com/"


def test_remember_and_restore_custom_website(monkeypatch: pytest.MonkeyPatch):
    """「当前网站」记住上次实际使用的站点：下次打开、展开下拉都停在这一项。"""
    _ensure_app()
    from PyQt6.QtWidgets import QComboBox

    from mdcx.controllers.main_window import init as init_mod

    config = Config()
    monkeypatch.setattr(manager, "config", config)
    init_mod.clear_custom_website_dirty()

    combo = QComboBox()
    for value in ("7mmtv", "MGStage", "JavDB"):
        combo.addItem(value, value)

    init_mod._remember_custom_website("MGStage")
    assert config.last_custom_website == "MGStage"
    assert init_mod.custom_website_dirty() is True

    # 非法站点值不记
    init_mod._remember_custom_website("不存在的站点")
    assert config.last_custom_website == "MGStage"

    combo.setCurrentIndex(0)
    init_mod._restore_custom_website_selection(combo)
    assert combo.currentIndex() == 1

    # 记进配置后能跟着配置文件往返（下次打开还在）
    restored = Config.model_validate_json(config.model_dump_json())
    assert restored.last_custom_website == "MGStage"


def test_switch_custom_website_remembers_selection(monkeypatch: pytest.MonkeyPatch):
    """在下拉里切换站点就算「实际使用」，要记下来。"""
    _ensure_app()
    from mdcx.controllers.main_window import init as init_mod

    config = Config()
    monkeypatch.setattr(manager, "config", config)
    init_mod.clear_custom_website_dirty()

    ui = SimpleNamespace(lineEdit_site_custom_url=QLineEdit())
    window = SimpleNamespace(Ui=ui)

    SettingsActionsMixin.switch_custom_website_change(window, "JavDB（综合） 综合：有码/无码/欧美/传媒")
    assert config.last_custom_website == "JavDB"
