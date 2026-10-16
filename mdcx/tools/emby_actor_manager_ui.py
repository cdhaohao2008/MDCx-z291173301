from __future__ import annotations

import asyncio
import concurrent.futures
import re
import threading
import weakref
from pathlib import Path

from pydantic import HttpUrl
from PyQt6.QtCore import QEvent, Qt, QThread, QTimer
from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtGui import QColor, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.enums import Switch
from ..config.manager import manager
from ..config.resources import resources
from ..models.emby import (
    normalize_premiere_date,
    normalize_production_year,
)
from ..ui_theme import build_scrollbar_style
from ..utils import executor
from ..utils.qt_text import left_anchor_text_edits
from ..utils.window_center import center_on_screen
from . import emby_actor_clean_rules as clean_rules
from . import emby_actor_source_catalog as source_catalog
from .emby_actor_manager import (
    ActorInfo,
    build_local_avatar_index,
    clean_actor_data_batch_async,
    fetch_actor_info_from_source,
    fetch_all_actors,
    from_graphis,
    get_all_staff_count,
    get_gfriends_index,
    get_media_folders,
    is_missing_overview,
    search_actor_info,
    sync_batch_async,
)
from .emby_actor_ui_kit import browse_folder, make_folder_row
from .emby_avatar_fetch import fetch_avatar_from_source, is_known_source, load_gfriends_index

# 演员管理器（主窗 + 设置 / 数据源测试 / 演员详情 / 选择媒体库 等子窗口）整体字号放大一号。
# 走 QSS 而非 setFont：Qt 里样式表的 font-size 会覆盖控件字体，且样式表沿 QObject 父子链
# 级联——有父窗口的子对话框一并生效；设置/数据源测试是无父独立顶层窗口，各自再设一条
# 同值规则，保证三处字号一致——setFont 对顶层窗口不继承，只对子控件生效。
_FONT_SIZE_STEP = 1


def _ui_font_pt(step: int | None = None) -> str:
    """返回「应用默认字号 + step」的磅值文本，供 QSS `font-size` 使用。

    step 缺省取模块级 `_FONT_SIZE_STEP`（运行时读取，便于测试改档）。
    基准取 `QApplication.font()`，随系统/主界面字号浮动；应用若用像素字号
    （pointSize <= 0）按 96dpi 折算成磅值，两者都取不到时以 9pt 为基准。
    窗口标题栏文字（Emby/Jellyfin演员管理器 / Emby/Jellyfin 演员设置）由系统窗口框绘制，
    不受 QSS 影响，故不在本项放大范围内。
    """
    if step is None:
        step = _FONT_SIZE_STEP
    font = QApplication.font()
    pt = font.pointSizeF()
    if pt <= 0:
        px = font.pixelSize()
        pt = px * 72.0 / 96.0 if px > 0 else 9.0
    return f"{pt + step:g}pt"


def _child_dialog_qss() -> str:
    """无父独立子窗口自带的 QSS：放大一号字号 + 蓝色主按钮。

    与 `EmbyActorManagerDialog._load_stylesheet()` 的同名规则同值。数据源测试窗与演员详情窗
    都是 parent=None 的独立顶层窗口，收不到管理器的样式表级联，故各自必须带一份。
    """
    return (
        f"QWidget {{ font-size: {_ui_font_pt()}; }}"
        "QPushButton#btnPrimary { background-color: #1565c0; color: #ffffff; }"
        "QPushButton#btnPrimary:hover { background-color: #1976d2; }"
    )


