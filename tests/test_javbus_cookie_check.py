"""JavBus Cookie 检查必须真正校验登录态（原实现无论填什么都报「连接正常」）。

背景：`_check_javbus_cookie` 原先只认 `lostpasswd`。实测（2026-10-18，`javbus.py::_JAVBUS_DOMAINS`
全部 7 个镜像 × 空/垃圾/伪造 uid 五种 Cookie，共 35 次真实请求）匿名访问 `/FSDSS-660` 返回的
完整详情页里既没有 `lostpasswd`，也没有 `/logout`，只有导航栏写着「登入」+ `action=login`，
头像恒为 `avatar.php?uid=0`。于是该分支永远命中不了：垃圾 Cookie 要么落到
`manager.config.javbus != input_cookie` 被自动写盘并报「✅ 连接正常！Cookie 已保存！」，
要么直接落回初始的「✅ 连接正常！」——这正是用户报的「填什么 Cookie 检测都是正常」。

本文件把三层判定钉死：
1. `classify_javbus_login_state`——登录态分类（含拦截页与未知结构）；
2. `javbus_cookie_verdict`——填了 / 没填 Cookie 两种口径的文案与状态；
3. `_check_javbus_cookie`——**只有确认有效才允许写盘**，其余只告警并保留 Cookie（议题 #130）。
"""

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# ── 实测页面片段（2026-10-18 取自 https://www.javbus.com/FSDSS-660 匿名响应）────────
_ANON_NAVBAR = (
    '<ul class="nav navbar-nav navbar-right" '
    "onclick=\"window.location.href= '/forum/member.php?mod=logging&action=login&referer=%2F%2Fwww.javbus.com%2FFSDSS-660'\">"
    '<li class="dropdown"><a href="#" class="dropdown-toggle">'
    '<img class="avatar" src="https://uc.javbus22.com/uc/avatar.php?uid=0&size=small">'
    '<span class="hidden-md hidden-sm ml5">登入</span></a></li></ul>'
)
_ANON_PAGE = (
    f'<!DOCTYPE html><html><body><nav>{_ANON_NAVBAR}</nav><div class="container">FSDSS-660 详情</div></body></html>'
)
# 登录后：头像带真实 uid、导航栏换成「登出」
_LOGGED_IN_NAVBAR = (
    '<ul class="nav navbar-nav navbar-right">'
    '<li class="dropdown"><a href="#" class="dropdown-toggle">'
    '<img class="avatar" src="https://uc.javbus22.com/uc/avatar.php?uid=4268&size=small">'
    '<span class="hidden-md hidden-sm ml5">javbus_user</span></a>'
    '<li><a href="/forum/member.php?mod=logging&action=logout">登出</a></li></ul>'
)
_LOGGED_IN_PAGE = f'<!DOCTYPE html><html><body><nav>{_LOGGED_IN_NAVBAR}</nav><div class="container">FSDSS-660 详情</div></body></html>'
# 登录墙：整页被换成找回密码表单（crawlers/javbus.py 正是据此判定未登录）
_LOST_PASSWD_PAGE = '<html><body><form action="/lostpasswd"><input name="email"></form></body></html>'
_CF_CHALLENGE_PAGE = "<html><head><title>Just a moment...</title></head><body>cf-chl-widget</body></html>"
_AGE_VERIFY_PAGE = '<html><body><div class="ageVerify"><form><button>我已經成年</button></form></div></body></html>'
# 用户在 Cookie 里伪造 uid 不影响判定：uid 来自服务端渲染，不读 cookie
_FORGED_UID_COOKIE = "uid=99999; username=admin; remember_age=1"


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    # MyMAinWindow.__init__ 里的 Init_Singal 把 exec_save_config 接到
    # pushButton_save_config_clicked，而该方法第一件事就是 manager.save()。测试用的
    # _DummyManager 刻意不实现 save（防用例真写盘，见 tests/test_actor_detail_display.py
    # 的说明），于是 emit 一旦真的走到生产连线就会弹模态「保存配置失败」把用例卡死。
    # 这里断开生产连线，改由各用例自己挂记录器——本文件要验的是「该不该发这个信号」。
    window.exec_save_config.disconnect()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, t).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.fixture()
def saved_cookie(monkeypatch):
    """把已保存的 javbus cookie 钉成固定值，并回传一个读写器。"""
    from mdcx.config.manager import manager

    def _apply(value: str) -> str:
        monkeypatch.setattr(manager.config, "javbus", value, raising=False)
        return value

    return _apply


def _patch_get_text(monkeypatch, html, error=""):
    from mdcx.controllers.main_window import cookie_checks

    monkeypatch.setattr(cookie_checks, "get_text_sync", lambda url, headers=None, **kw: (html, error))


