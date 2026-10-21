"""Python 3.14/3.15 依赖下限守卫（配合 `.github/workflows/build-py314.yml`）。

背景：3.14 流水线靠 `python-version: 3.14` + `uv sync --locked` 验证兼容性，
其中几处依赖下限是被 3.14/3.15 核对抬上来的，回退会让该流水线硬失败：

- `pyinstaller`：`6.14.2` 的元数据是 `requires-python = ">=3.8,<3.14"`，3.14 上装不上；
  `6.16.0~6.20.0` 声明 `<3.15`，3.15 上装不上；`6.21.0` 起才放宽到 `<3.16`；
- `av`：`15.0.0` 只有 cp39~cp313 的 wheel，3.14 上会退回源码编译（需 FFmpeg 开发库）；
  `17.0.0` 起改发 abi3 wheel（`19.0.2` 为 cp312-abi3），3.15 通用；
- `aiofiles`：`25.1.0` 起上游才测试并支持 3.14（`24.1.0` 早于 3.14）；
- `aiohttp`/`lxml`/`pillow`/`numpy`：从 `3.14.4`/`6.1.2`/`12.3.0`/`2.5.2` 起才发 cp315
  wheel，更早的版本在 3.15 上只能源码编译（需 MSVC 等编译工具链）。

另外几个带原生扩展的**传递依赖**也显式钉了下限（它们原本由别的包间接引入，
一旦重新 `uv lock` 就有回退到无 cp315 wheel 老版本的风险）：

- `cffi`（curl-cffi 依赖，C 扩展）：`2.0.0` 只发到 cp314，`2.1.1` 起才有 cp315 wheel；
- `jiter`（openai 依赖，Rust 扩展）：`0.12.0` 无 cp315 wheel，`0.17.0` 起才有；
- `markupsafe`（jinja2 依赖，C 扩展）：`3.0.3` 无 cp315 wheel，`3.0.4` 起才有；
- `pydantic-core`（pydantic 依赖，Rust 扩展）：`2.41.5` 无 cp315 wheel，`2.50.1` 起才有；
- `PyQt6-sip`（pyqt6 依赖，C++ 扩展）：`13.11.1` 无 cp315 wheel，`13.13.0` 起才有。

`pyyaml` 是唯一至今没有 cp315 wheel 的包（`6.0.3` 只到 cp314），但它只是
`pre-commit` 的传递依赖且提供纯 Python 回退，CI 里用 cp314 wheel 顶替即可，
见 `.github/workflows/build-py315.yml`。

同时校验 `pyproject.toml` 与 `uv.lock` 的依赖声明不脱节：`uv sync --locked` 在
CI 里强校验 lock 是否与 manifest 一致，改依赖后忘了 `uv lock` 会直接 exit 1。
其余依赖（`pyqt6` cp39-abi3、`opencv-contrib-python-headless` cp37-abi3、
`curl-cffi` cp310-abi3、`oshash`/`zhconv` 纯 Python 等）无需设下限，见
`docs/Development.md`「构建」段。
"""

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).parent.parent

# 包名 -> 必须保持的版本声明（回退即视为 3.14/3.15 不兼容）
_REQUIRED_SPECIFIERS = {
    "aiofiles": ">=25.1.0",
    "aiohttp": ">=3.14.5",
    "av": ">=19.0.2",
    "lxml": ">=6.1.3",
    "numpy": ">=2.5.4",
    "pillow": ">=13.0.0",
    "pyinstaller": ">=6.22.3,<7",
    # 带原生扩展的传递依赖：下限 = 首个提供 cp315 wheel 的版本
    "cffi": ">=2.1.1",
    "jiter": ">=0.17.0",
    "markupsafe": ">=3.0.4",
    "pydantic-core": ">=2.50.1",
    "pyqt6-sip": ">=13.13.0",
}

