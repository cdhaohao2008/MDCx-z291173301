"""微信 / 支付宝账单导入：把 xlsx 账单里的「收入」流水解析成赞助榜单记录。

同一套列名映射吃三种账单，靠表头识别、不看文件名：

* 微信支付账单明细：``交易时间 / 交易类型 / 交易对方 / 商品 / 收/支 / 金额(元) / …``
* 微信经营账户明细：``交易时间 / 收支类型 / 交易类型 / 明细名称 / 金额 / 单号 / …``
* 支付宝交易记录明细：``交易时间 / 交易分类 / 交易对方 / 对方账号 / 商品说明 / 收/支 / 金额 / …``

三类账单在数据区之前都有一大段说明行（昵称、起止时间、统计摘要），故先在前
``_HEADER_SCAN_ROWS`` 行里找出「同时含时间列与金额列」的那一行当表头，再按列名映射
取值，绝不按列序号硬取——支付宝与微信的列序并不相同。

只认收入（``收/支`` 或 ``收支类型`` 为 收入/收/入账），退款、支出、不计收支一律跳过。

榜单口径（用户 2026-10-26 需求）：

* 新人榜：**最新的 10 个捐助者**，按时间倒序。
* 土豪榜：**捐助金额最大的 10 个人**，按金额倒序。
* 两个榜都按「捐助者」去重：同一个人多次捐助时，新人榜留他最近的一笔、土豪榜留他
  金额最大的一笔（用户原话既说「10 笔捐款」又说「10 个人」，去重后取代表笔同时满足
  两种说法，且不会出现同一个人占满整榜）。

记录落盘成 ``resources/donate_records.json``（随包分发，**所有人**都能在赞助窗口看到），
导入时另写一份 ``userdata/donate_records.json``——打包运行时 ``resources`` 在
``_MEIPASS`` 临时目录里、重启即失效，用户数据目录那份才是本机即时生效的副本。
读取时两份取并集（按 姓名+时间+金额 去重），故作者本机导入后立刻能看到，发布后
所有用户也能看到随包的那份。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RECORDS_FILENAME = "donate_records.json"
RECORDS_VERSION = 1

# 表头最多扫这么多行（微信/支付宝账单的说明区通常 10~20 行）
_HEADER_SCAN_ROWS = 80

# 列名别名（归一化后精确匹配；金额列额外允许「金额(元)」这类带单位写法）
_TIME_ALIASES = ("交易时间", "创建时间", "付款时间", "入账时间", "发生时间", "记账时间", "时间")
_AMOUNT_ALIASES = ("金额", "金额(元)", "金额(人民币)", "发生金额", "交易金额", "收支金额")
_DIR_ALIASES = ("收/支", "收支", "收支类型", "资金方向", "借贷标志", "收支方向")
_PARTY_ALIASES = ("交易对方", "对方", "付款方", "商户名称", "对方名称", "交易对象")
_DETAIL_ALIASES = ("明细名称", "商品", "商品说明", "商品名称", "备注", "交易说明")
_KIND_ALIASES = ("交易类型", "交易分类", "业务类型")
_STATUS_ALIASES = ("当前状态", "交易状态", "状态", "订单状态")

_INCOME_WORDS = ("收入", "收", "入账", "已收入", "转入")
_EXPENSE_WORDS = ("支出", "支", "出账", "借", "不计收支", "不计入收支")
_REFUND_WORDS = ("退款", "退回", "已退", "全额退")

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日 %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日",
)

_AMOUNT_STRIP = "¥￥$,， 元\t\r\n"

# 用命名元组而不是 `except (A, B):`：ruff 0.17.2 的 formatter 会把括号形式改写成
# Python 2 的 `except A, B:`（本仓 3.15 下语法虽合法，但格式会被反复改写）。
_READ_ERRORS = (OSError, ValueError)
_NUMBER_ERRORS = (TypeError, ValueError)


class BillImportError(Exception):
    """账单无法解析时抛出（调用方负责弹提示，不要把堆栈甩给用户）。"""


@dataclass(frozen=True)
class DonationRecord:
    """一笔捐助：捐助者、时间（ISO 形态的字符串）、金额（元）。"""

    name: str
    time: str
    amount: float

    def as_dict(self) -> dict:
        return {"name": self.name, "time": self.time, "amount": round(self.amount, 2)}

    @classmethod
    def from_dict(cls, raw: object) -> DonationRecord | None:
        """宽松解析：脏数据直接丢弃，不让一条坏记录拖垮整个榜单。"""
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        time_text = str(raw.get("time") or "").strip()
        try:
            amount = float(raw.get("amount") or 0)
        except _NUMBER_ERRORS:
            return None
        if not name or amount <= 0:
            return None
        return cls(name=name, time=time_text, amount=amount)


# --------------------------------------------------------------------- 单元格解析


def _norm_header(value: object) -> str:
    """表头归一化：去空白/全角空格，全角括号转半角。"""
    text = str(value or "")
    for src, dst in (("\u3000", ""), (" ", ""), ("（", "("), ("）", ")"), ("\n", "")):
        text = text.replace(src, dst)
    return text.strip()


def _parse_amount(value: object) -> float:
    """金额单元格 → float；无法解析返回 0。"""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    text = str(value or "")
    for ch in _AMOUNT_STRIP:
        text = text.replace(ch, "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        # 「100.00元(已退款)」这类尾巴：抓第一个数字
        matched = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(matched.group()) if matched else 0.0


def _parse_time(value: object) -> str:
    """时间单元格 → ``YYYY-MM-DD HH:MM:SS``；解析不了就原样返回（榜单仍可展示）。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def _is_income(value: str) -> bool:
    """``收/支`` 或 ``收支类型`` 的值是否算收入。

    「不计收支」同时含「收」「支」两字，必须先判掉，否则会被当成收入。
    """
    text = value.strip()
    if not text:
        return True  # 该行没填方向：账单里罕见，按收入收下，宁可多算不漏
    if "不计" in text:
        return False
    if any(word in text for word in _REFUND_WORDS):
        return False
    if text in _EXPENSE_WORDS:
        return False
    return text in _INCOME_WORDS or "收入" in text or "入账" in text