def _patch_get_text_by_url(monkeypatch, pages, default=(None, "没有这个节点")):
    """按 URL 返回不同页面，用来验证「多节点投票」而不是「所有节点同答」。

    `pages` 的 key 用 URL 子串匹配，命中即返回该节点的 (html, error)。
    """
    from mdcx.controllers.main_window import cookie_checks

    def _fake(url, headers=None, **kw):
        for needle, page in pages.items():
            if needle in url:
                return page if isinstance(page, tuple) else (page, "")
        return default

    monkeypatch.setattr(cookie_checks, "get_text_sync", _fake)


def _patch_custom_node(monkeypatch, url):
    """把「软件设置」里自定义的 JavBus 网址钉成 `url`。

    换掉 `cookie_checks.manager` 整个引用而不是给 `manager.config` 打补丁：
    全量跑时 `manager.config` 是真的 pydantic `Config`，而它对未知属性直接
    `__setattr__` 抛 `ValueError: "Config" object has no field "get_site_url"`，
    `monkeypatch.setattr(..., raising=False)` 也拦不住（那参数只作用于 getattr）。
    """
    from types import SimpleNamespace

    from mdcx.controllers.main_window import cookie_checks

    stub = SimpleNamespace(config=SimpleNamespace(get_site_url=lambda *a, **kw: url, javbus=""))
    monkeypatch.setattr(cookie_checks, "manager", stub)


# ── 1. 页面分类 ────────────────────────────────────────────────────────────────


def test_classify_anonymous_page_is_logged_out():
    from mdcx.controllers.main_window.cookie_checks import classify_javbus_login_state

    assert classify_javbus_login_state(_ANON_PAGE) == "logged_out"


def test_classify_logged_in_page():
    from mdcx.controllers.main_window.cookie_checks import classify_javbus_login_state

    assert classify_javbus_login_state(_LOGGED_IN_PAGE) == "logged_in"


@pytest.mark.parametrize(
    "page",
    [_CF_CHALLENGE_PAGE, _AGE_VERIFY_PAGE, "<html><body>redirecting to /doc/driver-verify?referer=x</body></html>"],
)
def test_classify_blocked_pages(page):
    """拦截页既不能证明有效也不能证明无效，须单独归类。"""
    from mdcx.controllers.main_window.cookie_checks import classify_javbus_login_state

    assert classify_javbus_login_state(page) == "blocked"


@pytest.mark.parametrize("page", [None, "", "<html><body>coming soon</body></html>"])
def test_classify_unknown_pages(page):
    from mdcx.controllers.main_window.cookie_checks import classify_javbus_login_state

    assert classify_javbus_login_state(page) == "unknown"


def test_forged_uid_cookie_cannot_fake_login_state():
    """Cookie 里伪造 uid 不作数：uid 由服务端渲染，匿名页永远是 uid=0。"""
    from mdcx.controllers.main_window.cookie_checks import classify_javbus_login_state

    assert "uid=99999" not in _ANON_PAGE  # 前提：匿名页确实没被伪造值污染
    assert classify_javbus_login_state(_ANON_PAGE) == "logged_out"


# ── 2. 判定与文案 ──────────────────────────────────────────────────────────────


def test_verdict_garbage_cookie_reports_invalid():
    """用户报的核心症状：垃圾 Cookie 必须被判无效，而不是「连接正常」。"""
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_verdict

    for junk in ("junk=1", "remember_age=1; PHPSESSID=zzz", _FORGED_UID_COOKIE):
        state, tips = javbus_cookie_verdict(junk, _ANON_PAGE, "")
        assert state == "invalid", f"{junk!r} 应判无效，实得 {state}"
        assert tips.startswith("❌")


def test_verdict_valid_cookie_reports_valid():
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_verdict

    state, tips = javbus_cookie_verdict("PHPSESSID=real", _LOGGED_IN_PAGE, "")
    assert state == "valid"
    assert tips.startswith("✅")


def test_verdict_empty_cookie_asks_whether_node_needs_cookie():
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_verdict

    assert javbus_cookie_verdict("", _LOST_PASSWD_PAGE, "")[0] == "needed"
    assert "需要Cookie" in javbus_cookie_verdict("", _LOST_PASSWD_PAGE, "")[1]
    assert javbus_cookie_verdict("", _ANON_PAGE, "")[0] == "not_needed"


def test_verdict_unreachable_and_blocked_are_distinct():
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_verdict

    assert javbus_cookie_verdict("PHPSESSID=real", None, "连接超时")[0] == "unreachable"
    assert javbus_cookie_verdict("PHPSESSID=real", _CF_CHALLENGE_PAGE, "")[0] == "blocked"


