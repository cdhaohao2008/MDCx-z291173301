"""唯一发版工作流 `.github/workflows/build-py315.yml` 的守卫。

背景：2026-10-21 起程序整体迁移到 Python 3.15，本工作流接过了原 `build-py314.yml`
（Python 3.14 发版主流程）的全部职责，`build-py314.yml` 一并删除——两条流程共用同一套
纯数字 tag 命名空间且都按 `overwrite: true` 覆盖资产，同时发版会互相把对方的包刷掉。
更早的 2026-09-28 起原 3.13 主流程 `build-py313.yml`（更早叫 `release.yml`）连同单平台
手动构建的 `build-windows.yml` / `build-linux.yml` 一并删除，多平台矩阵已完全覆盖后两者的
功能。本工作流同时负责 `push` tag `2*` 自动发版与 `workflow_dispatch` 手动补发，
任何一处被改坏都会伤到发版或客户端自动更新：

1. **tag 必须是纯数字**（= `mdcx/consts.py` 的 `LOCAL_VERSION`）：`mdcx/base/web.py` 的
   `check_version()` 遍历 releases（`per_page=10`）收集全部 `tag_name.isdigit()` 的值并
   取其中**最大**的一个，非纯数字 tag 会被跳过，自动更新就永久失效。故不得回退到早期
   版本的 `py314-<版本号>` / `py315-<版本号>` 预览 tag 方案。（取最大而非取第一条的理由见
   `tests/test_version_check_pick_latest.py`：`/releases` 按 `created_at` 倒序，本工作流
   各平台用同一 tag + `overwrite` 重建 release，补发旧 tag 会把它顶到第一条。）
2. **必须监听 tag `2*`**：3.13 / 3.14 流程删除后，本工作流是唯一监听 tag 的地方；丢了
   `push.tags` 就再没有自动发版路径了。同时保留 `workflow_dispatch` 供手动补发。
3. **输入只有 tag 与 prerelease**：平台固定三平台（无 `platforms` 开关）、发版不再有
   `publish` 勾选、relock 回退不再有 true/false 开关（3.15 恒允许回退）。
4. **缺产物不发版**：`build-app` 带 `continue-on-error`，所以 `publish-release` 必须用
   `needs.build-app.result == 'success'` 把关（不能写 `success()`：`needs` 里任一失败腿
   都会让它整体跳过），并在上传前核对三个平台产物齐全——半成品 Release 比不发更糟。
5. **资产命名是客户端契约**：`MDCx-<展示版本号>-<tag>-<平台>-<架构>-<sha>.<ext>`，同名资产靠
   `overwrite: true` 覆盖更新，格式一改客户端下载链接就全断。展示版本号取
   `mdcx/consts.py` 的 `VERSION_NAME` 去 v 前缀（`v2.4.7` → `2.4.7`），只进文件名、
   不参与版本比较；`tag` 仍是纯数字 `LOCAL_VERSION`，`check_version()` 比的就是它。
   资产名同时写在 `docs/Development.md` 与 `DADA/MEMORY.md`，改一处要同步三处。
6. **macOS Intel 腿已于 2026-10-20 退役**：macOS 放弃 x86_64，矩阵、产物核对项与
   `Create Release - macOS (Intel)` 三处必须同时消失（`_RETIRED_MACOS_INTEL`）。
7. **必须用 Python 3.15 构建**：`UV_PYTHON` / `python-version` / 构建前断言三处锁 3.15，
   编出来的包才与 `requires-python >=3.14`（3.15 为当前目标）匹配。
8. **Release 正文必须走文件，不能塞进 action 的 `body` 输入**：JS action 的每个 `with:`
   输入都会被 runner 变成一个 `INPUT_*` 环境变量，而 Linux 对单个环境变量有 128 KiB
   硬上限（`MAX_ARG_STRLEN`）。changelog 改按日期分段后单段可以很大（`## 2026-10-20`
   那段 340+ KiB），一超限 runner 连 node 进程都起不来，报 "Argument list too long"，
   `publish-release` 在第一个 Create Release 就崩——此时三个平台的包已经传上去，
   留下的是一条没有正文的半成品 Release。故正文落盘成 `release-notes.md`，再用
   `gh release edit --notes-file` 写入。
9. **Release 标题格式**：`MDCx <日期版本号>`（如 `MDCx 20261022`），日期取自**软件
   源代码**的 `mdcx/consts.py` `LOCAL_VERSION`（发版流程先 bump 它、再打同名的纯数字
   tag，故与 tag 同源），不再带展示版本号与括号。标题只给人看——客户端 `check_version()`
   只读 `tag_name`，标题改名不影响自动更新。

按仓库惯例做文本断言（`tests/` 不引入 yaml 依赖），改工作流后请同步更新本文件。
"""

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_WORKFLOW = _ROOT / ".github" / "workflows" / "build-py315.yml"

