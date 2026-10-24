"""FC2PPVDB / JavBus / JavDB 的 Cookie 登录态检测。

从 `main_window.py` 按集群切出。FC2PPVDB 部分逻辑与文案逐字不变；
JavBus 部分按 2026-10-18 的实网实测重做了登录态判定（见下方 `classify_javbus_login_state`），
并在 2026-10-19 修掉了「有效 Cookie 被误报无效」——根因是检测打的是不带 www 的裸 apex，
跨主机 301 时 httpx 会丢掉请求头里的 Cookie（见 `_JAVBUS_COOKIE_CHECK_BASES` 注释）。
JavDB 部分在 2026-10-24 按同一思路重做（见 `classify_javdb_login_state`）：官方换到
javdb580.com 后，详情页对未登录访问一律 302 到 /login，旧判定只认 `/logout`，
再加上自定义网址里残留的 `www.javdb580.com` 是空壳域名，检测便永远失败。
"""

import re
import threading
import traceback

from mdcx.base.web_sync import get_text_sync
from mdcx.config.enums import Website
from mdcx.config.manager import manager
from mdcx.crawlers.fc2ppvdb import (
    FC2CMADB_BASE_URL,
    cookie_has_login_key,
    cookie_str_to_dict,
    fetch_article_info_with_warmup,
)
from mdcx.log_console import with_site_prefix
from mdcx.signals import signal_qt
from mdcx.utils import executor
from mdcx.utils.site_url import without_www

# ── JavBus 登录态判定 ────────────────────────────────────────────────────────
# 实测（2026-10-18，`javbus.py::_JAVBUS_DOMAINS` 全部 7 个镜像 × 空/垃圾/伪造 uid 五种 Cookie，
# 共 35 次真实请求）：未登录时导航栏头像恒为 `avatar.php?uid=0`，并带「登入」+ `action=login`；
# `/logout`、`/favorite`、`/history` 在这批部署上一律 404（两个镜像群已不实现这些路由），
# 故它们**不能**当登录态信号——原先只判 `lostpasswd` 的写法因此永远命中不了，
# 任何 Cookie 都会落到「✅ 连接正常」甚至被自动写盘。以头像 uid 为准、登出文案为辅。
_JAVBUS_AVATAR_UID = re.compile(r"avatar\.php\?uid=(-?\d+)")
_JAVBUS_LOGGED_IN_MARKERS = ("登出", "action=logout", "/logout")
_JAVBUS_LOGGED_OUT_MARKERS = ("登入", "action=login", "lostpasswd")
# CloudFlare 挑战页 / 年龄验证闸门 / 浏览器验证页：拿到它们既证明不了有效也证明不了无效
_JAVBUS_BLOCKED_MARKERS = (
    "just a moment",
    "cf-chl-",
    "checking your browser",
    "cf-browser-verification",
    "driver-verify",
    "ageverify",
    "我已經成年",
    "我已经成年",
)

# ── JavBus 检测节点 ───────────────────────────────────────────────────────────
# 域名「带不带 www」直接决定登录态能不能判出来。裸 apex（https://javbus.com）会 301
# 跳到 www.javbus.com，而 httpx 在跨主机重定向时无条件丢掉请求头里的 Cookie
# （`Client._redirect_headers` 里的 `headers.pop("Cookie", None)`，注释写明
# 「用 client 的 cookie jar 决定 Cookie 头，而不是沿用原始请求上的」）。于是跳转后
# 的请求成了匿名请求：服务端照样返回 200 的完整详情页，只是头像恒为
# `avatar.php?uid=0`，判定遂落到「❌ Cookie无效或已过期！」——而用户填的
# Cookie 其实完全有效，站点只是从头到尾没收到它。
# 2026-10-19 实测（真实 Cookie + 代理）：javbus.com → uid=0；
# www.javbus.com 与 www.dmmsee.casa → uid=678400，且均无重定向。
# 故这里只列 Cookie 能直达到位的入口域名。
# 2026-10-24 复核：四个线路的裸域仍全部 301 到 www（javbus.com / dmmsee.casa /
# javsee.cyou / cdnbus.bond），第二条兜底地址原先写成了 `www.dmmbus.casa`（与
# javbus.py 声明的镜像 `dmmsee.casa` 不是同一个域名），一并改回 `www.dmmsee.casa`。
_JAVBUS_COOKIE_CHECK_BASES = (
    "https://www.javbus.com",
    "https://www.dmmsee.casa",
    "https://www.javsee.cyou",
    "https://www.cdnbus.bond",
)
_JAVBUS_CHECK_PATH = "/FSDSS-660"
# 单个节点给不出定论 ≠ Cookie 有问题（301 丢 Cookie、CloudFlare 拦、节点已挂都会
# 让某一个域名误报），所以所有候选节点都投一票，取可信度最高的那一票。
# 排序：能证明登录态的（valid/invalid）压过「证明不了」的（blocked/unreachable/unknown）；
# 未填 Cookie 时「需要 Cookie」压过「无需 Cookie」。
_JAVBUS_VERDICT_RANK = {
    "valid": 6,
    "invalid": 5,
    "needed": 4,
    "not_needed": 3,
    "blocked": 2,
    "unreachable": 1,
    "unknown": 0,
}