class _FlushLogTextEdit(QPlainTextEdit):
    """运行日志框：滚动条拖到最底时末行文字底边正好贴住视口底边，下方不留空白。

    现象（最小化 >9 行 / 最大化 >11 行，日志下方恒有 10~20px 空白）与根因：Qt 的竖向
    滚动按**整行**换档（一档一个行距，单位不是像素），而它给竖向滚动条算的每页行数
    比视口真正装得下的整行数少一行——`pageStep = (视口高 - 1) // 行距`（离屏实测：
    视口 120/行距 15 → pageStep 7 而非 8；90 → 5 而非 6；84（非整除）→ 5）。于是滚到
    上限时，末行下面恒空出一整行（视口 120、行距 15 实测 15px，即用户报的 10~20px），
    视口高不是行距整数倍时再多空出「视口高 % 行距」（实测 84 → 9px）。

    空白由两个独立来源叠加而成，各治各的：

    1. 「整行」部分——Qt 自己少算的那一行（`_flush_tail`）。每次内容/视口/滚动范围
       变化后，按公式把滚动上限压到「末行贴视口底」的那一档。滚动上限本来就是 Qt
       少算一行造成的，压到贴底档并不少给任何一行内容：用户仍能上滚看全部历史，
       末行也不会被裁掉（贴底档取的是位移够用的最小档）。
    2. 「亚行」部分——视口高除不尽行距时那点余量。Qt 只能整行换档，这部分压滚动
       上限压不掉，只能让视口高度落到行距整数倍：正常走 `_fit_visible_rows` 时由
       本控件的文档边距归零顺带达成（见下），余下情形由对话框的
       `_snap_log_viewport_to_whole_lines`（缩日志窗格、余量给演员表）与本控件的
       `_absorb_viewport_residue`（窗格已到 `minimumSizeHint` 缩不动时并进下侧视口
       边距）兜底。

    文档边距归零（原 4px 视觉留白改由 `setViewportMargins` 给出）正是为了第 2 条的
    第一段：文档边距是尾部空白的一部分（首块自带上边距、末块高度里多含同尺寸下边
    距），归零后 `_fit_visible_rows` 的目标视口 `行数 x 行距 + 文档边距` 恰好等于
    `行数 x 行距`——`log_chrome` 是实测值、已含视口边距，故最终
    `viewport().height()` 精确落在整行上。视口边距属于 chrome，会被 `log_chrome`
    扣掉，不参与 Qt 的滚动余量。

    量法（Qt 没给可用的滚动位移接口，但换算关系是确定的）：文档内容底 = 各块
    `blockBoundingRect` 高度之和（离屏实测九种场景——单行块、换行块、空块、尾部空块、
    500 块上限——该和都精确等于「可视行数 x 行距」）；滚动位移 = 档位 x 行距。故
    贴底所需档位 = `ceil((内容底 - 视口高) / 行距)`，内容不满视口、或 Qt 自己的上限
    已经更严（取数/换行等场合）时一律不动。
    """

    # 文档边距归零后，用视口边距补回同样的视觉留白（只影响 chrome，不参与滚动计算）
    _INSET = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flush_busy = False
        self._flush_queued = False
        self._inset_bottom = self._INSET  # 当前下侧视口边距（余量吸收后会大于 _INSET）
        self.document().setDocumentMargin(0.0)
        self.setViewportMargins(self._INSET, self._INSET, self._INSET, self._inset_bottom)
        # 三类变化都要重算贴底档：内容增删（含 maximumBlockCount 淘汰旧块）改内容底、
        # 视口几何改每档能滚多远、Qt 自己重算滚动范围会把上限放回「多一行」那档。
        self.document().contentsChange.connect(self._schedule_flush)
        self.verticalScrollBar().rangeChanged.connect(self._schedule_flush)
        self.viewport().installEventFilter(self)

    def eventFilter(self, a0, a1):
        # 竖向滚动条显隐会只改视口高度而不改控件高度（不经过 resizeEvent），须另行接住
        if a1 is not None and a1.type() == QEvent.Type.Resize and a0 is self.viewport():
            self._schedule_flush()
        return super().eventFilter(a0, a1)

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._schedule_flush()

    def _schedule_flush(self, *_args) -> None:
        """合并同拍多次触发只排一次：压上限会再发 rangeChanged，不排则事件风暴。"""
        if self._flush_queued:
            return
        self._flush_queued = True
        QTimer.singleShot(0, self._flush_tick)

    def _flush_tick(self) -> None:
        self._flush_queued = False
        self._flush_tail()

    def _absorb_viewport_residue(self, line_h: int) -> bool:
        """视口高不是行距整数倍时，把这点余量并进下侧视口边距，视口即落到整行上。

        Qt 只能整行换档，视口高与行距除不尽时，末行下方恒差「视口高 % 行距」，
        滚动上限再怎么压都消不掉。对话框那边会把日志窗格缩到整行（`_snap_log_
        viewport_to_whole_lines`，余量给演员表），只有窗格已到 `minimumSizeHint`
        缩不动时（高度不够、行高对齐 bail 的窄窗）才落到这里：边距只影响可视区
        高度、不影响控件高度与滚动范围，末行照样贴可视区底边。

        `vp0`（边距左右对称时的可视区高度）只由控件高度决定，故目标边距是控件
        高度的单值函数，一轮即收敛、不会来回摆：视口缩进余量后正是行距整数倍，
        `vp0` 仍不变，下一轮算出同一个目标即空操作。
        """
        vp = self.viewport().height()
        if vp <= 0:
            return False
        vp0 = vp + self._inset_bottom - self._INSET
        target = self._INSET + vp0 % line_h
        if target == self._inset_bottom:
            return False
        self._inset_bottom = target
        self.setViewportMargins(self._INSET, self._INSET, self._INSET, target)
        return True

    def _flush_tail(self) -> None:
        """把滚动上限压到「末行贴视口底」的那一档，消掉日志下方的空白。"""
        if self._flush_busy:
            return
        try:
            line_h = self.fontMetrics().lineSpacing()
            vp = self.viewport().height()
            if line_h <= 0 or vp <= 0:
                return
            if self._absorb_viewport_residue(line_h):
                return  # 视口高度已变，贴底档留到下一轮（视口 resize 会再排一次）
            bar = self.verticalScrollBar()
            if bar.maximum() <= 0:
                return  # 空文档 / 内容不满视口：没有「滚到底」可言
            bottom = 0.0
            block = self.document().begin()
            while block.isValid():
                bottom += self.blockBoundingRect(block).height()
                block = block.next()
            need = bottom - vp  # 末行贴视口底所需的滚动位移（像素）
            if need <= 0:
                return  # 内容不满视口
            flush_at = int(-(-need // line_h))  # ceil(need / 行距)：够用的最小档位
            if flush_at >= bar.maximum():
                return  # Qt 自己的上限已经够严（甚至更严），不动
            self._flush_busy = True
            try:
                bar.setMaximum(flush_at)  # Qt 会把 value 钳进新范围
            finally:
                self._flush_busy = False
        except (RuntimeError, AttributeError):
            pass  # C++ 对象已销毁等竞态：纯外观调整，静默放弃


DEFAULT_CLEAN_RULES = clean_rules.DEFAULT_CLEAN_RULES
"""数据清洗默认替换规则: 两条 minnano 占位文案(半角/全角逗号)替换为空, 始终保留。"""


def _ensure_default_clean_rules(
    cleaned: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """补齐默认规则: 缺失的默认原始数值追加到末尾, 已有条目保持原顺序与替换值不变。

    保证「两条 minnano 占位规则始终保留」——用户误删后下次加载/保存自动补回。
    """
    return clean_rules._ensure_default_clean_rules(cleaned)


def _sanitize_clean_rules(rules: object) -> list[tuple[str, str]]:
    """清洗规则归一化: config 存盘形态(list[list[str]])/用户输入统一成有效 (原始, 替换) 序列。

    原始数值为空或非字符串的行丢弃(空行视为未填完); 替换数值非字符串时按空串处理
    (即删除原始数值)。供对话框回读与扫描口径共用。
    """
    return clean_rules._sanitize_clean_rules(rules)


def load_clean_rules() -> list[tuple[str, str]]:
    """读出上次保存的清洗替换规则; 无配置/非法时返回默认规则, 缺失的默认条目自动补齐。

    数据清洗窗口弹出时默认加载本函数返回值, 故首开即见两条 minnano 占位规则。
    """
    return clean_rules.load_clean_rules(manager.config)


def save_clean_rules(rules: object) -> list[tuple[str, str]]:
    """持久化用户确认的清洗替换规则, 返回归一化后的规则。失败时静默返回归一化结果。

    保存时自动补齐缺失的默认规则, 保证两条 minnano 占位规则始终保留。
    """
    return clean_rules.save_clean_rules(rules, manager)


def format_detail_cell_text(overview: object) -> str:
    """详情列表格展示文本：去 <br>/残留标签/占位字符，仅展示层清洗，不改数据。

    - 空、纯空白、“(无)”/“（无）”一律置空（不再显示“（无）”）；
    - “<br>”变体先转空格，再剥除其余 <...> 标签（含截图中的截断“<b...”）；
    - 剥除“(无)”/“（无）”残留与“=”装饰线（“====== 个人资料 ======”只留文字）；
    - 空白坍缩后截断 80 字 + “...”，空结果返回空串。
    """
    return clean_rules.format_detail_cell_text(overview)


def scan_actor_data_noise(actors: list[ActorInfo], rules: object | None = None) -> list[tuple[ActorInfo, str, bool]]:
    """议题 #149: 扫描需要清洗的演员——简介含历史噪声(清洗后有变化)或生日非法(0000-00-00 等)。

    返回 (actor, 清洗后简介, 是否重置生日) 三元组; 生日为 Emby 未设置零值 0001-01-01
    或可被 normalize_premiere_date 正常解析时不算噪声。rules 为用户自定义
    (原始数值, 替换数值) 序列, 为空时仅走内置清洗(旧口径, 保证测试与兼容)。
    """
    return clean_rules.scan_actor_data_noise(actors, rules)


"""数据清洗默认替换规则: 两条 minnano 占位文案(半角/全角逗号)替换为空, 始终保留。"""


class LibrarySelectDialog(QDialog):
    # 默认最小 480x320；20 行时约 618x412(宽按 3:2)，不超过屏幕可用区 85%。
    # 议题 #146: 默认最小尺寸只够 ~7 行, 媒体库多时需滚动半屏。
    # 现按库数自适应初始大小(最多同时展示 20 行, 宽高 3:2, 不超过屏幕可用区 85%)。
    # 议题 #156: 行高由 item 显式 sizeHint 钉死为复选框高度, 并预留横向滚动条空间——
    # 此前行高靠估算、与实际渲染行高无确定关系, Windows 上 20 行预算只容得下 19 行。
    MAX_VISIBLE_ROWS = 20
    MIN_WIDTH = 480
    MIN_HEIGHT = 320

    @staticmethod
    def initial_size(
        row_h: int, visible_rows: int, chrome_h: int, avail_w: int, avail_h: int, slack: int = 12
    ) -> tuple[int, int]:
        """计算对话框初始宽高: 高 = chrome + 可见行 + slack, 宽按 3:2, 双向钳制到屏幕可用区 85%。

        纯函数便于测试: chrome_h 为除列表可视区外的窗口内容高度(layout sizeHint 差值);
        slack 覆盖列表边框与可能出现的横向滚动条高度(议题 #156)。
        """
        target_h = chrome_h + visible_rows * row_h + slack
        # 整体向上缩进一行汉族的高度（约 20px）
        target_h = max(LibrarySelectDialog.MIN_HEIGHT, target_h - 20)
        target_w = int(round(target_h * 3 / 2))
        target_w = max(LibrarySelectDialog.MIN_WIDTH, min(target_w, int(avail_w * 0.85)))
        target_h = max(LibrarySelectDialog.MIN_HEIGHT, min(target_h, int(avail_h * 0.85)))
        return target_w, target_h

    def __init__(self, libraries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择媒体库")
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMinimumHeight(self.MIN_HEIGHT)
        # 议题 #156: 合集(boxsets)是 Emby 自动创建的空壳库(无演员/标签), 默认不展示;
        # 极端情况下全部库都是合集时回退展示原始列表, 避免空对话框
        filtered = [lib for lib in libraries if (lib.get("CollectionType") or "") != "boxsets"]
        self._hidden_boxsets = len(libraries) - len(filtered)
        self._libraries = filtered or list(libraries)
        self._checkboxes: list[QCheckBox] = []
        self._centered_once = False
        self._init_ui()
        avail = self._apply_initial_size()
        self._center_on_screen(avail)

    def _apply_initial_size(self):
        parent = self.parentWidget()
        screen_obj = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        available = screen_obj.availableGeometry()
        count = self.list_widget.count()
        # 议题 #156: 行高取 item 显式 sizeHint(在 _init_ui 中 setSizeHint 钉死), 不再估算
        row_h = self.list_widget.sizeHintForRow(0) if count else 26
        visible = max(1, min(count, self.MAX_VISIBLE_ROWS))
        chrome_h = max(0, self.layout().sizeHint().height() - self.list_widget.sizeHint().height())
        # 预留横向滚动条高度: 长库名触发横向滚动条时会吃掉约一行可视高度
        slack = 12 + self.list_widget.horizontalScrollBar().sizeHint().height()
        self.resize(*self.initial_size(row_h, visible, chrome_h, available.width(), available.height(), slack))
        return available

    def _center_on_screen(self, avail=None, *, allow_defer: bool = True) -> None:
        """打开默认居于屏幕正中央(与管理器主窗同款口径: 以外框 frameGeometry 为准)。"""
        # 统一走 mdcx.utils.window_center 的唯一实现（外框 frameGeometry 口径）。
        center_on_screen(self, avail, allow_defer=allow_defer)

    def showEvent(self, event):
        super().showEvent(event)
        # 严格居中只做首次: 用户手动挪过之后再次 show 不拽回正中。
        try:
            if not getattr(self, "_centered_once", False):
                self._centered_once = True
                self._center_on_screen(allow_defer=False)
        except Exception:
            pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        count = len(self._libraries)
        # 议题 #156: 隐藏合集库时在计数里明说, 避免"库数对不上"的疑惑
        hidden_note = f"，已隐藏 {self._hidden_boxsets} 个合集库" if self._hidden_boxsets else ""
        label = QLabel(f"选择要获取演员的媒体库（共 {count} 个{hidden_note}，默认全选）：")
        layout.addWidget(label)
        self.list_widget = QListWidget()
        for lib in self._libraries:
            name = lib.get("Name", "未知")
            ctype = lib.get("CollectionType", "")
            display = f"{name}  [{ctype}]" if ctype else name
            cb = QCheckBox(display)
            cb.setChecked(True)
            self._checkboxes.append(cb)
            item = QListWidgetItem()
            # 议题 #156: 行高钉死为复选框高度, 使 _apply_initial_size 的行数预算与实际渲染一致
            item.setSizeHint(cb.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, cb)
        layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("取消全选")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)
        layout.addLayout(btn_layout)

    def _set_all(self, checked: bool):
        for cb in self._checkboxes:
            cb.setChecked(checked)

    def get_selected_ids(self) -> list[str]:
        selected = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked() and i < len(self._libraries):
                selected.append(self._libraries[i].get("Id", ""))
        return selected


class _WorkerCancelled(Exception):
    """后台协程被关窗/停止取消，不向用户弹错误。"""


# 议题 #175: wait 超时后把仍在跑的 QThread 从窗口父级卸下，并保住 Python 引用，
# 避免 WA_DeleteOnClose 拆掉 C++ 线程对象导致整个进程 abort。
_ORPHAN_WORKER_THREADS: set[QThread] = set()

# 同步（阻塞）业务函数的专用线程池：与 AsyncBackgroundExecutor 刻意分开，
# 后者跑在共享后台事件循环上，塞阻塞调用会把整条循环卡死。此处只承载
# _run_blocking 的任务，由 QThread 侧轮询 + abort 收尾。
_BLOCKING_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="mdcx-blocking")


def _detach_running_thread(thread: QThread) -> None:
    thread.setParent(None)
    _ORPHAN_WORKER_THREADS.add(thread)

    def _drop(_checked: bool = False, *, _t=thread) -> None:
        _ORPHAN_WORKER_THREADS.discard(_t)
        _t.deleteLater()

    thread.finished.connect(_drop)


class _CancellableWorkerThread(QThread):
    """议题 #175: 关窗时必须能打断 executor 阻塞，否则 QThread 随父窗口销毁会 abort 主进程。"""

    # _run_coro 轮询 future 的步长：abort 后最长再堵这么久 run() 必返回，
    # 线程正常 finish 走 wait 放行，不再依赖关窗超时的 detach 保命。
    _ABORT_POLL_INTERVAL = 0.2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._future = None
        self._lock = threading.Lock()
        self._abort_requested = threading.Event()

    def cancel(self):
        self.abort()

    def abort(self):
        # 先立 flag 再 cancel：即使协程卡在不可取消的原生阻塞里，
        # _run_coro 的轮询也能看到 flag 自行退出，run() 不再无限堵在 result()。
        self._abort_requested.set()
        with self._lock:
            future = self._future
        if future is not None and not future.done():
            future.cancel()

    def _await_future(self, future):
        """轮询等待已登记的 future，abort 后立即按取消返回（不无限堵住 run()）。"""
        try:
            while True:
                try:
                    return future.result(timeout=self._ABORT_POLL_INTERVAL)
                except concurrent.futures.TimeoutError:
                    # 未完成且关窗/abort 已请求：不等协程了，直接按取消返回，
                    # run() 退出 → finished 正常发射 → wait() 放行。
                    if self._abort_requested.is_set():
                        raise _WorkerCancelled("关窗/停止时放弃等待后台协程")
                    continue
        except (concurrent.futures.CancelledError, asyncio.CancelledError) as e:
            raise _WorkerCancelled from e
        finally:
            with self._lock:
                self._future = None

    def _run_coro(self, coro):
        future = executor.submit(coro)
        with self._lock:
            self._future = future
        return self._await_future(future)

    def _run_blocking(self, fn, *args):
        """_run_coro 的同步版：把阻塞函数也丢进线程池，从而同样可被 abort 打断。

        同步业务函数（如 sync_actor）若直接在 run() 里裸调，卡在网络请求上时
        abort() 无从下手，关窗只能干等超时；统一登记 future 后，_await_future
        的轮询看到 abort 标记就立刻收尾，run() 返回 → finished 发射 → wait() 放行。

        不能复用 ``executor``（AsyncBackgroundExecutor）：它只收协程，且在它
        的后台事件循环里跑阻塞函数会卡住整条共享循环。故用独立的线程池。
        """
        future = _BLOCKING_EXECUTOR.submit(fn, *args)
        with self._lock:
            self._future = future
        return self._await_future(future)


class FetchActorsThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    fetch_done = Signal(list, int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library_ids = None

    def run(self):
        try:
            actors, raw_count = self._run_coro(
                fetch_all_actors(
                    filter_actor_only=manager.config.actor_filter_only,
                    deduplicate=manager.config.actor_deduplicate,
                    parent_ids=self.library_ids,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                )
            )
            # 总数(含导演/制片/编剧等)。议题 #158: 这里原先无条件再拉一次全量
            # /Persons(真机 1.4W 人、单次 1.6s 的重端点)；未勾选「获取演员类型」时
            # 主查询拿到的就是全量名单, 再拉一次纯属重复重查询。改用带 60s 短缓存的
            # get_all_staff_count, 复用主查询结果。
            all_staff_count = self._run_coro(get_all_staff_count())
            self.fetch_done.emit(actors, raw_count, all_staff_count)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


class PreparePreviewThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    preview_done = Signal(list)
    error = Signal(str)

    _INFO_PLACEHOLDER = "无维基百科信息"

    @classmethod
    def _is_missing_image(cls, a: ActorInfo) -> bool:
        """是否缺头像: 服务器无 Primary 头像标签。"""
        return not getattr(a, "has_image", False)

    @classmethod
    def _is_missing_info(cls, a: ActorInfo) -> bool:
        """是否缺简介: 无简介, 或简介仅剩「无维基百科信息」占位文案。

        #147: 该判口径必须与「统计栏缺简介」保持一致——占位简介按缺处理,
        否则取数模式选中的数与统计栏分项对不上。实现委托模型层
        is_missing_overview, 避免两处各写一遍造成漂移。
        """
        return is_missing_overview(a)

    @classmethod
    def select_targets(cls, actors: list[ActorInfo], mode: str) -> list[ActorInfo]:
        """议题 #127: 按获取模式筛出需要处理的演员子集, 避免无效人次的遍历与服务器的复核。

        - missing_image: 仅缺头像的演员
        - missing_info : 仅缺简介的演员（含简介只剩占位文案的情况）
        - missing_all  : 缺头像或缺简介的并集
        - missing_both : 缺头像且缺简介的交集（议题 #155，对应统计栏「全缺」）
        - force_*      : 用户显式选择「重新获取」, 不做筛选
        """
        if mode.startswith("force"):
            return list(actors)

        if mode == "missing_both":
            return [a for a in actors if cls._is_missing_image(a) and cls._is_missing_info(a)]

        want_image = mode in ("missing_all", "missing_image")
        want_info = mode in ("missing_all", "missing_info")

        return [
            a for a in actors if (want_image and cls._is_missing_image(a)) or (want_info and cls._is_missing_info(a))
        ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []
        self.targets: list[ActorInfo] | None = None
        self.mode = "missing_all"
        self.gfriends_index = None
        self.cache_dir = resources.u("emby_actor_cache")
        self.image_sources = ["gfriends", "graphis", "minnano", "local"]
        self.local_avatar_dir = ""
        self._local_avatar_index: dict[str, str] | None = None
        self._cancel = False

    def cancel(self):
        # 「停止获取」只设标志，等当前演员收尾后预览结果仍回填；关窗走 abort() 打断阻塞。
        self._cancel = True

    def run(self):
        try:
            from .minnano_crawler import load_cache as minnano_load_cache

            minnano_load_cache()
            targets = self.targets if self.targets is not None else self.select_targets(self.actors, self.mode)
            total = len(targets)
            if total == 0:
                self.preview_done.emit(self.actors)
                return
            need_image = self.mode in ("missing_all", "missing_image", "missing_both", "force_all", "force_image")
            need_info = self.mode in (
                "missing_all",
                "missing_info",
                "missing_both",
                "force_all",
                "force_info",
                "force_overview",
            )
            force = "force" in self.mode
            cancelled = self._run_coro(self._process_all(targets, need_image, need_info, force, total))
            if not cancelled:
                self.progress.emit(total, total, "预览数据准备完成")
            self.preview_done.emit(self.actors)
        except _WorkerCancelled:
            return
        except Exception:
            import traceback

            self.error.emit(f"获取数据失败: {traceback.format_exc()}")

    async def _process_all(
        self, targets: list[ActorInfo], need_image: bool, need_info: bool, force: bool, total: int
    ) -> bool:
        """在单个 event loop 内并发处理所有演员，避免多线程多 loop 并发共享 async_client。"""
        if need_image and "local" in self.image_sources and self.local_avatar_dir:
            self.progress.emit(0, total, "扫描本地头像目录...")
            self._local_avatar_index = await asyncio.to_thread(build_local_avatar_index, self.local_avatar_dir)

        sem = asyncio.Semaphore(10)

        async def guarded(actor: ActorInfo) -> ActorInfo:
            async with sem:
                try:
                    if need_image:
                        await self._try_fetch_image(actor, force)
                    if need_info:
                        await self._try_fetch_info(actor, force)
                except Exception:
                    import traceback

                    from ..signals import signal

                    signal.show_log_text(f"🔶 演员处理异常: {actor.name}: {traceback.format_exc()}")
                return actor

        completed = 0
        cancelled = False
        tasks = [guarded(actor) for actor in targets]
        for coro in asyncio.as_completed(tasks):
            if self._cancel:
                cancelled = True
                break
            completed += 1
            actor = await coro
            self.progress.emit(completed, total, f"处理中: {actor.name} ({completed}/{total})")
        return cancelled

    async def _try_fetch_image(self, actor: ActorInfo, force: bool):
        if not force and actor.has_image:
            return
        graphis_attempted = False
        graphis_backdrop: str | None = None
        # 头像：按配置源顺序第一个命中即采用（保留用户设置优先级）
        for src in self.image_sources:
            if src == "graphis":
                graphis_attempted = True
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[0]:
                    actor.new_image_path = graphis_result[0]
                    actor.need_update_image = True
                    graphis_backdrop = graphis_result[1]
                    break
                continue
            result = await self._fetch_avatar_from(actor, src)
            if result:
                actor.new_image_path = result
                actor.need_update_image = True
                break
        # 背景图：头像命中不代表有背景（gfriends/local/minnano 均无背景），
        # 若仍缺背景，用 graphis 补——避免头像先命中导致背景永远无法补齐。
        # graphis 若已在头像循环尝试过，直接复用其结果，不重复请求。
        if not actor.has_backdrop and not actor.need_update_backdrop and "graphis" in self.image_sources:
            if graphis_backdrop:
                actor.new_backdrop_path = graphis_backdrop
                actor.need_update_backdrop = True
            elif not graphis_attempted:
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[1]:
                    actor.new_backdrop_path = graphis_result[1]
                    actor.need_update_backdrop = True

    async def _fetch_avatar_from(self, actor: ActorInfo, src: str) -> str | None:
        """从单个图源尝试获取头像路径；未命中返回 None。graphis 由 _try_fetch_image 特判处理。"""
        return await fetch_avatar_from_source(
            actor,
            src,
            gfriends_index=self.gfriends_index,
            cache_dir=self.cache_dir,
            local_avatar_dir=self.local_avatar_dir,
            local_avatar_index=self._local_avatar_index,
        )

    async def _try_fetch_info(self, actor: ActorInfo, force: bool):
        # 议题 #127: 简介缺失判定已由 select_targets 前置（列表阶段已带回 existing_overview，
        # 不再逐演员发 fetch_actor_detail 复核）；占位简介视为缺失需重新补全。
        if not force and actor.has_overview and self._INFO_PLACEHOLDER not in actor.existing_overview:
            return
        result = await search_actor_info(actor)
        if result:
            actor.need_update_info = True
        if getattr(self, "mode", "") == "force_overview":
            # 议题 #164: 「重新获取所有演员简介」只回写简介——清空其余 new_* 字段,
            # 同步出口(update_person_info)按真值逐字段写入, 出生日期/出生地/标签/
            # ProviderIds 均保持服务器原值; 简介没取到则不标记待同步。
            actor.new_taglines = []
            actor.new_production_year = None
            actor.new_premiere_date = ""
            actor.new_production_locations = []
            actor.new_provider_ids = {}
            actor.need_update_info = bool(actor.new_overview)


class SyncThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    actor_done = Signal(str, str, bool, str)  # (actor_id, name, success, msg)
    sync_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []

    def run(self):
        try:
            success, fail = self._run_coro(
                sync_batch_async(
                    self.actors,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                    actor_callback=lambda actor, ok, msg: self.actor_done.emit(actor.actor_id, actor.name, ok, msg),
                )
            )
            self.sync_done.emit(success, fail)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


class CleanDataThread(_CancellableWorkerThread):
    """议题 #149: 存量数据清洗(简介噪声/非法生日), 不经取数流程。"""

    progress = Signal(int, int, str)
    # 议题 #162: actor_done 携带失败原因——此前 msg 在回调处被丢弃, 清洗失败只剩计数
    actor_done = Signal(str, bool, str)  # (actor_id, success, 结果消息)
    clean_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[ActorInfo, str, bool]] = []

    def run(self):
        try:
            success, fail = self._run_coro(
                clean_actor_data_batch_async(
                    self.items,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                    actor_callback=lambda actor, ok, msg: self.actor_done.emit(actor.actor_id, ok, msg),
                )
            )
            self.clean_done.emit(success, fail)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


def _future_result_or(future, default):
    """取 Future 结果；协程异常时返回 default，避免异常传播到后台 loop 线程。"""
    try:
        return future.result()
    except Exception:
        return default


_OPEN_CLEAN_RULES_DIALOGS: dict = {}
"""存活的数据清洗规则独立窗(强引用注册表)。

`parent=None` 只切断 Qt 层级联, 切不断 Python 引用链——规则窗唯一的 Python
持有者原本是管理器 `_clean_rules_dialog`, 管理器关闭后被 GC 时会连带销毁
规则窗(离屏实测: 双双 `wrapper alive: False`)。注册表多持一份强引用,
随 `destroyed` 按 id 摘除(清理闭包只捕获 int, 不形成引用环), 保证两窗
关闭互不影响。"""


class DetailSyncThread(_CancellableWorkerThread):
    """演员详情窗口的「同步回写」任务线程。

    原先 ActorDetailDialog._run_sync 直接拉一根裸 threading.Thread：它不继承
    _CancellableWorkerThread，既没有 abort()/cancel() 可打断，也没有注册进
    _shutdown_worker_threads 的统一收尾，于是关窗只能干等、同步任务既停不掉
    也不会被回收。改为与其它工作线程同源后，abort() 能取消登记的 future，
    关窗亦可 wait + 必要时 detach 兜底（议题 #175 同一套保命手段）。
    """

    sync_done = Signal(object)

    def __init__(self, actor, sync_type: str, parent=None):
        super().__init__(parent)
        self._actor = actor
        self._sync_type = sync_type

    def run(self):
        from .emby_actor_manager import sync_actor

        try:
            result = self._run_blocking(sync_actor, self._actor, self._sync_type)
        except _WorkerCancelled:
            return
        except Exception:
            import traceback

            result = (False, f"同步异常: {traceback.format_exc()}")
        self.sync_done.emit(result)


class ActorCleanRulesDialog(QDialog):
    """数据清洗规则编辑窗: 全局 (原始数值 → 替换数值) 字面替换表, 确定后才实际清洗。

    独立顶层窗口(与演员管理器互不影响): 无父级、非模态, 可与管理器并存操作;
    最小化/关闭/移动不再级联影响对方。每次点击「数据清洗」都弹出本窗
    (含无待清洗数据时), 打开时装载上次保存的规则; 用户可编辑单元格、添加行、
    删除选中行, 窗口可拉伸缩小; 点确定则保存规则并关闭, 调用方据此执行实际清洗,
    点取消则不做任何改动。
    """

    def __init__(self, actors: list[ActorInfo] | None = None, parent=None):
        # 独立顶层窗口: parent 参数仅为兼容旧调用而保留, 不再传入——管理器
        # 最小化/关闭/遮挡不再级联影响规则窗口; 调用方用 show() 单例复用。
        super().__init__(None)
        self.setWindowTitle("数据清洗规则")
        self.setMinimumSize(640, 420)
        self.resize(720, 480)
        self.setSizeGripEnabled(True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 独立窗口随关闭销毁, 管理器侧 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet(f"QWidget {{ font-size: {_ui_font_pt()}; }}")
        self._centered_once = False
        self._actors = list(actors or [])
        layout = QVBoxLayout(self)

        hint = QLabel(
            "每行一条替换规则: 简介中出现「原始数值」时替换为「替换数值」"
            "(替换为空即删除该片段)。内置占位/非法生日清洗始终生效, 此处规则叠加其上。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["原始数值", "替换数值"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        add_btn = QPushButton("添加规则")
        add_btn.clicked.connect(self._on_add_row)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._on_delete_selected)
        default_btn = QPushButton("恢复默认")
        default_btn.setToolTip("填入内置 minnano 占位文案示例规则")
        default_btn.clicked.connect(self._on_restore_default)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addWidget(default_btn)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

        self.set_rules(load_clean_rules())
        try:
            self.table.itemChanged.disconnect(self._refresh_status)
        except (TypeError, RuntimeError):
            pass
        self.table.itemChanged.connect(self._refresh_status)
        self._refresh_status()

    def _hold_refresh(self):
        """批量改表时暂停 itemChanged → 状态刷新, 返回重连函数。"""
        try:
            self.table.itemChanged.disconnect(self._refresh_status)
        except (TypeError, RuntimeError):
            pass

    def _resume_refresh(self):
        try:
            self.table.itemChanged.disconnect(self._refresh_status)
        except (TypeError, RuntimeError):
            pass
        self.table.itemChanged.connect(self._refresh_status)
        self._refresh_status()

    def _on_add_row(self):
        self._hold_refresh()
        try:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(""))
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.editItem(self.table.item(row, 0))
        finally:
            self._resume_refresh()

    def _on_delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            # 无选中时删最后一行, 避免用户面对空表无从下手
            if self.table.rowCount():
                rows = [self.table.rowCount() - 1]
        self._hold_refresh()
        try:
            for r in rows:
                self.table.removeRow(r)
        finally:
            self._resume_refresh()

    def _on_restore_default(self):
        self.set_rules(list(DEFAULT_CLEAN_RULES))

    def set_rules(self, rules: object):
        cleaned = _sanitize_clean_rules(rules)
        self._hold_refresh()
        try:
            self.table.setRowCount(0)
            for original, replacement in cleaned:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(original))
                self.table.setItem(row, 1, QTableWidgetItem(replacement))
        finally:
            self._resume_refresh()

    def rules(self) -> list[tuple[str, str]]:
        """返回表格当前有效规则(跳过原始数值空白行)。"""
        raw: list[tuple[str, str]] = []
        for row in range(self.table.rowCount()):
            orig_item = self.table.item(row, 0)
            repl_item = self.table.item(row, 1)
            raw.append(
                (
                    orig_item.text() if orig_item is not None else "",
                    repl_item.text() if repl_item is not None else "",
                )
            )
        return _sanitize_clean_rules(raw)

    def _refresh_status(self, *_args):
        try:
            count = len(scan_actor_data_noise(self._actors, self.rules()))
            self.status_label.setText(f"按当前规则将清洗 {count} 个演员(共 {len(self._actors)} 个)")
        except Exception:
            self.status_label.setText("")

    def _center_on_screen(self, avail=None, *, allow_defer: bool = True) -> None:
        """把窗口外框放到所在屏幕可用区的正中央(与演员详情窗同款口径)。"""
        # 统一走 mdcx.utils.window_center 的唯一实现（外框 frameGeometry 口径）。
        center_on_screen(self, avail, allow_defer=allow_defer)

    def showEvent(self, event):
        super().showEvent(event)
        # 严格居中只做首次: 用户手动挪过之后再次 show 不拽回正中。
        try:
            if not getattr(self, "_centered_once", False):
                self._centered_once = True
                self._center_on_screen()
        except Exception:
            pass


class EmbyActorManagerDialog(QDialog):
    _connect_result = Signal(object)
    _media_folders_result = Signal(object)
    _gfriends_result = Signal(object)
    # 双档可视行数：最大化/全屏 20 行演员 + 10 行日志，普通窗 15 行 + 8 行日志。
    # 对齐只许纯内部手段（行高 + 分隔条分配），窗格不锁、窗口几何不动（主界面同款）。
    TABLE_VISIBLE_ROWS = 20
    LOG_VISIBLE_LINES = 10
    NORMAL_TABLE_ROWS = 15
    NORMAL_LOG_LINES = 8
    # 按钮行高度：数据源测试窗 `_sync_panel_stretch` 同款——最大化/全屏时按
    # 对话框当前高度/基准高度比例拉升，还原恢复；只设 minimumHeight（不锁 max），
    # 宽度由 `_apply_button_widths` 管——两者正交。
    # 连接组左内边距 16：QSS 标题 `left:10 + padding 4 =14` 距组左，
    # 标签 x = 边距+1（组边框）；13→14 与标题文本左对齐后，用户要求再右移 3px，
    # 故 16→17；右 6/上下 4 不动。
    CONN_BASE_MARGINS = (16, 4, 6, 4)

    # 窄态专用的组标题覆盖样式（只挂到连接组这一个控件上，宽态清空即回全局值）：
    # 全局 QSS 是 `QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }`
    # （实测标题文字起点 ink x=20），这里局部覆盖为 left:0 + padding:0 2px，
    # 实测 ink x=8，与「连接Emby/Jellyfin」按钮内字体起点（按钮 x=1 + 边框/内边距 7）
    # 严格对齐；服务器地址标签同步 padding-left:1px（内容起点 x=2，叠加「服」字
    # 约 6px 字形左边距后首笔同为 x=8）。
    _CONN_TITLE_QSS = "QGroupBox::title { left: 0px; padding: 0 2px; }"

    def __init__(self, parent=None):
        # 不传 parent：始终保持独立顶层窗口。议题 #61——以主窗口为 parent 时，
        # 主窗口 hide 会级联隐藏 dialog，最大化 dialog 又会把主窗口带出。
        super().__init__(None)
        self.setWindowTitle("Emby/Jellyfin演员管理器")
        self.setMinimumSize(self._BASE_MIN_W, 720)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象，主窗口侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 初始落在最小尺寸上体验局促，默认取屏幕可用区 80%（离屏/无屏环境回退最小尺寸）
        # 启动居中：和软件主界面同款，以外框 frameGeometry 居中到可用区正中央。
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        if avail is not None:
            self.resize(max(1080, int(avail.width() * 0.8)), max(720, int(avail.height() * 0.8)))
        else:
            self.resize(1080, 720)
        self._center_on_screen(avail)
        # 最大化/最小化/还原不做任何定制：窗格不锁高度、不记普通态矩形、
        # 不复位几何，全走系统原生行为（主界面同款）。
        self.setSizeGripEnabled(True)
        self.setStyleSheet(self._load_stylesheet())
        self.cache_dir = resources.u("emby_actor_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._actors: list[ActorInfo] = []
        self._raw_count: int = 0
        self._all_staff_count: int = 0
        # 议题 #143: 计数方式为持久化配置, 重开管理器/重启后恢复
        self._show_unique: bool = manager.config.actor_count_mode == 1
        self._gfriends_index = None
        self._preview_thread = None
        self._sync_thread = None
        self._clean_thread = None
        self._clean_items: dict[str, tuple[str, bool]] = {}
        self._clean_failed: list[tuple[str, str]] = []  # 议题 #162: (actor_id, 失败消息)
        self._clean_rules: list[tuple[str, str]] = []
        self._fetch_thread = None
        self._refresh_thread = None
        # 独立子窗口单例引用（设置/数据源测试/数据清洗规则）：destroyed 信号负责清空
        self._settings_dialog = None
        self._test_dialog = None
        self._clean_rules_dialog = None
        # 演员详情独立窗口（与管理器互不干扰）：按 actor_id 常驻，可多开、
        # 随各自关闭销毁；destroyed 信号负责从字典摘除。
        self._detail_dialogs: dict[str, ActorDetailDialog] = {}
        # 议题 #25: 任务会话代数——取消/重启任务后旧线程的排队回调整体作废
        self._session_gen = 0
        self._failed_names: set[str] = set()
        self._log_file: Path | None = None
        # 获取演员列表支持未手动连接时自动连接：_connected 初始 False，_pending_auto_fetch
        # 标记“获取按钮触发的连接成功后继续走媒体库流程”；_pending_auto_preview
        # 标记“数据获取选项触发的链式流程（连接→取演员列表→取数预览）”。
        self._connected: bool = False
        self._pending_auto_fetch: bool = False
        self._pending_auto_preview: bool = False
        self._pending_auto_clean: bool = False
        self._pending_auto_export: bool = False
        self._emby_url: str = str(manager.config.emby_url or "")
        self._emby_key: str = manager.config.api_key or ""
        # 输入框修改自动保存（防抖）：每击键只重启计时，停顿 800ms 后写配置，
        # 避免逐字存盘刷爆 IO。
        self._conn_save_timer = QTimer(self)
        self._conn_save_timer.setSingleShot(True)
        self._conn_save_timer.setInterval(800)
        self._conn_save_timer.timeout.connect(self._auto_save_connection_fields)
        self._splitter = None
        # 用户亲手拖过分隔条后，本次打开不再自动重排（取数/缩放都不抢回）；
        # 对话框关闭即销毁、重开是新实例，天然恢复默认行数（数据源测试窗同款）。
        self._user_moved_splitter = False
        self._setting_splitter_sizes = False
        self._fit_verify_queued = False
        self._viewport_refit_queued = False
        self._list_widget = None
        self._log_widget = None
        self._conn_grid = None
        self._init_ui()
        self._connect_signals()
        self._open_log_file()
        # 按钮比例拉升的基准（数据源测试窗 `_dialog_base_h` 同款）：正常几何下的
        # 对话框高度 + 各按钮 sizeHint 高；最大化时 target = base × 当前/基准。
        self._dialog_base_h = max(1, self.height() or 720)
        self._conn_btn_base_h: dict[str, int] = {}
        for _name in self._CONN_BUTTON_NAMES:
            _w = getattr(self, _name, None)
            try:
                self._conn_btn_base_h[_name] = max(1, _w.sizeHint().height()) if _w is not None else 0
            except Exception:
                self._conn_btn_base_h[_name] = 0

    def _center_on_screen(self, avail=None, *, allow_defer: bool = True) -> None:
        """启动居中：和软件主界面同款，把外框整体放到可用区正中央。

        主界面同款两点：以 frameGeometry（含标题栏/边框）为准而非客户区；
        move() 收的是边框左上角，无需再补偿边框厚度。窗口比可用区还大时
        钳到可用区左上角，保证标题栏留在屏内抓得到。
        """
        # 统一走 mdcx.utils.window_center 的唯一实现（外框 frameGeometry 口径）。
        center_on_screen(self, avail, allow_defer=allow_defer)

    def _begin_session(self, thread) -> None:
        """任务线程发起时颁发代数；与对话框当前值一致才允许写回 UI/状态。"""
        self._session_gen += 1
        thread._session_gen = self._session_gen

    def _is_stale_session(self) -> bool:
        """回调入口守卫：sender 携带的会话代数已过期则返回 True（调用方直接丢弃）。"""
        gen = getattr(self.sender(), "_session_gen", None)
        return gen is not None and gen != self._session_gen

    def _load_stylesheet(self) -> str:
        # 首条 QWidget 规则统一下发放大后的字号：写在最前且只含 font-size，
        # 下方各控件规则（QGroupBox 加粗 / 按钮配色等）仍照常合并生效。
        # 控件自身样式表里若再写死 font-size 会盖掉本规则（故提示文字只留颜色）。
        # 滚动条沿用主窗口设置页同款 build_scrollbar_style：竖条宽 16px、直角实心滑块、
        # 滑块最小 44px，深浅主题跟随配置的 dark_mode 开关（与设置页同值）。
        try:
            dark = Switch.DARK_MODE in (manager.config.switch_on or [])
        except Exception:
            dark = False
        return f"""
        QWidget {{ font-size: {_ui_font_pt()}; }}
        QGroupBox {{ font-weight: bold; border: 1px solid #cccccc; border-radius: 4px; margin-top: 4px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QTableWidget {{ gridline-color: #e0e0e0; selection-background-color: #bbdefb; }}
        QTableWidget::item:selected {{ background-color: #42a5f5; color: #ffffff; }}
        QPushButton#btnSync {{ background-color: #2e7d32; color: #ffffff; font-weight: bold; }}
        QPushButton#btnSync:hover {{ background-color: #388e3c; }}
        QPushButton#btnDanger {{ background-color: #c62828; color: #ffffff; }}
        QPushButton#btnDanger:hover {{ background-color: #d32f2f; }}
        QPushButton#btnPrimary {{ background-color: #1565c0; color: #ffffff; }}
        QPushButton#btnPrimary:hover {{ background-color: #1976d2; }}
        """ + build_scrollbar_style(dark)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        # 顶部收紧：连接设置组上移，腾出纵向空间给演员表格
        # （最大化 20 行、普通窗 15 行完整显示）。
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(12, 4, 12, 6)
        self._build_connection_section(main_layout)
        splitter = QSplitter(Qt.Orientation.Vertical)
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self._build_actor_list(list_layout)
        splitter.addWidget(list_widget)
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self._build_log_section(log_layout)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)
        self._splitter = splitter
        self._list_widget = list_widget
        self._log_widget = log_widget
        # 分隔条完全交给用户与 stretch（4:1）：不锁窗格高度，最大化/最小化/还原
        # 全走系统原生行为（主界面同款）。子窗格不可折叠到 0，避免日志被压没。
        splitter.setChildrenCollapsible(False)
        # 用户亲手拖过后不再自动重排（数据源测试窗 _result_user_moved 同款）。
        splitter.splitterMoved.connect(self._on_splitter_moved)

        # 横向滚动条冒出时按真实视口宽重算列宽（见 eventFilter）。
        try:
            self.table.horizontalScrollBar().installEventFilter(self)
            self.log_text.horizontalScrollBar().installEventFilter(self)
            # 纵向滚动条显隐只改 viewport 几何：视口变化后补对行数（见 eventFilter）。
            log_viewport = self.log_text.viewport()
            assert log_viewport is not None
            log_viewport.installEventFilter(self)
        except Exception:
            pass

        # 底部状态栏：当前状态 + Emby 连接状态
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("未连接")
        main_layout.addWidget(self.status_bar)

        # 初始保持「总数: 」这类空白前缀, 有数据后再由 _update_statistics 填数字。
        # 所有显示用文本框内容优先从左展示（程序回填时无焦点 → 光标归 0）
        left_anchor_text_edits(self)

    def _set_status(self, message: str):
        connected = hasattr(self, "_connected") and self._connected
        prefix = "已连接" if connected else "未连接"
        self.status_bar.showMessage(f"{prefix} | {message}")

    def _set_progress(self, current: int, total: int, label: str) -> None:
        """把后台线程进度换算成百分比显示在底部状态栏，不占表格布局高度。

        以前这里用的是演员表布局里的 QProgressBar，显隐会吃掉/归还约 26px
        表格视口高度——该控件已彻底删除。状态栏是单行定高控件，改文字
        不触发任何布局变化，表格高度在获取中和完成后保持不动。
        """
        try:
            if total > 0:
                pct = max(0, min(100, int(current * 100 / total)))
                self._set_status(f"{label} {current}/{total}（{pct}%）")
        except (RuntimeError, AttributeError, TypeError, ValueError, ZeroDivisionError):
            pass

    def _build_connection_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("Emby/Jellyfin 连接设置")
        self._conn_group = group
        grid = QGridLayout(group)
        # 收紧连接组内边距/行距：整体上移，纵向少占约一行高度。
        grid.setContentsMargins(*self.CONN_BASE_MARGINS)
        self._conn_grid = grid
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(6)
        self._lbl_server = QLabel("服务器地址:")
        grid.addWidget(self._lbl_server, 0, 0)
        self.txt_url = QLineEdit(str(manager.config.emby_url or ""))
        self.txt_url.setPlaceholderText("http://192.168.1.100:8096")
        grid.addWidget(self.txt_url, 0, 1)
        grid.addWidget(QLabel("API 密钥:"), 0, 2)
        self.txt_api_key = QLineEdit(manager.config.api_key or "")
        self.txt_api_key.setPlaceholderText("Emby：管理后台 → 高级 → API 密钥；Jellyfin：控制台 → API 密钥")
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self.txt_api_key, 0, 3)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout = btn_layout
        self.btn_connect = QPushButton("连接Emby/Jellyfin")
        self.btn_connect.setObjectName("btnPrimary")
        btn_layout.addWidget(self.btn_connect)
        self.btn_fetch = QPushButton("获取演员列表")
        self.btn_fetch.setObjectName("btnPrimary")
        self.btn_fetch.setEnabled(True)
        btn_layout.addWidget(self.btn_fetch)
        self.cmb_fetch_mode = QComboBox()
        # 议题 #164: 按「单缺字段 → 双缺 → 并集 → 重新获取组」范围递增排序;
        # 去掉（并集）（交集）标注——名称已自明, 集合术语保留在 tooltip。
        self.cmb_fetch_mode.addItems(
            [
                "仅缺失简介",
                "仅缺失头像",
                "头像和简介都缺",
                "缺失头像或缺失简介",
                "重新获取所有演员详情",
                "重新获取所有演员简介",
                "重新获取所有演员头像",
                "重新获取所有演员头像和简介",
            ]
        )
        # 议题 #147: 明确「或=并集(缺任一即取)/且=交集(两者都缺)」, 并说明占位简介按缺失处理,
        # 与统计栏分项统一口径。议题 #155: 补「交集」独立入口, 与统计栏「全缺」分项对应。
        self.cmb_fetch_mode.setItemData(
            0, "仅缺简介的演员（简介仅剩「无维基百科信息」占位也按缺处理）", Qt.ItemDataRole.ToolTipRole
        )
        self.cmb_fetch_mode.setItemData(1, "仅缺头像的演员（含缺简介者，只要缺头像）", Qt.ItemDataRole.ToolTipRole)
        self.cmb_fetch_mode.setItemData(
            2,
            "缺头像 且 缺简介 = 交集（两者都缺才选取，对应统计栏「全缺」；占位简介按缺处理）",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.cmb_fetch_mode.setItemData(
            3, "缺头像 或 缺简介 = 并集（缺任其一即选取；全缺也在内）", Qt.ItemDataRole.ToolTipRole
        )
        # 议题 #149: 全量刷新简介/出生日期/出生地/标签等信息; 影片数来自服务器、
        # 头像交由第三方工具, 均不在本模式范围内。
        self.cmb_fetch_mode.setItemData(
            4,
            "不筛缺失，为全部演员 重新获取 简介/出生日期/出生地/标签（不动头像与影片数）",
            Qt.ItemDataRole.ToolTipRole,
        )
        # 议题 #164: 仅简介的重新获取——同步出口按真值逐字段写入, 只回写简介,
        # 不覆盖手动修正过的出生日期/出生地/标签。
        self.cmb_fetch_mode.setItemData(
            5,
            "不筛缺失，为全部演员 重新获取 简介（只回写简介，出生日期/出生地/标签/头像/影片数均不动）",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.cmb_fetch_mode.setItemData(6, "不筛缺失，为全部演员 重新获取 头像", Qt.ItemDataRole.ToolTipRole)
        self.cmb_fetch_mode.setItemData(7, "不筛缺失，为全部演员 重新获取 头像+简介", Qt.ItemDataRole.ToolTipRole)
        # 议题 #164: 重排后默认项显式锚定并集(index 3)——保持"打开即最通用模式"的既有行为
        self.cmb_fetch_mode.setCurrentIndex(3)
        # 最小宽 1080 预算：下拉 220→210（-10，仍 > sizeHint 199，最长项不裁字）
        self.cmb_fetch_mode.setFixedWidth(210)
        btn_layout.addWidget(self.cmb_fetch_mode)
        # 数据工具下拉框：数据获取（原「根据设定获取数据」按钮并入）/数据清洗/
        # 数据导出/数据导入，按此顺序排列；默认选中数据获取。
        self.cmb_data_tool = QComboBox()
        self.cmb_data_tool.addItems(["数据获取", "数据清洗", "数据导出", "数据导入"])
        self.cmb_data_tool.setItemData(
            0, "按获取模式取数：缺失补全或全量重新获取（取数中再次选择可停止）", Qt.ItemDataRole.ToolTipRole
        )
        self.cmb_data_tool.setItemData(1, "原地清洗服务器存量演员数据（不经取数流程）", Qt.ItemDataRole.ToolTipRole)
        self.cmb_data_tool.setItemData(2, "把已获取的演员数据导出为 xlsx 表格", Qt.ItemDataRole.ToolTipRole)
        self.cmb_data_tool.setItemData(3, "从 xlsx 表格导入演员数据", Qt.ItemDataRole.ToolTipRole)
        self.cmb_data_tool.setToolTip("数据工具：按需选择数据获取/数据清洗/数据导出/数据导入")
        # 最小宽 1080 预算（窄态默认）：下拉按自身 sizeHint 定宽（恰容下文字+箭头，
        # 不裁字）；腾出的空间由「数据源测试」「清空缓存目录」收窄补回，宽态恢复自适应。
        btn_layout.addWidget(self.cmb_data_tool)
        # 兼容别名：既有测试与按钮行高度逻辑仍通过 btn_clean 取到本下拉框。
        self.btn_clean = self.cmb_data_tool
        self.btn_sync = QPushButton("开始全部更新同步")
        self.btn_sync.setObjectName("btnSync")
        self.btn_sync.setEnabled(False)
        btn_layout.addWidget(self.btn_sync)
        self._help_single = "使用说明：①填写地址和密钥→②连接/获取演员列表→③选择模式获取数据→④绿色行==待更新→⑤同步到服务器，双击行查看编辑详情"
        # 窄态（还原/常规/最小化）固定两行：在「③选择模式获取数据」处断行，
        # 两行等长，故窄态按钮行省下的就是「单行宽度 - 两行宽度」这一段，
        # 窗口最小宽度可据此下调（见 _narrow_min_width）。宽态仍用单行原文。
        # 断点按用户指定：第一行结尾「③选择模式获」，第二行以「取数据」开头。
        self._help_narrow = (
            "使用说明：①填写地址和密钥→②连接/获取演员列表→③选择模式获\n"
            "取数据→④绿色行==待更新→⑤同步到服务器，双击行查看编辑详情"
        )
        help_label = QLabel(self._help_single)
        self.help_label = help_label
        # 不写 font-size：跟随 _load_stylesheet 里放大后的统一字号，写死 12px 会反盖回去。
        # 位于「开始全部更新同步」按钮右侧（按钮行内），向上向右收纳以节省纵向空间；
        # 允许折行：单行长文本不折行时会撑大对话框最小宽度，折行后最小宽度回到按钮行决定。
        # 窄窗两行（断点按实测字宽动态平衡）、宽窗一行：见 _update_help_line_break（resize/show 时按实宽切换）。
        help_label.setWordWrap(True)
        help_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 关键：开启 wordWrap 的 QLabel，其 sizeHint/minimumSizeHint 仍按【单行】文字宽返回，
        # 布局据此算出的最小宽是单行态（实测 1383px），而非两行态（963+420=1383 同值但
        # 那是巧合；真正需要的是让布局认两行后的宽度）。这里显式压住 minimumWidth：
        # 窄态由 _narrow_help_width 给两行实宽、宽态归零（恢复自适应），
        # 使布局最小宽随窗口状态切换，而不是恒按单行计。
        help_label.setMinimumWidth(0)
        # 窄态下 help 改按自身文字宽度定宽（Maximum/Fixed）：它此前是 Expanding，
        # 会把整行富余宽度全吸收，于是「使用说明→数据源测试」之间出现几十像素
        # 的大缝（实测 max_gap=23 ~ 37），用户看到的“按钮之间有空白”其实全来自它。
        # 定宽后富余宽度落到按钮行末尾（帮助 label 右侧空白），窄态两段按钮互贴。
        # 宽态仍在 _apply_button_row_compact 里恢复 Expanding，最大化逐像素不变。
        help_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        help_label.setStyleSheet("color: #888888; padding: 0;")
        btn_layout.addWidget(help_label, 1)
        # 右间距与左间距对称：help 已是 Expanding stretch=1，吃掉全部富余宽度；
        # 此处再加一个零 stretch 的 addStretch 只会在右侧多占一份 spacing，
        # 使「详情→数据源测试」变成两份间距、与「同步→使用说明」的一份不对称。
        # 删掉后两侧都只剩一份 layout spacing（4px）：最小化图标态量到的是 4px；
        # 最大化时省下的 4px 进了不可见的 label 空宽，文字与按钮可见像素不动。
        self.btn_test_source = QPushButton("数据源测试")
        self.btn_test_source.setObjectName("btnPrimary")
        btn_layout.addWidget(self.btn_test_source)
        self.btn_clear_cache = QPushButton("清空缓存目录")
        self.btn_clear_cache.setObjectName("btnPrimary")
        btn_layout.addWidget(self.btn_clear_cache)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("btnPrimary")
        # 窄态宽度由 _apply_button_widths 按窗口状态统一管（等宽组取半），此处保持自适应。
        btn_layout.addWidget(self.btn_settings)
        grid.addLayout(btn_layout, 1, 0, 1, 4)
        parent_layout.addWidget(group)

    def _build_actor_list(self, parent_layout: QVBoxLayout):
        parent_layout.setSpacing(2)
        parent_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout = QHBoxLayout()
        # 收紧统计栏上下边距：腾出的纵向空间让演员表格正好显示整行数
        # （最大化 20 行、普通窗 15 行）。
        stats_layout.setSpacing(2)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_all_staff = QLabel("总数: ")
        self.lbl_all_staff.setToolTip(
            "全服演职人员总数（含导演/编剧/制片等非演出人员），不受媒体库选择、「仅演员」开关、"
            "计数方式、筛选与搜索影响。恒为全库原始条目数。"
        )
        self.lbl_total = QLabel("演员: ")
        self.lbl_total.setToolTip(
            "当前列表演员数（受媒体库选择、「仅演员」开关、计数方式影响；不受筛选与搜索影响）。"
            "唯一名字数模式下 完整+缺头像+缺简介+全缺=演员；"
            "原始条目数模式 + 去重抓取下 上式+重复=演员（重复条目细节已丢弃，差额即重复数）；"
            "原始条目数模式 + 未去重抓取下 四项之和=演员，重复为信息性展示（不另加）。"
        )
        # 议题 #157: 重复演员数 = 原始条目数 − 唯一名字数, 直接展示免用户两种计数方式手算
        self.lbl_duplicate = QLabel("重复: ")
        self.lbl_duplicate.setToolTip(
            "重复演员数 = 同名演员产生的多余条目数（原始条目数 − 唯一名字数，与计数方式无关）。\n"
            "「原始条目数」恒为过滤后、去重前的条目数；「唯一名字数」按名字去重。\n"
            "可在「设置」中勾选「重复演员去重（按名称合并）」合并同名条目。"
        )
        self.lbl_has_both = QLabel("完整: ")
        self.lbl_has_both.setToolTip("有头像且有简介（简介仅剩「无维基百科信息」占位或纯空白按缺处理）。")
        self.lbl_missing_image = QLabel("缺头像: ")
        self.lbl_missing_image.setToolTip("仅缺头像（有简介）。全缺者计入「全缺」，不在此项。")
        self.lbl_missing_info = QLabel("缺简介: ")
        self.lbl_missing_info.setToolTip("仅缺简介（含占位简介与纯空白简介）。全缺者计入「全缺」，不在此项。")
        self.lbl_missing_all = QLabel("全缺: ")
        self.lbl_missing_all.setToolTip("缺头像且缺简介 = 交集（对应取数模式「头像和简介都缺」）。")
        self.lbl_backdrop = QLabel("有背景图: ")
        self.lbl_backdrop.setToolTip(
            "有背景图的演员数，与「完整/缺头像/缺简介/全缺」四项同基数统计。\n"
            "计数方式切到「原始条目数」时基数是当前列表的全部条目；若列表已按「重复演员去重」抓取，"
            "列表本身已无同名重复，两种计数方式结果相同。"
        )
        for lbl in (
            self.lbl_all_staff,
            self.lbl_total,
            self.lbl_duplicate,
            self.lbl_has_both,
            self.lbl_missing_image,
            self.lbl_missing_info,
            self.lbl_missing_all,
            self.lbl_backdrop,
        ):
            lbl.setStyleSheet("padding: 0px 6px;")
            stats_layout.addWidget(lbl)
        # 有背景图留出足够显示数字的空间：按 5 位数预留最小宽度，避免右侧筛选控件挤压导致数字被裁
        self.lbl_backdrop.setMinimumWidth(self.lbl_backdrop.fontMetrics().horizontalAdvance("有背景图: 99999") + 20)
        stats_layout.addSpacing(6)
        stats_layout.addWidget(QLabel("筛选:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(["全部", "待同步", "缺头像", "缺背景", "缺简介", "缺头像和简介", "完整"])
        self.cmb_filter.currentTextChanged.connect(self._on_filter_changed)
        stats_layout.addWidget(self.cmb_filter)
        stats_layout.addWidget(QLabel("  搜索:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("输入演员名搜索...")
        self.txt_search.setMinimumWidth(120)
        self.txt_search.setMaximumWidth(200)
        self.txt_search.textChanged.connect(self._on_filter_changed)
        stats_layout.addWidget(self.txt_search)
        hint = QLabel("双击行可编辑")
        # 同上：不钉死字号，跟随统一放大的字号
        hint.setStyleSheet("color: #888888;")
        stats_layout.addWidget(hint)
        stats_layout.addStretch()
        stats_layout.addWidget(QLabel("计数方式:"))
        self.cmb_count_mode = QComboBox()
        self.cmb_count_mode.addItems(["原始条目数", "唯一名字数"])
        # 议题 #143: 先恢复已保存的选择再 connect, 避免构造时误触发保存
        self.cmb_count_mode.setCurrentIndex(1 if self._show_unique else 0)
        self.cmb_count_mode.currentIndexChanged.connect(self._on_count_mode_changed)
        stats_layout.addWidget(self.cmb_count_mode)
        parent_layout.addLayout(stats_layout)
        # 注意：此处原来有一个 QProgressBar（获取/同步时显隐），它在演员表布局里
        # 吃掉/归还约 26px 视口高度，导致最大化获取演员时只能看到 19 整行——该控件
        # 已彻底删除。进度改走底部状态栏文本（_set_progress），单行定高，改文字
        # 不影响任何布局，表格行数在获取中/完成后纹丝不动。
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["状态", "姓名", "头像", "简介", "详情", "出生日期", "出生地", "标签", "影片数"]
        )
        horizontal_header = self.table.horizontalHeader()
        assert horizontal_header is not None
        horizontal_header.setStretchLastSection(False)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # 议题 #136：详情/标签改为按 3:1 分配剩余宽度（标签过宽、详情过窄），
        # 具体宽度由 _apply_column_widths 在 resize 时按视口计算，总宽保持铺满。
        horizontal_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        horizontal_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        vertical_header = self.table.verticalHeader()
        assert vertical_header is not None
        vertical_header.setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 50)
        self.table.setColumnWidth(3, 50)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 200)
        self.table.setColumnWidth(8, 60)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        parent_layout.addWidget(self.table)
        # 议题 #160: 纵向滚动条显隐只改 viewport 几何、不触发窗口 resizeEvent;
        # 监听 viewport 尺寸变化, 在其后按真实视口宽重算列宽, 消除随之出现的横向滚动条
        table_viewport = self.table.viewport()
        assert table_viewport is not None
        table_viewport.installEventFilter(self)

    # 出生日期宽恒定 100；状态/头像/简介取其一半 50，影片数恒定 60；
    # 姓名与出生地同宽，按窗口状态取相对宽度：
    # 还原/常规/最小化：出生地=出生日期等宽 100，标签=出生日期×2=200；
    # 最大化/全屏：出生地=出生日期×2=200，标签=出生日期×3=300；详情吃掉剩余视口。
    _BIRTHDAY_W = 100
    _HALF_BIRTHDAY_W = _BIRTHDAY_W // 2  # 状态/头像/简介取出生日期一半
    _VIDEO_COUNT_W = 60  # 影片数恒定
    _FIXED_COLUMN_WIDTHS = {
        0: _HALF_BIRTHDAY_W,
        2: _HALF_BIRTHDAY_W,
        3: _HALF_BIRTHDAY_W,
        5: _BIRTHDAY_W,
        6: _BIRTHDAY_W,
        8: _VIDEO_COUNT_W,
    }  # 姓名(1)不再定宽，跟随出生地
    _DETAIL_WIDTH_RATIO = 0.75  # 历史比例（议题 #136），现仅保留兼容，实际按出生日期倍率定宽

    # 最小宽 1080 预算：获取模式下拉 220→210 沿用既有定值；数据工具下拉按自身 sizeHint
    # 定宽（恰容下最长项+箭头，随字体自适应）；其余六个按钮（连接/获取演员列表/
    # 全部更新同步/数据源测试/清空缓存/设置）任何窗口状态都按文字实际占用宽度定宽
    # （最大化与最小化一致；同步按钮文案带计数后缀时会变长，按当前文案实测，不裁字）。
    _FETCH_W_WIDE = 220
    _FETCH_W_NARROW = 210
    # 宽态（最大化/全屏）保持的原始最小宽；窄态由 _narrow_min_width 实测下调。
    _BASE_MIN_W = 1080
    # 窄态最小宽下限：计数栏（8 个统计标签 + 筛选 + 搜索框 + 计数方式）横向排布，
    # 窄于它 Qt 会挤压控件；另加余量。不低于该值时表格/统计栏观感正常。
    _NARROW_MIN_W_FLOOR = 720

    # 按文字实际占用宽度定宽的六个按钮：最大化与最小化宽度一致。
    _TEXT_FIT_BUTTONS = (
        ("btn_connect", "_connect_hint_w"),
        ("btn_fetch", "_fetch_hint_w"),
        ("btn_test_source", "_test_source_hint_w"),
        ("btn_clear_cache", "_clear_cache_hint_w"),
        ("btn_settings", "_settings_hint_w"),
    )

    # 按钮行高度只动这 8 个（提示 label 是文本、随行高居中，不碰）。
    _CONN_BUTTON_NAMES = (
        "btn_connect",
        "btn_fetch",
        "cmb_fetch_mode",
        "btn_clean",
        "btn_sync",
        "btn_test_source",
        "btn_clear_cache",
        "btn_settings",
    )

    def _apply_button_heights(self) -> None:
        """按钮行高度：数据源测试窗 `_sync_panel_stretch` 同款比例拉升。

        最大化/全屏时按钮与下拉按「对话框当前高度/基准高度」同步拉升
        （只设 minimumHeight、不锁 max，数值不变时不重复设置）；
        还原/常规/最小化时比例回到 1.0（与原来一致，不做任何改动）。
        宽度由 `_apply_button_widths` 管——两者正交。用户拖过分隔条后不碰
        （本次打开全程 hands-off）。重复调用结果一致。
        """
        try:
            if getattr(self, "_user_moved_splitter", False):
                return
            wide = self._is_wide_state()
        except (RuntimeError, AttributeError):
            return
        except Exception:
            return
        try:
            try:
                base_h = getattr(self, "_dialog_base_h", 0) or 0
                cur_h = self.height() or 0
                ratio = (cur_h / base_h) if (wide and base_h > 0 and cur_h > 0) else 1.0
            except Exception:
                ratio = 1.0
            stored = getattr(self, "_conn_btn_base_h", None) or {}
            for name in self._CONN_BUTTON_NAMES:
                w = getattr(self, name, None)
                if w is None:
                    continue
                try:
                    base = stored.get(name, 0) or 0
                    if base <= 0:
                        base = w.sizeHint().height()
                    if base <= 0:
                        continue
                    target = max(1, int(round(base * ratio)))
                    if w.minimumHeight() != target:
                        w.setMinimumHeight(target)
                except (RuntimeError, AttributeError):
                    continue
                except Exception:
                    continue
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _deferred_after_resize(self) -> None:
        """resize/show 下一拍： settled 状态定档，先按钮行高、再行数对齐。

        按钮拉升会改变连接组高度、进而改变 splitter 可用高度——必须等布局
        落定后再量 `_fit_visible_rows`，故 fit 在其后再排一拍（两拍链）。
        """
        self._apply_button_widths()
        self._apply_button_heights()
        self._apply_column_widths()
        self._update_help_line_break()
        QTimer.singleShot(0, self._fit_visible_rows)

    def _button_natural_width(self, attr: str, widget) -> int:
        """按钮自然宽度：优先用首次显示时记录的值；未记录（首次显示前）且尚未定宽时
        直接读 sizeHint——setFixedWidth 后 sizeHint 即返回固定值，不能再用它反推，
        否则越收越窄（此处只在定宽前调用，读到的是真自然宽度）。"""
        hint = getattr(self, attr, 0)
        if hint:
            return int(hint)
        try:
            return int(widget.sizeHint().width())
        except (RuntimeError, AttributeError):
            return 0

    def _sync_button_natural_width(self) -> int:
        """同步按钮自然宽度：文案带计数后缀（“开始全部更新同步(N 项)”），长度会变，
        故每次按当前文案实测字宽 + 内边距开销；开销取首次显示时记录值，未记录时
        按当前（未定宽即自然）sizeHint 与字宽之差现算。"""
        btn = getattr(self, "btn_sync", None)
        if btn is None:
            return 0
        try:
            advance = btn.fontMetrics().horizontalAdvance(btn.text())
        except (RuntimeError, AttributeError):
            return 0
        overhead = getattr(self, "_sync_overhead_w", 0)
        if not overhead:
            try:
                overhead = btn.sizeHint().width() - advance
            except (RuntimeError, AttributeError):
                overhead = 0
        return int(advance + (overhead if overhead > 0 else 15))

    def _apply_button_widths(self) -> None:
        """按钮行各控件宽度：六个按钮按文字实际占用宽度定宽（最大化与最小化一致）。

        获取模式下拉宽态 220 / 窄态 210；数据工具下拉窄态按自身 sizeHint 定宽、
        宽态恢复自适应；连接/获取演员列表/全部更新同步/数据源测试/清空缓存/
        设置六个按钮在任何窗口状态下都按各自文字实际占用宽度定宽（同步按钮按
        当前文案实测，计数后缀变长时跟随变宽，不裁字）。
        只改 min/max，不碰布局、行数、列宽、提示词逻辑；重复调用幂等。
        """
        try:
            wide = self._is_wide_state()
        except Exception:
            return
        try:
            cmb = getattr(self, "cmb_fetch_mode", None)
            data_tool = getattr(self, "cmb_data_tool", None)
            if cmb is None or data_tool is None:
                return
            if wide:
                if cmb.minimumWidth() != self._FETCH_W_WIDE or cmb.maximumWidth() != self._FETCH_W_WIDE:
                    cmb.setFixedWidth(self._FETCH_W_WIDE)
                if data_tool.minimumWidth() != 0 or data_tool.maximumWidth() != self._HELP_MAX_W:
                    data_tool.setMinimumWidth(0)
                    data_tool.setMaximumWidth(self._HELP_MAX_W)
            else:
                if cmb.minimumWidth() != self._FETCH_W_NARROW or cmb.maximumWidth() != self._FETCH_W_NARROW:
                    cmb.setFixedWidth(self._FETCH_W_NARROW)
                data_hint = getattr(self, "_data_tool_hint_w", 0) or data_tool.sizeHint().width()
                if data_tool.minimumWidth() != data_hint or data_tool.maximumWidth() != data_hint:
                    data_tool.setFixedWidth(data_hint)
            # 六个按钮：按文字实际占用宽度定宽，最大化与最小化一致。
            for name, hint_attr in self._TEXT_FIT_BUTTONS:
                w = getattr(self, name, None)
                if w is None:
                    continue
                want = self._button_natural_width(hint_attr, w)
                if want <= 0:
                    continue
                if w.minimumWidth() != want or w.maximumWidth() != want:
                    w.setFixedWidth(want)
            sync = getattr(self, "btn_sync", None)
            if sync is not None:
                want = self._sync_button_natural_width()
                if want > 0 and (sync.minimumWidth() != want or sync.maximumWidth() != want):
                    sync.setFixedWidth(want)
            self._apply_button_row_compact()
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _narrow_help_width(self) -> int:
        """窄态帮助标签的定宽：固定两行文案（`_help_narrow`）中较宽一行的文字实宽（无附加余量）。

        按钮之间紧贴着没空白没间距：帮助标签按文字实宽精确取宽，不再多留 4px，
        与前后按钮间距 0 配合，窄态 2-9 号缝隙归零。窄态恒两行、宽态恒单行，
        两者互不换算，故只算两行文案。宽态逻辑不动。
        """
        label = getattr(self, "help_label", None)
        narrow = getattr(self, "_help_narrow", None)
        if label is None or not narrow:
            return 0
        try:
            fm = label.fontMetrics()
            return int(max(fm.horizontalAdvance(line) for line in narrow.split("\n")))
        except (RuntimeError, AttributeError):
            return 0

    def _narrow_min_width(self) -> int:
        """窄态窗口最小宽：按钮行（各控件按文字实宽定宽 + 两行帮助）实测最宽。

        窄态下帮助恒两行、六个按钮各按文字实宽定宽，整行宽度即各控件实宽之和
        （窄态项间距 0、组左右 0，故不另加）；对话框最小宽还需容下组边框
        2px + 主布局左右 12+12，合计外层 26，由布局自身决定，取实测值加此外层，
        不再叠加额外固定量，避免把最小宽推得远大于真实需求。
        宽态仍用 _BASE_MIN_W(1080)，最大化布局与最小尺寸语义均不变。
        """
        try:
            fixed = 0
            for name in self._CONN_BUTTON_NAMES:
                w = getattr(self, name, None)
                if w is not None:
                    fixed += w.width()
            help_w = self._narrow_help_width()
            # 组边框 + 表格列宽下限（详情列等）由布局自身决定，取实测值加余量即可，
            # 不再叠加额外固定量，避免把最小宽推得远大于真实需求。
            row = fixed + help_w
            try:
                main = self.layout()
                outer = 2  # 连接组左右边框各 1px（QSS border:1px）。
                if main is not None:
                    mg = main.contentsMargins()
                    outer += int(mg.left() + mg.right())
            except (RuntimeError, AttributeError):
                outer = 26
            return int(max(row + outer, self._NARROW_MIN_W_FLOOR))
        except (RuntimeError, AttributeError):
            return self._BASE_MIN_W

    def _apply_button_row_compact(self) -> None:
        """按钮行紧凑排布 + 窄态标题/标签左移：仅窄态生效，宽态恢复原样。

        窄态按钮之间紧贴着没空白没间距：项间距 4→0，连接组左 16→0（删掉 1 号
        左空白，按钮贴组边框）、右 6→0（删掉 10 号右空白），2-9 号项缝同步归零；
        再把按钮行按内容宽左对齐（setAlignment(AlignLeft)）——窗口比按钮行宽出的
        富余宽度不再被这一行平摊成 1-10 号空白，而是整条给上一行的服务器地址/
        API 密钥输入框（它们本就是 Expanding，变宽是输入框正常表现，不是空白）。
        窄态还把组标题与服务器地址标签一起左移，与「连接Emby/Jellyfin」按钮内的
        字体严格上下对齐：三者文字起点同落在组客户区 x=8（按钮贴左 x=1 +
        按钮左边框/内边距 7）。标题用**本控件级**样式表把全局
        `left:10 + padding:0 4px`（实测 ink x=20）局部覆盖为
        `left:0 + padding:0 2px`（实测 ink x=8），服务器地址标签 padding-left
        由 13px 改 1px（标签 x=1 → 内容起点 2 + 「服」字形左边距 ≈6 → ink x=8）。
        上下边距与垂直间距一律不动，故窄态高度不变。
        宽态（最大化/全屏）布局、控件、提示词逐像素不变（左 16/右 6/间距 4、
        对齐恢复 0=填满、服务器标签与组标题都恢复全局原样）。重复调用幂等。
        """
        try:
            wide = self._is_wide_state()
        except Exception:
            return
        try:
            btn_layout = getattr(self, "_btn_layout", None)
            grid = getattr(self, "_conn_grid", None)
            help_label = getattr(self, "help_label", None)
            if btn_layout is None or grid is None or help_label is None:
                return
            if wide:
                if btn_layout.spacing() != 4:
                    btn_layout.setSpacing(4)
                # 宽态：按钮行恢复填满整行（最大化逐像素不变，空白照旧由帮助标签吸收）。
                if btn_layout.alignment() != Qt.AlignmentFlag(0):
                    btn_layout.setAlignment(Qt.AlignmentFlag(0))
                margins = grid.contentsMargins()
                base = self.CONN_BASE_MARGINS
                if (margins.left(), margins.top(), margins.right(), margins.bottom()) != base:
                    grid.setContentsMargins(*base)
                # 宽态：服务器地址标签恢复无垫左（最大化逐像素不变）。
                lbl_server = getattr(self, "_lbl_server", None)
                if lbl_server is not None and lbl_server.styleSheet() != "":
                    lbl_server.setStyleSheet("")
                # 宽态：组标题恢复全局 QSS 的 `left:10 + padding:0 4px`（最大化逐像素不变）。
                group_box = getattr(self, "_conn_group", None)
                if group_box is not None and group_box.styleSheet() != "":
                    group_box.setStyleSheet("")
                # 宽态：帮助标签恢复自适应（最大化逐像素不变），最低宽归零。
                if help_label.maximumWidth() != self._HELP_MAX_W or help_label.minimumWidth() != 0:
                    help_label.setMaximumWidth(self._HELP_MAX_W)
                    help_label.setMinimumWidth(0)
                    _lay = help_label.parentWidget().layout() if help_label.parentWidget() is not None else None
                    if _lay is not None:
                        _lay.activate()
                    # 宽度放开后排下一拍，把文案从窄态两行切回宽态单行。
                    QTimer.singleShot(0, self._update_help_line_break)
            else:
                if btn_layout.spacing() != 0:
                    btn_layout.setSpacing(0)
                # 窄态：按钮行按内容宽左对齐，富余宽度整条让给上一行输入框，
                # 彻底删掉 1-10 号空白（行左、行右、按钮之间都不再被平摊空白）。
                if btn_layout.alignment() != Qt.AlignmentFlag.AlignLeft:
                    btn_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                margins = grid.contentsMargins()
                if margins.left() != 0 or margins.right() != 0:
                    grid.setContentsMargins(0, margins.top(), 0, margins.bottom())
                # 窄态：组标题与服务器地址文本左移到「连接Emby/Jellyfin」按钮内文字起点
                # 严格对齐（组客户区内 x=8：按钮贴左 x=1 + 按钮左边框/内边距 7）。
                # 标题偏移原本由全局 QSS `QGroupBox::title { left:10; padding:0 4px }`
                # 决定（实测 ink x=20），故用**本控件级**样式表局部覆盖为
                # `left:0 + padding:0 2px`（实测 ink x=8），不影响「运行日志」
                # 等其它 QGroupBox；宽态清空本控件样式表即回到全局值。
                group_box = getattr(self, "_conn_group", None)
                if group_box is not None and group_box.styleSheet() != self._CONN_TITLE_QSS:
                    group_box.setStyleSheet(self._CONN_TITLE_QSS)
                # 服务器地址标签同理：标签 x=1，padding-left 1 → 内容起点 2，
                # 再加上「服」字约 6px 的字形左边距，墨迹起点正好 x=8，
                # 与标题的「E」、按钮内「连」三者的首笔严格同列。
                lbl_server = getattr(self, "_lbl_server", None)
                if lbl_server is not None and lbl_server.styleSheet() != "padding-left: 1px;":
                    lbl_server.setStyleSheet("padding-left: 1px;")
                # 窄态：帮助标签按自身文字宽度定宽，不再吸收富余宽度。
                want_help = self._narrow_help_width()
                if want_help > 0 and help_label.maximumWidth() != want_help:
                    help_label.setMaximumWidth(want_help)
                    help_label.setMinimumWidth(want_help)
                    _lay = help_label.parentWidget().layout() if help_label.parentWidget() is not None else None
                    if _lay is not None:
                        _lay.activate()
            # 窄态同步下调窗口最小宽（两行帮助文案省下的宽度即所减部分）；
            # 宽态恢复原最小宽，最大化布局与最小尺寸语义均不变。
            try:
                self._apply_narrow_min_width()
            except (RuntimeError, AttributeError):
                pass
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _apply_narrow_min_width(self) -> None:
        """按窗口状态同步对话框最小宽：窄态用 `_narrow_min_width`（实测两行态最宽），
        宽态恢复 1080。只改最小宽，窗口自身几何/高度一律不动。"""
        try:
            want = self._BASE_MIN_W if self._is_wide_state() else self._narrow_min_width()
            base_h = max(720, int(self.minimumHeight() or 720))
            if self.minimumWidth() != want or self.minimumHeight() != base_h:
                self.setMinimumSize(want, base_h)
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _is_wide_state(self) -> bool:
        """最大化/全屏即宽态，其余（还原/常规/最小化）即窄态。"""
        try:
            return bool(self.isMaximized() or self.isFullScreen())
        except (RuntimeError, AttributeError):
            return False
        except Exception:
            return False

    def _apply_column_widths(self) -> None:
        """按视口宽度重排各列，保证总宽铺满且比例按窗口状态切换。"""
        table = getattr(self, "table", None)
        if table is None:
            return
        viewport_w = table.viewport().width()
        if viewport_w <= 0:
            return
        birthday_w = self._BIRTHDAY_W
        wide = self._is_wide_state()
        birthplace_w = birthday_w * 2 if wide else birthday_w
        name_w = birthplace_w  # 姓名列与出生地同宽
        tags_w = birthday_w * 3 if wide else birthday_w * 2
        base_fixed = (
            self._FIXED_COLUMN_WIDTHS.get(0, 50)
            + name_w
            + self._FIXED_COLUMN_WIDTHS.get(2, 50)
            + self._FIXED_COLUMN_WIDTHS.get(3, 50)
            + self._FIXED_COLUMN_WIDTHS.get(8, 60)
        )
        fixed_sum = base_fixed + birthday_w + birthplace_w + tags_w
        detail_w = max(viewport_w - fixed_sum, 120)
        # 防御性重入保护: setColumnWidth 实测不改 viewport 宽(不会自激), 嵌套调用为同值空操作
        if getattr(self, "_applying_widths", False):
            return
        self._applying_widths = True
        try:
            table.setColumnWidth(1, name_w)
            table.setColumnWidth(5, birthday_w)
            table.setColumnWidth(6, birthplace_w)
            table.setColumnWidth(4, detail_w)
            table.setColumnWidth(7, tags_w)
        finally:
            self._applying_widths = False

    def _on_splitter_moved(self, *_args) -> None:
        """用户亲手拖动分隔条：本次打开记住，不再自动重排（取数/缩放都不抢回）。

        我们自己 setSizes 时不算（`_setting_splitter_sizes` 守卫）；对话框关闭即
        销毁、重开是新实例，天然恢复默认行数（数据源测试窗 `_result_user_moved` 同款）。
        """
        if getattr(self, "_setting_splitter_sizes", False):
            return
        self._user_moved_splitter = True
        # 拖后不再重排行高，但日志下方不许留空白：视口高度仍要吸附到整行
        self._queue_log_line_snap()

    def _queue_log_line_snap(self) -> None:
        """合并同拍多次请求，只排一次日志视口整行吸附（守卫与 fit 同款）。"""
        try:
            if getattr(self, "_log_snap_queued", False):
                return
            self._log_snap_queued = True
        except (RuntimeError, AttributeError):
            return
        QTimer.singleShot(0, self._log_line_snap_tick)

    def _log_line_snap_tick(self) -> None:
        self._log_snap_queued = False
        self._snap_log_viewport_to_whole_lines()

    def _snap_log_viewport_to_whole_lines(self) -> None:
        """把日志视口高度吸附到行距的整数倍：这是尾部空白归零的唯一手段。

        Qt 竖向滚动按整行换档、上限恰好落在「末行贴视口底」的那一档，故
        `空白 = 视口高 % 行距`（见 `_FlushLogTextEdit` 实测记录）。`_fit_visible_rows`
        正常落定时视口本就是 `行数 x 行距`（文档边距归零后），余下两种情形会留下
        余数：用户手拖分隔条（行高对齐让位）、高度不够时 fit bail（连可读下限都
        塞不下）。此处把这两种情形的余数像素从日志窗格挪给演员表窗格——表格多/
        少十几像素不会引入半行（行高始终由 fit 的整数除法给出）。

        与 fit 互为固定点：fit 的目标视口恒是整行，吸附后再跑 fit 是空操作；已
        整行、量不到、最小化、日志窗格比余数还矮——都是空操作，绝不循环。
        """
        log = getattr(self, "log_text", None)
        splitter = getattr(self, "_splitter", None)
        if log is None or splitter is None:
            return
        if getattr(self, "_setting_splitter_sizes", False):
            return
        try:
            if self.isMinimized() or (self.windowState() & Qt.WindowState.WindowMinimized):
                return
            line_h = log.fontMetrics().lineSpacing()
            if line_h <= 0:
                return
            over = log.viewport().height() % line_h
            if over == 0:
                return
            sizes = splitter.sizes()
            if len(sizes) < 2 or sizes[1] <= over:
                return  # 日志窗格比这点余数还矮：吸了会压掉末行，不动
            self._setting_splitter_sizes = True
            try:
                splitter.setSizes([int(sizes[0] + over), int(sizes[1] - over)])
            finally:
                self._setting_splitter_sizes = False
        except (RuntimeError, AttributeError):
            return

    def eventFilter(self, a0, a1):
        """议题 #160: viewport 尺寸变化(含纵向滚动条显隐/DPI 变化)后重算列宽，
        使各列总宽始终铺满视口、不产生横向滚动条。只做表格内部列宽，
        从不碰窗口自身几何（最大化/最小化/还原全走系统原生行为）。
        表格/日志视口变化另补排一次行数对齐：日志条数增长冒出滚动条只改
        viewport 几何、不触发窗口 resize，整行数不能 silently 漂移。
        """
        table = getattr(self, "table", None)
        log = getattr(self, "log_text", None)
        if a1 is not None and a1.type() == QEvent.Type.Resize:
            if table is not None and a0 is table.viewport():
                self._apply_column_widths()
            if (table is not None and a0 is table.viewport()) or (log is not None and a0 is log.viewport()):
                self._queue_viewport_refit()
        return super().eventFilter(a0, a1)

    def _queue_viewport_refit(self) -> None:
        """视口几何变化后的补对：合并同拍多次事件，只排一次，守卫与 fit 同款。"""
        # 无论后续补对是否被守卫挡下（用户拖过分隔条 / 我们自己正在 setSizes），
        # 整行吸附都要排：它只挪余数像素，不改用户选的分配。
        self._queue_log_line_snap()
        try:
            if getattr(self, "_user_moved_splitter", False):
                return
            if getattr(self, "_setting_splitter_sizes", False):
                return
            if getattr(self, "_viewport_refit_queued", False):
                return
            self._viewport_refit_queued = True
        except (RuntimeError, AttributeError):
            return
        except Exception:
            return
        QTimer.singleShot(0, self._viewport_refit_tick)

    def _viewport_refit_tick(self) -> None:
        self._viewport_refit_queued = False
        try:
            if getattr(self, "_user_moved_splitter", False):
                return
            if self.isMinimized() or (self.windowState() & Qt.WindowState.WindowMinimized):
                return
        except (RuntimeError, AttributeError):
            return
        except Exception:
            return
        self._fit_visible_rows()

    def _fit_verify_tick(self) -> None:
        """fit 下一拍校验：布局若在 fit 落定之后才 settle，按实测对照存档目标，
        漂移才重对——已精确是空操作，天然收敛不循环。"""
        self._fit_verify_queued = False
        try:
            if getattr(self, "_user_moved_splitter", False):
                return
            if self.isMinimized() or (self.windowState() & Qt.WindowState.WindowMinimized):
                return
            table = getattr(self, "table", None)
            log = getattr(self, "log_text", None)
            if table is None or log is None:
                return
            want_vp = getattr(self, "_last_want_vp", None)
            want_log = getattr(self, "_last_want_log_vp", None)
            if want_vp is None or want_log is None:
                return
            if table.viewport().height() == want_vp and log.viewport().height() == want_log:
                return
        except (RuntimeError, AttributeError):
            return
        except Exception:
            return
        self._fit_visible_rows()

    def resizeEvent(self, a0):
        # 主界面同款：只同步内部控件几何，从不改窗口自身 min/max/fixed 与几何——
        # 最大化/最小化/还原全走系统原生行为。按钮拉升先行（settled 态下一拍再定一次，盖住最大化过渡帧的旧态），
        # 行数对齐排在其后（拉升改变连接组高度，须等布局落定再量，不抬 minimumSizeHint）。
        super().resizeEvent(a0)
        self._apply_button_widths()
        self._apply_button_heights()
        self._apply_column_widths()
        self._update_help_line_break()
        QTimer.singleShot(0, self._deferred_after_resize)

    def showEvent(self, a0):
        super().showEvent(a0)
        # 首次显示时样式已 polish（QSS 放大字号已生效），此时先解除定宽再记录各控件
        # 的自然宽度，供窄态做基准；构造时/定宽后的 sizeHint（默认字号/固定值）都偏小。
        if not getattr(self, "_hints_captured", False):
            self._hints_captured = True
            _widgets = [
                ("_data_tool_hint_w", getattr(self, "cmb_data_tool", None)),
                ("_connect_hint_w", getattr(self, "btn_connect", None)),
                ("_fetch_hint_w", getattr(self, "btn_fetch", None)),
                ("_test_source_hint_w", getattr(self, "btn_test_source", None)),
                ("_clear_cache_hint_w", getattr(self, "btn_clear_cache", None)),
                ("_settings_hint_w", getattr(self, "btn_settings", None)),
            ]
            for _attr, _w in _widgets:
                if _w is None:
                    continue
                try:
                    _w.setMinimumWidth(0)
                    _w.setMaximumWidth(self._HELP_MAX_W)
                except (RuntimeError, AttributeError):
                    pass
            for _attr, _w in _widgets:
                if _w is None:
                    continue
                try:
                    setattr(self, _attr, _w.sizeHint().width())
                except (RuntimeError, AttributeError):
                    pass
            # 同步按钮内边距开销：自然宽度 - 当前文案字宽，窄态按实时文案重算自然宽度时用。
            _sync = getattr(self, "btn_sync", None)
            if _sync is not None:
                try:
                    _adv = _sync.fontMetrics().horizontalAdvance(_sync.text())
                    self._sync_overhead_w = _sync.sizeHint().width() - _adv
                except (RuntimeError, AttributeError):
                    pass
        self._apply_button_widths()
        self._apply_button_heights()
        self._apply_column_widths()
        QTimer.singleShot(0, self._update_help_line_break)
        QTimer.singleShot(0, self._deferred_after_resize)
        # 窄态默认宽度缩进：排在本拍之后（按钮已按文字实宽定窄，_narrow_min_width 才准）。
        QTimer.singleShot(0, self._shrink_narrow_width)

    def _shrink_narrow_width(self) -> None:
        """窄态默认宽度缩进：把窗口收到按钮行内容宽，删掉三处同源空白，并保持屏幕居中。

        设置按钮右侧空白、统计栏「双击行可编辑」右侧空白、表格详情列富余，
        三者都来自「窗口宽 − 内容宽」的同一段富余宽度，故只需在窄态把窗口宽
        收到 `_narrow_min_width()`（= 按钮行实宽和 + 外层 26），三处一起缩掉。
        只在首次显示与「最大化→还原」时各收一次，用户之后手动拉宽不受限制
        （不逐次强拉，窗口仍可自由拖动）。最大化/全屏一律不动，几何与布局不变。
        重复调用幂等：宽度已贴合则无操作。

        **缩宽后必须重新居中**：`resize()` 只改尺寸、**左上角 (x, y) 原地不动**，
        而 `__init__` 里的 `_center_on_screen()` 是按缩宽前的宽度（屏幕 80%）算的，
        缩窄后右边界内收、几何中心会整体左移半个差值（1536→1392 即左移 72px），
        表现为「打开后偏左」。故这里 resize 之后紧跟一次 `_center_on_screen()`，
        走 `mdcx.utils.window_center` 的 frameGeometry 口径（与主界面同款），
        把缩完的窗口重新放回屏幕可用区正中央。
        """
        try:
            if self._is_wide_state():
                return
            want = self._narrow_min_width()
            if want > 0 and self.width() > want:
                self.resize(want, self.height())
                # 缩宽改变了 frame 宽度，居中结果随之改变 → 重定位回屏幕正中央。
                self._center_on_screen()
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def changeEvent(self, event):
        """窗口状态变化：从最大化/全屏还原回窄态时，按内容宽再缩一次贴合。

        最大化/全屏期间布局、控件、提示词一律不动；这里只在「还原成窄态」这一拍
        排一次缩宽，其余事件照旧交给父类。
        """
        super().changeEvent(event)
        try:
            if event.type() == QEvent.Type.WindowStateChange and not self._is_wide_state():
                QTimer.singleShot(0, self._shrink_narrow_width)
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    # Qt 默认最大宽：清除限宽用（与 16777215 字面值同义，写常量免魔法数）。
    _HELP_MAX_W = 16777215

    def _update_help_line_break(self) -> None:
        """窄窗两行、宽窗一行：按 help_label 实宽切换；窄窗断点动态平衡并限宽贴边。

        旧固定断在「获|取」的双行在部分字体下两行不等长，第一行行尾空出一大块
        （视觉上右边比左边宽）。改按当前字体实测字宽取差值最小的断点，两行等长；
        可行时再把 label 最大宽度钳到最长行宽——行尾与 label 右缘对齐，右边距只剩
        一份 layout spacing（4px），与左侧「同步→使用说明」对称，多出的宽度落在
        行尾（设置按钮右侧空白），各按钮与文字位置不动。

        窄态（还原/常规/最小化）不再做动态折行：恒用用户指定的固定两行文案
        `_help_narrow`（在「③选择模式获取数据」处断行），并按两行文字实宽定宽
        （`_narrow_help_width`）——既不吸收富余宽度（此前让「使用说明→数据源测试」
        之间出现 23~37px 大缝），又省下「单行宽度 - 两行宽度」这段宽度用于下调
        窄态最小宽。宽态逻辑与最大化渲染逐像素不变。
        """
        label = getattr(self, "help_label", None)
        single = getattr(self, "_help_single", None)
        narrow = getattr(self, "_help_narrow", None)
        if label is None or single is None or narrow is None:
            return
        try:
            wide = self._is_wide_state()
        except Exception:
            wide = True
        narrow_width = 0 if wide else self._narrow_help_width()
        # 先解除上一轮限宽并同步一次布局，再量 label 真正能拿到的宽度；
        # 否则加宽窗口后读到的还是被钳住的旧宽，永远切不回单行。
        if label.maximumWidth() != self._HELP_MAX_W:
            label.setMaximumWidth(self._HELP_MAX_W)
            try:
                lay = label.parentWidget().layout() if label.parentWidget() is not None else None
                if lay is not None:
                    lay.activate()
            except Exception:
                pass
        if not wide:
            # 窄态：恒用固定两行文案（用户指定在「③选择模式获取数据」处断行），
            # 并按两行文字实宽定宽——不再按可用宽度做动态折行，也不再吸收富余宽度。
            if label.text() != narrow:
                label.setText(narrow)
            if narrow_width > 0 and label.maximumWidth() != narrow_width:
                label.setMaximumWidth(narrow_width)
                try:
                    lay = label.parentWidget().layout() if label.parentWidget() is not None else None
                    if lay is not None:
                        lay.activate()
                except Exception:
                    pass
            return
        # 宽态：单行放得下就用原文单行，否则按实测字宽找两行等长断点（最大化不变）。
        avail = label.width()
        if avail <= 0:
            return
        fm = label.fontMetrics()
        if fm.horizontalAdvance(single) + 4 <= avail:
            if label.text() != single:
                label.setText(single)
            return
        balanced = self._balanced_help_text(single, fm, avail)
        if balanced is None:
            if label.text() != narrow:
                label.setText(narrow)
            return
        if label.text() != balanced:
            label.setText(balanced)
        line_w = max(fm.horizontalAdvance(ln) for ln in balanced.split("\n"))
        if label.maximumWidth() != line_w:
            label.setMaximumWidth(line_w)

    @staticmethod
    def _balanced_help_text(text: str, fm, avail: int) -> str | None:
        """找断点把 text 切成两行：两行都 <=avail 且长度差最小；无可行断点回 None。

        中文随处可断，按字逐个累宽度挑差值最小者。窄到连两行都塞不下时回 None，
        调用方回落固定双行（保持现状，不再加行）。
        """
        widths = [0]
        for ch in text:
            widths.append(widths[-1] + fm.horizontalAdvance(ch))
        total = widths[-1]
        if total <= avail:
            return text
        best: int | None = None
        best_diff: int | None = None
        for i in range(1, len(text)):
            left = widths[i]
            right = total - left
            if left > avail or right > avail:
                continue
            diff = abs(left - right)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = i
                if diff == 0:
                    break
        if best is None:
            return None
        return text[:best] + "\n" + text[best:]

    def _fit_visible_rows(self) -> None:
        """行数对齐（仅内部）：演员表视口 = rows 整行，日志 = lines 整行不缺行。

        主界面同款约束：只调表行高与 splitter 分配，绝不 setFixedHeight 锁窗格、
        绝不 setGeometry 自身、绝不留存几何——真机实测行高增减与 setSizes 均不抬
        `minimumSizeHint`，最大化/最小化/还原动画零干扰。高度不够（连可读下限
        都塞不下）时直接返回（小窗自然布局）；最小化时跳过。行高整数除法 absorb
        余量：余数（< rows px）均摊到前余数行各 +1px，表格侧 total 恰好 rows 整行、
        日志侧恰好 lines 整行——无半行、无 peek、无空白垫。
        """
        table = getattr(self, "table", None)
        log = getattr(self, "log_text", None)
        splitter = getattr(self, "_splitter", None)
        list_widget = getattr(self, "_list_widget", None)
        log_widget = getattr(self, "_log_widget", None)
        if table is None or log is None or splitter is None or list_widget is None or log_widget is None:
            return
        # 本次 fit 无论成不成（提前 bail 也算），日志视口都得落到整行上
        self._queue_log_line_snap()
        # 用户拖过分隔条：本次打开保持拖后位置，取数/缩放都不抢回；
        # 重开是新实例，天然回到默认行数。
        if getattr(self, "_user_moved_splitter", False):
            return
        try:
            if self.isMinimized() or (self.windowState() & Qt.WindowState.WindowMinimized):
                return
            maximized = self.isMaximized() or self.isFullScreen()
        except (RuntimeError, AttributeError):
            return
        except Exception:
            maximized = False
        rows, log_lines = (
            (self.TABLE_VISIBLE_ROWS, self.LOG_VISIBLE_LINES)
            if maximized
            else (self.NORMAL_TABLE_ROWS, self.NORMAL_LOG_LINES)
        )
        try:
            vhead = table.verticalHeader()
            line_h = log.fontMetrics().lineSpacing()
            if line_h <= 0:
                return
            try:
                doc_top = int(log.document().documentMargin())
            except Exception:
                doc_top = 0
            # 硬下限只保可读（字高 + 2），不再保"自然行高 - 2"：高分屏大字体下
            # 20 行档需要收到自然行高一成左右（如 40→35）才能装下，否则直接 bail、
            # 最大化永远落回自然布局（用户报障 21.5 行 / 11 行即此）。
            # 必须同时服从表头 minimumSectionSize：低于它时 setDefaultSectionSize/
            # setRowHeight 会被静默钳位，算出的整行数全部作废（实测 21→24 的坑）。
            hard_min = max(table.fontMetrics().height() + 2, int(vhead.minimumSectionSize()))

            header_h = table.horizontalHeader().height()
            try:
                handle = max(0, splitter.count() - 1) * splitter.handleWidth()
            except Exception:
                handle = 0
            # 巨幅 resize 后内部布局要等事件循环才落定：首轮量到的 chrome 可能是
            # 过渡态（如日志窗格尚未铺开，log_target 会算大、日志下方留空白），
            # 故每轮重测 chrome/avail 再重算，最多 4 轮；仍不收敛由尾部的下一拍
            # 校验兜底。全程只调表行高与 splitter 分配（setRowHeight/
            # setDefaultSectionSize 实测不抬 minimumSizeHint）。
            want_vp = None
            want_log_vp = log_lines * line_h + doc_top
            list_target = None
            log_target = None
            avail = 0
            for _ in range(4):
                table_fixed = (
                    (list_widget.height() - table.height())
                    + header_h
                    + (table.height() - header_h - table.viewport().height())
                )
                log_chrome = (log_widget.height() - log.height()) + (log.height() - log.viewport().height())
                avail = splitter.height() - handle
                if avail <= 0:
                    return
                log_need = log_chrome + want_log_vp
                row_h = (avail - table_fixed - log_need) // rows
                if row_h < hard_min:
                    return  # 实在塞不下：小窗自然布局，不干预
                # 余数 rem（< rows px）均摊到前 rem 行各 +1px：表格侧 total 恰好
                # rows*row_h + rem，日志侧恰好 log_need——无半行、无 peek。
                # 只动前 rem 行并 reset 上轮旧分布（O(40) 以内），新行自动取默认行高。
                rem = (avail - table_fixed - log_need) - rows * int(row_h)
                rem = max(0, min(int(rem), rows - 1))
                if row_h != vhead.defaultSectionSize():
                    vhead.setDefaultSectionSize(int(row_h))
                if vhead.defaultSectionSize() != int(row_h):
                    return  # 被静默钳位：按自然布局，不留半截状态
                n_rows = table.rowCount()
                plus_old = int(getattr(self, "_plus_rows", 0) or 0)
                try:
                    for i in range(min(plus_old, n_rows)):
                        table.setRowHeight(i, int(row_h))
                    for i in range(min(rem, n_rows)):
                        table.setRowHeight(i, int(row_h) + 1)
                except Exception:
                    pass
                self._plus_rows = int(min(rem, n_rows))
                list_target = table_fixed + rows * int(row_h) + rem
                log_target = log_need
                want_vp = rows * int(row_h) + rem
                # 我们自己的 setSizes 不算用户拖动：守卫住 splitterMoved 信号，
                # 否则第一次对齐就把自己锁死、以后永远不再对齐。
                self._setting_splitter_sizes = True
                try:
                    try:
                        splitter.setSizes([int(list_target), int(log_target)])
                    except Exception:
                        return
                finally:
                    self._setting_splitter_sizes = False
                # 横向滚动条出现时会吃掉日志视口高度（属正常 chrome，不追）。
                if table.viewport().height() == want_vp and (
                    log.horizontalScrollBar().isVisible() or log.viewport().height() == want_log_vp
                ):
                    break
            if want_vp is None or list_target is None or log_target is None:
                return
            self._last_want_vp = int(want_vp)
            self._last_want_log_vp = int(want_log_vp)
            # 下一拍校验：若布局在本次落定之后才 settle，按落定几何再对一次；
            # 已精确则是空操作。同一时刻只排一个，多源排队自动合并。
            if not getattr(self, "_fit_verify_queued", False):
                self._fit_verify_queued = True
                QTimer.singleShot(0, self._fit_verify_tick)
        except (RuntimeError, AttributeError):
            # C++ 对象已销毁等竞态：纯外观调整，静默放弃
            pass

    def _build_log_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 2, 4, 2)
        self.log_text = _FlushLogTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        layout.addWidget(self.log_text)
        parent_layout.addWidget(group)

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_fetch.clicked.connect(self._on_fetch)
        self.cmb_data_tool.activated.connect(self._on_data_tool_chosen)
        self.btn_sync.clicked.connect(self._on_sync)
        self.btn_settings.clicked.connect(self._on_open_settings)
        self.btn_test_source.clicked.connect(self._on_open_test_source)
        self.btn_clear_cache.clicked.connect(self._on_clear_cache)
        self._connect_result.connect(self._on_connect_result)
        self._media_folders_result.connect(self._on_media_folders_result)
        self._gfriends_result.connect(self._on_gfriends_result)
        self.txt_url.textChanged.connect(self._on_connection_text_changed)
        self.txt_api_key.textChanged.connect(self._on_connection_text_changed)

    def _on_open_settings(self):
        self._show_child_window("_settings_dialog", EmbyActorSettingsDialog)

    def _on_open_test_source(self):
        self._show_child_window("_test_dialog", ActorSourceTestDialog)

    def _show_child_window(self, attr: str, factory):
        """设置/数据源测试与管理器互相独立：非模态顶层窗口，可与管理器并存操作；

        单例复用——已存在则提前台（含从最小化还原），已销毁则新建；
        destroyed 信号清引用，避免悬空指针。
        """
        try:
            existing = getattr(self, attr, None)
            if existing is not None:
                if existing.isMinimized():
                    existing.showNormal()
                else:
                    existing.show()
                existing.raise_()
                existing.activateWindow()
                return
        except RuntimeError:
            # C++ 对象已被销毁（WA_DeleteOnClose 释放），换新的
            setattr(self, attr, None)
        dialog = factory()
        dialog.destroyed.connect(lambda *_a, _attr=attr: setattr(self, _attr, None))
        setattr(self, attr, dialog)
        dialog.show()

    def _on_clear_cache(self):
        from ..config.resources import resources

        cache_dirs = [self.cache_dir, resources.u("actor")]
        reply = QMessageBox.question(
            self,
            "确认清空缓存",
            "将删除已下载的演员头像缓存，下次获取时会重新下载\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        import shutil

        for cache_dir in cache_dirs:
            if not cache_dir.is_dir():
                continue
            for f in cache_dir.iterdir():
                try:
                    if f.is_dir():
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        f.unlink()
                    removed += 1
                except Exception:
                    continue
        self.log(f"🧹 已清空 {len(cache_dirs)} 个缓存目录，删除 {removed} 个文件/目录")

    def _open_log_file(self):
        """打开演员管理器日志文件（追加模式）。

        议题 #88：与主程序日志同目录（data_folder/Log，而非 userdata/logs），
        并按打开时刻加时间戳命名（如 2026-09-07-05-13-17 actor_manager.log），
        避免历次会话全塞进同一个 actor_manager.log。
        """
        import time

        try:
            log_dir = manager.data_folder / "Log"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%d-%H-%M-%S")
            self._log_file = log_dir / f"{ts} actor_manager.log"
        except Exception:
            self._log_file = None

    def _close_log_file(self):
        """关闭日志文件（由 Qt 在窗口关闭时自动调用）"""
        self._log_file = None

    def log(self, msg: str):
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] {msg}"
        self.log_text.appendPlainText(formatted)
        if self._log_file is not None:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_connect.setEnabled(enabled)
        # 获取演员列表无需前置手动连接：未连接时点击会自动连接后再取数，故只看总开关。
        self.btn_fetch.setEnabled(enabled)
        actors = getattr(self, "_actors", None) or []
        # 预览/清洗按钮常开：无演员列表时点击会自动走完链路，故只看总开关。
        self.cmb_data_tool.setEnabled(enabled)
        self.btn_clean.setEnabled(enabled)
        pending = any(a.need_update_info or a.need_update_image or a.need_update_backdrop for a in actors)
        self.btn_sync.setEnabled(enabled and pending)

    def _is_connection_current(self, url: str, key: str) -> bool:
        """输入框地址/密钥与已连接会话一致时才视为可直接取数。"""
        return bool(self._connected) and url == (self._emby_url or "") and key == (self._emby_key or "")

    def _start_connect_test(self, url: str, key: str) -> bool:
        """提交连接探测；返回 False 表示提交失败（调用方自行恢复按钮）。"""
        from .emby_shared import _emby_api_prefix, _emby_get_json

        # 先暂存待验证值，成功后才写入 _emby_url/_emby_key 并持久化，避免错误地址污染已有连接。
        self._pending_url = url
        self._pending_key = key

        async def test():
            # 议题 #133: 连接探测改用轻量直连 httpx(无指纹/无池/无限流)。
            # Emby/Jellyfin 都用 Authorization 头携带 token, 统一走 header 校验,
            # 不再为 Emby 单独拼 ?api_key=。token 必须经 token= 参数透传给
            # _emby_request, 仅预拼 headers 会被其按全局配置重写回旧密钥,
            # 导致换新密钥后仍用旧密钥探测而一直 401。
            # 用输入框地址拼绝对 URL 探测，避免新地址尚未持久化时误测旧地址。
            probe_url = f"{url.rstrip('/')}{_emby_api_prefix()}/System/Info"
            resp, err = await _emby_get_json(probe_url, token=key)
            if resp:
                name = resp.get("ServerName", "Emby")
                version = resp.get("Version", "")
                return True, f"连接成功！{name} v{version}"
            return False, f"连接失败: {err}"

        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("连接中...")
        self._set_status("连接中...")
        try:
            future = executor.submit(test())
        except Exception as e:
            future = None
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("已连接" if self._connected else "连接Emby/Jellyfin")
            self.btn_fetch.setEnabled(True)
            self._pending_auto_fetch = False
            self._set_status("连接失败")
            self.log(f"❌ 连接失败: {e}")
            return False
        future.add_done_callback(lambda fut: self._connect_result.emit(_future_result_or(fut, (False, "连接失败"))))
        return True

    def _on_connect(self):
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请输入服务器地址和 API 密钥")
            return
        self._pending_auto_fetch = False
        self._start_connect_test(url, key)

    def _on_connect_result(self, result: tuple[bool, str]):
        ok, msg = result
        self.btn_connect.setEnabled(True)
        # 手动用错误地址复测失败时，已有连接不应被按钮文案抹掉。
        self.btn_connect.setText("已连接" if (ok or self._connected) else "连接Emby/Jellyfin")
        # 获取/预览/清洗按钮触发的自动连接：恢复可点状态由后续流程接管，失败时才在此恢复。
        pending_fetch = self._pending_auto_fetch
        pending_preview = self._pending_auto_preview
        pending_clean = self._pending_auto_clean
        pending_export = self._pending_auto_export
        if ok:
            self._connected = True
            self._emby_url = getattr(self, "_pending_url", self.txt_url.text().strip())
            self._emby_key = getattr(self, "_pending_key", self.txt_api_key.text().strip())
            self.btn_fetch.setEnabled(True)
            self._set_status("连接成功")
            self.log(f"✅ {msg}")
            self._persist_connection()
            if pending_preview:
                self._pending_auto_preview = False
                # 配置已持久化，后续请求走新地址：有演员列表直接取数预览，
                # 否则先走媒体库流程，取到列表后再自动取数预览。
                if self._actors:
                    self._start_preview()
                else:
                    self._pending_auto_preview = True
                    self._request_media_folders()
            elif pending_clean:
                self._pending_auto_clean = False
                # 配置已持久化：有演员列表直接进清洗流程，
                # 否则先走媒体库流程，取到列表后再自动进清洗流程。
                if self._actors:
                    self._start_clean()
                else:
                    self._pending_auto_clean = True
                    self._request_media_folders()
            elif pending_export:
                self._pending_auto_export = False
                # 配置已持久化：有演员列表直接导出，
                # 否则先走媒体库流程，取到列表后再自动导出。
                if self._actors:
                    self._do_export_actors()
                else:
                    self._pending_auto_export = True
                    self._request_media_folders()
            elif pending_fetch:
                self._pending_auto_fetch = False
                # 配置已持久化，后续媒体库/演员请求走新地址，直接进入取数流程。
                self._request_media_folders()
        else:
            if pending_fetch:
                self._pending_auto_fetch = False
                self.btn_fetch.setEnabled(True)
            if pending_preview:
                self._pending_auto_preview = False
            if pending_clean:
                self._pending_auto_clean = False
            if pending_export:
                self._pending_auto_export = False
            self._set_status("连接失败")
            self.log(f"❌ {msg}")
            QMessageBox.critical(self, "连接失败", f"服务器地址或 API 密钥错误\n{msg}")

    def _on_connection_text_changed(self):
        """地址/密钥输入框变化：已连接会话即失效（下次获取自动重连），并防抖自动保存。"""
        if self._connected and not self._is_connection_current(
            self.txt_url.text().strip(), self.txt_api_key.text().strip()
        ):
            self._connected = False
            self.btn_connect.setText("连接Emby/Jellyfin")
            self._set_status("连接信息已修改，请重新连接或获取")
        self._conn_save_timer.start()

    def _auto_save_connection_fields(self):
        """防抖到期后把输入框最新值写回全局配置并存盘。

        密钥（含清空成空串）直接保存，重开对话框即显示最新值/空；
        地址沿用主窗口同款归一化后仅在合法非空时保存——配置模型
        emby_url 为 HttpUrl 存不住空串，清空时输入框维持空显示，
        下次打开会回填上次合法地址（与主窗口行为一致）。
        """
        url_text = self.txt_url.text().strip()
        key_text = self.txt_api_key.text().strip()
        try:
            cfg = manager.config.model_copy(deep=True)
        except Exception:
            return
        changed = False
        if key_text != (cfg.api_key or ""):
            cfg.api_key = key_text
            changed = True
        norm = url_text.replace("：", ":").strip("/ ")
        if norm and "://" not in norm:
            norm = "http://" + norm
        if norm:
            try:
                new_url = HttpUrl(norm)
            except Exception:
                new_url = None
            if new_url is not None and str(cfg.emby_url) != str(new_url):
                cfg.emby_url = new_url
                changed = True
        if not changed:
            return
        try:
            manager._replace_config(cfg)
        except Exception:
            return
        threading.Thread(target=manager.save, daemon=True).start()

    def _persist_connection(self):
        """把 UI 填写的地址/密钥写回全局配置，保证后续请求与界面一致。"""
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.api_key = self._emby_key
            cfg.emby_url = HttpUrl(self._emby_url)
            manager._replace_config(cfg)
            # 写盘移后台线程，避免主线程同步 IO 卡顿
            threading.Thread(target=manager.save, daemon=True).start()
            self.log("💾 已保存连接设置到配置")
        except Exception as e:
            self.log(f"🔶 连接设置保存失败，继续使用当前配置: {e}")

    def _on_fetch(self):
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请填写服务器地址和 API 密钥")
            return
        if not self._is_connection_current(url, key):
            # 未连接或输入框改过地址/密钥：先自动连接，成功后继续取数。
            # 新链路接管，旧的预览/清洗/导出待处理标记作废，避免后续回调误触发。
            self._pending_auto_fetch = True
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            self.btn_fetch.setEnabled(False)
            self.log("⏳ 正在自动连接服务器...")
            if not self._start_connect_test(url, key):
                self._pending_auto_fetch = False
                self.btn_fetch.setEnabled(True)
            return
        self._request_media_folders()

    def _request_media_folders(self):
        self.btn_fetch.setEnabled(False)
        self._set_status("获取媒体库列表...")
        try:
            future = executor.submit(get_media_folders())
        except Exception as e:
            self.btn_fetch.setEnabled(True)
            self._set_status("获取媒体库列表失败")
            self.log(f"❌ 获取媒体库列表失败: {e}")
            return
        future.add_done_callback(lambda fut: self._media_folders_result.emit(_future_result_or(fut, [])))

    def _on_media_folders_result(self, libraries: list[dict]):
        self.btn_fetch.setEnabled(True)
        if not libraries:
            self._set_status("获取媒体库列表失败")
            self.log("❌ 无法获取媒体库列表")
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            return
        dlg = LibrarySelectDialog(libraries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.log("⏹ 用户取消")
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            return
        selected_ids = dlg.get_selected_ids()
        if not selected_ids:
            QMessageBox.warning(self, "提示", "请至少选择一个媒体库")
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            return
        library_ids = None if len(selected_ids) == len(libraries) else selected_ids
        self._current_library_ids = library_ids  # 供同步后自动刷新复用，避免丢媒体库过滤
        self._set_buttons_enabled(False)
        self._set_status("获取演员列表...")
        self.log("📜 开始获取演员列表...")
        self._fetch_thread = FetchActorsThread(self)
        self._fetch_thread.library_ids = library_ids
        self._begin_session(self._fetch_thread)
        self._fetch_thread.progress.connect(self._on_fetch_progress)
        self._fetch_thread.fetch_done.connect(self._on_fetch_finished)
        self._fetch_thread.error.connect(self._on_thread_error)
        self._fetch_thread.start()

    def _on_fetch_progress(self, current: int, total: int, msg: str):
        if self._is_stale_session():
            return
        if total > 0:
            self._set_progress(current, total, "获取演员列表")
        self.setWindowTitle(f"Emby/Jellyfin演员管理器 - {msg}")

    def _on_fetch_finished(self, actors: list[ActorInfo], raw_count: int, all_staff_count: int = 0):
        if self._is_stale_session():
            return
        self._actors = actors
        self._raw_count = raw_count
        # 议题 #158: 全量统计查询可能单独失败(0), 别把已知的总数抹成 0 显示「总数: 0」
        if all_staff_count > 0:
            self._all_staff_count = all_staff_count
        self._set_status("获取完成")
        unique_names = len({a.name for a in actors})
        dup = max(raw_count - unique_names, 0)
        self.log(
            f"获取完成，共 {len(actors)} 个演员（原始条目 {raw_count}，唯一名字 {unique_names}，重复 {dup}，全服总数 {self._all_staff_count}）"
        )
        self._populate_table(actors)
        self._update_statistics(actors)
        self._set_buttons_enabled(True)
        # 清洗链式流程无需等头像索引：取到列表后直接进清洗流程（含确认弹窗）。
        if self._pending_auto_clean:
            self._pending_auto_clean = False
            if actors:
                self._start_clean()
            else:
                self.log("⚠️ 未获取到演员，无法继续数据清洗")
        # 导出链式流程同样无需等头像索引：取到列表后直接导出。
        if self._pending_auto_export:
            self._pending_auto_export = False
            if actors:
                self._do_export_actors()
            else:
                self.log("⚠️ 未获取到演员，无法导出")
        try:
            future = executor.submit(get_gfriends_index())
        except Exception as e:
            self.log(f"🔶 Gfriends 索引加载失败: {e}")
            if self._pending_auto_preview:
                self._pending_auto_preview = False
                if actors:
                    self._start_preview()
            return
        future.add_done_callback(lambda fut: self._gfriends_result.emit(_future_result_or(fut, None)))

    def _on_gfriends_result(self, index):
        self._gfriends_index = index
        if index:
            self.log(f"✅ Gfriends 头像库加载完成，共 {len(index)} 个头像")
        # 预览链式流程等头像索引就绪后再取数预览，避免首轮漏掉 Gfriends 源。
        if self._pending_auto_preview:
            self._pending_auto_preview = False
            if self._actors:
                self._start_preview()
            else:
                self.log("⚠️ 未获取到演员，无法继续获取数据")

    def _on_prepare_preview(self):
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.cancel()
            # 议题 #25: 代数+1 作废旧线程全部排队回调；UI 立即恢复可操作，
            # 不再等旧线程收尾信号（旧版依赖它恢复按钮，cancel→快速重开存在覆盖窗口）
            self._session_gen += 1
            self.log("⏹️ 用户取消")
            self._set_status("已取消")
            self._set_buttons_enabled(True)
            return
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请填写服务器地址和 API 密钥")
            return
        if not self._is_connection_current(url, key):
            # 未连接或输入框改过地址/密钥：先自动连接，成功后继续取数预览。
            # 新链路接管，旧的获取/清洗/导出待处理标记作废，避免后续回调误触发。
            self._pending_auto_preview = True
            self._pending_auto_fetch = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            self.log("⏳ 正在自动连接服务器...")
            if not self._start_connect_test(url, key):
                self._pending_auto_preview = False
            return
        if not self._actors:
            # 已连接但尚无演员列表：先走媒体库流程，取到列表后自动取数预览。
            self._pending_auto_preview = True
            self._pending_auto_fetch = False
            self._pending_auto_clean = False
            self._pending_auto_export = False
            self._request_media_folders()
            return
        self._start_preview()

    def _start_preview(self):
        mode_map = {
            "仅缺失简介": "missing_info",
            "仅缺失头像": "missing_image",
            "头像和简介都缺": "missing_both",
            "缺失头像或缺失简介": "missing_all",
            "重新获取所有演员详情": "force_info",
            "重新获取所有演员简介": "force_overview",
            "重新获取所有演员头像": "force_image",
            "重新获取所有演员头像和简介": "force_all",
        }
        mode = mode_map.get(self.cmb_fetch_mode.currentText(), "missing_all")
        # 议题 #127: 「缺失」类模式只处理子集, 不再逐人遍历全库
        targets = PreparePreviewThread.select_targets(self._actors, mode)
        if self._actors and not targets:
            self.log("✅ 按当前模式没有需要获取数据的演员")
            return
        self._set_buttons_enabled(False)
        # 取数中下拉框保持可用：再次选择「数据获取」即停止获取（旧「停止获取」按钮同款）。
        self.cmb_data_tool.setEnabled(True)
        self._set_status("获取数据中...")
        self.log(f"📥 正在获取数据（模式: {self.cmb_fetch_mode.currentText()}，共 {len(targets)} 人）")
        self._preview_thread = PreparePreviewThread(self)
        self._preview_thread.actors = self._actors
        self._preview_thread.targets = targets
        self._preview_thread.mode = mode
        self._preview_thread.gfriends_index = self._gfriends_index
        self._preview_thread.cache_dir = self.cache_dir
        self._preview_thread.image_sources = list(manager.config.actor_image_sources)

        self._preview_thread.local_avatar_dir = (
            manager.config.actor_photo_folder if hasattr(manager.config, "actor_photo_folder") else ""
        )
        self._begin_session(self._preview_thread)
        self._preview_thread.progress.connect(self._on_fetch_progress)
        self._preview_thread.preview_done.connect(self._on_preview_finished)
        self._preview_thread.error.connect(self._on_thread_error)
        self._preview_thread.start()

    def _on_preview_finished(self, actors: list[ActorInfo]):
        if self._is_stale_session():
            return
        self._actors = actors
        self._populate_table(actors)
        self._update_statistics(actors)
        to_sync = [a for a in actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        self.btn_sync.setEnabled(len(to_sync) > 0)
        self.btn_sync.setText(f"开始全部更新同步({len(to_sync)} 项)")
        self._set_status("数据准备完成")
        self.log(f"✅ 预览准备完成，{len(to_sync)} 项待同步")
        self._set_buttons_enabled(True)

    def _on_clean_data(self):
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请填写服务器地址和 API 密钥")
            return
        if not self._is_connection_current(url, key):
            # 未连接或输入框改过地址/密钥：先自动连接，成功后继续清洗流程。
            # 新链路接管，旧的获取/预览/导出待处理标记作废，避免后续回调误触发。
            self._pending_auto_clean = True
            self._pending_auto_fetch = False
            self._pending_auto_preview = False
            self._pending_auto_export = False
            self.log("⏳ 正在自动连接服务器...")
            if not self._start_connect_test(url, key):
                self._pending_auto_clean = False
            return
        if not self._actors:
            # 已连接但尚无演员列表：先走媒体库流程，取到列表后自动进清洗流程。
            self._pending_auto_clean = True
            self._pending_auto_fetch = False
            self._pending_auto_preview = False
            self._pending_auto_export = False
            self._request_media_folders()
            return
        self._start_clean()

    def _on_data_tool_chosen(self, index: int):
        """数据工具下拉框：0 数据获取 / 1 数据清洗 / 2 数据导出 / 3 数据导入。"""
        try:
            text = self.cmb_data_tool.itemText(index)
        except (RuntimeError, AttributeError):
            return
        if text == "数据获取":
            self._on_prepare_preview()
            return
        if self._preview_thread and self._preview_thread.isRunning():
            # 取数中下拉框保持可用作停止开关：其他选项此时不执行，避免并发互踩。
            QMessageBox.information(self, "提示", "正在获取中，请稍候")
            return
        if text == "数据导出":
            self._on_export_data()
        elif text == "数据导入":
            self._on_import_data()
        else:
            self._on_clean_data()

    def _on_export_data(self):
        """数据导出：未连接时自动连接，无演员列表时自动获取后再导出。"""
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请填写服务器地址和 API 密钥")
            return
        if not self._is_connection_current(url, key):
            # 未连接或输入框改过地址/密钥：先自动连接，成功后继续导出流程。
            # 新链路接管，旧的获取/预览/清洗待处理标记作废，避免后续回调误触发。
            self._pending_auto_export = True
            self._pending_auto_fetch = False
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self.log("⏳ 正在自动连接服务器...")
            if not self._start_connect_test(url, key):
                self._pending_auto_export = False
            return
        if not self._actors:
            # 已连接但尚无演员列表：先走媒体库流程，取到列表后自动导出。
            self._pending_auto_export = True
            self._pending_auto_fetch = False
            self._pending_auto_preview = False
            self._pending_auto_clean = False
            self._request_media_folders()
            return
        self._do_export_actors()

    def _on_import_data(self):
        """数据导入：暂未实现，给出明确提示。"""
        QMessageBox.information(self, "数据导入", "数据导入功能开发中，暂不可用。")

    def _do_export_actors(self):
        """把当前演员列表导出为 xlsx（文件名：演员数据表<时间>.xlsx）。

        每次导出都弹文件保存框让用户确认：文件名显示框内预填本次要导出的文件名，
        初始目录为设置里的导出目录（有效时）；用户确认后按所选路径导出，
        所选目录写回配置；取消则中止导出。
        """
        from .emby_actor_export import (
            EXPORT_FALLBACK_SCREEN_PX,
            effective_screen_width_px,
            export_filename,
            resolve_export_dir,
            text_col_width_for_screen_width,
            write_actor_export_xlsx,
        )

        actors = self._get_filtered_actors() if self._actors else []
        if not actors:
            QMessageBox.information(self, "数据导出", "当前没有可导出的演员数据。")
            return
        configured = resolve_export_dir(getattr(manager.config, "actor_export_folder", ""))
        default_path = (
            str(Path(str(configured)) / export_filename())
            if configured
            else export_filename()
        )
        chosen, _selected_filter = QFileDialog.getSaveFileName(
            self, "选择数据导出目录", default_path, "Excel 工作簿 (*.xlsx)"
        )
        if not chosen:
            self.log("⏹ 已取消数据导出（未选择导出目录）")
            return
        file_path = Path(chosen)
        if file_path.suffix.lower() != ".xlsx":
            file_path = file_path.with_suffix(".xlsx")
        export_dir = file_path.parent
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.actor_export_folder = str(export_dir)
            manager._replace_config(cfg)
            manager.save()
            self.log(f"💾 已保存数据导出目录到配置: {export_dir}")
        except Exception as e:
            self.log(f"🔶 数据导出目录保存失败，继续使用所选目录: {e}")
        # 列宽按用户屏幕逻辑宽度计算（物理宽 / Windows 缩放比，如 1920@125% → 1536）：
        # 扣除左侧序号列、右侧滚动条与出生日期/头像/简介/状态固定列宽后，
        # 剩余均分给姓名/详情/出生地/标签，保证头像/简介/状态三列默认可见、无需横向滚动。
        screen = self.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            screen_px = EXPORT_FALLBACK_SCREEN_PX
        else:
            screen_px = effective_screen_width_px(screen)
        text_width = text_col_width_for_screen_width(screen_px)
        try:
            write_actor_export_xlsx(file_path, actors, text_col_width=text_width)
        except Exception as e:
            self.log(f"❌ 数据导出失败: {e}")
            QMessageBox.critical(self, "数据导出失败", f"❌ 数据导出失败:\n{e}")
            return
        self.log(f"✅ 数据导出完成，共 {len(actors)} 个演员: {file_path}")
        QMessageBox.information(self, "数据导出完成", f"✅ 共导出 {len(actors)} 个演员:\n{file_path}")

    def _start_clean(self, rules=None):
        """数据清洗: 无规则时先弹独立规则编辑窗, 有规则时直接按规则扫描执行。

        规则窗与管理器互相独立: 无父级、非模态, 可与管理器并存操作,
        最小化/关闭/移动互不级联。单例复用——已存在则提前台。
        对话框打开时默认加载上次保存的规则(缺省时为两条 minnano 占位规则);
        点确定经 finished 回调保存用户编辑后的规则并回调用本函数执行,
        点取消/X 则直接返回。按当前规则无待清洗数据时仅提示, 不启动线程(规则已保存)。
        """
        if rules is None:
            if not self._actors:
                return
            try:
                existing = self._clean_rules_dialog
                if existing is not None:
                    if existing.isMinimized():
                        existing.showNormal()
                    else:
                        existing.show()
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                # C++ 对象已被销毁(WA_DeleteOnClose 释放), 换新的
                self._clean_rules_dialog = None
            dialog = ActorCleanRulesDialog(list(self._actors))
            _self_ref = weakref.ref(self)

            def _forget(*_a, _ref=_self_ref):
                mgr = _ref()
                if mgr is None:
                    return
                try:
                    mgr._clean_rules_dialog = None
                except (RuntimeError, AttributeError):
                    pass

            dialog.destroyed.connect(_forget)

            # finished 接到闭包而非管理器 bound method: 闭包只弱引管理器,
            # 管理器先被回收时规则窗仍能独立收尾(确定则保存规则), 且连接本身
            # 不再强留管理器, 两窗生命周期彻底解耦。
            def _on_done(result, _ref=_self_ref, _dlg=dialog):
                mgr = _ref()
                if mgr is None:
                    if result == QDialog.DialogCode.Accepted:
                        try:
                            save_clean_rules(_dlg.rules())
                        except Exception:
                            pass
                    return
                try:
                    mgr._on_clean_rules_finished(result)
                except RuntimeError:
                    pass

            dialog.finished.connect(_on_done)
            # 注册表多持一份强引用, 随 destroyed 按 id 摘除, 详见模块级说明。
            _dialog_key = id(dialog)
            _OPEN_CLEAN_RULES_DIALOGS[_dialog_key] = dialog
            dialog.destroyed.connect(lambda *_a, _key=_dialog_key: _OPEN_CLEAN_RULES_DIALOGS.pop(_key, None))
            self._clean_rules_dialog = dialog
            dialog.show()
            return
        dirty = scan_actor_data_noise(self._actors, rules)
        if not dirty:
            try:
                QMessageBox.information(self, "数据清洗", "✅ 按当前规则未发现需要清洗的数据")
            except RuntimeError:
                pass
            return
        self._set_buttons_enabled(False)
        self._set_status("数据清洗中...")
        self.log(f"🧹 开始数据清洗，共 {len(dirty)} 个演员...")
        self._clean_items = {a.actor_id: (new_ov, fix_birth) for a, new_ov, fix_birth in dirty}
        self._clean_failed = []
        self._clean_thread = CleanDataThread(self)
        self._clean_thread.items = dirty
        self._begin_session(self._clean_thread)
        self._clean_thread.progress.connect(self._on_sync_progress)
        self._clean_thread.actor_done.connect(self._on_clean_actor_done)
        self._clean_thread.clean_done.connect(self._on_clean_finished)
        self._clean_thread.error.connect(self._on_thread_error)
        self._clean_thread.start()

    def _on_clean_rules_finished(self, result):
        """独立规则窗 finished 回调: 确定则保存规则并回切清洗执行, 取消则丢弃。

        规则窗已独立于管理器——管理器先关导致 UI 已销毁时, 仅持久化规则不再起线程,
        避免撞上已销毁的 C++ 对象。
        """
        try:
            dialog = self._clean_rules_dialog
        except (RuntimeError, AttributeError):
            return
        if dialog is None:
            return
        try:
            accepted = result == QDialog.DialogCode.Accepted
            rules_data = dialog.rules() if accepted else None
        except RuntimeError:
            try:
                self._clean_rules_dialog = None
            except (RuntimeError, AttributeError):
                pass
            return
        # 先摘除引用再销毁: 规则窗关闭不影响管理器, 管理器清洗也不影响规则窗。
        try:
            self._clean_rules_dialog = None
            dialog.deleteLater()
        except RuntimeError:
            pass
        if not accepted or rules_data is None:
            return
        try:
            rules = save_clean_rules(rules_data)
        except Exception:
            return
        self._clean_rules = list(rules)
        try:
            self._start_clean(rules)
        except RuntimeError:
            pass

    def _on_clean_actor_done(self, actor_id: str, success: bool, msg: str):
        if self._is_stale_session():
            return
        # 清洗成功后立即就地更新内存状态; 失败保留原值, 下次清洗可重试
        # 议题 #162: 失败逐条落日志(名字+服务器原因), 完成时汇总, 消除"只见计数不见原因"盲区
        if not success:
            self._clean_failed.append((actor_id, msg))
            self.log(f"🔴 清洗失败: {msg}")
            return
        actor = next((a for a in self._actors if a.actor_id == actor_id), None)
        item = self._clean_items.get(actor_id)
        if actor is None or item is None:
            return
        new_ov, fix_birth = item
        actor.existing_overview = new_ov
        # 与 is_missing_overview 同口径: 纯空白简介算「缺简介」, 否则清洗出一个空白简介
        # 反而会把「缺简介」计数改小, 出现「越清洗缺得越少」的假象。
        actor.has_overview = bool((new_ov or "").strip())
        if fix_birth:
            actor.existing_premiere_date = ""

    def _on_clean_finished(self, success: int, fail: int):
        if self._is_stale_session():
            return
        self._set_buttons_enabled(True)
        self._set_status("数据清洗完成")
        self._clean_items = {}
        # 数据清洗完成后默认保存用户修改编辑后的规则(本次实际使用的规则, 含两条常驻默认)。
        _pending_rules = getattr(self, "_clean_rules", None)
        if _pending_rules:
            save_clean_rules(_pending_rules)
            self._clean_rules = []
        self.log(f"🧹 数据清洗完成！成功: {success}, 失败: {fail}")
        # 议题 #162: 清洗是直接改写服务器的, 无"待同步"残留——完成提示讲清这一点,
        # 并列出失败者名单与重试指引, 避免用户误以为还要点「开始全部更新同步」。
        names = []
        for actor_id, _ in self._clean_failed:
            actor = next((a for a in self._actors if a.actor_id == actor_id), None)
            names.append(actor.name if actor else actor_id)
        self._clean_failed = []
        detail = ""
        if names:
            preview = "、".join(names[:20]) + ("…" if len(names) > 20 else "")
            detail = f"\n\n❌ 失败 {len(names)} 个: {preview}\n失败原因见上方运行日志；再点一次「数据清洗」即可仅重试失败项。"
        if fail == 0:
            detail += "\n\n清洗已直接写入服务器，无需再点「开始全部更新同步」。"
        QMessageBox.information(self, "数据清洗完成", f"✅ 成功: {success}\n❌ 失败: {fail}{detail}")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)

    def _on_sync(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        if not to_sync:
            QMessageBox.information(self, "提示", "没有需要同步的项")
            return
        reply = QMessageBox.question(
            self,
            "确认同步",
            f"将同步 {len(to_sync)} 个演员的信息/头像/背景图到 Emby/Jellyfin，\n此操作不可撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_buttons_enabled(False)
        self.btn_sync.setText("同步中...")
        self._set_status("同步中...")
        self.log(f"📛 开始同步 {len(to_sync)} 个演员...")
        self._failed_names.clear()
        self._sync_thread = SyncThread(self)
        self._sync_thread.actors = to_sync
        self._begin_session(self._sync_thread)
        self._sync_thread.progress.connect(self._on_sync_progress)
        self._sync_thread.actor_done.connect(self._on_sync_actor_done)
        self._sync_thread.sync_done.connect(self._on_sync_finished)
        self._sync_thread.error.connect(self._on_thread_error)
        self._sync_thread.start()

    def _on_sync_progress(self, current: int, total: int, msg: str):
        if self._is_stale_session():
            return
        self._set_progress(current, total, "同步")
        self.setWindowTitle(f"Emby/Jellyfin演员管理器 - {msg}")

    def _on_sync_actor_done(self, actor_id: str, name: str, success: bool, msg: str):
        if self._is_stale_session():
            return
        # 用 actor_id 匹配，避免同名演员（未去重时）按名字错位更新状态
        actor = next((a for a in self._actors if a.actor_id == actor_id), None)
        if success:
            if actor is not None:
                self._apply_sync_success(actor)
            self.log(f"✅ {name} 同步成功")
        else:
            # 失败的演员保留 need_update 标记，可在下次同步重试;
            # 按 actor_id 记录, 同名多条目(未去重)不会互相覆盖。
            self._failed_names.add(actor_id)
            self.log(f"❌ {name} 同步失败: {msg}")

    def _apply_sync_success(self, a: ActorInfo):
        if a.need_update_image:
            a.has_image = bool(a.new_image_path)
            a.need_update_image = False
        if a.need_update_info:
            a.has_overview = bool(a.new_overview and a.new_overview.strip())
            a.existing_overview = a.new_overview or a.existing_overview
            a.existing_taglines = list(a.new_taglines)
            a.existing_production_year = a.new_production_year
            a.existing_premiere_date = a.new_premiere_date
            a.existing_production_locations = list(a.new_production_locations)
            a.need_update_info = False
        if a.need_update_backdrop:
            a.has_backdrop = bool(a.new_backdrop_path)
            a.need_update_backdrop = False

    def _on_sync_finished(self, success: int, fail: int):
        if self._is_stale_session():
            return
        self._set_buttons_enabled(True)
        self.btn_sync.setText("开始全部更新同步")
        self._set_status("同步完成")
        self.log(f"同步完成！成功: {success}, 失败: {fail}")
        QMessageBox.information(self, "同步完成", f"✅ 成功: {success}\n❌ 失败: {fail}")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        # 同步完成后 3 秒自动重新获取演员列表，确保与 Emby 完全一致
        self.log("⏳ 3 秒后自动刷新演员列表...")
        QTimer.singleShot(3000, self._on_auto_refresh)

    def _on_auto_refresh(self):
        if not hasattr(self, "_connected") or not self._connected:
            return
        self._set_buttons_enabled(False)
        self.log("🔄 正在自动刷新演员列表...")
        self._refresh_thread = FetchActorsThread(self)
        self._refresh_thread.library_ids = getattr(self, "_current_library_ids", None)
        self._refresh_thread.progress.connect(self._on_fetch_progress)
        self._refresh_thread.fetch_done.connect(self._on_auto_refresh_finished)
        self._refresh_thread.error.connect(self._on_thread_error)
        self._refresh_thread.start()

    def _on_auto_refresh_finished(self, actors: list[ActorInfo], raw_count: int, all_staff_count: int = 0):
        # fetch_done 信号为 (list, int, int) 三参, 此处必须同形接收,
        # 否则自动刷新完成时触发 TypeError, 且「总数」栏无法更新。
        if self._failed_names:
            failed_old = {a.actor_id: a for a in self._actors if a.actor_id in self._failed_names}
            if failed_old:
                merged = []
                for new in actors:
                    old = failed_old.get(new.actor_id)
                    if old is None:
                        merged.append(new)
                        continue
                    # 失败演员保留待同步状态与本地新数据，仅用刷新结果更新服务器侧状态
                    old.has_image = new.has_image
                    old.has_overview = new.has_overview
                    old.has_backdrop = new.has_backdrop
                    old.existing_overview = new.existing_overview
                    old.movie_count = new.movie_count
                    old.movie_titles = new.movie_titles
                    merged.append(old)
                actors = merged
                self.log(f"🔁 已保留 {len(failed_old)} 个同步失败演员的待同步状态，可直接重试")
        self._actors = actors
        self._raw_count = raw_count
        if all_staff_count:
            self._all_staff_count = all_staff_count
        self._populate_table(actors)
        self._update_statistics(actors)
        self._set_status("自动刷新完成")
        unique_names = len({a.name for a in actors})
        self.log(
            f"✅ 自动刷新完成，共 {len(actors)} 个演员（原始条目 {raw_count}，唯一名字 {unique_names}，全服总数 {self._all_staff_count}）"
        )
        self._set_buttons_enabled(True)

    def _on_thread_error(self, msg: str):
        if self._is_stale_session():
            return
        # 链式流程中断：清掉待处理的自动获取/预览/清洗/导出标记，避免后续回调误触发。
        self._pending_auto_fetch = False
        self._pending_auto_preview = False
        self._pending_auto_clean = False
        self._pending_auto_export = False
        # 线程已结束，恢复按钮状态，避免"同步中..."残留
        self.btn_sync.setText("开始全部更新同步")
        self._set_buttons_enabled(True)
        self.log(f"🔶 错误: {msg}")
        QMessageBox.critical(self, "错误", msg)

    def closeEvent(self, event):
        # 议题 #175: 获取数据中关窗会 "QThread: Destroyed while thread is still running"
        # 把整个进程 abort（Windows 上看起来像主程序一起退出，日志为空）。
        # 关闭前取消全部工作线程并等待；超时则卸父级，避免随 WA_DeleteOnClose 一起销毁。
        self._shutdown_worker_threads()
        super().closeEvent(event)

    def _shutdown_worker_threads(self, timeout_ms: int = 5000) -> None:
        attrs = ("_fetch_thread", "_preview_thread", "_sync_thread", "_clean_thread", "_refresh_thread")
        threads = []
        for attr in attrs:
            thread = getattr(self, attr, None)
            if thread is None:
                continue
            for sig_name in (
                "progress",
                "error",
                "fetch_done",
                "preview_done",
                "sync_done",
                "clean_done",
                "actor_done",
            ):
                sig = getattr(thread, sig_name, None)
                if sig is None:
                    continue
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            if hasattr(thread, "abort"):
                thread.abort()
            elif hasattr(thread, "cancel"):
                thread.cancel()
            threads.append(thread)
        remaining = timeout_ms
        for thread in threads:
            if not thread.isRunning():
                continue
            waited = thread.wait(max(remaining, 0))
            if waited or not thread.isRunning():
                continue
            _detach_running_thread(thread)
            remaining = 0

    def _on_filter_changed(self):
        self._populate_table(self._actors)

    def _on_table_double_clicked(self, row: int, col: int):
        # 表格启用排序后视觉行序 != _get_filtered_actors() 索引，用演员名反查，避免打开错误演员
        item = self.table.item(row, 1)
        if item is None:
            return
        name = item.text()
        actor = next((a for a in self._actors if a.name == name), None)
        if actor is None:
            return
        self._open_detail_dialog(actor)

    def _open_detail_dialog(self, actor: ActorInfo):
        """演员详情独立窗口：无父级、非模态，与管理器互不干扰、可并存操作。

        同一演员只开一个（已存在则前台/还原）；不同演员可多开。
        打开位置落在管理器中央，之后各走各的几何。
        """
        key = actor.actor_id or actor.name
        existing = self._detail_dialogs.get(key)
        if existing is not None:
            try:
                if existing.isMinimized():
                    existing.showNormal()
                else:
                    existing.show()
                existing.raise_()
                existing.activateWindow()
                return existing
            except RuntimeError:
                # C++ 对象已被销毁，掉进新建分支
                self._detail_dialogs.pop(key, None)
        dialog = ActorDetailDialog(actor, None, on_synced=self._make_detail_synced())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 定位交给 ActorDetailDialog.showEvent 里的 _center_on_screen()：严格居中于
        # 屏幕可用区。原先这里按「管理器窗口中心」定位，既会随管理器被拖动而偏移，
        # 又用客户区尺寸配 move()（move 收的是外框左上角），整体偏下偏右一个标题栏。
        # 重复打开时复用已有窗口：它已被用户挪过位置，保持原样、不再强制拉回正中。
        _self_ref = weakref.ref(self)

        def _forget(*_a, _key=key, _ref=_self_ref):
            mgr = _ref()
            if mgr is None:
                return
            try:
                mgr._detail_dialogs.pop(_key, None)
            except RuntimeError:
                pass

        dialog.destroyed.connect(_forget)
        self._detail_dialogs[key] = dialog
        dialog.show()
        return dialog

    def _make_detail_synced(self):
        """详情回写回调：弱引用守卫，管理器先关则静默丢弃（独立窗口互不干扰）。

        直接传 bound method 会强引用管理器，导致管理器关不掉、或关后回写
        撞上已销毁的 C++ 对象。
        """
        _self_ref = weakref.ref(self)

        def _synced(actor: ActorInfo):
            mgr = _self_ref()
            if mgr is None:
                return
            try:
                mgr._on_detail_synced(actor)
            except RuntimeError:
                pass

        return _synced

    def _on_detail_synced(self, actor: ActorInfo):
        # 同步单个演员后刷新主窗口表格与统计
        self.log(f"✅ {actor.name} 同步完成，刷新列表")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        self._update_sync_button()

    def _get_filtered_actors(self) -> list[ActorInfo]:
        filter_mode = self.cmb_filter.currentText()
        search_text = self.txt_search.text().strip().lower()
        # 与统计栏/取数模式共用同一缺失口径: 占位简介按缺简介处理 (#147)。
        # 此前这里直接读 has_overview, 占位简介者会被算作"有简介",
        # 与统计栏「缺简介」分项互相矛盾;「缺头像和简介」旧条件只剔除
        # has_image and has_overview 者, 会把单缺者也放进来。
        is_missing_image = PreparePreviewThread._is_missing_image
        is_missing_info = PreparePreviewThread._is_missing_info
        filtered = []
        for a in self._actors:
            missing_image = is_missing_image(a)
            missing_info = is_missing_info(a)
            if filter_mode == "缺头像" and not missing_image:
                continue
            elif filter_mode == "缺背景" and a.has_backdrop:
                continue
            elif filter_mode == "缺简介" and not missing_info:
                continue
            elif filter_mode == "缺头像和简介" and (not missing_image or not missing_info):
                continue
            elif filter_mode == "完整" and (missing_image or missing_info):
                continue
            elif filter_mode == "待同步" and not (a.need_update_info or a.need_update_image or a.need_update_backdrop):
                continue
            if search_text and search_text not in a.name.lower():
                continue
            filtered.append(a)
        return filtered

    def _populate_table(self, actors: list[ActorInfo]):
        self.table.setSortingEnabled(False)
        filtered = self._get_filtered_actors() if actors else []
        self.table.setRowCount(len(filtered))
        for row, actor in enumerate(filtered):
            icon_item = QTableWidgetItem(actor.status_icon)
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, icon_item)
            name_item = QTableWidgetItem(actor.name)
            name_item.setToolTip(f"ID: {actor.actor_id}")
            self.table.setItem(row, 1, name_item)
            img_item = QTableWidgetItem("✅" if actor.has_image else "❌")
            img_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_image:
                img_item.setText("🔄")
            img_item.setToolTip(
                f"头像: {'有' if actor.has_image else '无'} | 背景图: {'有' if actor.has_backdrop else '无'}"
            )
            self.table.setItem(row, 2, img_item)
            info_item = QTableWidgetItem("✅" if not is_missing_overview(actor) else "❌")
            info_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_info:
                info_item.setText("🔄")
            self.table.setItem(row, 3, info_item)
            # 详情列仅展示清洗文本：缺简介/占位/空一律置空，不显示“（无）”；
            # <br>/残留标签/“=”装饰线只在展示层剥除，数据与同步不受影响。
            if is_missing_overview(actor):
                try:
                    from ..models.emby import clean_overview_text as _clean_ov

                    _rest = _clean_ov(actor.existing_overview)
                except Exception:
                    _rest = ""
                overview_text = format_detail_cell_text(_rest)
            else:
                overview_text = format_detail_cell_text(actor.existing_overview)
            self.table.setItem(row, 4, QTableWidgetItem(overview_text))
            # 议题 #134：详情与标签之间展示出生日期、出生地，均为 Emby 服务器现有值
            raw_birthday = (actor.existing_premiere_date or "")[:10]
            # Emby 未设置生日时返回 0001-01-01，按空值展示，避免列表出现占位日期
            birthday_text = "" if raw_birthday.startswith("0001-01-01") else raw_birthday
            birthday_item = QTableWidgetItem(birthday_text)
            # 议题 #153：出生日期为定宽列, 居中显示与 状态/头像/影片数 列观感一致
            birthday_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, birthday_item)
            location_text = (
                ", ".join(actor.existing_production_locations) if actor.existing_production_locations else ""
            )
            self.table.setItem(row, 6, QTableWidgetItem(location_text))
            tags = ", ".join(actor.existing_taglines[:2]) if actor.existing_taglines else ""
            self.table.setItem(row, 7, QTableWidgetItem(tags))
            mc_item = QTableWidgetItem(str(actor.movie_count) if actor.movie_count > 0 else "0")
            mc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.movie_titles:
                mc_item.setToolTip("\n".join(actor.movie_titles[:20]))
            self.table.setItem(row, 8, mc_item)
            if actor.need_update_info or actor.need_update_image or actor.need_update_backdrop:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor("#c8e6c9"))
        self.table.setSortingEnabled(True)
        self._update_sync_button()
        # 取数后行高/视口落定，按当前窗口状态重对一次行数（纯内部，不碰窗口几何）。
        QTimer.singleShot(0, self._fit_visible_rows)

    def _on_count_mode_changed(self, index: int):
        self._show_unique = index == 1
        self._update_statistics(self._actors)
        # 议题 #143: 切换即保存, 重启 MDCx / 重开管理器后保持不变
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.actor_count_mode = 1 if index == 1 else 0
            manager._replace_config(cfg)
            manager.save()
        except Exception as e:
            self.log(f"🔶 计数方式保存失败: {e}")

    def _update_statistics(self, actors: list[ActorInfo]):
        actors = actors or []
        # 计数基数与「计数方式」下拉对齐: 唯一模式按名字去重(首条保留),
        # 原始模式按列表全部条目统计。分项恒以该基数划分, 保证
        # 唯一模式: 完整+缺头像+缺简介+全缺 == 演员;
        # 原始模式 + 去重抓取: 上式 + 重复 == 演员(去重抓取下重复条目细节已丢弃, 差额即重复数);
        # 原始模式 + 未去重抓取: 四项之和 == 演员, 重复为信息性展示(不另加, 否则 double-count)。
        if self._show_unique:
            seen: set[str] = set()
            base: list[ActorInfo] = []
            for a in actors:
                if a.name not in seen:
                    seen.add(a.name)
                    base.append(a)
            unique_count = len(seen)
            total = unique_count
        else:
            base = list(actors)
            unique_count = len({a.name for a in actors})
            total = self._raw_count if self._raw_count > 0 else len(actors)
        # 议题 #157: 重复数 = 过滤后条目数 − 唯一名字数, 与计数方式切换无关, 恒为同名多余条目
        self.lbl_duplicate.setText(f"重复: {max(self._raw_count - unique_count, 0)}")
        # 议题 #147: 分项与「获取数据」模式用同一套缺失判定 (占位简介按缺处理),
        # 保证统计栏的 缺头像/缺简介/全缺 之和与取数模式选中的候选数一致; 完整=两者皆不缺。
        # 变量名按"缺什么"命名, 避免 has_image_only/has_info_only 式反直觉旧名再次错位。
        is_missing_image = PreparePreviewThread._is_missing_image
        is_missing_info = PreparePreviewThread._is_missing_info
        complete = sum(1 for a in base if not is_missing_image(a) and not is_missing_info(a))
        missing_image_only = sum(1 for a in base if is_missing_image(a) and not is_missing_info(a))
        missing_info_only = sum(1 for a in base if is_missing_info(a) and not is_missing_image(a))
        missing_both = sum(1 for a in base if is_missing_image(a) and is_missing_info(a))
        backdrop_count = sum(1 for a in base if a.has_backdrop)
        self.lbl_all_staff.setText(f"总数: {self._all_staff_count}")
        self.lbl_total.setText(f"演员: {total}")
        self.lbl_has_both.setText(f"完整: {complete}")
        self.lbl_missing_image.setText(f"缺头像: {missing_image_only}")
        self.lbl_missing_info.setText(f"缺简介: {missing_info_only}")
        self.lbl_missing_all.setText(f"全缺: {missing_both}")
        self.lbl_backdrop.setText(f"有背景图: {backdrop_count}")

    def _update_sync_button(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        sync_count = len(to_sync)
        self.btn_sync.setEnabled(sync_count > 0)
        self.btn_sync.setText(f"开始全部更新同步({sync_count} 项)" if sync_count > 0 else "开始全部更新同步")
        # 同步按钮文案带计数后缀，长度会变：按当前文案重算自然宽度，避免裁字。
        self._apply_button_widths()


IMAGE_SOURCE_NAMES = source_catalog.IMAGE_SOURCE_NAMES
"""数据源展示名目录，见 :mod:`mdcx.tools.emby_actor_source_catalog`。"""
INFO_SOURCE_NAMES = source_catalog.INFO_SOURCE_NAMES
"""数据源展示名目录，见 :mod:`mdcx.tools.emby_actor_source_catalog`。"""


class _SourceQuickSettingsPanel(QGroupBox):
    """快速设置面板：头像/信息数据源拖拽排序，改动即自动保存。

    数据源测试窗口与演员详情窗口共用，避免两处重复实现。面板只管两个数据源列表，
    「本地头像目录」行由各窗口自建（数据源测试窗放在底部标题行、演员详情窗放在中列
    按钮行上方），因此本地头像目录的改动保存统一走各窗口自己的槽函数。
    """

    def __init__(self, parent=None, fixed_width: int | None = 300):
        super().__init__("快速设置", parent)
        if fixed_width is not None:
            self.setFixedWidth(fixed_width)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("头像数据源（拖拽排序）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.image_list, manager.config.actor_image_sources, IMAGE_SOURCE_NAMES)
        layout.addWidget(self.image_list)
        layout.addWidget(QLabel("信息数据源（拖拽排序）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.info_list, manager.config.actor_info_sources, INFO_SOURCE_NAMES)
        layout.addWidget(self.info_list)
        layout.addStretch()
        self._lists_expanded = False

        img_model = self.image_list.model()
        if img_model:
            img_model.rowsMoved.connect(self._save)
        info_model = self.info_list.model()
        if info_model:
            info_model.rowsMoved.connect(self._save)

    def set_lists_expanded(self, expanded: bool) -> None:
        """最大化时头像/信息两列表 1:1 分配面板纵向富余高度；还原时恢复默认效果。

        通过布局 stretch 实现：富余空间只按 stretch>0 分配，两列表 stretch=1、
        底部弹簧保持 0，最大化时弹簧分不到高度；还原时改回 0 即恢复原状。
        同值不重复触发布局，避免 resize 递归。
        """
        try:
            if self._lists_expanded == expanded:
                return
            self._lists_expanded = expanded
            _layout = self.layout()
            if _layout is not None:
                _layout.setStretchFactor(self.image_list, 1 if expanded else 0)
                _layout.setStretchFactor(self.info_list, 1 if expanded else 0)
        except Exception:
            pass

    @staticmethod
    def _fill_list(list_widget: QListWidget, sources: list[str], names: dict[str, str]):
        list_widget.clear()
        for src in sources:
            item = QListWidgetItem(names.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            list_widget.addItem(item)

    def _save(self, *args):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = [
            self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())
        ]
        cfg.actor_info_sources = [
            self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())
        ]
        # 本地头像目录由各窗口自建的输入框保存（数据源测试窗 / 演员详情窗），
        # 面板只改数据源顺序，原样带回当前值，不覆盖。
        cfg.actor_photo_folder = manager.config.actor_photo_folder
        manager._replace_config(cfg)
        manager.save()


class EmbyActorSettingsDialog(QDialog):
    """Emby 演员数据源设置：数据源优先级排序 + 本地目录 + Gfriends + 数据库开关。"""

    def __init__(self, parent=None):
        # 独立顶层窗口：parent 参数仅为兼容旧调用而保留，不再传入——管理器
        # 最小化/关闭不再级联影响设置窗口；调用方用 show() 单例复用（见 _on_open_settings）。
        super().__init__(None)
        self.setWindowTitle("Emby/Jellyfin 演员设置")
        self.setWindowFlags(
            (self.windowFlags() | Qt.WindowType.Window)
            & ~(Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        )
        # 关闭时由 Qt 销毁 C++ 对象，管理器侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 无父独立窗口收不到管理器的 QSS 级联，字号规则自带一条，与管理器同值。
        self.setStyleSheet(f"QWidget {{ font-size: {_ui_font_pt()}; }}")
        self.setMinimumSize(480, 720)
        self.resize(480, 720)

        # 打开时默认在屏幕可用区居中（主界面同款：以 frameGeometry 外框为准，
        # 原生窗口未创建时延后一次；小屏时钳制，避免标题栏移出可视区）。
        def _center_dialog(avail_rect):
            frame = self.frameGeometry()
            x = avail_rect.x() + max(0, (avail_rect.width() - frame.width()) // 2)
            y = avail_rect.y() + max(0, (avail_rect.height() - frame.height()) // 2)
            self.move(max(x, avail_rect.x()), max(y, avail_rect.y()))

        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None and avail.isValid():
                self.resize(min(480, avail.width()), min(720, avail.height()))
                if self.windowHandle() is not None:
                    _center_dialog(avail)
                else:
                    QTimer.singleShot(0, lambda av=avail: _center_dialog(av))
        except Exception:
            pass
        layout = QVBoxLayout(self)

        filter_group = QGroupBox("Emby/Jellyfin 演员获取过滤")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_only_check = QCheckBox("获取演员类型（不包含导演/编剧/制片人，含客串）")
        self.filter_only_check.setChecked(manager.config.actor_filter_only)
        self.filter_only_check.setToolTip(
            "勾选：只保留在所选库影片演职表中担任演员/客串(GuestStar)的人员；\n"
            "不勾选：所选库内所有角色（导演/编剧/制片等）全部保留。"
        )
        filter_layout.addWidget(self.filter_only_check)
        self.deduplicate_check = QCheckBox("重复演员去重（按照服务器演员姓名合并）")
        self.deduplicate_check.setChecked(manager.config.actor_deduplicate)
        filter_layout.addWidget(self.deduplicate_check)
        layout.addWidget(filter_group)

        layout.addWidget(QLabel("头像数据源优先级（拖拽排序，上=优先）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_image_sources:
            item = QListWidgetItem(IMAGE_SOURCE_NAMES.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.image_list.addItem(item)
        layout.addWidget(self.image_list)

        layout.addWidget(QLabel("信息数据源优先级（拖拽排序，上=优先）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_info_sources:
            item = QListWidgetItem(INFO_SOURCE_NAMES.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.info_list.addItem(item)
        layout.addWidget(self.info_list)

        self.export_folder_edit = QLineEdit(getattr(manager.config, "actor_export_folder", "") or "")
        layout.addLayout(
            make_folder_row("数据导出目录:", self.export_folder_edit, self._browse_export_folder),
        )

        self.photo_folder_edit = QLineEdit(manager.config.actor_photo_folder)
        layout.addLayout(
            make_folder_row("本地头像目录:", self.photo_folder_edit, self._browse_photo_folder),
        )

        gf_row = QHBoxLayout()
        gf_row.addWidget(QLabel("Gfriends地址:"))
        self.gfriends_edit = QLineEdit(str(manager.config.gfriends_github))
        gf_row.addWidget(self.gfriends_edit)
        layout.addLayout(gf_row)

        btn_row = QHBoxLayout()
        self.use_db_check = QCheckBox("使用本地信息数据库")
        self.use_db_check.setChecked(manager.config.use_database)
        btn_row.addWidget(self.use_db_check)
        btn_row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # 目录 / Gfriends 地址等显示框内容优先从左展示（长 URL 不被滚掉前缀）
        left_anchor_text_edits(self)

    def _browse_export_folder(self):
        browse_folder(self, "选择数据导出目录", self.export_folder_edit, cursor_reset=False)

    def _browse_photo_folder(self):
        browse_folder(self, "选择本地头像目录", self.photo_folder_edit, cursor_reset=False)

    def _save(self):
        image_sources = [self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())]
        info_sources = [self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())]
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = image_sources
        cfg.actor_info_sources = info_sources
        cfg.actor_filter_only = self.filter_only_check.isChecked()
        cfg.actor_deduplicate = self.deduplicate_check.isChecked()
        cfg.actor_photo_folder = self.photo_folder_edit.text().strip()
        cfg.actor_export_folder = self.export_folder_edit.text().strip()
        cfg.use_database = self.use_db_check.isChecked()
        try:
            cfg.gfriends_github = self.gfriends_edit.text().strip()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"Gfriends 地址无效: {e}")
            return
        manager._replace_config(cfg)
        manager.save()
        # 非模态独立窗口：accept 只隐藏不销毁，下次打开会残留旧实例；直接关闭，
        # 靠 WA_DeleteOnClose 销毁，管理器侧 destroyed 信号随之清空引用。
        self.close()


class ActorSourceTestThread(_CancellableWorkerThread):
    """数据源测试线程：在后台执行网络请求，通过信号回传结果。"""

    progress = Signal(str)  # 实时状态（如“正在从XX获取头像/信息”），主线程更新状态栏
    result = Signal(list, object, object)  # logs, avatar_path, info_dict
    error = Signal(str)

    def __init__(self, parent, name: str, need_image: bool, need_info: bool):
        super().__init__(parent)
        self._name = name
        self._need_image = need_image
        self._need_info = need_info

    def run(self):
        try:
            # 走共享后台执行器（app 持久事件循环），与 FetchActorsThread/SyncThread 一致。
            # 议题 #87：此前自建一次性事件循环再关闭，数据源测试复用共享 curl_cffi
            # 客户端时其 cffi 定时器被注册到该一次性 loop 上；loop 关闭后定时器仍触发，
            # 回调里抛 "Event loop is closed"，Windows 上弹 Python-CFFI error。
            # 改走 executor.submit + result（提交到永不随线程关闭的后台循环），根除该弹窗。
            # progress 经 Signal 发回主线程（跨线程 queued 投递），执行器池线程直接 emit 安全。
            def _report(msg: str) -> None:
                try:
                    self.progress.emit(msg)
                except RuntimeError:
                    pass

            logs, avatar_path, info = self._run_coro(
                _actor_source_test_execute(self._name, self._need_image, self._need_info, progress_callback=_report)
            )
            self.result.emit(logs, avatar_path, info)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


async def _actor_source_test_execute(
    name: str,
    need_image: bool,
    need_info: bool,
    progress_callback=None,
) -> tuple[list[str], str | None, object]:
    """纯数据版本：不操作 UI，返回 (logs, avatar_path, info)。

    progress_callback(msg): 逐源开始前回调，由调用方经 Signal 转发到主线程做实时状态显示。
    """

    def _report(msg: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(msg)
            except Exception:
                pass

    _IMAGE_PROGRESS = source_catalog.IMAGE_PROGRESS
    _INFO_PROGRESS = source_catalog.INFO_PROGRESS
    _IMAGE_RESULT_NAMES = source_catalog.IMAGE_RESULT_NAMES
    _INFO_RESULT_NAMES = source_catalog.INFO_RESULT_NAMES

    logs: list[str] = []
    avatar_path: str | None = None
    info: object = None
    actor = ActorInfo(name=name, actor_id="", server_id="")

    if need_image:
        gfriends_index = await load_gfriends_index()
        for src in manager.config.actor_image_sources:
            _report(_IMAGE_PROGRESS.get(src, f"正在从{src}获取头像"))
            result: object = None
            try:
                if not is_known_source(src):
                    logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: 未知数据源")
                    continue
                result = await fetch_avatar_from_source(
                    actor,
                    src,
                    gfriends_index=gfriends_index,
                    cache_dir=resources.u("emby_actor_cache"),
                    local_avatar_dir=manager.config.actor_photo_folder,
                )
            except Exception as e:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ❌ 异常 {e}")
                continue
            if result:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ✅ 已命中")
                if isinstance(result, (str, Path)) and Path(result).exists():
                    avatar_path = str(result)
                elif isinstance(result, tuple) and result and Path(result[0]).exists():
                    avatar_path = str(result[0])
            else:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ❌ 未命中")

    if need_info:
        for src in manager.config.actor_info_sources:
            _report(_INFO_PROGRESS.get(src, f"正在从{src}获取信息"))
            try:
                ok, desc, data = await fetch_actor_info_from_source(actor, src)
            except Exception as e:
                logs.append(f"{_INFO_RESULT_NAMES.get(src, src)}: ❌ 异常 {e}")
                continue
            _display = _INFO_RESULT_NAMES.get(src, src)
            if ok:
                _detail = ""
                if "（" in desc and "）" in desc:
                    try:
                        _detail = desc.split("（", 1)[1].rsplit("）", 1)[0].replace(" ", "")
                    except Exception:
                        _detail = ""
                logs.append(f"{_display}: ✅ 已命中{_detail and f'，{_detail}'}")
            else:
                logs.append(f"{_display}: ❌ 未命中")
            if ok and data:
                if info is None:
                    info = data
                else:
                    # 多源合并：后命中的源只补全空字段，不覆盖已有内容；
                    # 简介保留更长者，避免 wiki 长简介被本地空/短简介覆盖导致预览空白。
                    try:
                        if getattr(info, "birthday", "") in ("", "0000-00-00") and getattr(
                            data, "birthday", ""
                        ) not in ("", "0000-00-00"):
                            info.birthday = data.birthday
                        if getattr(info, "year", "") in ("", "0000") and getattr(data, "year", "") not in ("", "0000"):
                            info.year = data.year
                        _old_ov = getattr(info, "overview", "") or ""
                        _new_ov = getattr(data, "overview", "") or ""
                        if _new_ov and (not _old_ov or len(_new_ov) > len(_old_ov)):
                            info.overview = _new_ov
                        for _f in ("locations", "taglines", "tags", "genres"):
                            _old = list(getattr(info, _f, None) or [])
                            _new = list(getattr(data, _f, None) or [])
                            if _new and not _old:
                                setattr(info, _f, _new)
                            elif _new:
                                _merged = _old + [x for x in _new if x not in _old]
                                setattr(info, _f, _merged)
                        _old_pid = getattr(info, "provider_ids", None) or {}
                        _new_pid = getattr(data, "provider_ids", None) or {}
                        if _new_pid:
                            try:
                                _old_pid.update(_new_pid)
                            except Exception:
                                pass
                    except Exception:
                        pass
    return logs, avatar_path, info


class ActorSourceTestDialog(QDialog):
    """数据源测试窗口：按配置的数据源优先级逐源尝试获取头像/简介，展示各源结果。

    “更新数据”把本次获取到的头像/简介写回 Emby/Jellyfin 服务器对应演员；
    空字段保留服务器原数据（update_person_info 只写非空新值）。
    """

    _update_done = Signal(bool, str)

    def __init__(self, parent=None):
        # 独立顶层窗口：parent 参数仅为兼容旧调用而保留，不再传入——管理器
        # 最小化/关闭不再级联影响测试窗口；调用方用 show() 单例复用（见 _on_open_test_source）。
        super().__init__(None)
        self.setWindowTitle("数据源测试")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象（closeEvent 已先取消后台线程），
        # 管理器侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 无父独立窗口收不到管理器的 QSS 级联，字号规则与蓝色主按钮样式自带一份（与管理器同值）。
        self.setStyleSheet(_child_dialog_qss())
        self.setMinimumSize(1080, 720)
        self.resize(1080, 720)
        # 打开时默认在屏幕可用区居中；小屏时钳制，避免标题栏移出可视区。
        # 与主窗口一致：使用 frameGeometry 精确计算外框居中，原生窗口未创建时延后一次。
        _w, _h = 1080, 720

        def _center_dialog(avail_rect):
            frame = self.frameGeometry()
            x = avail_rect.x() + max(0, (avail_rect.width() - frame.width()) // 2)
            y = avail_rect.y() + max(0, (avail_rect.height() - frame.height()) // 2)
            self.move(max(x, avail_rect.x()), max(y, avail_rect.y()))

        try:
            screen = QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None and avail.isValid():
                _w = min(_w, avail.width())
                _h = min(_h, avail.height())
                self.resize(_w, _h)
                if self.windowHandle() is not None:
                    _center_dialog(avail)
                else:
                    QTimer.singleShot(0, lambda av=avail: _center_dialog(av))
        except Exception:
            pass
        root = QVBoxLayout(self)

        # 上部内容容器：顶部输入行 + 主体三列 + 底部标题行，整体作为分割条上窗格，
        # 与结果框之间可上下拖拽分配高度。
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 顶部：演员姓名输入框直达按钮左边界；实时状态红字叠在输入框内部右侧。
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("演员姓名："))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入演员名（如：三上悠亚）")
        self.name_edit.returnPressed.connect(lambda: self._run(True, True))
        name_row.addWidget(self.name_edit, stretch=1)
        # 实时状态：QLabel 以输入框为父控件浮于框内右侧，点击穿透不影响编辑；
        # 右侧预留文本边距，演员名与状态不重叠。轮换显示“正在从XX获取头像/信息”避免无反馈。
        self.status_label = QLabel(self.name_edit)
        self.status_label.setStyleSheet("color: #c00000; background: transparent;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status_label.setText("")
        self.status_label.hide()
        self.name_edit.installEventFilter(self)
        self.btn_both = QPushButton("获取头像和简介")
        self.btn_both.setObjectName("btnPrimary")
        name_row.addWidget(self.btn_both)
        # 更新数据：把本次获取到的头像/简介写入服务器对应演员（空字段保留原数据）。
        self.btn_update = QPushButton("更新数据")
        self.btn_update.setObjectName("btnPrimary")
        name_row.addWidget(self.btn_update)
        top_layout.addLayout(name_row)
        QTimer.singleShot(0, self._layout_status_overlay)

        # 主体：左(头像) + 中(信息字段表) + 右(快速设置面板)，宽度 1:2:1，随窗口同步缩放
        main_row = QHBoxLayout()

        # 左列：头像预览 + 获取头像（预览框按列宽等比放大，见 _fit_avatar_frame）
        left_col = QVBoxLayout()
        self.avatar_label = QLabel("头像预览")
        # 最小值只做显示下限，不跟随显示尺寸：若用 setFixedSize
        # 把最小锁成当前显示尺寸，QSplitter 会以该最小值钳住上窗格，导致结果框
        # 只能向下拉、向上拉不动。此处最小恒定（宽 190 与原来一致、高降到 196），
        # 显示尺寸只走最大上限（见 _fit_avatar_frame）。
        self.avatar_label.setMinimumSize(190, 196)
        self.avatar_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_col.addStretch()
        # stretch=1 让富余垂直空间优先给预览框（上限仍受 _fit_avatar_frame 的
        # maximumSize 钳制）；水平不设对齐，预览框撑满整列、与“获取头像”按钮同宽。
        # 最小值恒定 190x196 不抬高 QSplitter 上窗格的最小高度，结果框可上下双向拖拽。
        left_col.addWidget(self.avatar_label, 1)
        left_col.addStretch()
        self.btn_image = QPushButton("获取头像")
        self.btn_image.setObjectName("btnPrimary")
        left_col.addWidget(self.btn_image)
        self._left_col = left_col
        main_row.addLayout(left_col, stretch=1)

        # 中列：详细信息预览（字段/值）+ 获取信息
        info_col = QVBoxLayout()
        info_col.addWidget(QLabel("详细信息预览:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.info_table.setWordWrap(True)
        self.info_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        # 值列用只读编辑框承载，此处再把表格自身的选中高亮去掉，避免出现蓝色背景。
        self.info_table.setStyleSheet(
            "QTableWidget::item:selected { background: palette(base); color: palette(text); }"
            "QTableWidget::item:focus { border: none; }"
        )
        self.info_table.installEventFilter(self)
        info_col.addWidget(self.info_table)
        self.btn_info = QPushButton("获取信息")
        self.btn_info.setObjectName("btnPrimary")
        info_col.addWidget(self.btn_info)
        # 记录对话框与两按钮默认高度：最大化时按钮高度随对话框高度同步拉升，还原时恢复
        # （见 _sync_panel_stretch）。最小化/普通窗口不做任何改动。
        self._dialog_base_h = max(1, self.height() or 720)
        self._btn_image_base_h = self.btn_image.sizeHint().height()
        self._btn_info_base_h = self.btn_info.sizeHint().height()
        main_row.addLayout(info_col, stretch=2)

        # 右列：快速设置面板（改即自动保存；本地头像目录由本窗口自建、放在底部标题行，
        # 面板内不建目录行；释放固定 300 宽，按 1:2:1 的 1 份随窗口缩放）
        panel = _SourceQuickSettingsPanel(self, fixed_width=None)
        panel.setMinimumWidth(200)
        self._panel = panel
        # 面板自身尺寸变化后同步底部盒：面板 Resize 事件里读到的已是布局后的最终宽度，
        # 专治最大化→还原等多帧 resize 中对话框 resizeEvent 读到旧值、盒宽卡死的问题。
        panel.installEventFilter(self)
        main_row.addWidget(panel, stretch=1)

        top_layout.addLayout(main_row)
        self._main_row = main_row

        # 底部标题行：左“各数据源结果”，右“本地头像目录”+输入框+浏览。
        # 输入框盒宽度随上面板同步、右对齐到对话框右边缘，冒号对准“获取信息”按钮右边界。
        bottom_header = QHBoxLayout()
        bottom_header.addWidget(QLabel("各数据源结果:"))
        bottom_header.addStretch(1)
        bottom_header.addWidget(QLabel("本地头像目录:"))
        folder_box = QWidget()
        folder_box.setFixedWidth(300)
        folder_layout = QHBoxLayout(folder_box)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit(manager.config.actor_photo_folder)
        self.folder_edit.setCursorPosition(0)
        folder_browse_btn = QPushButton("浏览")
        folder_browse_btn.setObjectName("btnPrimary")
        self._folder_browse_btn = folder_browse_btn
        folder_browse_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(folder_browse_btn)
        bottom_header.addWidget(folder_box)
        self._folder_box = folder_box
        top_layout.addLayout(bottom_header)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        # 各数据源结果框可上下拖拽调高度：上部内容与结果框之间加垂直分割条；
        # 默认高度保持 150（首帧布局后 _init_result_splitter 设置），重开窗口恢复默认。
        self._result_splitter = QSplitter(Qt.Orientation.Vertical)
        self._result_splitter.addWidget(top_widget)
        self._result_splitter.addWidget(self.result_text)
        self._result_splitter.setChildrenCollapsible(False)
        self._result_splitter.setStretchFactor(0, 1)
        self._result_splitter.setStretchFactor(1, 0)
        # 用户亲手拖过分割条后不再自动纠正高度。
        self._result_user_moved = False
        self._result_splitter.splitterMoved.connect(self._on_result_splitter_moved)
        root.addWidget(self._result_splitter, stretch=1)

        self.btn_both.clicked.connect(lambda: self._run(True, True))
        self.btn_image.clicked.connect(lambda: self._run(True, False))
        self.btn_info.clicked.connect(lambda: self._run(False, True))
        self.btn_update.clicked.connect(self._on_update)
        self._update_done.connect(self._on_update_done)
        self.folder_edit.textChanged.connect(self._save_folder)
        self._avatar_pixmap = None
        self._thread = None
        # 更新数据用的已获取快照：_run 开始时清空，_on_result 成功时写入；
        # 只有拿到头像或详细信息后，更新按钮才会执行写入。
        self._fetched_name = ""
        self._fetched_avatar = None
        self._fetched_info = None
        self._updating = False
        # 最大化时随高度同步拉升的顶行控件默认高度（见 _sync_panel_stretch）：
        # 获取头像和简介/更新数据/浏览三按钮 + 演员名输入框 + 本地头像目录输入框。
        self._btn_both_base_h = self.btn_both.sizeHint().height()
        self._btn_update_base_h = self.btn_update.sizeHint().height()
        self._browse_btn_base_h = self._folder_browse_btn.sizeHint().height()
        self._name_edit_base_h = self.name_edit.sizeHint().height()
        self._folder_edit_base_h = self.folder_edit.sizeHint().height()
        # 布局请求在事件分发中同步执行完布局，延迟一拍读到的即最终几何，
        # 兜底多帧 resize（最大化→还原）中各同步读取拿到的旧值。
        self.installEventFilter(self)
        # 所有显示用文本框内容优先从左展示（含演员名 / 头像目录 / 结果框）
        left_anchor_text_edits(self)

    def _browse_folder(self):
        browse_folder(self, "选择本地头像目录", self.folder_edit, cursor_reset=True)

    def _save_folder(self):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_photo_folder = self.folder_edit.text().strip()
        manager._replace_config(cfg)
        manager.save()

    def closeEvent(self, event):
        thread = getattr(self, "_thread", None)
        if thread is not None:
            try:
                thread.result.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                thread.progress.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                thread.error.disconnect()
            except (TypeError, RuntimeError):
                pass
            thread.cancel()
            if thread.isRunning() and not thread.wait(5000):
                _detach_running_thread(thread)
        super().closeEvent(event)

    def _set_status(self, msg: str) -> None:
        """框内右侧红字状态：为空时隐藏并恢复输入框边距，否则显示并预留不重叠边距。"""
        try:
            label = self.status_label
            edit = self.name_edit
        except (AttributeError, RuntimeError):
            return
        try:
            label.setText(msg or "")
            if not msg:
                label.hide()
                edit.setTextMargins(0, 0, 0, 0)
                return
            label.show()
            self._layout_status_overlay()
        except (AttributeError, RuntimeError):
            pass

    def _layout_status_overlay(self) -> None:
        """把状态 QLabel 贴到输入框内部右侧，并给输入框留出右侧文本边距防重叠。
        右侧留 6px 空隙，避免遮住输入框圆角边框。"""
        try:
            label = self.status_label
            edit = self.name_edit
        except (AttributeError, RuntimeError):
            return
        try:
            if not label.text():
                return
            margin = 6
            hint = label.sizeHint()
            max_w = max(0, int(edit.width() * 0.8))
            w = min(max(0, hint.width() + margin * 2), max_w) if max_w > 0 else hint.width()
            w = max(w, 10)
            h = max(edit.height(), 10)
            label.setGeometry(edit.width() - w - 6, 0, w, h)
            label.raise_()
            edit.setTextMargins(0, 0, w + 8, 0)
        except (AttributeError, RuntimeError, ValueError):
            pass

    def _set_running(self, running: bool) -> None:
        for btn in (self.btn_both, self.btn_image, self.btn_info, self.btn_update):
            try:
                btn.setEnabled(not running)
            except RuntimeError:
                pass
        if running:
            self.btn_both.setText("获取中")
        else:
            self.btn_both.setText("获取头像和简介")

    def _run(self, need_image: bool, need_info: bool):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入演员姓名")
            return
        old = getattr(self, "_thread", None)
        if old is not None and old.isRunning():
            QMessageBox.information(self, "提示", "正在获取中，请稍候")
            return
        if getattr(self, "_updating", False):
            QMessageBox.information(self, "提示", "正在更新数据，请稍候")
            return
        kinds = []
        if need_image:
            kinds.append("头像")
        if need_info:
            kinds.append("简介")
        start_msg = f"正在为“{name}”获取{'和'.join(kinds)}"
        self._set_status(start_msg)
        self.result_text.clear()
        # 新一轮获取开始即清空旧快照：只有本轮拿到数据后，更新按钮才会执行写入。
        self._fetched_name = name
        self._fetched_avatar = None
        self._fetched_info = None
        self._set_running(True)
        self._thread = ActorSourceTestThread(self, name, need_image, need_info)
        self._thread.progress.connect(self._on_progress)
        self._thread.result.connect(self._on_result)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(lambda: self._set_running(False))
        self._thread.start()

    def _on_progress(self, msg: str):
        self._set_status(msg)

    def _on_result(self, logs: list[str], avatar_path: str | None, info: object):
        # 中间进度只显示在顶部输入框右侧红字状态，不写入底部结果框；此处只追加最终各源结论。
        for log in logs:
            self.result_text.append(log)
        self._set_status("")
        self._set_running(False)
        if avatar_path and Path(avatar_path).exists():
            self._show_avatar(avatar_path)
            self._fetched_avatar = avatar_path
        if info:
            self._populate_info_table(info)
            try:
                from ..models.emby import EMbyActressInfo

                if isinstance(info, EMbyActressInfo):
                    self._fetched_info = info
            except Exception:
                pass

    def _on_error(self, msg: str):
        self._set_status(f"❌ 错误: {msg}")
        self.result_text.append(f"❌ 错误: {msg}")
        self._set_running(False)

    @staticmethod
    def _is_blank(value: object) -> bool:
        """空/None/占位零值（生日 0000-00-00、年份 0000）一律视为“无数据”，更新时保留服务器原值。"""
        if value is None:
            return True
        if isinstance(value, str):
            s = value.strip()
            return not s or s in ("0000-00-00", "0000")
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    def _has_fetched_data(self) -> bool:
        """本次是否拿到可更新的数据：头像文件存在，或简介任一字段有具体值。"""
        try:
            if self._fetched_avatar and Path(self._fetched_avatar).exists():
                return True
        except Exception:
            pass
        info = getattr(self, "_fetched_info", None)
        if info is None:
            return False
        try:
            if not self._is_blank(getattr(info, "overview", "")):
                return True
            if not self._is_blank(getattr(info, "birthday", "")):
                return True
            if not self._is_blank(getattr(info, "year", "")):
                return True
            if getattr(info, "locations", None):
                return True
            if getattr(info, "taglines", None):
                return True
        except Exception:
            pass
        return False

    def _on_update(self):
        """更新数据：把本次获取到的头像/简介写入 Emby/Jellyfin 服务器对应演员。

        未连接服务器时提示去演员管理器主页面连接；未获取到数据时不执行；
        空字段保留服务器原数据（见 _do_update_async，只写非空新值）。
        """
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入演员姓名")
            return
        old = getattr(self, "_thread", None)
        if old is not None and old.isRunning():
            QMessageBox.information(self, "提示", "正在获取中，请稍候")
            return
        if getattr(self, "_updating", False):
            QMessageBox.information(self, "提示", "正在更新数据，请稍候")
            return
        if name != (getattr(self, "_fetched_name", "") or "") or not self._has_fetched_data():
            QMessageBox.information(self, "提示", "请先获取头像或简介数据，再更新")
            return
        if not manager.config.emby_url or not manager.config.api_key:
            QMessageBox.warning(self, "提示", "请先在演员管理器主页面连接 Emby/Jellyfin 服务器")
            return
        # 快照：后台更新期间用户改动界面不影响本次写入内容。
        info = self._fetched_info
        try:
            _avatar = self._fetched_avatar if self._fetched_avatar and Path(self._fetched_avatar).exists() else None
        except Exception:
            _avatar = None
        _overview = str(getattr(info, "overview", "") or "") if info is not None else ""
        _birthday = str(getattr(info, "birthday", "") or "") if info is not None else ""
        _year = str(getattr(info, "year", "") or "") if info is not None else ""
        _locations = list(getattr(info, "locations", None) or []) if info is not None else []
        _taglines = list(getattr(info, "taglines", None) or []) if info is not None else []
        self._updating = True
        try:
            self.btn_update.setEnabled(False)
            self.btn_update.setText("更新中")
        except RuntimeError:
            pass
        self._set_status(f"正在更新“{name}”到服务器...")
        try:
            future = executor.submit(
                self._do_update_async(name, _avatar, _overview, _birthday, _year, _locations, _taglines)
            )
        except Exception as e:
            self._updating = False
            try:
                self.btn_update.setEnabled(True)
                self.btn_update.setText("更新数据")
            except RuntimeError:
                pass
            self._set_status("")
            QMessageBox.critical(self, "更新失败", f"❌ 更新任务提交失败: {e}")
            return

        def _emit(fut):
            try:
                self._update_done.emit(*_future_result_or(fut, (False, "❌ 更新失败")))
            except RuntimeError:
                pass

        future.add_done_callback(_emit)

    async def _do_update_async(
        self,
        name: str,
        avatar_path: str | None,
        overview: str,
        birthday: str,
        year: str,
        locations: list,
        taglines: list,
    ) -> tuple[bool, str]:
        from .emby_actor_manager import _ACTOR_DETAIL_CACHE, _sync_actor_async, fetch_actor_detail
        from .emby_shared import _build_jellyfin_headers, _emby_api_prefix, _emby_get_json

        try:
            # 存活探测：配置里有地址/密钥不代表此刻连通，连不上就提示去主页面连接。
            resp, _err = await _emby_get_json(
                f"{_emby_api_prefix()}/System/Info",
                headers=_build_jellyfin_headers(),
            )
            if not resp:
                return False, "⚠️ 未连接到 Emby/Jellyfin 服务器，请先在演员管理器主页面连接后再更新"
            detail = await fetch_actor_detail(name)
            if not detail or not detail.get("Id"):
                return False, f"❌ 服务器中未找到演员“{name}”，请确认该演员已在媒体库中"
            actor = ActorInfo(
                name=detail.get("Name") or name,
                actor_id=detail.get("Id", ""),
                server_id=detail.get("ServerId", ""),
            )
            # 服务器现有值全部带上：空字段回填既不覆盖，也避免 Emby 空引用 400。
            actor.existing_overview = detail.get("Overview") or ""
            actor.existing_taglines = detail.get("Taglines") or []
            actor.existing_production_year = detail.get("ProductionYear")
            actor.existing_premiere_date = detail.get("PremiereDate") or ""
            actor.existing_production_locations = detail.get("ProductionLocations") or []
            actor.existing_provider_ids = detail.get("ProviderIds") or {}
            actor.existing_genres = detail.get("Genres") or []
            actor.existing_tags = detail.get("Tags") or []
            # has_* 必须同步推导：统计栏的「缺头像/缺简介」走 is_missing_overview/is_missing_image，
            # 只填 existing_* 而不填 has_* 会被判成「全缺」（ActorInfo 默认值都是 False）。
            actor.has_image = "Primary" in (detail.get("ImageTags") or {})
            actor.has_overview = bool(actor.existing_overview.strip())
            # 只有有具体值/图像的字段才记为新值写入；空一律保留服务器原数据。
            need_info = False
            if (overview or "").strip():
                actor.new_overview = overview
                need_info = True
            _tags = [str(t).strip() for t in (taglines or []) if str(t).strip()]
            if _tags:
                actor.new_taglines = _tags
                need_info = True
            _locs = [str(v).strip() for v in (locations or []) if str(v).strip()]
            if _locs:
                actor.new_production_locations = _locs
                need_info = True
            if normalize_premiere_date(birthday):
                actor.new_premiere_date = birthday
                need_info = True
            if normalize_production_year(year) is not None:
                actor.new_production_year = normalize_production_year(year)
                need_info = True
            need_image = False
            if avatar_path:
                try:
                    if Path(avatar_path).exists():
                        actor.new_image_path = avatar_path
                        need_image = True
                except Exception:
                    pass
            if not need_info and not need_image:
                return False, "本次获取到的数据均为空，已保留服务器原数据，未执行更新"
            actor.need_update_info = need_info
            actor.need_update_image = need_image
            sync_type = "both" if (need_info and need_image) else ("image" if need_image else "info")
            ok, msg = await _sync_actor_async(actor, sync_type)
            if ok:
                try:
                    _ACTOR_DETAIL_CACHE.pop(name, None)
                except Exception:
                    pass
            return ok, msg
        except Exception as e:
            return False, f"❌ 更新异常: {e}"

    def _on_update_done(self, ok: bool, msg: str):
        self._updating = False
        try:
            self.btn_update.setEnabled(True)
            self.btn_update.setText("更新数据")
        except RuntimeError:
            return
        self._set_status("" if ok else "❌ 更新失败")
        try:
            self.result_text.append(msg)
        except RuntimeError:
            pass
        try:
            if ok:
                QMessageBox.information(self, "更新完成", msg)
            else:
                QMessageBox.warning(self, "提示", msg)
        except RuntimeError:
            pass

    @staticmethod
    def _format_overview(text: object) -> str:
        """简介格式化为一行一条：<br>/<p> 等转换行，去残留标签，空白行最多保留一个。"""
        import html as _html

        if not isinstance(text, str) or not text:
            return ""
        t = re.sub(r"(?i)<br\s*/?>", "\n", text)
        t = re.sub(r"(?i)</p\s*>", "\n", t)
        t = re.sub(r"(?i)<p[^>]*>", "", t)
        t = re.sub(r"<[^>]+>", "", t)
        # 合并被换行拆散的段落标题：“===== 个人资料\n=====”→“===== 个人资料 =====”。
        # 仅当某行以 ===== 开头但行内无收尾 =====、且下一行为纯 ===== 时合并；
        # 正常的单行标题无换行穿插，不受影响（与 wiki.py:_join_split_section_titles 同规则）。
        t = re.sub(r"(?m)^(={5,})[ \t]*([^=\n\s][^=\n]*?)[ \t]*\n[ \t]*(={5,})[ \t]*$", r"\1 \2 \3", t)
        try:
            t = _html.unescape(t)
        except Exception:
            pass
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.strip() for ln in t.split("\n")]
        # 去首尾空行，中间连续空行压成一个
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        out: list[str] = []
        _blank = False
        for ln in lines:
            if not ln:
                if not _blank:
                    out.append("")
                _blank = True
            else:
                out.append(ln)
                _blank = False
        return "\n".join(out)

    def _populate_info_table(self, info: object):
        from ..models.emby import EMbyActressInfo

        if not isinstance(info, EMbyActressInfo):
            return
        _overview = self._format_overview(info.overview or "")
        rows = [
            ("生日", info.birthday),
            ("年份", str(info.year) if info.year else ""),
            ("出生地", ", ".join(info.locations or [])),
            ("标签", ", ".join(info.taglines or [])),
            ("简介", _overview),
        ]
        # 切换前清除旧 cell widget，避免复用残留。
        try:
            for _r in range(5):
                try:
                    self.info_table.removeCellWidget(_r, 1)
                except Exception:
                    pass
        except Exception:
            pass
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            if r == 4:
                continue
            # 单行值用只读 QLineEdit 承载：不受表格选中高亮影响（无蓝底），框内可拖选复制。
            try:
                _edit = QLineEdit(str(value))
                _edit.setReadOnly(True)
                _edit.setFrame(False)
                _edit.setStyleSheet("QLineEdit { border: none; background: palette(base); }")
                self.info_table.setCellWidget(r, 1, _edit)
            except Exception:
                self.info_table.setItem(r, 1, QTableWidgetItem(str(value)))
        # 简介用只读 QTextEdit 承载：支持鼠标拖选复制，行内换行显示。
        try:
            _bio = QTextEdit()
            _bio.setReadOnly(True)
            _bio.setPlainText(_overview)
            _bio.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            _bio.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            _bio.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            _bio.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            _bio.setStyleSheet("QTextEdit { border: none; background: palette(base); }")
            _bio.setFrameStyle(0)
            self.info_table.setCellWidget(4, 1, _bio)
        except Exception:
            _item = QTableWidgetItem(_overview)
            _item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.info_table.setItem(4, 1, _item)
        self._fit_overview_row()
        # 填充后清除表格选中/当前格，避免值列出现蓝色选中背景。
        try:
            self.info_table.clearSelection()
        except Exception:
            pass
        # 列宽确定后文档换行高度才准确，下一帧再按最终宽度重算一次（重算后同样清选中）。
        try:
            QTimer.singleShot(0, self._fit_overview_row)
        except Exception:
            pass

    def _fit_overview_row(self) -> None:
        """简介行高：默认 8 倍行高，内容更高按文档高度撑高，到文字下方为止。

        不再填满表格视口：行高只与内容有关，表格剩余区域保持默认底色。
        末尾顺手清除选中，避免出现蓝色选中背景。"""
        try:
            _vh = self.info_table.verticalHeader()
            _base = (_vh.defaultSectionSize() if _vh is not None else 0) or 30
            for _r in range(4):
                try:
                    if self.info_table.rowHeight(_r) != _base:
                        self.info_table.setRowHeight(_r, _base)
                except Exception:
                    pass
            _default = _base * 8
            _content = 0
            try:
                _w = self.info_table.cellWidget(4, 1)
                if _w is not None:
                    _doc_h = _w.document().size().height()
                    _content = int(_doc_h + _w.contentsMargins().top() + _w.contentsMargins().bottom() + 12)
                else:
                    _it = self.info_table.item(4, 1)
                    if _it is not None:
                        _n = max(1, (_it.text() or "").count("\n") + 1)
                        _fm_h = self.info_table.fontMetrics().lineSpacing() or 16
                        _content = _n * _fm_h + 12
            except Exception:
                pass
            _want = max(_default, _content)
            if _want > 0 and self.info_table.rowHeight(4) != int(_want):
                self.info_table.setRowHeight(4, int(_want))
            try:
                self.info_table.clearSelection()
            except Exception:
                pass
        except Exception:
            pass

    def _show_avatar(self, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            self._avatar_pixmap = pix
            self._rescale_avatar()

    def _rescale_avatar(self):
        pix = getattr(self, "_avatar_pixmap", None)
        if pix is None or pix.isNull():
            return
        target = self.avatar_label.size()
        if target.width() < 2 or target.height() < 2:
            return
        self.avatar_label.setPixmap(
            pix.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _fit_avatar_frame(self):
        """头像预览框左右扩展到左列整个可显示宽度，宽高比保持 190:310；高度不够时按高度回缩。
        宽度同时钳制在 1:2:1 公平份额内：读当前列宽做目标，在多帧 resize
        （最大化→还原）后单调收敛。只设最大上限、不碰最小值：最小恒为构造时的
        120x196，QSplitter 上窗格最小高度不再被头像显示尺寸撑住，结果框才能上下双向拖拽。"""
        try:
            row = getattr(self, "_main_row", None)
            col = getattr(self, "_left_col", None)
            if row is None or col is None:
                return
            items = [row.itemAt(i) for i in range(3)]
            if any(it is None for it in items):
                return
            g0, g1, g2 = (it.geometry() for it in items)
            # 用三列实际几何反推公平份额，不依赖边距/间距常量。
            # 目标宽度直接取公平份额（由总宽实时算出，放大/还原双向收敛）：不能再与
            # 当前列宽取 min——放大那帧列宽还是旧的窄值，min 会把目标钉死在旧宽度，
            # 列宽长不大、下一帧量到的还是窄值，左列卡死、头像框比快速设置窄。
            gaps = (g1.x() - g0.right() - 1) + (g2.x() - g1.right() - 1)
            fair = (g2.right() - g0.x() + 1 - gaps) / 4.0
            avail_w = int(fair)
            avail_h = (
                g0.height()
                - self.btn_image.height()
                - col.spacing() * 3
                - col.contentsMargins().top()
                - col.contentsMargins().bottom()
            )
            if avail_w < 10 or avail_h < 10:
                return
            ratio = 310 / 190
            w, h = avail_w, int(round(avail_w * ratio))
            if h > avail_h:
                h, w = avail_h, int(round(avail_h / ratio))
            w, h = max(w, 10), max(h, 10)
            cur_max = self.avatar_label.maximumSize()
            if cur_max.width() != w or cur_max.height() != h:
                self.avatar_label.setMaximumSize(w, h)
        except Exception:
            pass

    def _sync_folder_box(self):
        """底部输入框盒宽度随上面板同步、右对齐，冒号对准“获取信息”按钮右边界。"""
        try:
            panel = getattr(self, "_panel", None)
            box = getattr(self, "_folder_box", None)
            if panel is None or box is None or panel.width() <= 0:
                return
            if box.width() != panel.width():
                box.setFixedWidth(panel.width())
        except Exception:
            pass

    def eventFilter(self, a0, a1):
        try:
            if a1 is not None:
                t = a1.type()
                if t == QEvent.Type.Resize and a0 is getattr(self, "_panel", None):
                    self._sync_folder_box()
                elif t == QEvent.Type.Resize and a0 is getattr(self, "name_edit", None):
                    self._layout_status_overlay()
                elif t == QEvent.Type.Resize and a0 is getattr(self, "info_table", None):
                    self._fit_overview_row()
                elif t == QEvent.Type.LayoutRequest and a0 is self:
                    QTimer.singleShot(0, self._after_layout)
                elif t == QEvent.Type.KeyPress and a0 is getattr(self, "info_table", None):
                    try:
                        if a1.matches(QKeySequence.StandardKey.Copy):
                            self._copy_info_selection()
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        return super().eventFilter(a0, a1)

    def _copy_info_selection(self) -> None:
        """复制信息表选中单元格文本（无选中时复制简介全文），供 Ctrl+C 用。"""
        try:
            _idx = self.info_table.selectedIndexes()
            _texts: list[str] = []
            if _idx:
                for _i in sorted(_idx, key=lambda x: (x.row(), x.column())):
                    if _i.column() == 1:
                        if _i.row() == 4:
                            _w = self.info_table.cellWidget(4, 1)
                            if _w is not None:
                                try:
                                    _cur = _w.textCursor()
                                    _texts.append(_cur.selectedText() if _cur.hasSelection() else _w.toPlainText())
                                    continue
                                except Exception:
                                    pass
                        _w04 = None
                        try:
                            _w04 = self.info_table.cellWidget(_i.row(), _i.column())
                        except Exception:
                            _w04 = None
                        if _w04 is not None and isinstance(_w04, QLineEdit):
                            try:
                                _texts.append(_w04.selectedText() if _w04.hasSelectedText() else _w04.text())
                            except Exception:
                                _texts.append(_w04.text() or "")
                        else:
                            _it = self.info_table.item(_i.row(), _i.column())
                            if _it is not None:
                                _texts.append(_it.text() or "")
                _data = "\n".join(_texts).strip()
            else:
                _w = self.info_table.cellWidget(4, 1)
                _data = (_w.toPlainText() if _w is not None else "").strip()
            if _data:
                QApplication.clipboard().setText(_data)
        except Exception:
            pass

    def _sync_panel_stretch(self) -> None:
        """最大化时的专属效果，还原时全部恢复默认；按钮高度只在数值变化时设置。

        - 右侧头像/信息两列表 1:1 分配富余高度；
        - 按钮与输入框高度按对话框当前高度/默认高度的比例同步拉升：
          获取头像/获取信息/获取头像和简介/更新数据/浏览 + 演员名输入框 + 本地头像目录输入框。
        普通/最小化窗口时不做任何改动，与原来完全一致。
        """
        try:
            try:
                _max = self.isMaximized()
            except Exception:
                _max = False
            _panel = getattr(self, "_panel", None)
            if _panel is not None and hasattr(_panel, "set_lists_expanded"):
                try:
                    _panel.set_lists_expanded(bool(_max))
                except Exception:
                    pass
            try:
                _base_h = getattr(self, "_dialog_base_h", 0) or 0
                _cur_h = self.height() or 0
                _ratio = (_cur_h / _base_h) if (_max and _base_h > 0 and _cur_h > 0) else 1.0
            except Exception:
                _ratio = 1.0
            for _btn_name, _base_name in (
                ("btn_image", "_btn_image_base_h"),
                ("btn_info", "_btn_info_base_h"),
                ("btn_both", "_btn_both_base_h"),
                ("btn_update", "_btn_update_base_h"),
                ("_folder_browse_btn", "_browse_btn_base_h"),
                ("name_edit", "_name_edit_base_h"),
                ("folder_edit", "_folder_edit_base_h"),
            ):
                try:
                    _btn = getattr(self, _btn_name, None)
                    if _btn is None:
                        continue
                    _base = getattr(self, _base_name, 0) or 0
                    if _base <= 0:
                        try:
                            _base = _btn.sizeHint().height()
                        except Exception:
                            continue
                    _target = max(1, int(round(_base * _ratio)))
                    if _btn.minimumHeight() != _target:
                        _btn.setMinimumHeight(_target)
                except Exception:
                    pass
        except Exception:
            pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event is not None and event.type() == QEvent.Type.WindowStateChange:
                self._sync_panel_stretch()
        except Exception:
            pass

    def _after_layout(self):
        """布局执行完后按最终几何重算：盒宽跟随面板、头像框适配左列、头像重绘、框内状态对齐。
        各子函数幂等且有同值保护，不会引起新的布局请求，自收敛。"""
        try:
            self._init_result_splitter()
        except Exception:
            pass
        try:
            self._sync_panel_stretch()
        except Exception:
            pass
        try:
            self._layout_status_overlay()
        except Exception:
            pass
        try:
            self._fit_overview_row()
        except Exception:
            pass
        try:
            self._sync_folder_box()
        except Exception:
            pass
        try:
            self._fit_avatar_frame()
        except Exception:
            pass
        try:
            self._rescale_avatar()
        except Exception:
            pass

    def _on_result_splitter_moved(self, _pos: int, _index: int) -> None:
        self._result_user_moved = True

    def _init_result_splitter(self) -> None:
        """结果框默认 150 高：用户未拖过且当前不是 150 时纠正，已是 150 则不碰。

        布局稳定前会触发多次，值相等时 setSizes 不再进布局，自然收敛不循环；
        对话框关闭即销毁、重开是新实例，天然恢复默认高度，不做持久化。
        """
        if getattr(self, "_result_user_moved", False):
            return
        sp = getattr(self, "_result_splitter", None)
        if sp is None:
            return
        try:
            sizes = sp.sizes()
            if len(sizes) != 2 or sizes[1] == 150:
                return
            total = sp.height()
            if total <= 0:
                return
            want = 150
            sp.setSizes([max(0, total - want), want])
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # 显示后布局几何才最终落定，下一帧把结果框定到默认 150 高。
        try:
            QTimer.singleShot(0, self._init_result_splitter)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._sync_panel_stretch()
        except Exception:
            pass
        try:
            self._layout_status_overlay()
        except Exception:
            pass
        try:
            self._fit_overview_row()
        except Exception:
            pass
        try:
            self._sync_folder_box()
        except Exception:
            pass
        try:
            self._fit_avatar_frame()
        except Exception:
            pass
        try:
            self._rescale_avatar()
        except Exception:
            pass


# 演员详情窗口头像预览框的最小高（原固定 130x180 的高，保留作首次布局前的下限；
# 实际高度由 ActorDetailDialog._sync_preview_heights 按 _AVATAR_PREVIEW_COL_RATIO 同步）。
_AVATAR_PREVIEW_MIN_H = 180
# 预览框占所在栏外框高的几分之一（3 = 三分之一）。写成常量而非裸 //3：
# 这个比例同时决定中栏下方「简介/信息」各让出多少高度，改比例时只动这一处。
_AVATAR_PREVIEW_COL_RATIO = 3


def _layout_min_h_excluding(lay: QBoxLayout, skip) -> int:
    """QBoxLayout 的最小高（contentsMargins + spacing + 各项 minimumSize 之和），
    跳过 `skip` 那个控件自身的那一份。

    供「预览框之外的内容至少还得留多少高」使用：预览框按栏高一半取高，若这份
    一半挤得其余控件放不下，就退到「栏高 − 其余最小高」——否则预览框的 minimumSize
    会把整栏最小高顶破，窗口被迫长高、预览框跟着再长高，形成死循环。
    """
    try:
        margins = lay.contentsMargins()
        total = margins.top() + margins.bottom() + max(0, lay.count() - 1) * lay.spacing()
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is None or item.widget() is skip:
                continue
            total += max(0, item.minimumSize().height())
        return max(0, total)
    except Exception:
        return 0


class ActorDetailDialog(QDialog):
    """演员详情编辑对话框：左栏现有数据，右栏新数据（可编辑），右侧快速设置面板。"""

    _detail_done = Signal(str, object)

    def __init__(self, actor: ActorInfo, parent=None, on_synced=None):
        super().__init__(parent)
        self.actor = actor
        self.on_synced = on_synced
        self.setWindowTitle(f"演员详情 - {actor.name}")
        # 原生最大化/最小化：与演员管理器、数据源测试窗口同款——只加标题栏按钮 hint，
        # 三栏按总宽精确 1:2:1，不做任何定制几何。
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 独立窗口：无父级、非模态打开，关闭即销毁 C++ 对象（同步任务走可取消的
        # QThread 子对象并在 closeEvent 里 abort + wait + 必要时 detach；
        # 其余后台回写全经信号 + _emit_done 守卫，关窗中途回写不炸）。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 无父级独立顶层窗口收不到管理器的 QSS 级联，字号与蓝色主按钮样式自带一份
        # （与管理器同值）：窗内所有控件比应用默认字号大一号；窗口标题栏文字由系统
        # 窗口框绘制、不受 QSS 影响，即「除演员详情标题外全部加大一号」。
        self.setStyleSheet(_child_dialog_qss())
        self._log_lines: list[str] = []
        self._sync_thread: DetailSyncThread | None = None
        # 默认宽高与数据源测试窗口一致（1080x720），小屏钳制。
        self.setMinimumSize(1080, 720)
        try:
            _screen = QGuiApplication.primaryScreen()
            _avail = _screen.availableGeometry() if _screen is not None else None
            if _avail is not None and _avail.isValid():
                self.resize(min(1080, _avail.width()), min(720, _avail.height()))
            else:
                self.resize(1080, 720)
        except Exception:
            self.resize(1080, 720)
        # 记录默认高度：最大化时按钮高度按 当前高度/默认高度 等比拉升、还原时恢复
        # （见 _sync_button_stretch）。最小化/普通窗口不做任何改动。
        self._dialog_base_h = max(1, self.height() or 720)
        # 初始焦点留给窗口本身：一开窗就把焦点高亮描在某个输入框上（Windows11 风格
        # 的 accent 蓝边框）既抢眼又没意义，用户点别处就消失，看着像多出一条蓝条。
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        root = QHBoxLayout(self)

        # 左栏：现有数据（Emby 当前）
        left = QGroupBox("现有数据")
        # 三栏按总宽精确 1:2:1：stretch 只分配 sizeHint 之外的富余，hint 不等
        # （目录输入框最小 260 等）则左栏永远比快速设置窄；水平 Ignored 让布局
        # 按 stretch 分总宽，最大化同步放大。
        left.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        left_layout = QVBoxLayout(left)
        self.existing_avatar_label = QLabel("头像预览")
        # 预览框占本栏 1/3 高度（由 _sync_preview_heights 按栏高同步）、横向铺满整栏，
        # 头像在框内水平居中。原本 setFixedSize(130, 180) 把框钉死在栏左上角：
        # 宽度被 maximumWidth 卡住不铺栏、高度写死 180 不随窗口变，两个问题一起消失。
        self.existing_avatar_label.setMinimumHeight(_AVATAR_PREVIEW_MIN_H)
        self.existing_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.existing_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_layout.addWidget(self.existing_avatar_label)
        self.existing_info = QTextEdit()
        self.existing_info.setReadOnly(True)
        # 只读展示框不占焦点：Windows11 风格会给「有焦点的文本框」描一圈强调色
        # （accent 蓝）边框，本框无内容可编辑、描了纯属误导，还会在左栏最底部
        # 留下一条用户以为多余的蓝条。顺带把它从 Tab 链里摘掉，Tab 直接落到可编辑处。
        self.existing_info.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 议题 #180: Emby 简介以 <br> 分行(服务器端渲染需要, 数据本身正确),
        # MDCx 详情展示把 <br> 还原为换行——仅此处替换, 不回写数据。
        self.existing_info.setPlainText(
            "简介: "
            + re.sub(r"<br\s*/?>", "\n", actor.existing_overview or "无", flags=re.IGNORECASE)
            + "\n生日: "
            + (actor.existing_premiere_date[:10] if actor.existing_premiere_date else "无")
            + "\n出生地: "
            + (", ".join(actor.existing_production_locations) if actor.existing_production_locations else "无")
            + "\n标签: "
            + (", ".join(actor.existing_taglines) if actor.existing_taglines else "无")
        )
        left_layout.addWidget(self.existing_info)
        root.addWidget(left, stretch=1)

        # 右栏：新数据（可编辑）
        right = QGroupBox("新数据（同步前可编辑）")
        right.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        right_layout = QVBoxLayout(right)
        self.new_avatar_label = QLabel("新头像预览")
        # 与左栏同款：占本栏 1/3 高度、横向铺满、头像水平居中（见 _sync_preview_heights）。
        # 新增的这份高度不从窗口长出来，而是从下方内容里挤——
        # overview_edit stretch=2 / info_table stretch=1，即多出来的高度优先由「简介」让出。
        self.new_avatar_label.setMinimumHeight(_AVATAR_PREVIEW_MIN_H)
        self.new_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.new_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        right_layout.addWidget(self.new_avatar_label)
        right_layout.addWidget(QLabel("新简介（可编辑）:"))
        self.overview_edit = QTextEdit()
        self.overview_edit.setPlainText(actor.new_overview)
        # stretch 2 / 1：新头像预览拿走的那份高度由下方两个可伸缩控件让出，简介占大头
        # （「新头像预览多占的空间从简介获取」）。窗口太矮、让到最小高还不够时，
        # 预览框那边会自动退让（见 _sync_preview_heights），两栏都不会被挤出可视区。
        right_layout.addWidget(self.overview_edit, stretch=2)
        right_layout.addWidget(QLabel("新信息（右键增删行，可编辑）:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_table.customContextMenuRequested.connect(self._info_table_menu)
        self._populate_info_table()
        right_layout.addWidget(self.info_table, stretch=1)

        # 本地头像目录行：原先挂在右侧快速设置面板底部，按用户要求移到中列、
        # 置于「获取头像/获取信息…」按钮行正上方（整体左移一栏、上移一行）。
        # 输入框改由本窗口自建，改动即自动保存（与数据源测试窗同款 _save_folder）。
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("本地头像目录:"))
        self.folder_edit = QLineEdit(manager.config.actor_photo_folder)
        self.folder_edit.setCursorPosition(0)
        self.folder_browse_btn = QPushButton("浏览")
        self.folder_browse_btn.setObjectName("btnPrimary")
        self.folder_browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(self.folder_browse_btn)
        right_layout.addLayout(folder_row)

        btn_row = QHBoxLayout()
        self.btn_fetch_image = QPushButton("获取头像")
        self.btn_fetch_info = QPushButton("获取信息")
        self.btn_sync_both = QPushButton("同步头像+简介")
        self.btn_sync_image = QPushButton("只同步头像")
        self.btn_sync_info = QPushButton("只同步简介")
        for b in (
            self.btn_fetch_image,
            self.btn_fetch_info,
            self.btn_sync_both,
            self.btn_sync_image,
            self.btn_sync_info,
        ):
            b.setObjectName("btnPrimary")
            btn_row.addWidget(b)
        right_layout.addLayout(btn_row)
        root.addWidget(right, stretch=2)

        # 两个头像预览框的高度跟着所在栏走（各占 1/3，见 _sync_preview_heights）。
        # 挂在左右两栏的 Resize 上而不是对话框的 resizeEvent：栏的 Resize 事件送达时
        # 栏高已是新值（布局尚未重排子控件），读到的就是准数，不依赖 Qt 重排顺序。
        self._preview_boxes = (left, right)
        self._in_preview_sync = False
        for _box in self._preview_boxes:
            _box.installEventFilter(self)

        # 右侧快速设置面板（改即保存）：不限定宽，与左右两栏按 1:2:1 分配
        # （数据源测试窗口同款 fixed_width=None，定宽会卡死 stretch）。
        panel = _SourceQuickSettingsPanel(self, fixed_width=None)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # 头像/信息两列表 1:1 占据面板高度：详情窗常开（数据源测试窗是最大化才开，
        # 此处按用户要求始终平分，底部弹簧分不到富余、两列表铺满面板）。
        panel.set_lists_expanded(True)
        root.addWidget(panel, stretch=1)

        self.btn_fetch_image.clicked.connect(lambda: self._run_fetch_image())
        self.btn_fetch_info.clicked.connect(lambda: self._run_fetch_info())
        self.btn_sync_both.clicked.connect(lambda: self._run_sync("both"))
        self.btn_sync_image.clicked.connect(lambda: self._run_sync("image"))
        self.btn_sync_info.clicked.connect(lambda: self._run_sync("info"))
        self.folder_edit.textChanged.connect(self._save_folder)

        # 记住六枚按钮的默认高度：最大化时按对话框高度比例等比拉升高度、宽度不动
        # （见 _sync_button_stretch）。按控件直接存引用——六枚都是 btnPrimary，
        # 用 objectName / 文案当键会互相顶掉。
        self._stretch_base_h: list[tuple[QPushButton, int]] = []
        for b in (
            self.btn_fetch_image,
            self.btn_fetch_info,
            self.btn_sync_both,
            self.btn_sync_image,
            self.btn_sync_info,
            self.folder_browse_btn,
        ):
            try:
                self._stretch_base_h.append((b, b.sizeHint().height()))
            except Exception:
                pass

        self._detail_done.connect(self._on_detail_done)
        self._load_existing_avatar()
        if actor.new_image_path:
            self._show_new_avatar(actor.new_image_path)

        # 所有显示用文本框内容优先从左展示（含头像目录 / 简介等编辑框）
        left_anchor_text_edits(self)

    def _browse_folder(self):
        browse_folder(self, "选择本地头像目录", self.folder_edit, cursor_reset=True)

    def _save_folder(self):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_photo_folder = self.folder_edit.text().strip()
        manager._replace_config(cfg)
        manager.save()

    def _sync_button_stretch(self) -> None:
        """最大化时按钮高度随对话框高度等比拉升（宽度不变），还原时恢复默认；
        同时按窗口状态调整【浏览】按钮宽度。

        高度：比例 = 当前对话框高度 / 默认高度（默认高度取 __init__ 里 resize 后的
        `_dialog_base_h`），只写 `minimumHeight`——不碰宽度，最大化时按钮变高不变宽。
        数值相同即跳过，避免反复触发布局；普通/最小化窗口比例恒为 1.0，等于不改动。

        宽度：【浏览】跟着【只同步简介】走 —— 最小化时与它等宽，最大化时收成它的一半。
        基准取兄弟按钮的当前宽（而非写死数值）：五个功能按钮本身会在栏宽变化时伸缩，
        写死会在别的分辨率下对不齐。
        """
        try:
            try:
                _max = self.isMaximized()
            except Exception:
                _max = False
            _base_h = getattr(self, "_dialog_base_h", 0) or 0
            _cur_h = self.height() or 0
            _ratio = (_cur_h / _base_h) if (_max and _base_h > 0 and _cur_h > 0) else 1.0
            for _btn, _base in getattr(self, "_stretch_base_h", None) or []:
                try:
                    if _base <= 0:
                        continue
                    _target = max(1, int(round(_base * _ratio)))
                    if _btn.minimumHeight() != _target:
                        _btn.setMinimumHeight(_target)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._sync_browse_width(_max)
        except Exception:
            pass

    def _sync_browse_width(self, maximized: bool) -> None:
        """【浏览】按钮宽度 = 【只同步简介】宽度（最大化时为其一半）。

        最小化窗口不参与：最小化时窗口不可见、尺寸不变，按钮保持还原态宽度即可，
        而 Qt 在最小化时也照发 `WindowStateChange`，故只按 isMaximized() 分支。
        """
        btn = getattr(self, "folder_browse_btn", None)
        ref = getattr(self, "btn_sync_info", None)
        if btn is None or ref is None:
            return
        try:
            ref_w = ref.width() or ref.sizeHint().width()
            if ref_w <= 0:
                return
            target = max(1, int(round(ref_w / 2.0))) if maximized else int(ref_w)
            if btn.width() != target:
                btn.setFixedWidth(target)
        except Exception:
            pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event is not None and event.type() == QEvent.Type.WindowStateChange:
                self._sync_button_stretch()
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_button_stretch()
        # 兄弟按钮的宽度在 resizeEvent 里还是上一帧的旧值（本方法由窗口尺寸变化驱动，
        # 此刻子控件尚未重排），【浏览】的对齐基准会差上一两像素。事件跑完后补一次，
        # 那时 btn_row 已重排、基准才准。QTimer 会自动合并同一轮里的多次调用。
        try:
            QTimer.singleShot(0, self._sync_button_stretch)
        except Exception:
            pass

    def _sync_info_table_min_h(self) -> None:
        """信息表至少要能完整显示全部行：下限 = 表头 + 逐行 rowHeight 之和 + 边框 + 2px。

        不设这个下限的话，栏内空间被「简介」分走时表格只剩表头加一两行，
        「标签/年份/生日/出生地/外部ID」得拖着滚动条才看得全（实测 1080x720 下
        表格只剩 107px，够看 2 行半）。多留的 2px 是取整余量：viewport 高 =
        控件高 − 边框 − 表头，正好等于行高之和时差 1px 就会冒出一条竖滚动条。
        行数随「右键增删行」变化，故每次同步都按当前 rowCount 重算。
        栏内实在不够（窗口很矮或行数很多）时不会硬撑：最小高只作下限，
        预览框那边另有退让，实在仍不够表格照常滚动，不会把窗口顶大。
        """
        try:
            table = self.info_table
            header = table.horizontalHeader()
            head_h = header.height() if header is not None and not header.isHidden() else 0
            rows_h = sum(max(0, table.rowHeight(i)) for i in range(table.rowCount()))
            need = head_h + rows_h + 2 * table.frameWidth() + 2
            if table.minimumHeight() != need:
                table.setMinimumHeight(need)
        except Exception:
            pass

    def _sync_column_heights(self) -> None:
        """栏高变化的统一出口：先给信息表定下限，再同步两个头像预览框的取高。

        顺序有讲究：信息表的下限会计进所在栏的最小高，预览框的退让量必须按
        定完下限之后的余量算，否则这一轮算出的预览框会偏高。
        """
        try:
            self._sync_info_table_min_h()
        except Exception:
            pass
        try:
            self._sync_preview_heights()
        except Exception:
            pass

    def _sync_preview_heights(self) -> None:
        """两个头像预览框各占所在栏 1/3 高度，头像在框内水平居中并按新框宽重绘。

        目标高 = 栏高 // _AVATAR_PREVIEW_COL_RATIO；若这一份会把其余控件挤出栏外
        （栏太矮），退到「栏高 − 栏内其余控件最小高之和」。这个退让是防死循环的关键：
        预览框一旦写死高度，它的 minimumSize 就算进栏的最小高，栏被顶大 → 栏高变 →
        目标高又变大 → 窗口继续被顶大，来回不停。限定「其余控件永远放得下」即已截断。
        """
        if getattr(self, "_in_preview_sync", False):
            return
        self._in_preview_sync = True
        try:
            for label in (self.existing_avatar_label, self.new_avatar_label):
                try:
                    box = label.parentWidget()
                    if box is None or box.layout() is None:
                        continue
                    col_h = box.height()
                    if col_h <= 0:
                        continue
                    target = col_h // _AVATAR_PREVIEW_COL_RATIO
                    rest_h = _layout_min_h_excluding(box.layout(), label)
                    if col_h - target < rest_h:
                        target = col_h - rest_h
                    target = max(1, target)
                    if label.height() != target:
                        label.setFixedHeight(target)
                    self._rescale_preview_pixmap(label)
                except Exception:
                    pass
        finally:
            self._in_preview_sync = False

    def _center_on_screen(self, avail=None, *, allow_defer: bool = True) -> None:
        """把窗口外框放到所在屏幕可用区的正中央（严格居中）。

        与管理器 `_center_on_screen()` 同款口径：以 **frameGeometry**（含标题栏/边框）
        为准而非客户区 —— `move()` 收的是外框左上角，用客户区算会整体偏下偏右一个
        标题栏的高度（本机实测 30px）。窗口比可用区还大时钳到可用区左上角，
        保证标题栏留在屏内抓得到。
        """
        # 统一走 mdcx.utils.window_center 的唯一实现（外框 frameGeometry 口径）。
        center_on_screen(self, avail, allow_defer=allow_defer)

    @staticmethod
    def _rescale_preview_pixmap(label: QLabel) -> None:
        """预览框尺寸变了就按新尺寸重绘头像（_show_pixmap 存下的原图，KeepAspectRatio）。

        文字态（无头像/加载中/加载失败）不动 —— QLabel 的 setText 会清掉 pixmap，
        此时 pixmap 为空，据此判断即可，无需在各 setText 处额外清标记。
        """
        try:
            src = label.property("avatarSrcPixmap")
            if src is None:
                return
            shown = label.pixmap()
            if shown is None or shown.isNull():
                return
            label.setPixmap(src.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio))
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            if event is not None and event.type() == QEvent.Type.Resize and obj in getattr(self, "_preview_boxes", ()):
                self._sync_column_heights()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        # 严格居中：必须等首帧 —— showEvent 之前窗口还没创建原生 handle，
        # frameGeometry 会退化成客户区，据此算出来会整体偏下一个标题栏的高度。
        # 只做首次：用户手动挪过之后再次 show（复用已有窗口）不该被拽回正中。
        try:
            if not getattr(self, "_centered_once", False):
                self._centered_once = True
                self._center_on_screen()
        except Exception:
            pass
        # 首帧两栏才拿到真实几何，事件过滤器多半已触发过；这里补一次，
        # 保证「尺寸恰好没变、没发出 Resize」时预览框高度与信息表下限也都是对的。
        try:
            self._sync_column_heights()
        except Exception:
            pass
        # 首帧才激活窗口，此时才抢得到初始焦点；见 __init__ 里 setFocusPolicy 的说明。
        try:
            self.setFocus()
        except Exception:
            pass
        # 首帧按钮行才有真实宽度：【浏览】的对齐基准取自【只同步简介】的当前宽，
        # 首帧之前读到的还是 sizeHint，对不齐（见 _sync_button_stretch）。
        try:
            self._sync_button_stretch()
        except Exception:
            pass

    def _populate_info_table(self):
        actor = self.actor
        provider_ids = ", ".join(f"{k}:{v}" for k, v in actor.new_provider_ids.items())
        rows = [
            ("标签", ", ".join(actor.new_taglines)),
            ("年份", str(actor.new_production_year) if actor.new_production_year else ""),
            ("生日", actor.new_premiere_date),
            ("出生地", ", ".join(actor.new_production_locations)),
            ("外部ID", provider_ids),
        ]
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            self.info_table.setItem(r, 1, QTableWidgetItem(value))

    def _info_table_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        add_action = menu.addAction("增加行")
        del_action = menu.addAction("删除行")
        chosen = menu.exec(self.info_table.viewport().mapToGlobal(pos))
        if chosen == add_action:
            row = self.info_table.rowCount()
            self.info_table.insertRow(row)
            self.info_table.setItem(row, 0, QTableWidgetItem(""))
            self.info_table.setItem(row, 1, QTableWidgetItem(""))
        elif chosen == del_action:
            self.info_table.removeRow(self.info_table.currentRow())
        # 行数变了，「全部行完整显示」所需高度随之改变：立刻重算下限，
        # 免得增删行后要等到下次最大化/还原才生效（_sync_info_table_min_h）。
        try:
            self._sync_column_heights()
        except Exception:
            pass

    def log(self, msg: str):
        """详情窗口本地日志：只记不弹窗（独立窗口不碰管理器的日志框）。

        此前详情窗口无此方法，三处失败路径调 self.log 会直接 AttributeError。
        """
        try:
            self._log_lines.append(msg)
        except Exception:
            pass

    def _emit_done(self, action: str, result: object):
        """后台回写统一出口：关窗中途回写撞上已销毁对象时静默丢弃。"""
        try:
            self._detail_done.emit(action, result)
        except RuntimeError:
            pass

    def _load_existing_avatar(self):
        if not self.actor.has_image:
            self.existing_avatar_label.setText("无头像")
            return
        self.existing_avatar_label.setText("加载中...")
        try:
            future = executor.submit(self._download_existing_avatar())
        except Exception as e:
            self.existing_avatar_label.setText("头像加载失败")
            self.log(f"🔶 加载现有头像失败: {e}")
            return
        future.add_done_callback(lambda fut: self._emit_done("existing_avatar", _future_result_or(fut, None)))

    async def _download_existing_avatar(self) -> str | None:
        from .emby_shared import _build_jellyfin_headers, _generate_server_url

        _, _, pic_url, _, _, _ = _generate_server_url(
            {"Name": self.actor.name, "Id": self.actor.actor_id, "ServerId": self.actor.server_id}
        )
        headers = _build_jellyfin_headers()
        async with manager.acquire_computed() as computed:
            body, err = await computed.async_client.get_content(pic_url, headers=headers, use_proxy=False)
        if not body:
            return None
        tmp = resources.u("emby_actor_cache") / f"emby_existing_{self.actor.actor_id}.jpg"
        tmp.write_bytes(body)
        return str(tmp)

    def _run_fetch_image(self):
        try:
            future = executor.submit(self._fetch_image())
        except Exception as e:
            self.log(f"🔶 获取头像失败: {e}")
            return
        future.add_done_callback(lambda fut: self._emit_done("fetch_image", _future_result_or(fut, (False, None))))

    async def _fetch_image(self) -> tuple[bool, str | None]:
        gfriends_index = await load_gfriends_index()
        for src in manager.config.actor_image_sources:
            result: object = None
            try:
                result = await fetch_avatar_from_source(
                    self.actor,
                    src,
                    gfriends_index=gfriends_index,
                    cache_dir=resources.u("emby_actor_cache"),
                    local_avatar_dir=manager.config.actor_photo_folder,
                )
            except Exception:
                continue
            if result:
                path = result[0] if isinstance(result, tuple) and result else result
                if isinstance(path, (str, Path)) and Path(path).exists():
                    self.actor.new_image_path = str(path)
                    self.actor.need_update_image = True
                    return True, str(path)
        return False, None

    def _run_fetch_info(self):
        try:
            future = executor.submit(search_actor_info(self.actor))
        except Exception as e:
            self.log(f"🔶 获取简介失败: {e}")
            return
        future.add_done_callback(lambda fut: self._emit_done("fetch_info", _future_result_or(fut, False)))

    def _on_detail_done(self, action: str, result: object):
        if action == "existing_avatar":
            if result:
                self._show_pixmap(self.existing_avatar_label, str(result))
            else:
                self.existing_avatar_label.setText("无头像")
        elif action == "fetch_image":
            ok, path = result if isinstance(result, tuple) and len(result) == 2 else (False, None)
            if ok and path:
                self._show_new_avatar(path)
            else:
                self.new_avatar_label.setText("未获取到新头像")
        elif action == "fetch_info":
            if result:
                self.overview_edit.setPlainText(self.actor.new_overview)
                self._populate_info_table()
        elif action == "sync":
            ok, msg = result if isinstance(result, tuple) and len(result) == 2 else (False, str(result))
            self.btn_sync_both.setEnabled(True)
            self.btn_sync_image.setEnabled(True)
            self.btn_sync_info.setEnabled(True)
            QMessageBox.information(self, "同步结果", msg)
            if ok and self.on_synced:
                self.on_synced(self.actor)

    def _run_sync(self, sync_type: str):
        self._apply_edits()
        self.btn_sync_both.setEnabled(False)
        self.btn_sync_image.setEnabled(False)
        self.btn_sync_info.setEnabled(False)

        # 走可取消的 QThread（与 _fetch/_preview/_sync/_clean 同源）而不是裸
        # threading.Thread：同步会真的写 Emby 服务器，关窗时必须能打断并回收，
        # 否则窗口已销毁、任务还在后台跑，回写只能被 _emit_done 静默丢弃。
        thread = DetailSyncThread(self.actor, sync_type, self)
        thread.sync_done.connect(lambda result: self._emit_done("sync", result))
        thread.finished.connect(lambda: self._sync_thread_finished(thread))
        self._sync_thread = thread
        thread.start()

    def _sync_thread_finished(self, thread):
        """线程收尾：只清理自己仍是当前线程的那一格，避免拆掉后续任务的引用。"""
        if getattr(self, "_sync_thread", None) is thread:
            self._sync_thread = None

    def closeEvent(self, event):
        # 与管理器 closeEvent 同源的收尾：先打断同步任务，再等它退出；
        # 等不到（卡在不可取消的原生阻塞）就卸父级并保住引用，避免
        # WA_DeleteOnClose 拆掉仍在运行的 QThread 导致进程 abort。
        thread = getattr(self, "_sync_thread", None)
        if thread is not None:
            thread.abort()
            if thread.isRunning() and not thread.wait(5000) and thread.isRunning():
                _detach_running_thread(thread)
            self._sync_thread = None
        super().closeEvent(event)

    def _apply_edits(self):
        actor = self.actor
        actor.new_overview = self.overview_edit.toPlainText().strip()
        actor.new_taglines = []
        actor.new_production_locations = []
        actor.new_production_year = None
        actor.new_premiere_date = ""
        for r in range(self.info_table.rowCount()):
            field_item = self.info_table.item(r, 0)
            value_item = self.info_table.item(r, 1)
            if not field_item or not value_item:
                continue
            field = field_item.text().strip()
            value = value_item.text().strip()
            if field == "标签":
                actor.new_taglines = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "年份":
                actor.new_production_year = int(value) if value.isdigit() else None
            elif field == "生日":
                actor.new_premiere_date = value
            elif field == "出生地":
                actor.new_production_locations = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "外部ID":
                provider_ids: dict[str, str] = {}
                for part in value.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if ":" in part:
                        k, v = part.split(":", 1)
                        provider_ids[k.strip()] = v.strip()
                actor.new_provider_ids = provider_ids
        if (
            actor.new_overview
            or actor.new_taglines
            or actor.new_production_year
            or actor.new_premiere_date
            or actor.new_provider_ids
        ):
            actor.need_update_info = True

    def _show_new_avatar(self, path: str):
        self._show_pixmap(self.new_avatar_label, path)

    @staticmethod
    def _show_pixmap(label: QLabel, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            # 存一份未缩放的原图：预览框高度随窗口变（_sync_preview_heights），
            # 框一变就得按新尺寸重绘，只在首次缩一次的话框大了头像不会跟着大。
            label.setProperty("avatarSrcPixmap", pix)
            label.setPixmap(pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio))