# 一次 Release 覆盖的平台资产（macOS 只剩 Apple Silicon 一条腿，文件名由 build-app 决定）
_ASSET_FILES = (
    "dist/MDCx-aarch64.dmg",
    "dist/MDCx.exe",
    "dist/MDCx",
)

_RELEASE_STEP_COUNT = 3

# 固定三平台矩阵（actions/runner#1985）。2026-10-20 起 macOS Intel（`macos-15-intel` /
# x86_64）那条腿连同其产物核对项与 `Create Release - macOS (Intel)` 步骤一并删除：
# macOS 已放弃 x86_64 架构，只编一份 Apple Silicon dmg。
_MATRIX_ITEMS = (
    '{"build": "macos", "os": "macos-latest", "arch": "aarch64"}',
    '{"build": "windows", "os": "windows-2025", "arch": "x86_64"}',
    '{"build": "linux", "os": "ubuntu-latest", "arch": "x86_64"}',
)

# 2026-10-20 删除的 macOS Intel 腿留下的三处痕迹，任一处复活即说明没删干净。
# 尤其第一条：矩阵里留着这条腿而产物核对项被删，会让 upload-artifact 因缺文件失败，
# 连带 `needs.build-app.result != 'success'` 掐死整条发版链路。
_RETIRED_MACOS_INTEL = (
    "macos-15-intel",
    "dist/MDCx-x86_64.dmg",
    "Create Release - macOS (Intel)",
)

# 客户端依赖的资产名，逐条写死（唯一发版流程，没有第二份可对照，改名即破坏下载链接）。
# 形如 `MDCx-<展示版本号>-<tag>-<平台>-<架构>-<sha>.<ext>`，例如
# `MDCx-2.4.7-20261020-windows-x86_64-<40位sha>.exe`：两个版本段并存——`asset_version`
# 是 `VERSION_NAME` 去 v 前缀（只给人看），`tag` 是纯数字 `LOCAL_VERSION`（`check_version()`
# 的 `int(tag_name)` 比较走的是它）。
_EXPECTED_ASSETS = (
    "asset_name: MDCx-${{ steps.metadata.outputs.asset_version }}-${{ steps.metadata.outputs.tag }}-macos-aarch64-${{ github.sha }}.dmg",
    "asset_name: MDCx-${{ steps.metadata.outputs.asset_version }}-${{ steps.metadata.outputs.tag }}-windows-x86_64-${{ github.sha }}.exe",
    "asset_name: MDCx-${{ steps.metadata.outputs.asset_version }}-${{ steps.metadata.outputs.tag }}-linux-x86_64-${{ github.sha }}",
)

# 已删除的工作流，守卫它们别被无意中加回来
# 2026-09-28：3.13 主流程 `build-py313.yml` 与单平台构建 `build-windows.yml` / `build-linux.yml`
# 2026-10-21：程序迁移到 3.15 后 `build-py314.yml` 也被本流程取代并删除
_REMOVED_WORKFLOWS = ("build-py313.yml", "build-windows.yml", "build-linux.yml", "build-py314.yml")


def _workflow() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def _workflow_code() -> str:
    """工作流去掉整行注释后的正文。

    文件头保留着「macOS Intel 腿为何退役」的说明注释（含 `macos-15-intel` 等字样），
    所以退役断言必须只看配置行，否则文档本身就会把守卫打红。
    """
    return "\n".join(line for line in _workflow().splitlines() if not line.lstrip().startswith("#"))