def _has_marker(html: str, markers: tuple[str, ...]) -> bool:
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in markers)


def classify_javbus_login_state(html: str | None) -> str:
    """把 JavBus 页面归类为 logged_in / logged_out / blocked / unknown。"""
    if not html:
        return "unknown"
    if _has_marker(html, _JAVBUS_BLOCKED_MARKERS):
        return "blocked"
    uids = [uid.strip() for uid in _JAVBUS_AVATAR_UID.findall(html)]
    if any(uid and int(uid) != 0 for uid in uids):
        return "logged_in"  # 头像带真实 uid，最硬的登录态证据
    logged_in = _has_marker(html, _JAVBUS_LOGGED_IN_MARKERS)
    logged_out = _has_marker(html, _JAVBUS_LOGGED_OUT_MARKERS)
    if logged_in and not logged_out:
        return "logged_in"
    if logged_out and not logged_in:
        return "logged_out"
    if uids:
        return "logged_out"  # uid 全为 0，同样是确凿的未登录
    return "unknown"


def javbus_cookie_verdict(input_cookie: str, html: str | None, error: str | None) -> tuple[str, str]:
    """判定 JavBus Cookie，返回 (状态, 提示文案)。

    状态：valid / invalid / not_needed / needed / blocked / unreachable / unknown。
    只有 valid 允许写盘，其余一律只告警并保留用户填的 Cookie（沿用议题 #130 的口径）。
    """
    cookie = (input_cookie or "").strip()
    if not html:
        return "unreachable", f"❌ 连接失败！请检查网络或代理设置！ {error or ''}".rstrip()
    state = classify_javbus_login_state(html)
    if state == "blocked":
        return "blocked", "⚠️ 被CloudFlare或年龄验证拦截，无法判定Cookie有效性（已保留，可稍后重试）"
    if not cookie:
        # 没填 Cookie 时只回答「这个节点要不要 Cookie」，不报「无效」
        if "lostpasswd" in html.lower():
            return "needed", "❌ 当前节点需要Cookie才能刮削！请填写Cookie或更换节点！"
        return "not_needed", "✅ 当前节点无需Cookie即可刮削，可留空！"
    if state == "logged_in":
        return "valid", "✅ 连接正常！"
    if state == "logged_out":
        return "invalid", "❌ Cookie无效或已过期！（已保留，可手动替换）"
    return "unknown", "⚠️ 未识别页面结构，无法判定Cookie有效性（已保留，可手动替换）"


def javbus_cookie_check_urls() -> list[str]:
    """JavBus Cookie 检测要依次尝试的地址（用户在网站设置里自定义了则排最前，已去重）。

    逐个试而不是只打一个，是因为单个节点说「无效」并不能证明 Cookie 无效。
    """
    bases: list[str] = []
    for candidate in (manager.config.get_site_url(Website.JAVBUS, ""), *_JAVBUS_COOKIE_CHECK_BASES):
        base = str(candidate or "").strip().rstrip("/")
        if base and base not in bases:
            bases.append(base)
    return [base + _JAVBUS_CHECK_PATH for base in bases]


def javbus_cookie_verdict_sync(input_cookie: str) -> tuple[str, str]:
    """逐节点实测 JavBus Cookie，返回 (状态, 文案)。

    任一节点判 valid 即立刻收工；否则走完全部候选，取可信度最高的一票。
    """
    headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
    best_state, best_tips = "", ""
    for url in javbus_cookie_check_urls():
        try:
            html, error = get_text_sync(url, headers=headers)
        except Exception as e:
            signal_qt.show_traceback_log(traceback.format_exc())
            html, error = None, str(e)
        state, tips = javbus_cookie_verdict(input_cookie, html, error)
        if _JAVBUS_VERDICT_RANK.get(state, 0) > _JAVBUS_VERDICT_RANK.get(best_state, -1):
            best_state, best_tips = state, tips
        if state == "valid":
            break
    return best_state, best_tips


