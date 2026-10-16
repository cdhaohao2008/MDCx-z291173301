"""演员数据导出为 xlsx（不依赖 Qt，可单测）。

列顺序与管理器表格一致（状态/姓名/头像/简介/出生日期/出生地/详情/标签/影片数）::

    状态 | 姓名 | 头像 | 简介 | 出生日期 | 出生地 | 详情 | 标签 | 影片数

- 状态：``actor.status_icon`` 原值（✅/❌/⚠️），与管理器表格第一列一致；
  其中 ⚠️ 左侧补一个空格（见 ``EXPORT_WARN_STATUS_PAD``），使其与 ✅/❌ 上下对齐；
- 头像：有头像 ✅，否则 ❌；
- 简介：按 :func:`is_missing_overview` 判定（占位简介按缺处理），有简介 ✅，否则 ❌；
- 详情：与表格同口径清洗（去 ``<br>``/残留标签/``(无)``/``=`` 装饰线、空白坍缩），
  但**不做 80 字截断**——导出是数据落盘，截断会丢信息；
- 出生日期：``YYYY-MM-DD`` 写成 Excel 日期类型（样例中为日期型单元格），
  ``0001-01-01``（Emby 未设置零值）与非法值按空值导出；
- 出生地/标签：全量现有值，以全角 ``，`` 连接（注意表格里标签只展示前两条）；
- 影片数：``actor.movie_count`` 原值（整数），与管理器表格第九列一致；
- 样式：全表宋体 11pt，对齐方式
  （状态/姓名/头像/简介/出生日期/影片数居中，出生地/详情/标签居左，纵向全部居中）。
- 列宽（均为 WPS 里看到的显示值）：状态/头像/简介三列 5.44；姓名 18；出生日期 12，
  完整展示 ``1958-04-29`` 这类日期（不出现 ``###``）的前提下尽量收窄；
  出生地 36；影片数 8（标签右侧）；
  详情/标签两列平分扣除上述固定列宽后的剩余列宽：调用方按用户屏幕实际宽度
  算出可分配宽度后传入（见 :func:`text_col_width_for_screen_width`），
  缺省时按总表宽 260 均分；I 列之后的列（J:XFD）全部隐藏，表总宽不变、
  默认占满整个可用列宽。写入 xlsx 时每个显示列宽都要再加
  ``WPS_COLUMN_WIDTH_OFFSET``，否则 WPS 会把同一份文件读小约 0.78
  （见该常量的实测说明）。
- 首行表头冻结（``A2``），向下滚动时状态/姓名/头像/简介/出生日期/出生地/详情/标签/影片数
  始终置顶显示。
"""

from __future__ import annotations

import datetime as _datetime
import re
from pathlib import Path

from ..models.emby import clean_overview_text
from .emby_actor_manager import is_missing_overview

EXPORT_HEADERS: tuple[str, ...] = ("状态", "姓名", "头像", "简介", "出生日期", "出生地", "详情", "标签", "影片数")
"""导出表头，从左到右的列顺序，与管理器表格九列一致。"""

EXPORT_FILENAME_PREFIX = "演员数据表"
"""导出文件名固定前缀，形如 ``演员数据表2026-10-12 13-52-01.xlsx``。"""

EXPORT_FILENAME_TIME_FORMAT = "%Y-%m-%d %H-%M-%S"
"""文件名时间部分格式（冒号换成连字符，Windows 文件名不允许冒号）。"""

EXPORT_DATE_NUMBER_FORMAT = "[$-409]yyyy\\-mm\\-dd;@"
"""出生日期列的 Excel 数字格式，与用户样例文件的实测格式一致。"""

EXPORT_FONT_NAME = "宋体"
EXPORT_FONT_SIZE = 11