def test_tag_is_plain_numeric_not_version_prefixed():
    """Release tag 必须是纯数字版本号，不得回退到 `py314-` / `py315-` 前缀。"""
    text = _workflow()

    for prefix in ("tag=py314-", "tag=py315-"):
        assert re.search(re.escape(prefix), text) is None, (
            f"build-py315.yml 不得给 tag 加 {prefix[4:]} 前缀：非纯数字 tag 会被 check_version 的 "
            "tag_name.isdigit() 跳过，客户端自动更新永久失效"
        )
    # 只查真正的配置行：工作流名/并发组里的 build-release- 是合法的
    assert re.search(r"(?m)^\s+asset_name:.*py31[45]", text) is None, (
        "资产名不得带 -py314- / -py315- 段：客户端按 `MDCx-<展示版本号>-<tag>-<平台>-<架构>-<sha>` 找资产"
    )
    assert 'echo "tag=$tag" >> "$GITHUB_OUTPUT"' in text, "metadata 步骤应回输出解析出的纯数字 tag"
    assert text.count("tag: ${{ steps.metadata.outputs.tag }}") == _RELEASE_STEP_COUNT, (
        "三个 Create Release 步骤都应引用纯数字 tag"
    )
    assert re.search(r"\^\[0-9\]\+\$", text), "tag 必须做纯数字校验（build-app 与 publish 两处都要）"


def test_workflow_listens_to_numeric_tag_pushes():
    """唯一的发版流程必须监听 `2*` tag，同时保留手动补发入口。"""
    text = _workflow()

    assert re.search(r"(?m)^  push:$", text) is not None, (
        "build-py315.yml 必须监听 push：3.13 / 3.14 流程均已删除，本工作流是唯一的 tag 触发发版路径"
    )
    assert re.search(r"(?m)^    tags:\s*$", text) is not None, "push 触发必须限定在 tags 上，不能监听分支推送"
    assert re.search(r'(?m)^      - "2\*"\s*$', text) is not None, (
        'tag 过滤器应保持 "2*"（纯数字 YYYYMMDD，2026 起；旧模式 "220*" 永不触发）'
    )
    assert re.search(r"(?m)^  workflow_dispatch:$", text) is not None, "应保留手动补发入口"
    # 不能退回只监听分支推送——那会在每次 GitHub Desktop 同步时误发一版
    assert re.search(r"(?m)^    branches:\s*$", text) is None, "不应监听分支推送，否则每次同步都会发版"


def test_prerelease_only_applies_to_manual_dispatch():
    """tag 推送一律发正式版，prerelease 只对手动触发生效。"""
    text = _workflow()

    assert 'if [ "${{ github.event_name }}" ] = "workflow_dispatch" ] && [ "$DISPATCH_PRERELEASE" = "true" ]' in text, (
        "prerelease 必须由 event_name 守卫，否则推 tag 也会被标成预发布"
    )
    assert re.search(r"(?m)^\s+prerelease: \$\{\{ steps\.metadata\.outputs\.prerelease \}\}$", text), (
        "三个 Create Release 步骤都应沿用 metadata 解析出的 prerelease"
    )


def test_only_tag_and_prerelease_inputs():
    """手动触发只留版本号与 prerelease 两个输入，恒构建三平台、恒允许 relock 回退。"""
    text = _workflow()

    for removed in ("platforms:", "publish:", "allow_relock:"):
        assert removed not in text, f"build-py315.yml 不应有 {removed} 输入"
    for reference in ("inputs.platforms", "inputs.publish", "inputs.allow_relock"):
        assert reference not in text, f"不应再引用 {reference}"
    assert re.search(r"(?m)^      tag:$", text) is not None, "应保留 tag 输入"
    assert re.search(r"(?m)^      prerelease:$", text) is not None, "应保留 prerelease 输入"


def test_matrix_always_builds_all_three_platforms():
    """平台固定三平台全量构建（macOS 只剩 Apple Silicon）。"""
    text = _workflow()

    for item in _MATRIX_ITEMS:
        assert f"items+=('{item}')" in text, f"矩阵缺少 {item}"
    assert "PLATFORMS" not in text, "平台固定全量构建，不应再有 PLATFORMS 分支"
    assert "没有匹配的平台" not in text, "不应再有平台筛选的报错分支"
    for artifact in (
        "mdcx-macos-${{ matrix.arch }}",
        "mdcx-windows-${{ matrix.arch }}",
        "mdcx-linux-${{ matrix.arch }}",
    ):
        assert f"name: {artifact}" in text, f"产物名缺失：{artifact}"
    assert "pattern: mdcx-*" in text, "下载产物的 pattern 应覆盖全部平台"