# ── JavDB 登录态判定 ────────────────────────────────────────────────────────
# 实测（2026-10-24，javdb580.com，真实 Cookie + 代理）：
# - 未登录 / Cookie 失效：`/v/{id}` 一律 302 到 `/login`，最终页是登录表单
#   `<form action="/user_sessions">`，页头只剩「注冊 / 登入」；
# - 有效 Cookie：`/v/{id}` 直接 200 详情页，含 `current-title` / `video-cover` / `/logout`；
# - `www.javdb580.com` 是空壳域名（200 + 1 字节换行），任何判定都拿不到内容。
# 旧实现只认 `/logout`，命中不了就报「未检测到登录态」——官方换域名后用户的自定义
# 网址里还留着 `www.javdb580.com`，于是有效 Cookie 也一直判失败。
_JAVDB_CHECK_PATH = "/v/D16Q5?locale=zh"
_JAVDB_COOKIE_CHECK_BASES = (
    "https://javdb580.com",
    "https://javdb.com",
)
_JAVDB_LOGIN_FORM_MARKERS = ('action="/user_sessions"', "action='/user_sessions'")
_JAVDB_DETAIL_MARKERS = ("current-title", "video-cover", "copy-to-clipboard")
_JAVDB_LOGGED_IN_MARKERS = ("/logout", "登出")
_JAVDB_LOGGED_OUT_MARKERS = ('href="/login"', "href='/login'", 'href="/users/new"', "登入")
_JAVDB_BLOCKED_MARKERS = (
    "just a moment",
    "cf-chl-",
    "checking your browser",
    "cf-browser-verification",
    "ray-id",
)
# 空壳页（`www.javdb580.com` 只回 1 字节换行）既证明不了有效也证明不了无效
_BLANK_PAGE_MIN_CHARS = 64
_JAVDB_VERDICT_RANK = {
    "valid": 7,
    "banned": 6,
    "region": 6,
    "invalid": 5,
    "needed": 4,
    "not_needed": 3,
    "blocked": 2,
    "unreachable": 1,
    "unknown": 0,
}


def classify_javdb_login_state(html: str | None) -> str:
    """把 JavDB 页面归类为 logged_in / logged_out / blocked / unknown。"""
    if not html or len(html.strip()) < _BLANK_PAGE_MIN_CHARS:
        return "unknown"
    if _has_marker(html, _JAVDB_BLOCKED_MARKERS):
        return "blocked"
    # 详情页能渲染出来，说明这次请求带着有效会话（官网对未登录访问只会跳登录页）
    if _has_marker(html, _JAVDB_DETAIL_MARKERS):
        return "logged_in"
    if _has_marker(html, _JAVDB_LOGIN_FORM_MARKERS):
        return "logged_out"
    if _has_marker(html, _JAVDB_LOGGED_IN_MARKERS):
        return "logged_in"
    if _has_marker(html, _JAVDB_LOGGED_OUT_MARKERS):
        return "logged_out"
    return "unknown"


def javdb_cookie_verdict(input_cookie: str, html: str | None, error: str | None) -> tuple[str, str]:
    """判定 JavDB Cookie，返回 (状态, 提示文案)。

    状态：valid / invalid / banned / region / blocked / needed / unreachable / unknown。
    只有 valid 允许写盘，其余一律只告警并保留用户填的 Cookie（沿用议题 #130 的口径）。
    """
    cookie = (input_cookie or "").strip()
    if not html or len(html.strip()) < _BLANK_PAGE_MIN_CHARS:
        detail = f" {error}" if error else ""
        return "unreachable", f"❌ 连接失败或页面为空！请检查网络或代理设置！{detail}".rstrip()
    if "The owner of this website has banned your access" in html:
        ip_list = re.findall(r"(\d+\.\d+\.\d+\.\d+)", html)
        ip_text = f"{ip_list[0]} " if ip_list else ""
        return "banned", f"❌ 你的 IP {ip_text}被 JavDb 封了！"
    if "Due to copyright restrictions" in html or "Access denied" in html:
        return "region", "❌ 当前 IP 被禁止访问！请使用非日本节点！"
    state = classify_javdb_login_state(html)
    if state == "blocked":
        return "blocked", "⚠️ 被CloudFlare拦截，无法判定Cookie有效性（已保留，可稍后重试）"
    if not cookie:
        return "needed", "❌ 当前官网需要Cookie才能刮削！请填写Cookie！"
    if state == "logged_in":
        return "valid", "✅ 连接正常！"
    if state == "logged_out":
        return "invalid", "❌ Cookie无效或已过期！（已保留，可手动替换）"
    return "unknown", "⚠️ 未识别页面结构，无法判定Cookie有效性（已保留，可手动替换）"


