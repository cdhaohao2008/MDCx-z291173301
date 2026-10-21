"""检测网络页（诊断跑批、进度回填、重试、复制报告、JavDB Cookie 检测）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import platform
import re
import threading
import time
import traceback

from PyQt6.QtWidgets import (
    QApplication,
)

from mdcx.base.web_sync import get_text_sync
from mdcx.config.enums import Website
from mdcx.config.manager import manager
from mdcx.consts import (
    LOCAL_VERSION,
    VERSION_NAME,
)
from mdcx.core.network_check import (
    DEFAULT_SEPARATOR_WIDTH,
    NetworkCheckStatus,
    merge_site_check_cache,
    run_network_check,
    scrape_probe_ladder_text,
)
from mdcx.log_console import with_site_prefix
from mdcx.signals import signal_qt
from mdcx.utils import (
    add_html_plain_text,
    executor,
)

from .handlers import net_separator_width


class NetCheckMixin:
    # region 检测网络
    def _measure_net_report_sep_chars(self) -> int:
        """主线程点按钮时量一次报告分隔线宽度，存给检测 worker 线程用。

        报告里的「-」「=」要和面板最上/最下两条横幅同长，故复用同一份可视宽测量
        （`_net_separator_chars` 已缓存，启动首屏量过一次），再过同一个收敛函数
        `net_separator_width`——两边的减 8 与下限 8 才不会各算各的。
        """
        self._net_report_sep_chars = net_separator_width(self._net_separator_chars())
        return self._net_report_sep_chars

    def _net_report_separator_width(self) -> int:
        """worker 线程读用的报告分隔线宽度（纯整数运算，不碰任何 Qt 控件）。

        没量过（例如直接调 `network_check()` 绕过按钮）时退回模块兜底值。
        """
        return self._net_report_sep_chars or DEFAULT_SEPARATOR_WIDTH

    def network_check(self):
        try:
            signal_qt.show_net_info("\n⛑ 开始检测网络...")
            cancel_event = threading.Event()
            self.network_check_cancel_event = cancel_event
            self.network_check_results = None
            self._net_check_lines = []
            self._net_live_results = []

            def progress(line):
                self._net_check_lines.append(line)
                signal_qt.show_net_info(line)

            def on_item_done(done: int, total: int):
                self.net_check_progress.emit(done, total)

            def on_item_result(result):
                """单项出结果就落缓存并刷新徽标——不让用户等到整轮跑完才看到状态。

                缓存按「本轮已出结果的完整列表」合并（而不是只喂这一条），
                Official 五站仍按本轮最差聚合，逐项写入也不会互相覆盖成最后一个。
                """
                if result.spec.site is None:
                    return
                self._net_live_results.append(result)
                merge_site_check_cache(self._net_live_results)
                self.net_check_item_done.emit()

            self.network_check_future = executor.submit(
                run_network_check(
                    progress=progress,
                    on_item_done=on_item_done,
                    on_item_result=on_item_result,
                    cancel_event=cancel_event,
                    separator_width=self._net_report_separator_width(),
                )
            )
            self.network_check_results = self.network_check_future.result()
            merge_site_check_cache(self.network_check_results)  # 持久化供站点选择列表回显
        except Exception as e:
            # 议题 #73 实证：空消息异常（裸 TimeoutError 等）只显示「出现异常：」毫无线索。
            # 带异常类型名，并把 traceback 直接展示在检测页——用户复制结果就是完整诊断。
            signal_qt.show_net_info(f"\n⛔️ 网络检测出现异常：{type(e).__name__}: {e}")
            signal_qt.show_net_info("=" * self._net_report_separator_width() + "\n")
            signal_qt.show_net_info(traceback.format_exc().rstrip())
            signal_qt.show_traceback_log(str(e))
            signal_qt.show_traceback_log(traceback.format_exc())
        finally:
            self.network_check_cancel_event = None
            self.network_check_future = None
            # 按钮状态必须在主线程恢复，经信号调度
            self.net_check_done.emit()

    def _run_net_retry(self):
        """后台线程：重试上次检测的失败/警告项。"""
        results = self.network_check_results
        if not results:
            signal_qt.show_net_info("⛔️ 请先运行一次完整检测，再使用「重试失败项」")
            return
        failed_specs = [
            result.spec
            for result in results
            if result.status in (NetworkCheckStatus.FAILED, NetworkCheckStatus.WARNING)
        ]
        if not failed_specs:
            signal_qt.show_net_info("✅ 上次检测没有失败/警告项，无需重试")
            return
        try:
            signal_qt.show_net_info(f"\n⛑ 重试{len(failed_specs)}个失败/警告项...")
            cancel_event = threading.Event()
            self.network_check_cancel_event = cancel_event
            self._net_check_lines = []
            self._net_live_results = []
            # 议题 #118：探测超时递进已移进单轮内部（30s/45s 最多两次），
            # 「重试失败项」回归纯重测——价值在于用户改完代理/CF 配置后再给一次机会
            signal_qt.show_net_info(f"⏱ 单站刮削探测自动递进重试，超时阶梯{scrape_probe_ladder_text()}")

            def progress(line):
                self._net_check_lines.append(line)
                signal_qt.show_net_info(line)

            def on_item_done(done: int, total: int):
                self.net_check_progress.emit(done, total)

            def on_item_result(result):
                if result.spec.site is None:
                    return
                self._net_live_results.append(result)
                merge_site_check_cache(self._net_live_results)
                self.net_check_item_done.emit()

            self.network_check_future = executor.submit(
                run_network_check(
                    progress=progress,
                    on_item_done=on_item_done,
                    on_item_result=on_item_result,
                    cancel_event=cancel_event,
                    specs=failed_specs,
                    emit_header=False,
                    separator_width=self._net_report_separator_width(),
                )
            )
            self.network_check_results = self.network_check_future.result()
            merge_site_check_cache(self.network_check_results)  # 部分重测同样合并进缓存
        except Exception as e:
            signal_qt.show_net_info(f"\n⛔️ 重试失败项出现异常：{type(e).__name__}: {e}")
            signal_qt.show_net_info(traceback.format_exc().rstrip())
            signal_qt.show_traceback_log(traceback.format_exc())
        finally:
            self.network_check_cancel_event = None
            self.network_check_future = None
            self.net_check_done.emit()

    def pushButton_net_retry_clicked(self):
        if self.network_check_future is not None:
            signal_qt.show_net_info("⏳ 上一次检测仍在进行，请稍后再试")
            return
        self._measure_net_report_sep_chars()
        t = threading.Thread(target=self._run_net_retry, daemon=True)
        t.start()

    def pushButton_net_copy_clicked(self):
        lines = getattr(self, "_net_check_lines", None) or []
        if not lines:
            signal_qt.show_net_info("⛔️ 暂无可复制内容，请先运行检测")
            return
        header = self._build_net_diagnostic_header()
        text = "\n".join(header + lines)
        QApplication.clipboard().setText(text)
        signal_qt.show_net_info("✅ 检测报告已复制到剪贴板（含版本/系统概要，代理地址已脱敏，可直接粘贴到 issue 求助）")

    @staticmethod
    def _build_net_diagnostic_header() -> list[str]:
        """生成复制到剪贴板的诊断报告头部：版本/系统/脱敏后的网络配置概要。"""
        from mdcx.utils import mask_proxy_url

        config = manager.config
        use_proxy = bool(config.use_proxy and config.proxy)
        proxy_info = mask_proxy_url(config.proxy) if use_proxy else "未启用"
        return [
            "=" * 88,
            "MDCx 网络诊断报告（提 issue 时可直接粘贴本段全部内容）",
            f"  版本: {VERSION_NAME} ({LOCAL_VERSION})",
            f"  系统: {platform.system()} {platform.release()} ({platform.machine()})",
            f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  代理: {proxy_info}    CloudFlare Bypass: {'已配置' if config.cf_bypass_url.strip() else '未配置'}"
            f"    外部CF服务: {'已配置' if config.cf_bypass_trawl_url.strip() else '未配置'}",
            "=" * 88,
        ]

    def _on_net_check_progress(self, done: int, total: int):
        """主线程：检测进行中，按钮文本显示进度百分比。"""
        if total > 0 and self.network_check_future is not None:
            self.Ui.pushButton_check_net.setText(f"停止检测 {done}/{total}")

    def _on_net_check_item(self):
        """主线程：单项结果已落缓存，立刻刷新站点下拉框徽标与悬停提示。

        逐项刷新而非只在 `_on_net_check_done` 里刷一次：之前站点状态要等整轮
        几十项跑完（含多个慢站/探测超时，实测 30+ 分钟）才变，用户会以为结果
        没同步。刷新只改图标/tooltip/网址角色，不重排文本、保留选中项。
        """
        from .init import refresh_network_check_badges

        refresh_network_check_badges(self)

    def _on_net_check_done(self):
        """主线程：网络检测完成，恢复按钮状态并刷新站点下拉框的检测状态徽标。"""
        from .init import refresh_network_check_badges

        refresh_network_check_badges(self)
        self.Ui.pushButton_check_net.setEnabled(True)
        self.Ui.pushButton_check_net.setText("开始检测")
        self.Ui.pushButton_check_net.setStyleSheet(
            "QPushButton#pushButton_check_net{background-color:#4C6EFF}QPushButton:hover#pushButton_check_net{background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{#4C6EE0}"
        )

    # 网络检查
    def pushButton_check_net_clicked(self):
        if self.Ui.pushButton_check_net.text() == "开始检测":
            if self.network_check_future is not None:
                # 上一个检测线程尚未结束，避免并发启动多个实例
                return
            self.Ui.pushButton_check_net.setText("停止检测")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#3758D8;}QPushButton:hover#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:pressed#pushButton_check_net{color: white;background-color:#2F49B8;}"
            )
            try:
                self._measure_net_report_sep_chars()
                self.t_net = threading.Thread(target=self.network_check, daemon=True)
                self.t_net.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_net_info(traceback.format_exc())
        elif self.Ui.pushButton_check_net.text().startswith("停止检测"):
            if self.network_check_cancel_event:
                self.network_check_cancel_event.set()
            signal_qt.show_net_info("\n⛔️ 正在停止网络检测...")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_check_net{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{color: white;background-color:#4C6EE0}"
            )
            self.Ui.pushButton_check_net.setText("开始检测")
        else:
            try:
                if self.network_check_cancel_event:
                    self.network_check_cancel_event.set()
            except Exception as e:
                signal_qt.show_traceback_log(str(e))
                signal_qt.show_traceback_log(traceback.format_exc())

    # 检测网络界面日志显示；按行首状态图标着色，便于小白快速定位失败项
    def show_net_info(self, text):
        try:
            color = ""
            stripped = str(text or "").lstrip()
            if stripped.startswith(("❌", "⛔️", "⛔")):
                color = "#e53935"
            elif stripped.startswith("⚠"):
                color = "#f9a825"
            elif stripped.startswith("✅"):
                color = "#43a047"
            self.net_logs_show.emit(add_html_plain_text(text, color=color))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.Ui.textBrowser_net_main.append(traceback.format_exc())

    # 检查javdb cookie
    def pushButton_check_javdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javdb.toPlainText()
        if not input_cookie:
            self.set_javdb_status.emit("❌ 未填写Cookie")
            self.show_log_text(" ❌ JavDb 未填写Cookie，可在「软件设置」-「网络」添加！")
            return
        self.set_javdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javdb_cookie, args=(input_cookie,), daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_javdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写Cookie，影响 FC2 刮削！"
        if not input_cookie:
            self.set_javdb_status.emit(tips)
            return tips
        # self.Ui.pushButton_check_javdb_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        header = {"cookie": input_cookie}
        javdb_url = manager.config.get_site_url(Website.JAVDB, "https://javdb.com") + "/v/D16Q5?locale=zh"
        try:
            response, error = get_text_sync(javdb_url, headers=header)
            if response is None:
                if "Cookie" in error:
                    # 议题 #130：网络/站点不可达不等于 cookie 失效，一律只告警、保留 cookie
                    tips = "❌ Cookie 检查失败（网络/站点不可达），已保留原 Cookie"
                else:
                    tips = f"❌ 连接失败！请检查网络或代理设置！ {response}"
            else:
                if "The owner of this website has banned your access based on your browser's behaving" in response:
                    ip_adress_list = re.findall(r"(\d+\.\d+\.\d+\.\d+)", response)
                    ip_adress = ip_adress_list[0] + " " if ip_adress_list else ""
                    tips = f"❌ 你的 IP {ip_adress}被 JavDb 封了！"
                elif "Due to copyright restrictions" in response or "Access denied" in response:
                    tips = "❌ 当前 IP 被禁止访问！请使用非日本节点！"
                elif "ray-id" in response:
                    tips = "❌ 访问被 CloudFlare 拦截！"
                elif "/logout" in response:  # 已登录，有登出按钮
                    # vip_info 自带标点/括号：未开通沿用括号补注，已开通则独立成句感叹
                    vip_info = "（未开通VIP）"
                    tips = f"✅ 连接正常！{vip_info}"
                    if input_cookie:
                        if "icon-diamond" in response or "/v/D16Q5" in response:  # 有钻石图标或者跳到详情页表示已开通
                            vip_info = "已开通VIP！"
                        if manager.config.javdb != input_cookie:  # 保存cookie
                            tips = f"✅ 连接正常！{vip_info}Cookie 已保存！"
                            self.exec_save_config.emit()
                        else:
                            tips = f"✅ 连接正常！{vip_info}"
                else:
                    # 议题 #130：/logout 缺失只说明"未检测到登录态"，可能是维护页/拦截页，
                    # 不构成 cookie 失效的确凿证据——只告警、保留 cookie，由用户手动替换。
                    tips = "❌ 未检测到登录态，Cookie可能无效（已保留，可手动替换）"
        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"
            signal_qt.show_traceback_log(tips)
        if input_cookie:
            self.set_javdb_status.emit(tips)
            # self.Ui.pushButton_check_javdb_cookie.setEnabled(True)
        self.show_log_text(with_site_prefix(tips, "JavDb"))
        return tips
