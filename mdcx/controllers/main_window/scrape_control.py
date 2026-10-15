"""刮削任务的启动 / 停止 / 进度条 / 线程收尾。

这里是 UI 与 core.scraper 之间唯一的交互面：只负责发起任务、展示进度和收尾线程，
不直接触碰爬虫或文件细节。"""

import threading
import time
import traceback

from PyQt6.QtWidgets import QMessageBox

from mdcx.base.file import (
    save_remain_list_now,
    save_success_list,
)
from mdcx.config.enums import Switch
from mdcx.config.manager import manager
from mdcx.core.scraper import (
    get_remain_list,
    start_new_scrape,
)
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils import (
    executor,
    get_current_time,
    get_used_time,
)


class ScrapeControlMixin:
    # region 主界面
    # 开始刮削按钮
    def pushButton_start_scrape_clicked(self):
        text = self.Ui.pushButton_start_cap.text()
        if text == "开始":
            if not get_remain_list():
                start_new_scrape(FileMode.Default)
        elif text == "■ 停止":
            self.pushButton_stop_scrape_clicked()

    # 停止确认弹窗
    def pushButton_stop_scrape_clicked(self):
        if Switch.SHOW_DIALOG_STOP_SCRAPE in manager.config.switch_on:
            box = QMessageBox(QMessageBox.Icon.Warning, "停止刮削", "确定要停止刮削吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("停止刮削")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.Ui.pushButton_start_cap.text() == "■ 停止":
            Flags.stop_requested = True
            signal_qt.stop = True
            # 唤醒移动文件线程的检查点（协作式停止，替代已删除的 ctypes 强杀）
            self._move_cancel_event.set()
            executor.run(save_success_list())
            # 停止时立即持久化最新剩余任务，不能只依赖 1.5s 定时器
            # （停止后定时器保存到的可能是竞态旧快照，续刮会丢任务，议题 #98）
            save_remain_list_now()
            Flags.rest_time_convert_ = Flags.rest_time_convert
            Flags.rest_time_convert = 0
            self.Ui.pushButton_start_cap.setText(" ■ 停止中 ")
            self.Ui.pushButton_start_cap2.setText(" ■ 停止中 ")
            signal_qt.show_scrape_info("⛔️ 刮削停止中...")
            executor.cancel_async()  # 取消异步任务
            if not self.threads_list:
                self.stop_used_time = 0.0
                self.show_stop_info_thread()
                return
            t = threading.Thread(target=self._kill_threads, daemon=True)  # 关闭线程池
            t.start()

    # 显示停止信息
    def _show_stop_info(self):
        signal_qt.reset_buttons_status.emit()
        try:
            Flags.rest_time_convert = Flags.rest_time_convert_
            if Flags.stop_other:
                signal_qt.show_scrape_info("⛔️ 已手动停止！")
                signal_qt.show_log_text(
                    "⛔️ 已手动停止！\n================================================================================"
                )
                self.set_label_file_path.emit("⛔️ 已手动停止！")
                return
            signal_qt.exec_set_processbar.emit(0)
            end_time = time.time()
            used_time = str(round((end_time - Flags.start_time), 2))
            if Flags.scrape_done:
                average_time = str(round((end_time - Flags.start_time) / Flags.scrape_done, 2))
            else:
                average_time = used_time
            signal_qt.show_scrape_info("⛔️ 刮削已手动停止！")
            self.set_label_file_path.emit(
                f"⛔️ 刮削已手动停止！\n   已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒"
            )
            signal_qt.show_log_text(
                f"\n ⛔️ 刮削已手动停止！\n 😊 已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒, 停止用时 {self.stop_used_time} 秒"
            )
            signal_qt.show_log_text("================================================================================")
            signal_qt.show_log_text(
                " ⏰ Start time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.start_time))
            )
            signal_qt.show_log_text(
                " 🏁 End time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
            )
            signal_qt.show_log_text(f"{' ⏱ Used time'.ljust(13)}: {used_time}S")
            signal_qt.show_log_text(f"{' 🍕 Per time'.ljust(13)}: {average_time}S")
            signal_qt.show_log_text("================================================================================")
            with Flags.guarded():
                Flags.again_dic.clear()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())
        finally:
            signal_qt.stop = False

    def show_stop_info_thread(
        self,
    ):
        t = threading.Thread(target=self._show_stop_info, daemon=True)
        t.start()

    # 关闭线程池和扫描线程（协作式停止：只 join 等待，不强杀线程。
    # threads_list 里的移动线程靠 _move_cancel_event 在检查点自行退出；
    # 刮削协程靠 signal.stop/Flags.stop_requested + cancel_async 退出。）
    def _kill_threads(self):
        with Flags.guarded():
            Flags.total_kills = len(self.threads_list)
            Flags.now_kill = 0
            total_kills = Flags.total_kills
        start_time = time.time()
        self.set_label_file_path.emit(f"⛔️ 正在停止刮削...\n   正在停止已在运行的任务线程（1/{total_kills}）...")
        signal_qt.show_log_text(
            f"\n ⛔️ {get_current_time()} 已停止添加新的刮削任务，正在停止已在运行的任务线程（{total_kills}）..."
        )
        signal_qt.show_traceback_log(f"⛔️ 正在停止正在运行的任务线程 ({total_kills}) ...")
        i = 0
        for each in self.threads_list:
            i += 1
            signal_qt.show_traceback_log(f"正在停止线程: {i}/{total_kills} {each.name} ...")
        signal_qt.show_traceback_log(
            "线程正在停止中，请稍后...\n 🍯 停止时间与线程数量及线程正在执行的任务有关，比如正在执行网络请求、文件下载等IO操作时，需要等待其释放资源。。。\n"
        )
        signal_qt.stop = True

        # 对全部线程使用一个总等待窗口，避免线程数量放大停止耗时。
        wait_deadline = time.monotonic() + 12.0
        for each in self.threads_list:
            remaining = wait_deadline - time.monotonic()
            if remaining <= 0:
                break
            each.join(timeout=remaining)

        self.stop_used_time = get_used_time(start_time)
        stopped_count = sum(not each.is_alive() for each in self.threads_list)
        signal_qt.show_log_text(f" 🕷 已停止线程：{stopped_count}/{total_kills}")
        if stopped_count == total_kills:
            signal_qt.show_traceback_log(f"所有线程已停止！！！({self.stop_used_time}s)\n ⛔️ 刮削已手动停止！\n")
            signal_qt.show_log_text(f" ⛔️ {get_current_time()} 所有线程已停止！({self.stop_used_time}s)")
        else:
            remaining = ", ".join(each.name for each in self.threads_list if each.is_alive())
            signal_qt.show_traceback_log(f"线程停止超时({self.stop_used_time}s)：{remaining}")
            signal_qt.show_log_text(f" ⚠️ {get_current_time()} 线程停止超时：{remaining}")
        thread_remain_list = []
        [thread_remain_list.append(t.name) for t in threading.enumerate()]  # 剩余线程名字列表
        thread_remain = ", ".join(thread_remain_list)
        signal_qt.show_traceback_log(f"剩余线程 ({len(thread_remain_list)}): {thread_remain}")
        self.show_stop_info_thread()

    # 进度条
    def set_processbar(self, value):
        self.Ui.progressBar_scrape.setProperty("value", value)
