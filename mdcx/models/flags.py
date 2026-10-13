import asyncio
import threading
from asyncio import Event
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from .enums import FileMode
from .model_types import ScrapeResult


class FileDoneDict(TypedDict):
    poster: Path | None
    thumb: Path | None
    fanart: Path | None
    trailer: Path | None
    local_poster: Path | None
    local_thumb: Path | None
    local_fanart: Path | None
    local_trailer: Path | None


def _new_lock():
    return asyncio.Lock()


JSON_DATA_CACHE_MAX_ENTRIES = 2000


@dataclass
class _Flags:
    _counter_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)

    async def increment(self, name: str, value: int = 1) -> int:
        async with self._counter_lock:
            current = getattr(self, name, 0) + value
            setattr(self, name, current)
            return current

    # 跨线程共享容器（remain_list / success_list / failed_list / again 系 dict）
    # 的互斥锁：读它们的是 UI 线程、写它们的是刮削协程（后台 loop 线程）、
    # 读写的还有工作线程（to_thread 内 task、移动线程、停止线程）。
    # 用法：一律 with Flags.guarded(): 包住“读-改-写/快照”整段，读侧在锁内
    # 取快照（list()/set()/dict()/len()），出锁后再遍历使用。
    # 注意：asyncio.Lock 不能跨线程拿，故这里单独用 threading.RLock；
    # 同 loop 线程内的协程并发仍由各 _*_lock（asyncio.Lock）负责。
    # 纯 bool 开关（stop_requested / stop_other / can_save_remain）是单字赋值，
    # 最坏只是瞬时过期读，无撕裂风险，保持无锁直读直写。
    _sync_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @contextmanager
    def guarded(self) -> Iterator[None]:
        """跨线程容器临界区（同步线程 + 后台 loop 线程通用）。"""
        with self._sync_lock:
            yield

    def increment_sync(self, name: str, value: int = 1) -> int:
        """同步线程用的计数器自增（对应协程侧的 increment）。"""
        with self._sync_lock:
            current = getattr(self, name, 0) + value
            setattr(self, name, current)
            return current

    # 指定刮削 #todo 改为传参
    appoint_url: str = ""
    website_name: str = ""

    # 演员库 json_get_status / json_get_set / json_data_dic 竞态防护
    _json_get_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)

    # file_new_path_dic 的 check-then-set 竞态防护
    _file_path_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)

    # 各共享 set/dic 的 check-then-set 竞态防护
    _file_done_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)
    _pic_catch_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)
    _extrafanart_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)
    _trailer_lock: asyncio.Lock = field(default_factory=_new_lock, repr=False)

    # 刮削相关
    rest_time_convert: int = 0
    rest_time_convert_: int = 0
    total_kills: int = 0
    now_kill: int = 0
    success_save_time: float = 0.0
    next_start_time: float = 0.0
    count_claw: int = 0
    can_save_remain: bool = False
    remain_list: list[Path] = field(default_factory=list)
    new_again_dic: dict[Path, tuple[str, str, str]] = field(default_factory=dict)
    again_dic: dict[Path, tuple[str, str, str]] = field(default_factory=dict)
    start_time: float = 0.0
    file_mode: FileMode = FileMode.Default
    counting_order: int = 0
    total_count: int = 0
    rest_now_begin_count: int = 0
    sleep_end: Event = field(default_factory=Event)
    rest_next_begin_time: float = 0.0
    scrape_starting: int = 0
    scrape_started: int = 0
    scrape_done: int = 0
    succ_count: int = 0
    fail_count: int = 0
    file_new_path_dic: dict[Path, list[Path]] = field(default_factory=dict)
    pic_catch_set: set[Path] = field(default_factory=set)
    file_done_dic: dict[str, FileDoneDict] = field(default_factory=dict)
    extrafanart_deal_set: set[Path] = field(default_factory=set)
    trailer_deal_set: set[Path] = field(default_factory=set)
    json_get_set: set[str] = field(default_factory=set)
    json_get_status: dict[str, bool | None] = field(default_factory=dict)
    json_get_events: dict[str, asyncio.Event] = field(default_factory=dict)
    json_data_dic: OrderedDict[str, ScrapeResult] = field(default_factory=OrderedDict)
    img_path: str = ""
    failed_list: list[tuple[Path, str]] = field(default_factory=list)
    scrape_start_time: float = 0.0
    success_list: set[Path] = field(default_factory=set)
    stop_other: bool = True
    stop_requested: bool = False

    # show
    log_txt: Any = None
    scrape_like_text: str = ""
    main_mode_text: str = ""

    single_file_path: Path = field(default_factory=Path)

    # for missing
    actor_numbers_dic: dict[str, list[str]] = field(default_factory=dict)
    local_number_set: set[str] = field(default_factory=set)
    local_number_cnword_set: set[str] = field(default_factory=set)

    def reset(self) -> None:
        # reset 多在 UI 线程跑，但容器正被后台 loop 线程读写，整体包锁
        # 快照式替换，避免“刚 clear 又被 append”的交叉丢失。
        with self._sync_lock:
            self._reset_locked()

    def _reset_locked(self) -> None:
        """reset 的锁内实现（调用方须已持有 _sync_lock）。"""
        self.appoint_url = ""
        self.website_name = ""
        self.failed_list = []
        self.counting_order = 0
        self.total_count = 0
        self.rest_now_begin_count = 0
        self.sleep_end.set()
        self.scrape_starting = 0
        self.scrape_started = 0
        self.scrape_done = 0
        self.succ_count = 0
        self.fail_count = 0
        self.file_new_path_dic = {}
        self.pic_catch_set = set()
        self.file_done_dic = {}
        self.extrafanart_deal_set = set()
        self.trailer_deal_set = set()
        self.json_get_set = set()
        self.json_get_status = {}
        self.json_get_events = {}
        self.json_data_dic = OrderedDict()
        self.img_path = ""
        self.stop_requested = False
        self.stop_other = True
        self.scrape_start_time = 0.0
        self.success_list = set()
        self.next_start_time = 0.0
        self.total_kills = 0
        self.now_kill = 0
        self.success_save_time = 0.0
        self.rest_time_convert = 0
        self.rest_time_convert_ = 0
        self.rest_next_begin_time = 0.0
        self.single_file_path = Path()
        self.actor_numbers_dic = {}
        self.local_number_set = set()
        self.local_number_cnword_set = set()
        self.count_claw = 0
        self.can_save_remain = False
        self.remain_list = []
        self.new_again_dic = {}
        self.again_dic = {}
        self.start_time = 0.0
        self.file_mode = FileMode.Default
        self.log_txt = None
        # 注意：scrape_like_text / main_mode_text 是配置派生的展示文案
        # （load/save_config 从持久化配置写入），不是单次运行态，reset 不得清空——
        # 否则刮削开始后左下角模式行只剩「💠 ·」光杆图标，没有文字说明（见 Development.md 左下角规范）。


Flags = _Flags()
