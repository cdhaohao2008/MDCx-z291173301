"""FC2PPVDB / JavBus 的 Cookie 登录态检测。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

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


class CookieChecksMixin:
    # endregion
    def pushButton_check_fc2ppvdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText().strip()
        if not input_cookie:
            self.set_fc2ppvdb_status.emit("❌ 未填写 Cookie")
            self.show_log_text(" ❌ FC2PPVDB 未填写 Cookie，可在「软件设置」-「网络」添加！")
            return
        self.set_fc2ppvdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_fc2ppvdb_cookie, args=(input_cookie,), daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_fc2ppvdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写 Cookie"
        if not input_cookie:
            self.set_fc2ppvdb_status.emit(tips)
            return tips

        if not cookie_has_login_key(input_cookie):
            tips = "❌ Cookie 无效！请粘贴 fc2cmadb.com 登录后的完整 cookie（含 XSRF-TOKEN 与 session 项）"
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
        input_cookie = self.Ui.plainTextEdit_cookie_javbus.toPlainText()
        self.set_javbus_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javbus_cookie, args=(input_cookie,), daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.show_log_text(traceback.format_exc())

    def _check_javbus_cookie(self, input_cookie: str):
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
        javbus_url = manager.config.get_site_url(Website.JAVBUS, "https://javbus.com") + "/FSDSS-660"

        try:
            response, error = get_text_sync(javbus_url, headers=headers)

            if response is None:
                tips = f"❌ 连接失败！请检查网络或代理设置！ {error}"
            elif "lostpasswd" in response:
                if input_cookie:
                    tips = "❌ Cookie 无效！"
                else:
                    tips = "❌ 当前节点需要 Cookie 才能刮削！请填写 Cookie 或更换节点！"
            elif manager.config.javbus != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常！Cookie 已保存！  "

        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"

        self.show_log_text(tips.replace("❌", " ❌ JavBus").replace("✅", " ✅ JavBus"))
        self.set_javbus_status.emit(tips)
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(True)
        return tips