def test_verdict_never_reports_valid_without_cookie():
    """空 Cookie + 已登录页面（会话复用）不得被当成「Cookie 有效」。"""
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_verdict

    state, _ = javbus_cookie_verdict("", _LOGGED_IN_PAGE, "")
    assert state == "not_needed"


# ── 3. 端到端：只有确认有效才写盘 ──────────────────────────────────────────────


def test_garbage_cookie_is_reported_invalid_and_not_saved(win, monkeypatch, saved_cookie):
    saved_cookie("")
    _patch_get_text(monkeypatch, _ANON_PAGE)

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("junk=1")

    assert tips.startswith("❌"), f"垃圾 Cookie 不应报正常，实得 {tips!r}"
    assert "无效" in tips
    assert saves == [], "无效 Cookie 不得触发写盘"


def test_valid_cookie_is_saved(win, monkeypatch, saved_cookie):
    saved_cookie("")
    _patch_get_text(monkeypatch, _LOGGED_IN_PAGE)

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=real")

    assert tips.startswith("✅")
    assert len(saves) == 1, "确认有效的新 Cookie 应保存一次"


def test_unchanged_valid_cookie_is_not_rewritten(win, monkeypatch, saved_cookie):
    saved_cookie("PHPSESSID=real")
    _patch_get_text(monkeypatch, _LOGGED_IN_PAGE)

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=real")

    assert tips.startswith("✅")
    assert saves == [], "与已保存值相同则不应重复写盘"


@pytest.mark.parametrize(
    ("html", "error"),
    [
        (None, "请求超时（120s）"),
        (_CF_CHALLENGE_PAGE, ""),
        ("<html><body>coming soon</body></html>", ""),
    ],
)
def test_non_conclusive_results_keep_cookie_and_never_save(win, monkeypatch, saved_cookie, html, error):
    """不可达 / 被拦截 / 结构不认识：只告警、保留 Cookie、不写盘（议题 #130 口径）。"""
    saved_cookie("")
    _patch_get_text(monkeypatch, html, error)

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=mine")

    assert not tips.startswith("✅"), f"{error or html} 不应报正常，实得 {tips!r}"
    assert saves == []


def test_check_never_saves_lostpasswd_cookie(win, monkeypatch, saved_cookie):
    """登录墙页面 + 已填 Cookie：判无效且不写盘（原稿会走到写盘分支）。"""
    saved_cookie("")
    _patch_get_text(monkeypatch, _LOST_PASSWD_PAGE)

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=mine")

    assert tips.startswith("❌")
    assert saves == []


def test_check_survives_request_exception(win, monkeypatch, saved_cookie):
    """get_text_sync 抛异常不得让界面卡在「检测中」。"""
    from mdcx.controllers.main_window import cookie_checks

    saved_cookie("")

    def boom(url, headers=None, **kwargs):
        raise RuntimeError("炸了")

    monkeypatch.setattr(cookie_checks, "get_text_sync", boom)

    tips = win._check_javbus_cookie("PHPSESSID=mine")

    assert tips.startswith("❌")
    assert "炸了" in tips


# ── 4. 设置页状态徽章与 Cookie 检查同源 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("html", "cookie", "expected"),
    [
        (_LOGGED_IN_PAGE, "PHPSESSID=real", "OK"),
        (_ANON_PAGE, "PHPSESSID=dead", "WARNING"),
        (_ANON_PAGE, "", "OK"),
        (_LOST_PASSWD_PAGE, "", "WARNING"),
    ],
)
def test_network_check_javbus_follows_same_verdict(monkeypatch, html, cookie, expected):
    """core/network_check.py 的 JavBus 站点检测不再对垃圾 Cookie 报「连接正常」。"""
    from mdcx.config.enums import Website
    from mdcx.config.manager import manager
    from mdcx.core.network_check import (
        NetworkCheckSpec,
        NetworkCheckStatus,
        _classify_http_result,
    )

    monkeypatch.setattr(manager.config, "javbus", cookie, raising=False)
    spec = NetworkCheckSpec(
        name="JavBus",
        group="网站",
        url="https://www.javbus.com/FSDSS-660",
        site=Website.JAVBUS,
    )

    status, _ = _classify_http_result(spec, 200, html)

    assert status == NetworkCheckStatus[expected], f"{cookie!r} / {html[:40]!r} 判定为 {status}"


