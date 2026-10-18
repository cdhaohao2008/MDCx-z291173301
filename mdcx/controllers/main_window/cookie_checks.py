"""FC2PPVDB / JavBus 的 Cookie 登录态检测。

从 `main_window.py` 按集群切出。FC2PPVDB 部分逻辑与文案逐字不变；
JavBus 部分按 2026-10-18 的实网实测重做了登录态判定（见下方 `classify_javbus_login_state`）。"""

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
from mdcx.signals import signal_qt
from mdcx.utils import executor

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
        return "valid", "✅ 连接正常，Cookie有效！"
    if state == "logged_out":
        return "invalid", "❌ Cookie无效或已过期！（已保留，可手动替换）"
    return "unknown", "⚠️ 未识别页面结构，无法判定Cookie有效性（已保留，可手动替换）"


class CookieChecksMixin:
    # endregion
    def pushButton_check_fc2ppvdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText().strip()
        if not input_cookie:
            self.set_fc2ppvdb_status.emit("❌ 未填写Cookie")
            self.show_log_text(" ❌ FC2PPVDB 未填写Cookie，可在「软件设置」-「网络」添加！")
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
        self.show_log_text(tips.replace("❌", " ❌ FC2PPVDB").replace("✅", " ✅ FC2PPVDB"))
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
        headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
        javbus_url = manager.config.get_site_url(Website.JAVBUS, "https://javbus.com") + "/FSDSS-660"

        try:
            response, error = get_text_sync(javbus_url, headers=headers)
        except Exception as e:
            signal_qt.show_traceback_log(traceback.format_exc())
            response, error = None, str(e)

        state, tips = javbus_cookie_verdict(input_cookie, response, error)
        # 只有真正验证到登录态才写盘：无效 / 被拦截 / 判定不了时一律只告警并保留用户填的 Cookie
        if state == "valid" and manager.config.javbus != input_cookie:
            self.exec_save_config.emit()
            tips = "✅ 连接正常，Cookie 已保存！"

        self.show_log_text(tips.replace("❌", " ❌ JavBus").replace("✅", " ✅ JavBus"))
        self.set_javbus_status.emit(tips)
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(True)
        return tips