# 已锁定的解析版本下限（uv.lock 实际 pin 的版本也必须够新）
_REQUIRED_LOCKED = {
    "aiohttp": (3, 14, 5),
    "av": (19, 0),
    "lxml": (6, 1, 3),
    "numpy": (2, 5, 4),
    "pillow": (13, 0, 0),
    "pyinstaller": (6, 22, 3),
    "cffi": (2, 1, 1),
    "jiter": (0, 17, 0),
    "markupsafe": (3, 0, 4),
    "pydantic-core": (2, 50, 1),
    "pyqt6-sip": (13, 13, 0),
}


def _pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _declared_specifiers() -> dict[str, str]:
    """把 pyproject.toml 里的 dependencies + dev 组解析成 {包名: 版本声明}。"""
    project = _pyproject()["project"]
    declared: dict[str, str] = {}
    for raw in list(project["dependencies"]) + list(_pyproject()["dependency-groups"]["dev"]):
        match = re.match(r"([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*(\S+)$", raw.strip())
        assert match is not None, f"无法解析依赖声明：{raw}"
        declared[match.group(1).lower().replace("_", "-")] = match.group(2)
    return declared


def _lock_root_metadata() -> str:
    """取 uv.lock 里根包（mdcx）的 [package.metadata...] 整段，含 requires-dist 与 requires-dev。"""
    content = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    for block in content.split("\n[[package]]\n"):
        if "\n[package.metadata]\n" in block:
            return block
    return ""


def _version_tuple(version: str, width: int) -> tuple[int, ...]:
    """把版本号拆成定长数字元组，缺位补 0（3.14 与 3.14.0 视为同一版本）。"""
    parts = [int(part) for part in re.findall(r"\d+", version)[:width]]
    parts += [0] * (width - len(parts))
    return tuple(parts)


def test_314_critical_specifiers_present():
    """几个关键包的版本声明不得被回退到不支持 3.14/3.15 的老版本。"""
    declared = _declared_specifiers()

    for name, expected in _REQUIRED_SPECIFIERS.items():
        assert name in declared, f"pyproject.toml 缺少依赖 {name}"
        assert declared[name] == expected, (
            f"{name} 的版本声明是 {declared[name]}，3.14/3.15 需要 {expected}；"
            "回退会让 build-py314.yml 的 `uv sync --locked` 失败，理由见 tests/test_py314_dependency_floors.py 文档"
        )


def test_uv_lock_metadata_matches_pyproject():
    """uv.lock 根包的 [package.metadata] 必须与 pyproject.toml 同步。

    CI 用 `uv sync --locked` 强校验，两者脱节时该步直接 exit 1（全平台）。
    """
    metadata = _lock_root_metadata()
    assert metadata, "uv.lock 中找不到根包的 [package.metadata] 段"

    for name, expected in _REQUIRED_SPECIFIERS.items():
        assert re.search(
            rf'(?m)^\s*\{{ name = "{re.escape(name)}", specifier = "{re.escape(expected)}" \}},$',
            metadata,
        ), (
            f"uv.lock 的 metadata 里没有 {name} = {expected}；"
            "请执行 `uv lock` 重新生成 lock，否则 CI 的 `uv sync --locked` 会失败"
        )


def test_locked_versions_admit_python_314():
    """uv.lock 实际 pin 的版本也必须够新（av 要有 abi3 wheel，pyinstaller 要允许 3.15）。"""
    content = (_ROOT / "uv.lock").read_text(encoding="utf-8")

    for name, floor in _REQUIRED_LOCKED.items():
        match = re.search(rf'(?m)^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"', content)
        assert match is not None, f"uv.lock 中找不到包 {name}"
        version = _version_tuple(match.group(1), len(floor))
        assert version >= floor, (
            f"uv.lock 里 {name} 锁的是 {match.group(1)}，低于 3.14/3.15 需要的 "
            f"{'.'.join(str(p) for p in floor)}；"
            "请执行 `uv lock --upgrade-package " + name + "`"
        )


def test_requires_python_has_no_upper_bound():
    """`requires-python` 不能带 upper bound，否则 3.14 直接不是合法解释器。"""
    requires_python = _pyproject()["project"]["requires-python"]

    assert "<" not in requires_python, (
        f'requires-python = "{requires_python}" 带 upper bound，会把 Python 3.14 排除在外，'
        "build-py314.yml 与 pyproject 前提冲突"
    )
