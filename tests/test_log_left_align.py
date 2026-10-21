"""软件日志窗口的每一行都必须严格左对齐（行首不留缩进）。

用户 2026-10-21 反馈：同一批日志消息在日志窗口里左边缘不齐——

    ✅ 数据库连接成功, 共有 21860 条女优信息   ← 行首多一个空格
    ✅ ThePornDB 连接正常！                   ← 行首多一个空格
    ✅ JavBus 连接正常！
    ⏳ 连接 Gfriends 网络头像库...
    ✅ Gfriends 连接成功！最新数据更新时间: 2026-10-20 23:24:48
    ✅ 本地缓存数据无需更新！本地数据更新时间: 2026-10-21 17:59:41

要求所有行左边缘一致（严格左对齐）。

修复分两层：

1. `mdcx/log_console.py::strip_leading_indent` —— 统一去掉消息**首行**行首的
   空格 / Tab。出口 `log_console.log_text()`（无 Qt 的日志内核）与主窗口日志页
   `LogPageMixin.show_log_text()`（UI 侧排队处）各过一道，两条来路都归一，
   窗口显示与落盘日志文件同形。
2. 生成这些消息的源码自身不再带行首空格（`actress_db.py` / `base/web.py` /
   `cookie_checks.py` / `net_check.py`），其中四处「站点名前缀」统一走
   `mdcx/log_console.py::with_site_prefix`，不再各写一份
   `replace("✅", " ✅ Site")`（那个替换串里的前导空格正是右移一格的元凶）。

为什么只动首行：日志里大量消息是「一行标题 + 若干缩进明细」的形态（traceback
的调用栈、路径清单、参数回显），那些缩进是内容本身的一部分，整段 lstrip 会把
traceback 的调用层级压平，反而更难读。
"""

import sqlite3
from collections import deque
from types import SimpleNamespace

import pytest

import mdcx.base.web as base_web
from mdcx.config.manager import manager
from mdcx.controllers.main_window import cookie_checks
from mdcx.controllers.main_window import logs as logs_page
from mdcx.log_console import log_console, strip_leading_indent, with_site_prefix
from mdcx.tools.actress_db import ActressDB


@pytest.fixture()
def captured_logs():
    """临时接管 log_console 的 UI 出口，收集真正送到日志窗口的文本。

    `mdcx.signals` 在导入时就把 `Signals.show_log_text` 注册成了出口，本文件
    顶部已导入相关模块（保证注册先于本 fixture 发生），这里只做临时替换并在
    收尾时还原。
    """
    original = log_console._text_sink
    seen: list[str] = []
    log_console.bind_text_sink(seen.append)
    try:
        yield seen
    finally:
        log_console.bind_text_sink(original)


# ── 归一函数本身 ─────────────────────────────────────────────────────────────


def test_strip_leading_indent_removes_spaces_and_tabs():
    assert strip_leading_indent(" ✅ 数据库连接成功") == "✅ 数据库连接成功"
    assert strip_leading_indent("   🔴 失败") == "🔴 失败"
    assert strip_leading_indent("\t⏳ 连接中") == "⏳ 连接中"
    assert strip_leading_indent("✅ 已经对齐") == "✅ 已经对齐"
    assert strip_leading_indent("") == ""


def test_strip_leading_indent_keeps_body_indent():
    """多行消息的内部缩进属于内容本身，不能被压平。"""
    traceback_text = 'Traceback (most recent call last):\n  File "x.py", line 3, in f\n    raise ValueError'
    assert strip_leading_indent(traceback_text) == traceback_text
    assert strip_leading_indent("  标题\n    缩进明细") == "标题\n    缩进明细"


def test_strip_leading_indent_keeps_leading_blank_line():
    """以换行开头的消息是刻意留空行分隔的，那个空行必须保留。"""
    assert strip_leading_indent("\n🔴 未找到作品") == "\n🔴 未找到作品"
    assert strip_leading_indent("  \n🔴 未找到作品") == "\n🔴 未找到作品"


def test_with_site_prefix_keeps_line_flush_left():
    """站点名前缀只加在图标后面，不再把整行右移一格。"""
    assert with_site_prefix("✅ 连接正常！", "JavBus") == "✅ JavBus 连接正常！"
    assert with_site_prefix("❌ 连接失败！", "ThePornDB") == "❌ ThePornDB 连接失败！"
    assert with_site_prefix("❌ 连接失败！", "JavBus").startswith("❌ JavBus ")


# ── 日志出口 ─────────────────────────────────────────────────────────────────


def test_log_console_sink_receives_left_aligned_text(captured_logs):
    log_console.log_text(" ✅ 数据库连接成功, 共有 21860 条女优信息")
    log_console.log_text("⏳ 连接 Gfriends 网络头像库...")
    assert captured_logs == [
        "✅ 数据库连接成功, 共有 21860 条女优信息",
        "⏳ 连接 Gfriends 网络头像库...",
    ]


