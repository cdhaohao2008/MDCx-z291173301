"""Qt 信号总线：17 个 pyqtSignal + 各自的 emit 包装。

与 `mdcx/log_console.py` / `mdcx/ui_hooks.py` 的分工
--------------------------------------------------
- 本模块 = **Qt 侧**，只有界面/控制器层需要它。
- `mdcx/log_console.py` = **Qt 无关侧**，详情日志缓冲、traceback 打印、停止标志、UI 日志出口。
- `mdcx/ui_hooks.py` = **Qt 无关侧**，按钮/标签这类界面动作的回调登记表。

`Signals` 构造时把自己的 `show_log_text` 注册为 `log_console` 的 UI 日志出口，
把四个界面动作注册为 `ui_hooks` 的回调，并把 `add_log` / `get_log` /
`show_traceback_log` / `stop` 全部转调给 `log_console`。
这样缓冲与停止标志只有一份实现，两侧永远同步（`signal.stop = True` 与 `log_console.stop`
是同一个变量），而底层模块可以只导入 `log_console`，不必把 PyQt6 拖进来。
"""

from typing import Literal

from PyQt6.QtCore import QObject, pyqtSignal

from .log_console import log_console
from .models.model_types import ShowData
from .ui_hooks import ui_hooks
from .utils import singleton


@singleton
class Signals(QObject):
    # region signal
    log_text = pyqtSignal(str)
    scrape_info = pyqtSignal(str)
    net_info = pyqtSignal(str)
    exec_set_main_info = pyqtSignal(ShowData)  # 主界面更新番号信息
    change_buttons_status = pyqtSignal()
    reset_buttons_status = pyqtSignal()
    # 两个工具按钮的独占忙/闲信号：只切换各自按钮的文案与可用性，
    # 与全局 change/reset_buttons_status 解耦，避免一个流程启动把另一个按钮
    # 也改成「正在刮削中...」（开始移动与检查缺失番号相互独立）。
    move_mp4_running = pyqtSignal(bool)
    find_missing_number_running = pyqtSignal(bool)
    set_label_file_path = pyqtSignal(str)
    label_result = pyqtSignal(str)
    logs_failed_settext = pyqtSignal(str)  # 失败面板添加信息日志信号
    view_success_file_settext = pyqtSignal(str)
    exec_set_processbar = pyqtSignal(int)  # 进度条信号量
    exec_exit_app = pyqtSignal()  # 退出信号量
    view_failed_list_settext = pyqtSignal(str)
    exec_show_list_name = pyqtSignal(str, ShowData, str)
    logs_failed_show = pyqtSignal(str)  # 失败面板添加信息日志信号

    # endregion
    def __init__(self):
        super().__init__()
        # 详情日志缓冲/停止标志的真身在 log_console，这里只做转调，保证 signal.* 与 log_console.* 同源。
        log_console.bind_text_sink(self.show_log_text)
        # 把四个界面动作登记到 ui_hooks，底层模块就能免 Qt 直调。
        ui_hooks.bind(
            change_buttons_status=self.change_buttons_status.emit,
            reset_buttons_status=self.reset_buttons_status.emit,
            set_label_file_path=self.set_label_file_path.emit,
            view_success_file_settext=self.view_success_file_settext.emit,
        )

    # region Qt 无关部分（转调 log_console）
    @property
    def stop(self) -> bool:
        return log_console.stop

    @stop.setter
    def stop(self, value: bool) -> None:
        log_console.stop = value

    def add_log(self, *text):
        """打印日志到日志页下方详情框"""
        log_console.add_log(*text)

    def get_log(self):
        return log_console.get_log()

    def show_traceback_log(self, text):
        log_console.show_traceback_log(text)

    # endregion

    # region Qt 侧
    def show_log_text(self, text):
        self.log_text.emit(text)

    def show_scrape_info(self, before_info=""):
        self.scrape_info.emit(before_info)

    def show_net_info(self, text):
        self.net_info.emit(text)

    def set_main_info(self, show_data=None):
        if show_data is None:
            show_data = ShowData.empty()
        self.exec_set_main_info.emit(show_data)

    def show_list_name(self, status: Literal["succ", "fail"], show_data: ShowData, real_number=""):
        self.exec_show_list_name.emit(status, show_data, real_number)

    # endregion


signal_qt = Signals()
signal: Signals = signal_qt


def set_signal(signal_instance: Signals):
    global signal
    signal = signal_instance
