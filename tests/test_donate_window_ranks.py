"""赞助窗口榜单填数回归（2026-10-26「导入账单后在新人榜/土豪榜展示」需求）。

左表新人榜 = 最新 10 个捐助者（时间倒序），右表土豪榜 = 金额最大的 10 个人（金额倒序），
两个榜都按捐助者去重；记录不足 10 条时其余行留空（版式与参考图一致，不显示占位文字）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

from mdcx.tools import bill_import as bi
from mdcx.views import donate_window as dw

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _dialog(app) -> dw.DonateDialog:
    dialog = dw.DonateDialog()
    app.processEvents()
    return dialog


def _grid(table) -> list[list[str]]:
    return [[table.item(row, col).text() for col in range(dw._RANK_COLS)] for row in range(dw._RANK_ROWS)]


def test_ranks_filled_from_records(app, monkeypatch):
    records = [
        bi.DonationRecord("小明", "2026-03-01 10:00:00", 20.0),
        bi.DonationRecord("老王", "2026-03-05 10:00:00", 500.0),
        bi.DonationRecord("小李", "2026-03-03 10:00:00", 88.0),
    ]
    monkeypatch.setattr(bi, "load_records", lambda: records)
    dialog = _dialog(app)
    try:
        newcomer, tycoon = dialog._rank_tables
        # 新人榜：时间倒序
        assert [row[0] for row in _grid(newcomer)[:3]] == ["老王", "小李", "小明"]
        # 土豪榜：金额倒序
        assert [row[0] for row in _grid(tycoon)[:3]] == ["老王", "小李", "小明"]
        assert _grid(tycoon)[0][2] == "¥500.00"
        # 不足 10 条时其余行留空
        assert _grid(newcomer)[3:] == [["", "", ""]] * (dw._RANK_ROWS - 3)
    finally:
        dialog.deleteLater()


def test_empty_records_leave_tables_blank(app, monkeypatch):
    monkeypatch.setattr(bi, "load_records", lambda: [])
    dialog = _dialog(app)
    try:
        for table in dialog._rank_tables:
            assert _grid(table) == [["", "", ""]] * dw._RANK_ROWS
    finally:
        dialog.deleteLater()


def test_broken_records_do_not_break_dialog(app, monkeypatch):
    """读记录抛异常时窗口照常弹出（收款码还得能用），榜单留空。"""

    def _boom():
        raise RuntimeError("坏数据")

    monkeypatch.setattr(bi, "load_records", _boom)
    dialog = _dialog(app)
    try:
        for table in dialog._rank_tables:
            assert _grid(table) == [["", "", ""]] * dw._RANK_ROWS
    finally:
        dialog.deleteLater()
