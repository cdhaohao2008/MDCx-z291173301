"""Qt 无关的日志内核：详情日志环形缓冲、traceback 打印、停止标志、UI 日志出口。

为什么单独成模块
----------------
`mdcx/signals.py` 里的 `Signals` 继承 `QObject`，任何一行 ``from ..signals import signal``
都会把 PyQt6 拖进调用方所在的层。但底层模块（core / base / crawlers / config）真正用到的
只有四件事：详情日志缓冲、traceback 打印、"要不要继续"的停止标志、以及往 UI 日志页写一行。
前两件和停止标志是纯 Python；第三件经由本模块的回调转交 Qt 侧。

于是本模块承接全部四件事，`mdcx/signals.py` 保留 15 个 pyqtSignal 与各自的 emit 包装并转调
这里，底层模块只依赖本模块即可，不再需要 Qt。

`log_text()` 不直接 emit Qt 信号，而是转发给 Qt 侧在构造时注册的回调（`bind_text_sink`）。
这样在没有 GUI 的环境（单元测试、纯脚本）里它退化为空操作，而不是在导入期就要求 PyQt6。
"""

import threading
import time
from collections.abc import Callable
from contextlib import suppress

from .utils import singleton


def strip_leading_indent(text: str) -> str:
    """去掉日志首行的水平缩进（空格 / Tab），使日志窗口严格左对齐。

    为什么只动首行：日志里大量消息是「一行标题 + 若干缩进明细」的形态
    （traceback 的调用栈、路径清单、参数回显），那些缩进是内容本身的一部分，
    整段 lstrip 会把 traceback 的调用层级压平，反而更难读。

    只吃掉行首的空格与 Tab，不吃换行——以 `\\n` 开头的消息（刻意留空行分隔）
    仍保留那个空行。
    """
    if not isinstance(text, str):
        text = str(text)
    return text.lstrip(" \t")


def with_site_prefix(text: str, site: str) -> str:
    """给日志消息补上站点名前缀：图标与站点名之间留一个空格，行首不留缩进。

    形如 ``"✅ 连接正常！"`` + ``"JavBus"`` → ``"✅ JavBus 连接正常！"``。
    早先各调用点各自 ``replace("✅", " ✅ Site")``，替换串里那个前导空格会让整行
    右移一格、与同批消息左边缘不齐；这里统一由 `strip_leading_indent` 兜底。
    """
    if not isinstance(text, str):
        text = str(text)
    return text.replace("❌", f"❌ {site}").replace("✅", f"✅ {site}")


@singleton
class LogConsole:
    """详情日志缓冲 + 停止标志 + UI 日志出口。不依赖 Qt，可被任意层直接导入。"""

    def __init__(self):
        self.log_lock = threading.Lock()
        self.detail_log_list = []
        # 明细日志上限：UI 卡顿/高频 add_log 时丢最旧，防无界堆积 OOM（get_log 仍一次性 drain）
        self._detail_log_max = 2000
        self.stop = False
        self._text_sink: Callable[[str], None] | None = None

    def bind_text_sink(self, sink: Callable[[str], None]) -> None:
        """注册 UI 日志出口。由 Qt 侧 `Signals` 在构造时调用（每个进程只会有一个）。"""
        self._text_sink = sink

    def add_log(self, *text):
        """打印日志到日志页下方详情框"""
        if self.stop:
            return
        try:
            with self.log_lock:
                self.detail_log_list.append(f" ⏰ {time.strftime('%H:%M:%S', time.localtime())} {' '.join(text)}")
                overflow = len(self.detail_log_list) - self._detail_log_max
                if overflow > 0:
                    del self.detail_log_list[:overflow]
        except Exception:
            pass

    def get_log(self):
        with self.log_lock:
            text = "\n".join(self.detail_log_list)
            self.detail_log_list = []
        return text

    def show_traceback_log(self, text):
        with suppress(Exception):
            print(text)
        self.add_log(text)

    def log_text(self, text):
        """写入 UI 日志页。未注册出口（无 GUI 环境）时静默丢弃。

        行首缩进在这里统一去掉：日志窗口里所有消息（含各业务模块自带的
        「 ✅ …」「 🔴 …」前缀缩进）左边缘一致，严格对齐。
        """
        sink = self._text_sink
        if sink is not None:
            sink(strip_leading_indent(text))


log_console = LogConsole()