EXPORT_WARN_STATUS_PAD = " "
"""状态列 ⚠️ 左侧补的空格（一个半角空格），使其与 ✅/❌ 上下对齐。

居中对齐下，前导空格会把可见字形向右推半个空格宽。注意：WPS 会把前后带空格的
单元格标绿三角警告（“可能导致计算结果出错”），此前补两个空格时已触发过一次；
现按要求减为一个，若 WPS 仍警告只能去掉（对齐与警告不可兼得）。
"""

EXPORT_ICON_COL_WIDTH = 5.44
"""状态/头像/简介三列列宽。"""

EXPORT_NAME_COL_WIDTH = 18
"""姓名列（B）固定列宽。"""

EXPORT_BIRTHPLACE_COL_WIDTH = 36
"""出生地列（F）固定列宽。"""

EXPORT_MOVIE_COL_WIDTH = 8
"""影片数列（I，标签右侧）固定列宽。"""

EXPORT_BIRTHDAY_COL_WIDTH = 12
"""出生日期列宽：完整展示 ``1958-04-29`` 这类日期（不出现 ``###``）的前提下尽量收窄。"""

WPS_COLUMN_WIDTH_OFFSET = 0.78
"""写入 xlsx 时的列宽补偿：让 WPS 显示值正好等于上面的显示列宽。

2026-10-17 用本机 ``ET.Application`` COM 实测：openpyxl 按显示值写入时，
WPS 读出的列宽统一小约 0.78（5.44→4.67、18→17.22、12→11.22、36→35.22、
8→7.22）；把写入值统一加 0.78 后，WPS 读数回到 5.44/18/12/36/8，
详情/标签两列也回到均分值。此处只补偿 WPS 的显示口径，文件本身仍是标准 xlsx。
"""


def _wps_stored_column_width(display_width: float) -> float:
    """把 WPS 显示列宽换算成 xlsx 里实际要写入的列宽。"""
    return display_width + WPS_COLUMN_WIDTH_OFFSET

EXPORT_TABLE_WIDTH = 260
"""导出表总宽（WPS 显示列宽单位）。详情/标签两列按 1:1 平分扣除出生日期列、
状态/头像/简介三列、姓名列、出生地列与影片数列后的剩余宽度，
把表右侧的大片空白默认摊进这两列，表总宽不变、默认占满整个可用列宽。"""

EXPORT_TEXT_COL_WIDTH = (
    EXPORT_TABLE_WIDTH
    - EXPORT_BIRTHDAY_COL_WIDTH
    - 3 * EXPORT_ICON_COL_WIDTH
    - EXPORT_NAME_COL_WIDTH
    - EXPORT_BIRTHPLACE_COL_WIDTH
    - EXPORT_MOVIE_COL_WIDTH
) / 2
"""详情/标签两列的均分列宽（无屏幕信息时的缺省值）。"""

SCREEN_ROW_HEADER_PX = 41
"""表格左侧序号列宽（像素，Excel/WPS 默认行号列宽）。"""

SCREEN_VSCROLL_PX = 17
"""表格右侧垂直滚动条宽（像素，Windows 标准滚动条宽）。"""

EXCEL_UNIT_PX = 7
"""一个 Excel 列宽单位约等于的像素数（Calibri 11 下数字 `0` 宽）。"""

EXPORT_COLUMN_COUNT = 9
"""导出表列数（状态/姓名/头像/简介/出生日期/出生地/详情/标签/影片数）。"""

EXCEL_TABLE_PADDING_PX = 5
"""每列列宽自带的内边距（像素）。Excel/WPS 把列宽换算成像素时，每列都要加约 5px
（九列共 45px），而不是整表只加一次。此前按整表 5px 算，少算了 40px，
在 1920@125% 下表格实际比算出来的宽约 50 物理像素，I 列（影片数）右边缘
被垂直滚动条盖住约 37px（2026-10-17 本机 WPS 截屏实测：表宽 1896px，
可用网格 1859px）。"""

