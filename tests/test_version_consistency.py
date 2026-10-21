"""版本号同步点一致性校验（发版流程回归）。

版本号有四个同步点：
1. `mdcx/consts.py` 的 `LOCAL_VERSION`（纯数字 YYYYMMDD，GitHub tag 也用它）
2. `mdcx/consts.py` 的 `VERSION_NAME`（展示名 vX.Y[.Z]；v3.0 起固定为 v3.0）
3. `pyproject.toml` 的 `version`（去掉 v 前缀）
4. `uv.lock` 根包 `mdcx` 的 `version`（CI 全平台 `uv sync --locked` 强校验，脱节即构建失败）

changelog 改按**日期**分段（`## YYYY-MM-DD`）后，版本号不再进标题，日期才是它的
同步点：`docs/Changelog.md` 必须有与 `LOCAL_VERSION` 同日期的段，且各段按日期倒序。

`scripts/bump.py --check` 与本测试覆盖同一不变量；此处用 pytest 让它进入常规回归。
"""

import re
import tomllib
from pathlib import Path

from mdcx.consts import LOCAL_VERSION, VERSION_NAME

_ROOT = Path(__file__).parent.parent


def test_version_name_matches_pyproject():
    package_version = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    display_version = VERSION_NAME.removeprefix("v")

    assert re.fullmatch(r"\d+\.\d+(?:\.\d+)?", display_version)
    assert package_version == display_version


def test_changelog_has_section_for_local_version():
    """changelog 必须有与 LOCAL_VERSION 同日期的段（今天的改动记在今天下）。"""
    changelog = (_ROOT / "docs" / "Changelog.md").read_text(encoding="utf-8")
    dates = re.findall(r"(?m)^##\s+(\d{4})-(\d{2})-(\d{2})\s*$", changelog)

    assert dates, "changelog 首个段格式应为 '## YYYY-MM-DD'"
    date_digits = {d[0] + d[1] + d[2] for d in dates}
    assert str(LOCAL_VERSION) in date_digits, (
        f"changelog 没有与 LOCAL_VERSION {LOCAL_VERSION} 同日期的段（今天的改动必须记在今天下）"
    )


def test_changelog_sections_sorted_by_date_desc():
    """changelog 的日期段必须按日期倒序（新 → 旧），否则读者会看到旧记录排在前面。"""
    changelog = (_ROOT / "docs" / "Changelog.md").read_text(encoding="utf-8")
    dates = [f"{d[0]}-{d[1]}-{d[2]}" for d in re.findall(r"(?m)^##\s+(\d{4})-(\d{2})-(\d{2})\s*$", changelog)]

    assert dates == sorted(dates, reverse=True), f"changelog 日期段未按倒序排列: {dates}"


def test_uv_lock_root_version_matches_display_name():
    """uv.lock 根包版本必须与展示版本一致。

    背景：曾出现只升 `pyproject.toml`、漏同步 `uv.lock` 的情况，CI 四个平台
    （windows/macos-aarch64/macos-intel/linux）的 `uv sync --locked` 在
    `Install locked dependencies` 步全部 exit 1。改版本号/日期后本测试即时告警。
    """
    uv_lock = _ROOT / "uv.lock"
    assert uv_lock.exists(), "uv.lock 缺失"
    content = uv_lock.read_text(encoding="utf-8")
    match = re.search(r'(?m)^\[\[package\]\]\nname = "mdcx"\nversion = "([^"]+)"', content)
    assert match is not None, (
        'uv.lock 中找不到根包 mdcx 的 version（期望 [[package]] / name = "mdcx" / version = "X.Y.Z" 三行连排）'
    )
    display_version = VERSION_NAME.removeprefix("v")
    assert match.group(1) == display_version, (
        f"uv.lock 根包 version={match.group(1)} 与 VERSION_NAME={VERSION_NAME} 不一致；"
        "请执行 `uv lock` 或 `uv run bump --name <版本>` 同步，否则 CI 构建必败"
    )
