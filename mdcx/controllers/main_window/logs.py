"""日志页（结果日志 / 请求日志 / 失败列表）的界面与落盘逻辑。

从 `main_window.py` 中按「集群」切出，业务逻辑、字符串与调用顺序完全不变，
只是换了个物理文件。宿主仍是 `MyMAinWindow`，因此 `self.*` 的解析时机不变。
"""

import os
import time
import traceback

from PyQt6.QtGui import QIcon, QTextCursor
from PyQt6.QtWidgets import QApplication, QFileDialog

from mdcx.config.extend import get_movie_path_setting
from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.core.scraper import start_new_scrape
from mdcx.log_console import strip_leading_indent
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils import add_html, add_html_plain_text


class LogPageMixin:
    # 日志页复制当前显示的日志到剪贴板（上栏＋可见的下栏；失败列表覆盖显示时复制其文本）
    def pushButton_copy_logs_clicked(self):
        if not self.Ui.textBrowser_log_main_3.isHidden():
            text = self.Ui.textBrowser_log_main_3.toPlainText()
        else:
            parts = [self.Ui.textBrowser_log_main.toPlainText()]
            if not self.Ui.textBrowser_log_main_2.isHidden():
                parts.append(self.Ui.textBrowser_log_main_2.toPlainText())
            text = "\n".join(part for part in parts if part.strip())
        if not text.strip():
            signal_qt.show_log_text("⛔️ 暂无可复制内容")
            return
        QApplication.clipboard().setText(text)
        signal_qt.show_log_text("✅ 当前显示的日志已复制到剪贴板")

    # 日志页清空显示（仅清界面，不动日志文件）
    def pushButton_clear_logs_clicked(self):
        self.main_log_queue.clear()
        self.logs_counts = 0
        self.req_logs_counts = 0
        self.Ui.textBrowser_log_main.clear()
        self.Ui.textBrowser_log_main_2.clear()

    # 上栏日志显示与滚动条分离：内置滚动条隐藏，仅作滚动范围数据源；
    # 外置独立滚动条 verticalScrollBar_log_main 负责交互，二者范围与位置镜像同步；
    # 日志不足一页（无需滚动）时外置条隐藏，不留右侧滑动轨道
    def _mirror_log_scrollbar(self) -> None:
        inner = self.Ui.textBrowser_log_main.verticalScrollBar()
        outer = self.Ui.verticalScrollBar_log_main
        outer.blockSignals(True)
        try:
            outer.setRange(inner.minimum(), inner.maximum())
            outer.setPageStep(inner.pageStep())
            outer.setSingleStep(inner.singleStep())
            outer.setValue(inner.value())
        finally:
            outer.blockSignals(False)
        outer.setVisible(inner.maximum() > inner.minimum())

    def _on_inner_log_scroll_changed(self, value: int) -> None:
        outer = self.Ui.verticalScrollBar_log_main
        if outer.value() != value:
            outer.blockSignals(True)
            try:
                outer.setValue(value)
            finally:
                outer.blockSignals(False)

    # 日志追加时保持滚动条位置不变（默认最上方），不自动拉到底；
    # 同时保住用户文本光标：append() 会把光标甩到末尾，后续窗口缩放/重排会
    # ensureCursorVisible 跳到底部，这里一并恢复，之后打开保留的才是上次位置
    @staticmethod
    def _append_log_preserve_scroll(browser, html: str) -> None:
        view_cursor = browser.textCursor()
        saved_pos = view_cursor.position()
        saved_anchor = view_cursor.anchor()
        bar = browser.verticalScrollBar()
        scroll_pos = bar.value()
        browser.append(html)
        doc_end = max(browser.document().characterCount() - 1, 0)
        restored = browser.textCursor()
        restored.setPosition(min(saved_anchor, doc_end), QTextCursor.MoveMode.MoveAnchor)
        restored.setPosition(min(saved_pos, doc_end), QTextCursor.MoveMode.KeepAnchor)
        browser.setTextCursor(restored)
        bar.setValue(scroll_pos)

    def _on_main_logs_show(self, html: str) -> None:
        self._append_log_preserve_scroll(self.Ui.textBrowser_log_main, html)

    def _on_main_req_logs_show(self, html: str) -> None:
        self._append_log_preserve_scroll(self.Ui.textBrowser_log_main_2, html)

    # 切页：日志页首次打开时滚动条默认置顶（含光标归位），后续打开保留上次位置不动
    def _on_stacked_page_changed(self, index: int) -> None:
        if self.Ui.stackedWidget.widget(index) is not self.Ui.page_log:
            return
        if self._log_page_opened:
            return
        self._log_page_opened = True
        for browser in (self.Ui.textBrowser_log_main, self.Ui.textBrowser_log_main_2):
            browser.moveCursor(QTextCursor.MoveOperation.Start)
            browser.verticalScrollBar().setValue(browser.verticalScrollBar().minimum())
        self._mirror_log_scrollbar()

    # 日志页点展开折叠日志
    def pushButton_show_hide_logs_clicked(self):
        if self.Ui.textBrowser_log_main_2.isHidden():
            self.show_hide_logs(True)
        else:
            self.show_hide_logs(False)

    # 日志页点展开折叠日志
    def show_hide_logs(self, show):
        if show:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.hide_logs_icon))
            self.Ui.textBrowser_log_main_2.show()
            # 硬编码 resize 会覆盖窗口缩放同步结果（议题 #68），统一交给 _sync_page_layouts；
            # 展开/收起不抢滚动条位置（默认最上方），不再强制拉到底
            self._sync_page_layouts()

            # self.Ui.textBrowser_log_main_2.moveCursor(self.Ui.textBrowser_log_main_2.textCursor().End)

        else:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.show_logs_icon))
            self.Ui.textBrowser_log_main_2.hide()
            self._sync_page_layouts()

    # 日志页点展开折叠失败列表
    def pushButton_show_hide_failed_list_clicked(self):
        if self.Ui.textBrowser_log_main_3.isHidden():
            self.show_hide_failed_list(True)
        else:
            self.show_hide_failed_list(False)

    # 日志页点展开折叠失败列表
    def show_hide_failed_list(self, show):
        if show:
            self.Ui.textBrowser_log_main_3.show()
            self.Ui.pushButton_scraper_failed_list.show()
            self.Ui.pushButton_save_failed_list.show()
            self.Ui.textBrowser_log_main_3.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main_3.verticalScrollBar().maximum()
            )

        else:
            self.Ui.pushButton_save_failed_list.hide()
            self.Ui.textBrowser_log_main_3.hide()
            self.Ui.pushButton_scraper_failed_list.hide()

    # 日志页点一键刮削失败列表
    def pushButton_scraper_failed_list_clicked(self):
        with Flags.guarded():
            failed_snapshot = list(Flags.failed_list)
        if failed_snapshot and self.Ui.pushButton_start_cap.text() == "开始":
            start_new_scrape(FileMode.Default, movie_list=[s[0] for s in failed_snapshot])
            self.show_hide_failed_list(False)

    # 日志页点另存失败列表
    def pushButton_save_failed_list_clicked(self):
        with Flags.guarded():
            has_failed = bool(Flags.failed_list)
        if has_failed:
            log_name = "failed_" + time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = get_movie_path_setting().movie_path / log_name
            filename, filetype = QFileDialog.getSaveFileName(
                None, "保存失败文件列表", log_name.as_posix(), "Text Files (*.txt)", options=self.options
            )
            if filename:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(self.Ui.textBrowser_log_main_3.toPlainText().strip())

    def _write_main_logs_to_file(self, logs: list[str]):
        if not logs:
            return
        text = "\n".join(logs) + "\n"
        try:
            Flags.log_txt.write(text.encode("utf-8"))
        except Exception:
            log_folder = manager.data_folder / "Log"
            if not os.path.exists(log_folder):
                os.makedirs(log_folder, exist_ok=True)
            log_name = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = log_folder / log_name
            try:
                old = Flags.log_txt
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
                Flags.log_txt = open(log_name, "wb", buffering=0)
                Flags.log_txt.write(text.encode("utf-8"))
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _flush_main_log_queue(self):
        if not self.main_log_queue:
            return
        logs: list[str] = []
        while self.main_log_queue and len(logs) < self.main_log_batch_size:
            logs.append(self.main_log_queue.popleft())
        if manager.config.save_log:
            self._write_main_logs_to_file(logs)
        try:
            self.logs_counts += len(logs)
            if self.logs_counts >= self.main_log_max_count:
                self.logs_counts = len(logs)
                self.main_logs_clear.emit("")
                self.main_logs_show.emit(add_html(strip_leading_indent("🗑️ 日志过多，已清屏！")))
            self.main_logs_show.emit(add_html("\n".join(logs)))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self._append_log_preserve_scroll(self.Ui.textBrowser_log_main, traceback.format_exc())

    # 显示详细日志
    def show_detail_log(self):
        text = signal_qt.get_log()
        if text and manager.config.show_web_log:
            self.main_req_logs_show.emit(add_html_plain_text(text))
            if self.req_logs_counts < 10000:
                self.req_logs_counts += 1
            else:
                self.req_logs_counts = 0
                self.req_logs_clear.emit("")
                self.main_req_logs_show.emit(add_html_plain_text(" 🗑️ 日志过多，已清屏！"))

    # 日志页面显示内容
    def show_log_text(self, text):
        if not text:
            return
        # 行首缩进统一在这里去掉：无论消息来自 log_console 还是 signal_qt.show_log_text，
        # 进队列前就已左对齐，窗口里每一行的左边缘一致（显示与落盘文件同源同形）。
        text = strip_leading_indent(str(text))
        if not text:
            return
        self.main_log_queue.append(text)
        # 无界 deque 在生产远超 100ms 消费时 OOM：丢最旧保内存（显示行为不变，只丢刷不出的旧行）
        if len(self.main_log_queue) > 2000:
            try:
                self.main_log_queue.popleft()
            except Exception:
                pass
