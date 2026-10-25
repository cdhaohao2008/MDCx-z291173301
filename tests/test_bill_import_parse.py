"""账单解析与榜单排序的回归测试（2026-10-26「导入微信/支付宝账单」需求）。

覆盖三类真实账单版式（微信支付账单 / 微信经营账户明细 / 支付宝交易明细）：
数据区之前都有一大段说明行，列序各不相同，只认列名不认序号。断言的重点是
「只算收入」——支出、退款、不计收支一律不能进榜。

榜单口径（用户需求）：新人榜 = 最新 10 个捐助者、土豪榜 = 金额最大的 10 个人，
两个榜都按捐助者去重（同一个人只占一行）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import openpyxl
import pytest

from mdcx.tools import bill_import as bi


def _write_xlsx(path, rows) -> str:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return str(path)


# 微信支付账单明细：说明区 + 表头 + 收入/支出/退款/不计收支各一笔
_WECHAT_PAY_ROWS = (
    ("微信支付账单明细",),
    ("微信昵称：[张三]",),
    ("起始时间：[2026-01-01 00:00:00] 终止时间：[2026-01-31 23:59:59]",),
    ("共4笔记录",),
    ("----------------------微信支付账单明细列表--------------------",),
    (
        "交易时间",
        "交易类型",
        "交易对方",
        "商品",
        "收/支",
        "金额(元)",
        "支付方式",
        "当前状态",
        "交易单号",
        "商户单号",
        "备注",
    ),
    ("2026-01-05 10:00:00", "二维码收款", "李四", "赞助", "收入", "¥50.00", "零钱", "已收钱", "1", "2", "/"),
    ("2026-01-06 11:00:00", "商户消费", "超市", "购物", "支出", "¥20.00", "零钱", "支付成功", "3", "4", "/"),
    ("2026-01-07 12:00:00", "退款", "王五", "退款", "收入", "¥30.00", "零钱", "已全额退款", "5", "6", "/"),
    ("2026-01-08 13:00:00", "转账", "赵六", "转账", "不计收支", "¥10.00", "零钱", "已转账", "7", "8", "/"),
)

# 微信经营账户明细：收支类型 + 明细名称「经营收款-来自 xxx」
_WECHAT_MERCHANT_ROWS = (
    ("可在电脑浏览器输入docs.qq.com 微信登录进行查看和下载打印文件",),
    ("微信经营账户明细",),
    ("经营者名称:[经营者_周涵]",),
    ("起始时间:[2026/10/01] 终止时间:[2026/10/26]",),
    (
        "交易时间",
        "收支类型",
        "交易类型",
        "明细名称",
        "金额",
        "单号",
        "余额变动",
        "收款服务费信息",
        "收款备注",
        "其他信息",
    ),
    ("2026/10/25 20:23:18", "收入", "经营收款", "经营收款-来自z*n", "100.00", "1034", "余额￥100.00", "/", "/", "/"),
    ("2026/10/26 09:00:00", "支出", "提现", "提现到银行卡", "50.00", "1035", "余额￥50.00", "/", "/", "/"),
)

# 支付宝交易记录明细：金额列无货币符号、日期用斜杠
_ALIPAY_ROWS = (
    ("支付宝交易记录明细查询",),
    ("账号:[abc@example.com]",),
    ("---------------------------------交易记录明细列表------------------------------------",),
    (
        "交易时间",
        "交易分类",
        "交易对方",
        "对方账号",
        "商品说明",
        "收/支",
        "金额",
        "收/付款方式",
        "交易状态",
        "交易订单号",
        "商家订单号",
        "备注",
    ),
    (
        "2026/02/01 09:30:00",
        "转账红包",
        "小明",
        "xm@example.com",
        "转账",
        "收入",
        "88.00",
        "余额",
        "交易成功",
        "A1",
        "B1",
        "",
    ),
    ("2026/02/02 10:00:00", "购物", "淘宝", "", "商品", "支出", "12.00", "余额", "交易成功", "A2", "B2", ""),
)


def test_wechat_pay_bill_keeps_only_income(tmp_path):
    records = bi.parse_bill(_write_xlsx(tmp_path / "wechat.xlsx", _WECHAT_PAY_ROWS))
    assert [(r.name, r.time, r.amount) for r in records] == [("李四", "2026-01-05 10:00:00", 50.0)]


def test_wechat_merchant_bill_strips_laicoming_prefix(tmp_path):
    """经营账户的「明细名称」是「经营收款-来自 z*n」，捐助者取「来自」后面那截。"""
    records = bi.parse_bill(_write_xlsx(tmp_path / "merchant.xlsx", _WECHAT_MERCHANT_ROWS))
    assert [(r.name, r.amount) for r in records] == [("z*n", 100.0)]
    assert records[0].time == "2026-10-25 20:23:18"


def test_alipay_bill_keeps_only_income(tmp_path):
    records = bi.parse_bill(_write_xlsx(tmp_path / "alipay.xlsx", _ALIPAY_ROWS))
    assert [(r.name, r.time, r.amount) for r in records] == [("小明", "2026-02-01 09:30:00", 88.0)]


def test_bill_without_header_raises(tmp_path):
    path = _write_xlsx(tmp_path / "bad.xlsx", (("随便", "写点什么"), ("没有表头",)))
    with pytest.raises(bi.BillImportError):
        bi.parse_bill(path)


def test_missing_file_raises():
    with pytest.raises(bi.BillImportError):
        bi.parse_bill("Z:/definitely/not/here.xlsx")


def test_income_direction_parsing():
    """「不计收支」同时含「收」「支」，必须先判掉，否则会被当成收入。"""
    assert bi._is_income("收入") is True
    assert bi._is_income("支出") is False
    assert bi._is_income("不计收支") is False
    assert bi._is_income("已全额退款") is False
    assert bi._is_income("") is True


def test_amount_parsing_handles_currency_and_commas():
    assert bi._parse_amount("¥1,234.56") == 1234.56
    assert bi._parse_amount("100.00元") == 100.0
    assert bi._parse_amount(88) == 88.0
    assert bi._parse_amount("") == 0.0


def _records(count: int) -> list[bi.DonationRecord]:
    return [
        bi.DonationRecord(name=f"捐助者{i:02d}", time=f"2026-03-{i:02d} 12:00:00", amount=float(i * 10))
        for i in range(1, count + 1)
    ]


def test_newcomer_rank_is_latest_ten_desc():
    rank = bi.newcomer_rank(_records(12))
    assert len(rank) == 10
    assert [r.name for r in rank] == [f"捐助者{i:02d}" for i in range(12, 2, -1)]


def test_tycoon_rank_is_top_ten_amount_desc():
    rank = bi.tycoon_rank(_records(12))
    assert len(rank) == 10
    assert [r.amount for r in rank] == sorted((r.amount for r in rank), reverse=True)
    assert rank[0].amount == 120.0
    assert all(r.amount >= 30.0 for r in rank)


def test_ranks_dedupe_same_donor():
    """同一个人捐多次：新人榜留最近一笔、土豪榜留金额最大一笔，各只占一行。"""
    records = [
        bi.DonationRecord("老王", "2026-03-01 10:00:00", 10.0),
        bi.DonationRecord("老王", "2026-03-05 10:00:00", 500.0),
        bi.DonationRecord("小李", "2026-03-03 10:00:00", 20.0),
    ]
    newcomer = bi.newcomer_rank(records)
    assert [(r.name, r.time) for r in newcomer] == [("老王", "2026-03-05 10:00:00"), ("小李", "2026-03-03 10:00:00")]
    tycoon = bi.tycoon_rank(records)
    assert [(r.name, r.amount) for r in tycoon] == [("老王", 500.0), ("小李", 20.0)]


def test_format_rank_time_drops_year_only_for_current_year():
    now = datetime(2026, 10, 26, 8, 0, 0)
    assert bi.format_rank_time("2026-10-25 20:23:18", now) == "10-25 20:23"
    assert bi.format_rank_time("2025-10-25 20:23:18", now) == "2025-10-25"


def test_merge_records_dedupes_identical_donations():
    one = bi.DonationRecord("老王", "2026-03-01 10:00:00", 10.0)
    assert bi.merge_records([one], [one, bi.DonationRecord("老王", "2026-03-01 10:00:00", 10.0)]) == [one]


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    bundled = tmp_path / "resources" / bi.RECORDS_FILENAME
    local = tmp_path / "userdata" / bi.RECORDS_FILENAME
    monkeypatch.setattr(bi, "_records_paths", lambda: (bundled, local))
    records = [bi.DonationRecord("老王", "2026-03-01 10:00:00", 10.0)]
    written = bi.save_records(records)
    assert written == bundled
    assert bi.load_records() == records  # 两份都写了，取并集后仍是一条


def test_load_records_merges_bundled_and_local(tmp_path, monkeypatch):
    """随包那份给所有用户看，用户数据那份给作者本机即时生效，读取时取并集。"""
    bundled = tmp_path / "resources" / bi.RECORDS_FILENAME
    local = tmp_path / "userdata" / bi.RECORDS_FILENAME
    monkeypatch.setattr(bi, "_records_paths", lambda: (bundled, local))
    bundled.parent.mkdir(parents=True)
    bundled.write_text('{"records": [{"name": "随包", "time": "2026-01-01 00:00:00", "amount": 5}]}', "utf-8")
    local.parent.mkdir(parents=True)
    local.write_text('{"records": [{"name": "本机", "time": "2026-01-02 00:00:00", "amount": 6}]}', "utf-8")
    assert [r.name for r in bi.load_records()] == ["随包", "本机"]


def test_load_records_survives_broken_file(tmp_path, monkeypatch):
    bundled = tmp_path / "resources" / bi.RECORDS_FILENAME
    local = tmp_path / "userdata" / bi.RECORDS_FILENAME
    monkeypatch.setattr(bi, "_records_paths", lambda: (bundled, local))
    bundled.parent.mkdir(parents=True)
    bundled.write_text("{ 这不是 json", "utf-8")
    assert bi.load_records() == []
