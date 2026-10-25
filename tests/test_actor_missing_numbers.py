"""「检查演员缺失番号」的番号归一化与缺失表输出。

站点返回的番号形态五花八门（DMM 的 `ssis00006`、JavDB 的 `SSIS-006`、
FC2 的 `FC2-PPV-1234567`），必须先归一化再和本地 number_list 比；
缺失表按用户样表：三列（番号/网站/链接地址），番号与网站居中、链接靠左，
列宽 8.8 / 11 / 100，番号 A-Z 排列。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from openpyxl.utils import get_column_letter

from mdcx.tools.actor_sources import NumberHit, display_number, extract_numbers, normalize_key
from mdcx.tools.missing import (
    _excel_target,
    _parse_actor_entry,
    _write_missing_excel,
    apply_forced_type,
    resolve_forced_type,
    split_single_actor,
)

_UI_PATH = Path(__file__).resolve().parent.parent / "mdcx" / "views" / "MDCx.ui"


def _combo_item_texts(widget_name: str) -> list[str]:
    """从 .ui 里取指定 QComboBox 的选项文案（顺序即界面顺序）。"""
    ui_src = _UI_PATH.read_text(encoding="utf-8")
    idx = ui_src.index(f'name="{widget_name}"')
    start = ui_src.rindex("<widget ", 0, idx)
    block = ui_src[start : ui_src.index("</widget>", idx)]
    return re.findall(r"<item>\s*<property name=\"text\">\s*<string>([^<]*)</string>", block)


def test_tool_actor_type_combo_reuses_fixed_type_options() -> None:
    """工具页「类型」下拉框 = 锁定类型的八项去掉「国产短剧」，顺序一致。

    国产短剧多为 AI 生成、没有演员，按演员名查不到东西，故不进这个下拉框。
    """
    from mdcx.config.enums import FixedScrapingType

    combo = _combo_item_texts("comboBox_actor_type")
    assert combo == [name for name in FixedScrapingType.names() if name != "国产短剧"]
    assert combo[0] == "自动判断"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("自动判断", ""),
        ("有码番号", "有码"),
        ("无码番号", "无码"),
        ("个摄番号", "FC2"),
        ("欧美视频", "欧美"),
        ("国产传媒", "国产"),
        ("动漫里番", "动漫"),
        ("", ""),
        ("不认识的类型", ""),
    ],
)
def test_resolve_forced_type(label: str, expected: str) -> None:
    assert resolve_forced_type(label) == expected


def test_apply_forced_type_overrides_actor_tags() -> None:
    entries = [_parse_actor_entry("三上悠亚"), _parse_actor_entry("水菜麗(无码)")]
    # 自动判断：保留名字后的标注
    assert apply_forced_type(entries, "自动判断") == [("三上悠亚", "有码"), ("水菜麗", "无码")]
    # 选了具体类型：全部按该类型查
    assert apply_forced_type(entries, "欧美视频") == [("三上悠亚", "欧美"), ("水菜麗", "欧美")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SSIS-006", "SSIS6"),
        ("ssis006", "SSIS6"),
        ("SSIS 006", "SSIS6"),
        ("SSIS-00006", "SSIS6"),
        ("ssis_006", "SSIS6"),
        ("FC2-PPV-1234567", "FC21234567"),
        ("FC2-1234567", "FC21234567"),
        ("fc2ppv1234567", "FC21234567"),
    ],
)
def test_normalize_key_folds_site_variants(raw: str, expected: str) -> None:
    assert normalize_key(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ssis00006", "SSIS-006"),
        ("SSIS_006", "SSIS-006"),
        ("SSIS-00006", "SSIS-006"),
        ("fc2 ppv 1234567", "FC2-1234567"),
        ("FC2-PPV-1234567", "FC2-1234567"),
        ("1pondo_123456_001", "1PONDO-123456-001"),
        ("", ""),
    ],
)
def test_display_number(raw: str, expected: str) -> None:
    assert display_number(raw) == expected


def test_extract_numbers_from_title() -> None:
    assert extract_numbers("【中文字幕】MDX-0236 某标题 1080P") == ["MDX-236"]
    assert extract_numbers("FC2-PPV-1234567 无码流出") == ["FC2-1234567"]
    assert extract_numbers("没有番号的标题") == []
    # 字母段后无分隔符时数字至少 3 位：`JN4286` 是番号，`SKE48`/`AKB48` 是团体名
    assert extract_numbers("马赛克破坏版 三上悠亚 第三部 JN4286") == ["JN-4286"]
    assert extract_numbers("SKE48的三上悠亚大玩3P Princess Peach TEK-067") == ["TEK-067"]
    assert extract_numbers("AKB48 合集") == []
    assert extract_numbers("乃木坂46 特辑") == []


def test_extract_numbers_require_separator_for_iqqtv() -> None:
    """IQQTV 只认标准「字母-数字」：自造编号 JN4286 不取，TEK-067 照取。"""
    title = "马赛克破坏版 三上悠亚 第三部 JN4286"
    assert extract_numbers(title) == ["JN-4286"]
    assert extract_numbers(title, require_separator=True) == []
    assert extract_numbers("SKE48的三上悠亚大玩3P TEK-067", require_separator=True) == ["TEK-067"]
    assert extract_numbers("MD-096 某标题", require_separator=True) == ["MD-096"]


def test_split_single_actor() -> None:
    """「只获取单演员」：演员表 ≥2 人算多演员；没给演员表的按单演员放行。"""
    rows = [
        NumberHit("A-001", "DMM_API", "", actors="三上悠亜"),
        NumberHit("A-002", "DMM_API", "", actors="三上悠亜,鬼头桃菜"),
        NumberHit("A-003", "JavDB", "", actors=""),
    ]
    single, multi = split_single_actor(rows)
    assert [hit.number for hit in single] == ["A-001", "A-003"]
    assert [hit.number for hit in multi] == ["A-002"]


def test_auto_site_chains_match_user_spec() -> None:
    """自动判断用的固定站点链（用户 2026-10-25 定稿，顺序即优先级）。"""
    from mdcx.tools.actor_sources import build_sources

    expected = {
        "有码": [
            "DMM",
            "DMM_API",
            "LibreDMM",
            "JavDB",
            "JavDB_API",
            "JavDB_APP",
            "Javlibrary·镜像",
            "JavLibrary",
            "JavBus",
            "IQQTV",
        ],
        "无码": ["AVSOX", "JavDB", "JavDB_API", "JavDB_APP"],
        "FC2": ["AVSOX", "FC2", "FC2PPVDB", "JavDB", "JavDB_API", "JavDB_APP"],
        "欧美": ["AVheat", "ThepornDB", "JavDB", "JavDB_API", "JavDB_APP"],
        "国产": ["IQQTV", "Madou.club", "Madouqu", "JavDay"],
        "动漫": ["JavDB_APP", "Getchu"],
    }
    for actor_type, sites in expected.items():
        sources, _skipped = build_sources(actor_type, use_config_sites=False)
        assert [source.site for source in sources] == sites, actor_type


def test_config_sites_ignore_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """指定类型时用「类型刮削网站」那一组，组内被禁用的站点照样参与。"""
    from mdcx.config.manager import manager
    from mdcx.config.models import Website
    from mdcx.tools.actor_sources import build_sources

    monkeypatch.setattr(manager.config, "website_youma", [Website.JAVBUS, Website.DMM])
    monkeypatch.setattr(manager.config, "website_disabled", [Website.JAVBUS, Website.DMM])
    sources, _skipped = build_sources("有码", use_config_sites=True)
    assert [source.site for source in sources] == ["JavBus", "DMM"]


def test_write_missing_excel_layout(tmp_path: Path) -> None:
    """七列表 + 表头居中 + 数据行链接靠左 + 列宽 13/13/13/13/13/13/100 + 日期是日期型。"""
    from openpyxl import load_workbook

    rows = [
        NumberHit(
            "EHM-001",
            "DMM_API",
            "https://video.dmm.co.jp/av/content/?id=h_295ehm00001",
            actors="三上悠亜,鬼头桃菜",
            release="2016-12-29",
            duration="96",
        ),
        NumberHit("FC2-1234567", "JavDB", "https://javdb580.com/v/b"),
    ]
    target = tmp_path / "三上悠亚2026-10-25 12-26-05.xlsx"
    _write_missing_excel(target, rows, "有码")

    sheet = load_workbook(target).active
    assert sheet.title == "Sheet1"
    assert [c.value for c in sheet[1]] == ["番号", "演员", "日期", "时长", "类型", "网站", "链接地址"]
    first = [c.value for c in sheet[2]]
    assert first[:2] == ["EHM-001", "三上悠亜,鬼头桃菜"]
    assert first[2].strftime("%Y-%m-%d") == "2016-12-29"
    assert first[3] == 96
    assert first[4:] == ["有码", "DMM_API", "https://video.dmm.co.jp/av/content/?id=h_295ehm00001"]
    assert [c.value for c in sheet[3]][4] == "有码"
    for index, expected in enumerate((13, 13, 13, 13, 13, 13, 100), start=1):
        assert sheet.column_dimensions[get_column_letter(index)].width == expected
    # 表头整行居中；数据行只有链接列靠左
    for cell in sheet[1]:
        assert cell.alignment.horizontal == "center"
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=7):
        for cell in row:
            assert cell.alignment.vertical == "center"
            if cell.column == 7 or (cell.column == 2 and "," in str(cell.value or "")):
                expected = "left"
            else:
                expected = "center"
            assert cell.alignment.horizontal == expected, (cell.coordinate, cell.value)
    # 演员列：单演员居中、多演员靠左
    assert sheet.cell(row=2, column=2).alignment.horizontal == "left"  # 三上悠亜,鬼头桃菜
    assert sheet.cell(row=3, column=2).alignment.horizontal == "center"  # 空（单值）


def test_excel_filename_carries_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """文件名 = 演员名 + YYYY-MM-DD HH-MM-SS.xlsx，落在本地资源库目录下。"""
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "local_library", [str(tmp_path)])
    target = _excel_target("三上悠亚")
    assert target is not None
    assert target.parent == tmp_path
    assert re.fullmatch(r"三上悠亚\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.xlsx", target.name), target.name


def test_media_type_display_uses_chuanmei_for_guochan(tmp_path: Path) -> None:
    """类型列：内部「国产」写「传媒」，其余同名。"""
    from openpyxl import load_workbook

    target = tmp_path / "t.xlsx"
    _write_missing_excel(target, [NumberHit("MD-096", "Madou.club", "")], "国产")
    assert load_workbook(target).active.cell(row=2, column=5).value == "传媒"