EXPORT_TABLE_MARGIN_PX = 48
"""表右侧安全边距（像素）。表总宽与视口严丝合缝时，Office/WPS 自身的边框差异
（网格线、皮肤滚动条、窗口边框等）会把 I 列挤出视口；留出该边距保证九列默认
一屏放下，无需横向滚动。"""

EXPORT_MIN_TEXT_COL_WIDTH = 10.0
"""详情/标签两列的最小列宽，小屏兜底不压成 0。"""

EXPORT_FALLBACK_SCREEN_PX = 1536.0
"""取不到屏幕信息时的兜底逻辑宽度（1920 物理像素 @125% 缩放）。"""


def _windows_system_scale() -> float | None:
    """Windows 系统缩放比（如 125% → 1.25），Qt 侧拿不到时才用它。

    本应用跑在 DPI-unaware 模式时，Qt 上报的 ``devicePixelRatio`` 与逻辑 DPI
    都是 1.0/96（实际拿到的是物理像素），此时只能走 Win32 API 取真实系统 DPI。
    非 Windows 或调用失败时返回 None。
    """
    try:
        import ctypes

        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return None
        try:
            dpi = user32.GetDpiForSystem()
            if dpi and dpi > 0:
                return float(dpi) / 96.0
        except (AttributeError, OSError):
            pass
        try:
            gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
            hdc = user32.GetDC(0)
            if hdc:
                try:
                    dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                    if dpi and dpi > 0:
                        return float(dpi) / 96.0
                finally:
                    user32.ReleaseDC(0, hdc)
        except (AttributeError, OSError):
            pass
    except Exception:
        pass
    return None


def effective_screen_width_px(screen: object) -> float:
    """用户屏幕逻辑宽度（像素）= 物理宽度 / Windows 缩放比。

    例如 1920 物理像素 @125% 缩放 → 1536；其他分辨率同理（`物理宽 / 缩放比`）。
    兼容三种刻度来源：Qt 高分屏缩放开时 ``availableGeometry`` 已是逻辑像素，
    关时（本应用现状：DPI-unaware）拿到的是物理像素且 Qt 侧刻度全为 1.0——
    此时改走 Win32 系统 DPI 取真实缩放比。统一按“物理宽 / 缩放比”换算——
    物理宽 = 逻辑宽 × ``devicePixelRatio``，缩放比取 Qt 侧与 Win32 侧的较大者，
    各模式都收敛到同一逻辑宽度。取不到时兜底 1536。
    """
    try:
        raw = float(screen.availableGeometry().width())  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError, RuntimeError):
        return EXPORT_FALLBACK_SCREEN_PX
    try:
        dpr = float(screen.devicePixelRatio()) or 1.0  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError, RuntimeError):
        dpr = 1.0
    try:
        dpi_scale = float(screen.logicalDotsPerInchX()) / 96.0  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError, RuntimeError, ZeroDivisionError):
        dpi_scale = 1.0
    win_scale = _windows_system_scale() or 0.0
    scale = max(dpr, dpi_scale, win_scale)
    if scale <= 0:
        return raw
    return raw * dpr / scale


def text_col_width_for_screen_width(screen_px: object) -> float:
    """按用户屏幕实际宽度算出详情/标签两列的均分列宽。

    公式：先扣除左侧序号列、右侧滚动条（Office/WPS 都会占用这部分宽度）与
    表右侧安全边距，剩下按列宽单位换算后，再扣除出生日期列、状态/头像/简介
    三列、姓名列、出生地列与影片数列固定列宽，剩余均分给两列。非法输入/小屏时兜底为最小列宽。
    """
    try:
        width_px = float(screen_px)
    except (TypeError, ValueError):
        return EXPORT_MIN_TEXT_COL_WIDTH
    content_px = width_px - SCREEN_ROW_HEADER_PX - SCREEN_VSCROLL_PX - EXPORT_TABLE_MARGIN_PX
    total_units = (content_px - EXPORT_COLUMN_COUNT * EXCEL_TABLE_PADDING_PX) / EXCEL_UNIT_PX
    text_width = (
        total_units
        - EXPORT_BIRTHDAY_COL_WIDTH
        - 3 * EXPORT_ICON_COL_WIDTH
        - EXPORT_NAME_COL_WIDTH
        - EXPORT_BIRTHPLACE_COL_WIDTH
        - EXPORT_MOVIE_COL_WIDTH
    ) / 2
    return max(EXPORT_MIN_TEXT_COL_WIDTH, text_width)