# ── 5. 检测节点：不能打裸 apex，且要多节点投票 ──────────────────────────────────
# 回归背景（2026-10-19）：`_check_javbus_cookie` 原本打的是不带 www 的
# `https://javbus.com`。该地址 301 跳到 www.javbus.com，而 httpx 在跨主机重定向时
# 无条件 `headers.pop("Cookie", None)`，跳转后的请求成了匿名请求——服务端照样返回
# 200 的完整详情页，只是头像恒为 `avatar.php?uid=0`，于是有效的 Cookie 被误报成
# 「❌ Cookie无效或已过期！」。实测：javbus.com → uid=0；
# www.javbus.com / www.dmmsee.casa → uid=678400 且无重定向。
# 2026-10-24 复核：四条线路（javbus.com / dmmsee.casa / javsee.cyou / cdnbus.bond）
# 的裸域仍全部 301 到 www，节点表随之补全为四个 www 入口。


def test_check_urls_default_to_www_nodes_only(monkeypatch):
    """默认节点必须是能把 Cookie 直送到服务器的 www 入口，且不得含裸 apex。"""
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_check_urls

    _patch_custom_node(monkeypatch, "")

    urls = javbus_cookie_check_urls()

    assert urls == [
        "https://www.javbus.com/FSDSS-660",
        "https://www.dmmsee.casa/FSDSS-660",
        "https://www.javsee.cyou/FSDSS-660",
        "https://www.cdnbus.bond/FSDSS-660",
    ]
    assert not any(url.startswith("https://javbus.com/") for url in urls), "裸 apex 会丢 Cookie，不得作为检测节点"


def test_check_urls_prefer_custom_node_and_dedupe(monkeypatch):
    """自定义网址排最前；与默认节点重合时不得重复请求。"""
    from mdcx.controllers.main_window.cookie_checks import javbus_cookie_check_urls

    _patch_custom_node(monkeypatch, "https://www.javbus.com/")

    assert javbus_cookie_check_urls() == [
        "https://www.javbus.com/FSDSS-660",
        "https://www.dmmsee.casa/FSDSS-660",
        "https://www.javsee.cyou/FSDSS-660",
        "https://www.cdnbus.bond/FSDSS-660",
    ]

    _patch_custom_node(monkeypatch, "https://my.mirror.tv")
    assert javbus_cookie_check_urls() == [
        "https://my.mirror.tv/FSDSS-660",
        "https://www.javbus.com/FSDSS-660",
        "https://www.dmmsee.casa/FSDSS-660",
        "https://www.javsee.cyou/FSDSS-660",
        "https://www.cdnbus.bond/FSDSS-660",
    ]


def test_check_falls_back_to_next_node_when_one_says_logged_out(win, monkeypatch, saved_cookie):
    """首个节点掉 Cookie/被拦不代表 Cookie 无效——只要有节点判 valid 就以 valid 为准。"""
    saved_cookie("")
    _patch_custom_node(monkeypatch, "")
    _patch_get_text_by_url(
        monkeypatch,
        {
            "javbus.com": _ANON_PAGE,  # 301 丢 Cookie → 服务端看到匿名用户
            "dmmsee.casa": _LOGGED_IN_PAGE,
        },
    )

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=real")

    assert tips.startswith("✅"), f"有效节点已确认，不应被前一个节点的误报盖掉，实得 {tips!r}"
    assert len(saves) == 1


def test_check_reports_invalid_only_when_every_node_agrees(win, monkeypatch, saved_cookie):
    """所有节点都判未登录时才报无效（此时确实是 Cookie 的问题）。"""
    saved_cookie("")
    _patch_custom_node(monkeypatch, "")
    _patch_get_text_by_url(monkeypatch, {"javbus.com": _ANON_PAGE, "dmmsee.casa": _ANON_PAGE})

    saves = []
    win.exec_save_config.connect(lambda: saves.append(1))

    tips = win._check_javbus_cookie("PHPSESSID=dead")

    assert tips.startswith("❌")
    assert "无效" in tips
    assert saves == []


def test_check_prefers_conclusive_verdict_over_inconclusive_one(win, monkeypatch, saved_cookie):
    """被 CloudFlare 拦 / 结构不认识只能算「判不了」，不能盖过站得住的结论。"""
    saved_cookie("")
    _patch_custom_node(monkeypatch, "")
    _patch_get_text_by_url(monkeypatch, {"javbus.com": _CF_CHALLENGE_PAGE, "dmmsee.casa": _ANON_PAGE})

    win.exec_save_config.connect(lambda: pytest.fail("无效判定不得触发写盘"))

    tips = win._check_javbus_cookie("PHPSESSID=dead")

    assert tips.startswith("❌")
    assert "无效" in tips, f"应取 invalid 而非 intercepted，实得 {tips!r}"