def _pick_name(detail: str, party: str) -> str:
    """捐助者名：优先「明细名称」里「来自 xxx」的尾巴（经营账户账单的写法）。"""
    text = detail.strip()
    if "来自" in text:
        tail = text.rsplit("来自", 1)[1].strip()
        if tail:
            return tail
    party = party.strip()
    if party and party not in {"/", "-"}:
        return party
    return "匿名"


# --------------------------------------------------------------------- 表头定位


def _header_map(row: tuple) -> dict[str, int]:
    """把一行表头映射成 {字段: 列号}；不是表头行就返回空字典。"""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        name = _norm_header(cell)
        if not name:
            continue
        if "time" not in mapping and name in _TIME_ALIASES:
            mapping["time"] = index
        elif "amount" not in mapping and (name in _AMOUNT_ALIASES or name.startswith("金额")):
            mapping["amount"] = index
        elif "dir" not in mapping and name in _DIR_ALIASES:
            mapping["dir"] = index
        elif "party" not in mapping and name in _PARTY_ALIASES:
            mapping["party"] = index
        elif "detail" not in mapping and name in _DETAIL_ALIASES:
            mapping["detail"] = index
        elif "kind" not in mapping and name in _KIND_ALIASES:
            mapping["kind"] = index
        elif "status" not in mapping and name in _STATUS_ALIASES:
            mapping["status"] = index
    if "time" in mapping and "amount" in mapping:
        return mapping
    return {}


def _cell(row: tuple, mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()


def parse_bill_rows(rows) -> list[DonationRecord]:
    """从二维行数据里抽捐助记录（供 xlsx / 测试共用，不依赖 openpyxl）。"""
    mapping: dict[str, int] = {}
    records: list[DonationRecord] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, tuple | list):
            continue
        if not mapping:
            if row_index < _HEADER_SCAN_ROWS:
                mapping = _header_map(tuple(row))
            continue
        time_text = _parse_time(row[mapping["time"]] if mapping["time"] < len(row) else "")
        if not time_text:
            continue  # 数据区里的空行 / 合计行
        kind = _cell(tuple(row), mapping, "kind")
        status = _cell(tuple(row), mapping, "status")
        if any(word in kind + status for word in _REFUND_WORDS):
            continue  # 退款不是捐助
        if not _is_income(_cell(tuple(row), mapping, "dir")):
            continue
        amount = _parse_amount(row[mapping["amount"]] if mapping["amount"] < len(row) else "")
        if amount <= 0:
            continue
        name = _pick_name(_cell(tuple(row), mapping, "detail"), _cell(tuple(row), mapping, "party"))
        records.append(DonationRecord(name=name, time=time_text, amount=round(amount, 2)))
    if not mapping:
        raise BillImportError("没找到账单表头（需要同时含「交易时间」和「金额」两列）")
    return records