def javdb_cookie_check_urls() -> list[str]:
    """JavDB Cookie 检测要依次尝试的地址（自定义网址在前，自动补去 www 变体与官方默认）。

    自定义网址里残留的 `www.javdb580.com` 是空壳域名，必须能回退到 `javdb580.com`。
    """
    bases: list[str] = []
    configured = str(manager.config.get_site_url(Website.JAVDB, "") or "").strip().rstrip("/")
    for candidate in (configured, without_www(configured), *_JAVDB_COOKIE_CHECK_BASES):
        base = str(candidate or "").strip().rstrip("/")
        if base and base not in bases:
            bases.append(base)
    return [base + _JAVDB_CHECK_PATH for base in bases]


def javdb_cookie_verdict_sync(input_cookie: str) -> tuple[str, str, str]:
    """逐节点实测 JavDB Cookie，返回 (状态, 文案, 命中页面 HTML)。

    任一节点判 valid 即立刻收工；否则走完全部候选，取可信度最高的一票。
    第三个返回值供调用方判断 VIP 图标（沿用原 `_check_javdb_cookie` 的展示口径）。
    """
    headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
    best_state, best_tips, best_html = "", "", ""
    for url in javdb_cookie_check_urls():
        try:
            html, error = get_text_sync(url, headers=headers)
        except Exception as e:
            signal_qt.show_traceback_log(traceback.format_exc())
            html, error = None, str(e)
        state, tips = javdb_cookie_verdict(input_cookie, html, error)
        if _JAVDB_VERDICT_RANK.get(state, 0) > _JAVDB_VERDICT_RANK.get(best_state, -1):
            best_state, best_tips, best_html = state, tips, html or ""
        if state == "valid":
            break
    return best_state, best_tips, best_html


class CookieChecksMixin:
    # endregion
    def pushButton_check_fc2ppvdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText().strip()
        if not input_cookie:
            self.set_fc2ppvdb_status.emit("❌ 未填写Cookie")
            self.show_log_text("❌ FC2PPVDB 未填写Cookie，可在「软件设置」-「网络」添加！")
            return
        self.set_fc2ppvdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_fc2ppvdb_cookie, args=(input_cookie,), daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_fc2ppvdb_cookie(self, input_cookie: str):
        input_cookie = (input_cookie or "").strip()
        tips = "❌ 未填写Cookie"
        if not input_cookie:
            self.set_fc2ppvdb_status.emit(tips)
            return tips

        if not cookie_has_login_key(input_cookie):
            tips = "❌ Cookie无效！请粘贴fc2cmadb.com登录后的完整Cookie（含XSRF-TOKEN与Session项）"
        else:
            cookies = cookie_str_to_dict(input_cookie)
            with manager.acquire_computed() as computed:
                response, error = executor.run(
                    fetch_article_info_with_warmup(
                        computed.async_client,
                        base_url=FC2CMADB_BASE_URL,
                        number="4988506",
                        cookies=cookies,
                        use_proxy=manager.config.use_proxy,
                    )
                )
            if response is None:
                tips = f"❌ Cookie 检查失败：{error}"
            elif not response.get("article"):
                tips = "❌ Cookie 检查失败：返回数据异常"
            elif not response.get("actresses") and not response.get("article", {}).get("actresses"):
                tips = "⚠️ Cookie 连通但未获取到演员数据，请确认已登录 fc2cmadb.com"
                if manager.config.fc2ppvdb != input_cookie:
                    self.exec_save_config.emit()
            elif manager.config.fc2ppvdb != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常，Cookie 已保存！"
            else:
                tips = "✅ 连接正常！"

        self.set_fc2ppvdb_status.emit(tips)
        self.show_log_text(with_site_prefix(tips, "FC2PPVDB"))
        return tips

    # javbus cookie
    def pushButton_check_javbus_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javbus.toPlainText().strip()
        self.set_javbus_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javbus_cookie, args=(input_cookie,), daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.show_log_text(traceback.format_exc())

    def _check_javbus_cookie(self, input_cookie: str):
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(False)
        input_cookie = (input_cookie or "").strip()

        try:
            state, tips = javbus_cookie_verdict_sync(input_cookie)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            state, tips = "unreachable", "❌ 连接失败！请检查网络或代理设置！"

        # 只有真正验证到登录态才写盘：无效 / 被拦截 / 判定不了时一律只告警并保留用户填的 Cookie
        if state == "valid" and manager.config.javbus != input_cookie:
            self.exec_save_config.emit()
            tips = "✅ 连接正常，Cookie 已保存！"

        self.show_log_text(with_site_prefix(tips, "JavBus"))
        self.set_javbus_status.emit(tips)
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(True)
        return tips