def test_macos_intel_leg_is_gone():
    """macOS 放弃 x86_64，Intel 腿的矩阵项 / 产物核对项 / 上传步骤必须三处同删。

    只删矩阵项而留着产物核对项最致命：`Verify all platform assets present` 会永远
    缺 `dist/MDCx-x86_64.dmg` 直接 exit 1，把**所有**平台的发版一起卡死；
    只删矩阵项而留着上传步骤则会让 svenstaro/upload-release-action 因文件缺失报错，
    在 `overwrite: true` 重建 release 的语义下可能留下半成品 Release。
    """
    code = _workflow_code()

    for retired in _RETIRED_MACOS_INTEL:
        assert retired not in code, (
            f"macOS Intel 腿已于 2026-10-20 退役（macOS 已放弃 x86_64），工作流里不该再出现：{retired}"
        )
    assert "-macos-x86_64-" not in code, "不该再拼 macos x86_64 资产名"
    assert code.count("- name: Create Release - macOS") == 1, "macOS 只应有 Apple Silicon 一个 Create Release 步骤"


def test_python_315_pins_and_relock_fallback():
    """3.15 三处专属：解释器锁 3.15、构建前断言、uv sync 失败自动回退。"""
    text = _workflow()

    assert 'python-version: "3.15"' in text, "必须用 Python 3.15 构建"
    assert 'UV_PYTHON: "3.15"' in text, "需 UV_PYTHON 兜住 setup-python 之外的 uv 调用"
    assert "Verify Python 3.15 in use" in text, "缺少解释器断言，uv 可能悄悄挑到别的版本"
    assert "sys.version_info[:2] == (3, 15)" in text, "断言必须检查 sys.version_info"
    assert "uv sync --locked --all-extras --dev" in text, "仍需先用 --locked 严格校验"
    assert re.search(
        r"if ! uv sync --locked --all-extras --dev[^\n]*; then.*uv sync --all-extras --dev",
        text,
        re.S,
    ), "uv sync --locked 失败必须自动回退重新解析（uv.lock 缺 cp315 wheel 时需要）"
    # 3.15 专属：PyYAML 至今无 cp315 wheel，用 PYYAML_FORCE_LIBYAML=0 让它跳过 C 扩展
    assert 'PYYAML_FORCE_LIBYAML: "0"' in text, (
        "3.15 下必须用 PYYAML_FORCE_LIBYAML=0 让 pyyaml 跳过 `yaml._yaml` C 扩展（无 cp315 wheel）"
    )
    assert "--no-install-package pyyaml" not in text, (
        "不必再跳过 pyyaml：PYYAML_FORCE_LIBYAML=0 已让它能从 sdist 直接产出纯 Python wheel"
    )
    assert "--python-version 3.14" not in text, "不再用 cp314 wheel 顶替：cp314 的 C 扩展与 3.15 ABI 不匹配，混装有隐患"
    assert 'UV_NO_SYNC: "1"' in text, "uv run 的隐式 sync 会重新解析并可能重建 pyyaml，必须关掉"


def test_publish_requires_all_platform_artifacts():
    """上传前必须核对三平台产物齐全，避免发半成品 Release。"""
    text = _workflow()

    assert "- name: Verify all platform assets present" in text, "缺少产物核对步骤"
    verify_idx = text.index("- name: Verify all platform assets present")
    assert verify_idx < text.index("- name: Create Release - macOS (Apple Silicon)"), (
        "产物核对必须在第一个 Create Release 之前"
    )
    for asset in _ASSET_FILES:
        assert f"[ -s {asset} ]" in text, f"产物核对漏了 {asset}"
        assert f"file: {asset}" in text, f"缺少 {asset} 的上传步骤"

    gate = re.search(r"(?m)^\s{4}if: \$\{\{ (.+) \}\}$", text)
    assert gate is not None, "找不到 publish-release 的 if 条件"
    assert "!cancelled()" in gate.group(1), "用 !cancelled() 而非 always()，run 被取消时不再白跑发版"
    assert "needs.build-app.result == 'success'" in gate.group(1), (
        "发版条件必须核对 build-app 的真实结果（build-app 开了 continue-on-error，"
        "不能写 success()：needs 里任一失败腿都会让它整体跳过）"
    )
    assert re.search(r"(?m)^\s{4}continue-on-error: true$", text) is not None, (
        "continue-on-error 缺失时上面的 needs 结果门禁就没有意义"
    )


def test_release_uploads_are_idempotent():
    """重跑同一 commit 时不得因已存在同名 Release 而失败。"""
    text = _workflow()

    assert text.count("overwrite: true") >= _RELEASE_STEP_COUNT, (
        "Create Release 步骤需要 overwrite: true，重跑时才不会失败"
    )
    assert "contents: write" in text, "创建 Release 需要 permissions: contents: write"
    assert text.count("- name: Create Release - ") == _RELEASE_STEP_COUNT, (
        f"应有 {_RELEASE_STEP_COUNT} 个 Create Release 步骤（macOS Apple Silicon + Windows + Linux）"
    )