def parse_bill(path: str | Path) -> list[DonationRecord]:
    """解析一个 xlsx 账单文件（第一个含表头的工作表）。"""
    try:
        import openpyxl
    except ImportError as exc:  # 打包缺 openpyxl 时给一句人话
        raise BillImportError("缺少 openpyxl 模块，无法读取 xlsx 账单") from exc

    file_path = Path(path)
    if not file_path.exists():
        raise BillImportError(f"账单文件不存在：{file_path}")
    try:
        workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        raise BillImportError(f"无法打开账单文件：{exc}") from exc
    try:
        for sheet in workbook.worksheets:
            rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
            try:
                return parse_bill_rows(rows)
            except BillImportError:
                continue
        raise BillImportError("账单里没有可识别的工作表（需要「交易时间」「金额」列）")
    finally:
        workbook.close()


# --------------------------------------------------------------------- 榜单


def newcomer_rank(records: list[DonationRecord], limit: int = 10) -> list[DonationRecord]:
    """新人榜：最新捐助的 ``limit`` 个捐助者，时间倒序（同一人只留最近一笔）。"""
    best: dict[str, DonationRecord] = {}
    for record in records:
        current = best.get(record.name)
        if current is None or record.time > current.time:
            best[record.name] = record
    return sorted(best.values(), key=lambda item: item.time, reverse=True)[:limit]


def tycoon_rank(records: list[DonationRecord], limit: int = 10) -> list[DonationRecord]:
    """土豪榜：金额最大的 ``limit`` 个捐助者，金额倒序（同一人只留最大一笔）。"""
    best: dict[str, DonationRecord] = {}
    for record in records:
        current = best.get(record.name)
        if current is None or record.amount > current.amount:
            best[record.name] = record
    return sorted(best.values(), key=lambda item: (-item.amount, item.time))[:limit]


# --------------------------------------------------------------------- 落盘


def _records_paths() -> tuple[Path, Path]:
    """(随包资源路径, 用户数据路径)。"""
    from ..config.resources import resources

    return Path(resources.r(RECORDS_FILENAME)), Path(resources.u(RECORDS_FILENAME))


def _read_records_file(path: Path) -> list[DonationRecord]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except _READ_ERRORS:
        return []
    items = raw.get("records") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    records: list[DonationRecord] = []
    for item in items:
        record = DonationRecord.from_dict(item)
        if record is not None:
            records.append(record)
    return records


def merge_records(*groups: list[DonationRecord]) -> list[DonationRecord]:
    """多份记录取并集（姓名+时间+金额 相同即视为同一笔），按时间升序稳定排列。"""
    seen: set[tuple[str, str, float]] = set()
    merged: list[DonationRecord] = []
    for group in groups:
        for record in group:
            key = (record.name, record.time, round(record.amount, 2))
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
    merged.sort(key=lambda item: (item.time, item.name, item.amount))
    return merged


def load_records() -> list[DonationRecord]:
    """读赞助榜单记录：随包资源 + 本机用户数据，取并集。"""
    bundled, local = _records_paths()
    return merge_records(_read_records_file(bundled), _read_records_file(local))


def save_records(records: list[DonationRecord]) -> Path:
    """写榜单记录，返回真正写成功的那份路径。

    优先写随包 ``resources/donate_records.json``（源码运行 / 作者本机，提交后即
    对所有用户生效）；该目录不可写（打包运行时 ``_MEIPASS`` 只读）时退回用户数据
    目录。两份都尝试写，哪份成功用哪份——打包后随包那份本来就改不了。
    """
    payload = {
        "version": RECORDS_VERSION,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "records": [record.as_dict() for record in records],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    bundled, local = _records_paths()
    written: Path | None = None
    for path in (bundled, local):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written = written or path
        except OSError:
            continue
    if written is None:
        raise BillImportError("账单记录写入失败（资源目录与用户数据目录都不可写）")
    return written


def format_amount(amount: float) -> str:
    """榜单金额展示：``¥1,234.00``。"""
    return f"¥{amount:,.2f}"


def format_rank_time(time_text: str, now: datetime | None = None) -> str:
    """榜单日期展示：今年的记录省掉年份（``10-25 20:23``），跨年的保留完整日期。

    赞助窗口的「日期时间」列只有 94 逻辑像素宽、字号 13px，``2026-10-25 20:23:18``
    这种 19 字全写会被 Qt 省略成「2026-10-25 20:2…」（本窗口明确要求日期列不省略）。
    实测 13px 下 ``10-25 20:23`` 约 68px、``2026-10-25`` 约 81px，都在列宽内；
    完整时间仍留在单元格 tooltip 里。
    """
    parsed = _parse_time(time_text)
    try:
        moment = datetime.strptime(parsed, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return parsed[:16]
    if moment.year == (now or datetime.now()).year:
        return moment.strftime("%m-%d %H:%M")
    return moment.strftime("%Y-%m-%d")
