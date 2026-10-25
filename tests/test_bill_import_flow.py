"""「导入账单」点击流程的端到端回归（选文件 → 解析 → 合并 → 落盘 → 提示）。

界面用真实的 ``MyMAinWindow``，只把三处外部交互打桩：文件选择框、消息框、记录落盘目录。
断言的重点是「点一下真的把账单变成了榜单数据」，以及未绑定机器上连流程都不进。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import sys

import openpyxl
import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from mdcx.tools import bill_import as bi

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod
    from mdcx.utils import machine_binding

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(machine_binding, "ensure_probe_started", lambda: None)
    monkeypatch.setattr(machine_binding, "probe_state", lambda: True)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    window._poll_bill_bind_state()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _bill_file(tmp_path) -> str:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in (
        ("微信支付账单明细",),
        ("交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)"),
        ("2026-10-25 20:23:18", "二维码收款", "z*n", "赞助", "收入", "¥100.00"),
        ("2026-10-24 09:00:00", "二维码收款", "老李", "赞助", "收入", "¥300.00"),
        ("2026-10-23 09:00:00", "商户消费", "超市", "购物", "支出", "¥20.00"),
    ):
        sheet.append(list(row))
    path = tmp_path / "bill.xlsx"
    workbook.save(path)
    return str(path)


def test_import_writes_records_and_ranks(win, monkeypatch, tmp_path):
    from mdcx.utils import machine_binding

    bundled = tmp_path / "resources" / bi.RECORDS_FILENAME
    local = tmp_path / "userdata" / bi.RECORDS_FILENAME
    monkeypatch.setattr(bi, "_records_paths", lambda: (bundled, local))
    monkeypatch.setattr(machine_binding, "is_bound_machine", lambda: True)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (_bill_file(tmp_path), "")))
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text, *a, **k: messages.append(text)))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda _p, _t, text, *a, **k: messages.append(text)))

    win.import_bill()

    payload = json.loads(bundled.read_text(encoding="utf-8"))
    assert [item["name"] for item in payload["records"]] == ["老李", "z*n"]  # 时间升序
    assert all(item["amount"] > 0 for item in payload["records"])
    assert len(payload["records"]) == 2  # 支出那笔没进来
    assert messages and "已导入 2 笔收入记录" in messages[0]

    # 赞助窗口读同一份记录 → 新人榜最新在前、土豪榜金额最大在前
    from mdcx.views.donate_window import DonateDialog

    dialog = DonateDialog()
    try:
        newcomer, tycoon = dialog._rank_tables
        assert newcomer.item(0, 0).text() == "z*n"  # 10-25 最新
        assert tycoon.item(0, 0).text() == "老李"  # 300 最大
        assert tycoon.item(0, 2).text() == "¥300.00"
    finally:
        dialog.deleteLater()


def test_import_refuses_on_unbound_machine(win, monkeypatch):
    from mdcx.utils import machine_binding

    called: list[int] = []
    monkeypatch.setattr(machine_binding, "is_bound_machine", lambda: False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: called.append(1) or ("", "")))
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda _p, _t, text, *a, **k: messages.append(text)))

    win.import_bill()

    assert called == []  # 连文件选择框都不弹
    assert messages == ["本功能未授权在当前电脑使用。"]


def test_import_reports_bad_bill(win, monkeypatch, tmp_path):
    from mdcx.utils import machine_binding

    bad = tmp_path / "bad.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["没有表头的账单"])
    workbook.save(bad)
    monkeypatch.setattr(machine_binding, "is_bound_machine", lambda: True)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (str(bad), "")))
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda _p, _t, text, *a, **k: messages.append(text)))

    win.import_bill()

    assert messages and "交易时间" in messages[0]