def test_user_reported_log_batch_is_left_aligned(captured_logs):
    """用户报的那一批消息，逐行核对最终形态。"""
    for message in (
        " ✅ 数据库连接成功, 共有 21860 条女优信息",
        " ✅ ThePornDB 连接正常！",
        " ✅ JavBus 连接正常！",
        " ✅ FC2PPVDB 连接正常！",
        "⏳ 连接 Gfriends 网络头像库...",
        "✅ Gfriends 连接成功！最新数据更新时间: 2026-10-20 23:24:48",
        "✅ 本地缓存数据无需更新！本地数据更新时间: 2026-10-21 17:59:41",
    ):
        log_console.log_text(message)

    assert captured_logs == [
        "✅ 数据库连接成功, 共有 21860 条女优信息",
        "✅ ThePornDB 连接正常！",
        "✅ JavBus 连接正常！",
        "✅ FC2PPVDB 连接正常！",
        "⏳ 连接 Gfriends 网络头像库...",
        "✅ Gfriends 连接成功！最新数据更新时间: 2026-10-20 23:24:48",
        "✅ 本地缓存数据无需更新！本地数据更新时间: 2026-10-21 17:59:41",
    ]


def test_main_log_page_queue_is_left_aligned():
    """主窗口日志页排队前就归一，窗口显示与落盘日志文件左边缘一致。"""

    class _Stub(logs_page.LogPageMixin):
        def __init__(self):
            self.main_log_queue: deque[str] = deque()

    stub = _Stub()
    stub.show_log_text(" ✅ 数据库连接成功, 共有 21860 条女优信息")
    stub.show_log_text("✅ ThePornDB 连接正常！")
    stub.show_log_text("   🔴 失败")

    assert list(stub.main_log_queue) == [
        "✅ 数据库连接成功, 共有 21860 条女优信息",
        "✅ ThePornDB 连接正常！",
        "🔴 失败",
    ]


# ── 各业务消息源头 ───────────────────────────────────────────────────────────


def test_actress_db_connect_log_is_left_aligned(tmp_path, monkeypatch, captured_logs):
    """「✅ 数据库连接成功, 共有 N 条女优信息」行首不留空格。"""
    db_path = tmp_path / "info.db"
    conn = sqlite3.connect(db_path)
    conn.execute("create table Info (Name text)")
    conn.execute("insert into Info values ('x')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(manager.config, "info_database_path", str(db_path))
    monkeypatch.setattr(ActressDB, "DB", None)

    ActressDB.init_db()

    assert captured_logs == ["✅ 数据库连接成功, 共有 1 条女优信息"]


class _FakeThePornDBResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"data": {"id": 1}}


class _FakeComputedLease:
    def __enter__(self):
        async_client = SimpleNamespace(request=lambda *args, **kwargs: None)
        return SimpleNamespace(async_client=async_client)

    def __exit__(self, exc_type, exc, traceback):
        return None


def test_theporndb_check_log_is_left_aligned(monkeypatch, captured_logs):
    """「✅ ThePornDB 连接正常！」行首不留空格。"""
    monkeypatch.setattr(manager.config, "theporndb_api_token", "token")
    monkeypatch.setattr(base_web.manager, "acquire_computed", lambda: _FakeComputedLease())
    monkeypatch.setattr(base_web.executor, "run", lambda _coro: (_FakeThePornDBResponse(), ""))

    result = base_web.check_theporndb_api_token()

    assert result == "✅ 连接正常！"
    assert captured_logs == ["✅ ThePornDB 连接正常！"]


class _CookieChecksStub(cookie_checks.CookieChecksMixin):
    """只提供被测方法用到的那几个出口，不起 Qt 窗口。"""

    def __init__(self):
        self.logs: list[str] = []
        self.statuses: list[str] = []
        self.saved = 0
        self.exec_save_config = SimpleNamespace(emit=self._on_save)
        self.set_javbus_status = SimpleNamespace(emit=self.statuses.append)

    def _on_save(self):
        self.saved += 1

    def show_log_text(self, text):
        self.logs.append(text)


def test_javbus_cookie_check_log_is_left_aligned(monkeypatch):
    """「✅ JavBus 连接正常！」行首不留空格。"""
    monkeypatch.setattr(cookie_checks, "javbus_cookie_verdict_sync", lambda _cookie: ("valid", "✅ 连接正常！"))
    monkeypatch.setattr(manager.config, "javbus", "cookie")

    stub = _CookieChecksStub()
    stub._check_javbus_cookie("cookie")

    assert stub.logs == ["✅ JavBus 连接正常！"]