# 新列顺序下居中：状态/姓名/头像/简介/出生日期/影片数居中，出生地/详情/标签居左。
_EXPORT_CENTER_COLS = frozenset((0, 1, 2, 3, 4, 8))

_UNSET_BIRTHDAY = "0001-01-01"
"""Emby 未设置生日时的零值，展示与导出时都按空值处理。"""

_BIRTHDAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def export_filename(now: _datetime.datetime | None = None) -> str:
    """返回 ``演员数据表<时间>.xlsx`` 形式的文件名。"""
    ts = (now or _datetime.datetime.now()).strftime(EXPORT_FILENAME_TIME_FORMAT)
    return f"{EXPORT_FILENAME_PREFIX}{ts}.xlsx"


def resolve_export_dir(config_value: object) -> Path | None:
    """校验设置里的导出目录，合法目录返回 Path，否则返回 None（调用方弹框让用户重选）。"""
    if not isinstance(config_value, str):
        return None
    path = Path(config_value.strip())
    if not config_value.strip() or not path.is_dir():
        return None
    return path


def actor_status_icon(actor: object) -> str:
    """状态列：直接复用 ActorInfo.status_icon（✅/❌/⚠️），与表格第一列同值。"""
    icon = getattr(actor, "status_icon", None)
    if isinstance(icon, str) and icon:
        return icon
    # 兜底：按“有头像且有简介完整”口径推导，与 status_icon 实现一致。
    has_image = bool(getattr(actor, "has_image", False))
    missing_info = bool(is_missing_overview(actor))  # type: ignore[arg-type]
    if has_image and not missing_info:
        return "✅"
    if not has_image and missing_info:
        return "❌"
    return "⚠️"