def test_release_notes_go_through_file_not_action_input():
    """Release 正文必须走文件，不能塞进 action 的 `body` 输入。

    2026-10-24 修：改 tag 20261020 补发时 `publish-release` 报
    "An error occurred trying to start process '.../node24/bin/node' ...
    Argument list too long"。根因是 changelog 正文被当成 JS action 的 `body` 输入传给
    `svenstaro/upload-release-action@v2`：runner 会把每个 `with:` 输入变成一个
    `INPUT_*` 环境变量，而 Linux 单个环境变量上限 128 KiB（`MAX_ARG_STRLEN`），
    `## 2026-10-20` 那段 changelog 有 340+ KiB，一超限 execve 直接 E2BIG，
    node 进程都起不来。此时三个平台的包已经传上去，Release 是半成品。
    """
    text = _workflow()

    # 旧写法（正文进 step output 再进 action 输入）必须彻底消失
    assert "steps.changelog.outputs.CHANGELOG" not in text, (
        "Release 正文不得再经 step output 传给 action：单个 INPUT_* 环境变量上限 128 KiB，"
        "changelog 单段超限时 runner 会报 'Argument list too long'，发版在第一个 "
        "Create Release 就崩，留下没有正文的半成品 Release"
    )
    # 正文落盘，只回小字段
    assert 'notes_file="release-notes.md"' in text, "changelog 正文应落盘成文件，不走 step output"
    assert '> "$notes_file"' in text, "changelog 区段应被写入 notes_file"
    assert 'echo "date=$date_str" >> "$GITHUB_OUTPUT"' in text, "changelog 步骤只应回日期等小字段"
    assert 'echo "notes_file=$notes_file" >> "$GITHUB_OUTPUT"' in text, "changelog 步骤应回 notes_file 路径"
    # 正文用 gh CLI 按文件写入（gh 是 GitHub-hosted runner 自带，正文走 HTTP 请求体）
    assert "- name: Publish release notes" in text, "缺少写入 Release 正文的步骤"
    assert 'gh release edit "$TAG"' in text, "正文应用 gh release edit 写入"
    assert '--notes-file "$body_file"' in text, "正文必须用 --notes-file 按文件写入"
    assert "GH_TOKEN: ${{ github.token }}" in text, "gh 需要 token 才有权改 Release"
    # 预发布状态要显式写：重跑同一 tag 时 gh 的 --prerelease 不传就不改
    assert "--prerelease" in text and "--prerelease=false" in text, (
        "预发布状态需显式写一次（重跑补发时状态可能与上次不一致）"
    )


def test_release_notes_respect_github_body_length_limit():
    """正文还得过 GitHub 的 125,000 字符上限，超了 API 直接 422。

    变更日志按日期分段后单段可以远超这个上限（`## 2026-10-20` 那段近 30 万字符），
    正文原样塞过去 API 会拒（"body is too long"），Release 仍是没正文的半成品。
    故按行截断到 120,000 字符（给截断提示留余量），并注明完整内容在哪。
    """
    text = _workflow()

    assert "LIMIT = 120_000" in text, "正文应按 120,000 字符上限截断（GitHub 硬上限 125,000）"
    assert "125,000" in text, "应写明 GitHub 的 125,000 字符硬上限"
    assert "release-body.md" in text, "截断后的正文应落到单独文件"
    assert "125,000-character limit" in text, "截断处应注明正文被截断"
    assert "docs/Changelog.md" in text, "截断处应指出完整内容的去处"
    # 截断后写正文用的是截断文件，不是原始文件
    assert '--notes-file "$body_file"' in text, "gh 应读取截断后的正文文件"
    assert 'body_file="$NOTES_FILE"' in text, "未超限时直接用原文件，不做无谓改写"


def test_release_notes_step_runs_after_all_create_release_steps():
    """`Publish release notes` 必须在三个 Create Release 之后。

    `svenstaro/upload-release-action` 每次都会用 `body` 覆盖 Release 正文，
    提前写正文会被它抹掉。
    """
    text = _workflow()

    notes_idx = text.index("- name: Publish release notes")
    last_create = text.rindex("- name: Create Release - ")
    assert notes_idx > last_create, "写正文的步骤必须放在所有 Create Release 之后：svenstaro 每次都会用 body 覆盖正文"
    assert text.count("- name: Create Release - ") == _RELEASE_STEP_COUNT, (
        f"应有 {_RELEASE_STEP_COUNT} 个 Create Release 步骤（macOS Apple Silicon + Windows + Linux）"
    )


