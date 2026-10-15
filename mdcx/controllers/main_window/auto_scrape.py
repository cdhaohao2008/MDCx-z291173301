"""自动刮削循环（定时触发 → 调度 → 启动）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import time

from PyQt6.QtCore import QTimer

from mdcx.config.enums import Switch
from mdcx.config.manager import manager
from mdcx.core.scraper import start_new_scrape
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt


class AutoScrapeMixin:
    # region 自动刮削
    def auto_scrape(self):
        if Switch.TIMED_SCRAPE in manager.config.switch_on and self.Ui.pushButton_start_cap.text() == "开始":
            QTimer.singleShot(100, self._auto_scrape_do_work)

    def _auto_scrape_do_work(self):
        timed_interval = manager.config.timed_interval
        self.atuo_scrape_count += 1
        signal_qt.show_log_text(
            f"\n\n 🍔 已启用「循环刮削」！间隔时间：{timed_interval}！即将开始第 {self.atuo_scrape_count} 次循环刮削！"
        )
        if Flags.scrape_start_time:
            signal_qt.show_log_text(
                " ⏰ 上次刮削时间: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.scrape_start_time))
            )
        start_new_scrape(FileMode.Default)

    def auto_start(self):
        if Switch.AUTO_START in manager.config.switch_on:
            signal_qt.show_log_text("\n\n 🍔 已启用「软件启动后自动刮削」！即将开始自动刮削！")
            self.pushButton_start_scrape_clicked()