def actor_detail_text(actor: object) -> str:
    """详情列全文：与表格展示同口径清洗，但不做 80 字截断（落盘不丢信息）。

    缺简介（含占位简介）时先经 clean_overview_text 去占位残留，与
    ``_populate_table`` 的缺简介分支一致；``<br>``/残留标签/``(无)``/``=`` 装饰线
    的处理与 ``format_detail_cell_text`` 一致。
    """
    existing = getattr(actor, "existing_overview", "") or ""
    if not isinstance(existing, str):
        return ""
    if is_missing_overview(actor):  # type: ignore[arg-type]
        existing = clean_overview_text(existing)
    t = existing.strip()
    if not t or t in ("(无)", "（无）", "无"):
        return ""
    t = re.sub(r"(?i)<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]*>", "", t)
    t = re.sub(r"(?i)<br\s*/?", " ", t)
    t = re.sub(r"<[^>]*$", "", t)
    for token in ("(无)", "（无）"):
        t = t.replace(token, "")
    t = re.sub(r"={2,}", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or t in ("(无)", "（无）"):
        return ""
    return t


def actor_birthday_cell(actor: object) -> _datetime.datetime | str:
    """出生日期单元格：``YYYY-MM-DD`` 返回 datetime（Excel 日期型），否则原样/空串。

    ``0001-01-01``（Emby 未设置零值）按空值导出，与表格展示一致。
    """
    raw = (getattr(actor, "existing_premiere_date", "") or "")[:10]
    if not raw or raw.startswith(_UNSET_BIRTHDAY):
        return ""
    match = _BIRTHDAY_RE.match(raw)
    if not match:
        return raw
    try:
        return _datetime.datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return raw


def actor_export_row(actor: object) -> tuple:
    """单个演员的导出数据行，顺序与 EXPORT_HEADERS 对应（状态/姓名/头像/简介/出生日期/出生地/详情/标签/影片数）。"""
    name = getattr(actor, "name", "") or ""
    detail = actor_detail_text(actor)
    birthday = actor_birthday_cell(actor)
    locations = getattr(actor, "existing_production_locations", None) or []
    birthplace = "，".join(str(v).strip() for v in locations if str(v).strip())
    taglines = getattr(actor, "existing_taglines", None) or []
    tags = "，".join(str(v).strip() for v in taglines if str(v).strip())
    image_icon = "✅" if getattr(actor, "has_image", False) else "❌"
    info_icon = "❌" if is_missing_overview(actor) else "✅"  # type: ignore[arg-type]
    status = actor_status_icon(actor)
    if status == "⚠️":
        status = f"{EXPORT_WARN_STATUS_PAD}{status}"
    try:
        movie_count = int(getattr(actor, "movie_count", 0) or 0)
    except (TypeError, ValueError):
        movie_count = 0
    return (status, name, image_icon, info_icon, birthday, birthplace, detail, tags, movie_count)


def build_export_rows(actors: list) -> list[tuple]:
    """全体演员的导出数据行（不含表头）。"""
    return [actor_export_row(a) for a in (actors or [])]


def write_actor_export_xlsx(
    file_path: str | Path, actors: list, text_col_width: float | None = None
) -> Path:
    """写出演员数据 xlsx，返回落盘路径。样式对齐用户样例文件。

    Args:
        file_path: 落盘路径（无 .xlsx 后缀时自动补）。
        actors: 演员列表。
        text_col_width: 详情/标签两列列宽，为 None 时用缺省均分值。
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font

    path = Path(file_path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    text_width = text_col_width if text_col_width else EXPORT_TEXT_COL_WIDTH
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    # 首行冻结：向下滚动时表头始终置顶显示。
    ws.freeze_panes = "A2"
    # 列宽：下面是 WPS 显示目标值，实际写入时每个都要加 WPS 显示补偿；
    # 状态/头像/简介（A/C/D）5.44，姓名（B）18，出生日期（E）12，
    # 出生地（F）36，影片数（I，标签右侧）8，详情/标签（G/H）平分剩余列宽，
    # 表总宽不变、默认占满整个可用列宽。
    stored_text_width = _wps_stored_column_width(text_width)
    for col_letter, width in (
        ("A", _wps_stored_column_width(EXPORT_ICON_COL_WIDTH)),
        ("B", _wps_stored_column_width(EXPORT_NAME_COL_WIDTH)),
        ("C", _wps_stored_column_width(EXPORT_ICON_COL_WIDTH)),
        ("D", _wps_stored_column_width(EXPORT_ICON_COL_WIDTH)),
        ("E", _wps_stored_column_width(EXPORT_BIRTHDAY_COL_WIDTH)),
        ("F", _wps_stored_column_width(EXPORT_BIRTHPLACE_COL_WIDTH)),
        ("G", stored_text_width),
        ("H", stored_text_width),
        ("I", _wps_stored_column_width(EXPORT_MOVIE_COL_WIDTH)),
    ):
        ws.column_dimensions[col_letter].width = width
    # I 列之后的列（J:XFD）全部隐藏，表右侧不再出现空白列。
    ws.column_dimensions.group("J", "XFD", hidden=True)
    font = Font(name=EXPORT_FONT_NAME, size=EXPORT_FONT_SIZE)
    for col, header in enumerate(EXPORT_HEADERS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row_idx, row in enumerate(build_export_rows(actors), start=2):
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = font
            horizontal = "center" if (col_idx - 1) in _EXPORT_CENTER_COLS else "left"
            cell.alignment = Alignment(horizontal=horizontal, vertical="center")
            if col_idx == 5 and isinstance(value, _datetime.datetime):
                cell.number_format = EXPORT_DATE_NUMBER_FORMAT
    wb.save(path)
    return path