def test_asset_names_and_release_title():
    """资产名与标题是对外契约，格式一改客户端下载链接就全断。"""
    text = _workflow()

    for asset_name in _EXPECTED_ASSETS:
        assert asset_name in text, f"缺少约定的资产名（客户端按此下载）：{asset_name}"
    assert "release_name: ${{ steps.metadata.outputs.name }}" in text, "标题应沿用 metadata 的解析结果"
    assert 'release_name="MDCx ${source_version}"' in text, "Release 标题应为 `MDCx <日期版本号>`（如 `MDCx 20261022`）"
    assert 'echo "name=$release_name" >> "$GITHUB_OUTPUT"' in text, "标题应写入 metadata 的 name 输出"
    assert "name=${version_name} (${tag})" not in text, (
        "标题不应再直接用带 v 前缀的 VERSION_NAME，否则列表里显示的是 `v2.7.4 (20261021)`"
    )


def test_release_title_date_comes_from_source_code():
    """标题里的日期版本号必须取自软件源代码（`mdcx/consts.py` 的 `LOCAL_VERSION`）。

    标题格式 `MDCx <日期版本号>`（如 `MDCx 20261022`）：日期是发版日，与 tag 同源，
    少了它列表里就分不清是哪一版。标题只给人看——客户端只读 `tag_name`。
    """
    text = _workflow()

    assert "source_version=$(grep -oE 'LOCAL_VERSION[[:space:]]*=[[:space:]]*[0-9]+' mdcx/consts.py" in text, (
        "标题日期应从 mdcx/consts.py 的 LOCAL_VERSION 读出（软件源代码里的日期）"
    )
    assert "source_version=${source_version:-$tag}" in text, "读不到源码日期时应退回 tag，保证标题不缺日期"
    assert 'if [ "$source_version" != "$tag" ]; then' in text, (
        "源码日期与 tag 不一致时要显式处理（补发旧 tag 时标题日期按 tag 走，免得与 tag、正文区段对不上）"
    )
    assert 'release_name="MDCx ${asset_version} (${tag})"' not in text, (
        "标题不应再带展示版本号与括号（旧格式 `MDCx <展示版本号> (<tag>)`）"
    )


def test_asset_version_segment_comes_from_version_name_without_v_prefix():
    """资产名里的展示版本号段必须是 `VERSION_NAME` 去 v 前缀，且三个发布步骤都引用它。"""
    text = _workflow()

    assert "asset_version=${version_name#v}" in text, (
        "展示版本号应由 VERSION_NAME 去掉 v 前缀得到（v2.4.7 → 2.4.7），不能直接拼带 v 的原值"
    )
    assert 'echo "asset_version=$asset_version" >> "$GITHUB_OUTPUT"' in text, (
        "metadata 步骤应回输出 asset_version，三个 Create Release 步骤都靠它拼文件名"
    )
    assert "asset_version=${asset_version:-$tag}" in text, "读不到 VERSION_NAME 时应退回 tag，保证资产文件名不会缺一段"
    assert text.count("steps.metadata.outputs.asset_version") == _RELEASE_STEP_COUNT, (
        f"三个 Create Release 步骤都应引用 asset_version（当前 {text.count('steps.metadata.outputs.asset_version')} 处）"
    )
    # asset_version 只进文件名，绝不能被写回 tag——tag 必须保持纯数字
    assert 'echo "tag=$tag"' in text and "asset_version=$tag" not in text, (
        "asset_version 不得覆盖 tag：tag 必须纯数字，否则 check_version 的 int(tag_name) 失效"
    )
    # build-app 的 Windows 预检步骤独立算了一遍展示版本号，日志里的文件名必须与真名一致
    assert "$versionName.TrimStart('v')" in text, (
        "Windows 预检步骤应按同一算法（去 v 前缀）算出计划发布文件名，否则日志与实际上传名对不上"
    )


def test_removed_workflows_are_gone():
    """已删除的四个工作流不得被加回来（会与本流程抢发或重复构建）。"""
    workflows = _ROOT / ".github" / "workflows"

    for name in _REMOVED_WORKFLOWS:
        assert not (workflows / name).exists(), f"{name} 已删除（三平台矩阵 / 唯一发版流程已覆盖其职责），不应再加回来"
    assert re.search(r"tag=py31[45]-", _workflow()) is None
