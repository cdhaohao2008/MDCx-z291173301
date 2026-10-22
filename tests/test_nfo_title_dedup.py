"""编辑 NFO 窗口标题「所见即所得」回归测试。

覆盖场景：
- 命名模板为 {{release}} {{number}} {{title}} 时，读取/整理模式下保存 NFO，
  标题里的 release/number 不能重复叠加（修复前会变成
  "2024-09-25 FC2-4541879 2024-09-25 FC2-4541879 【挑逗】"，且每保存一次长一截）
- 编辑 NFO 窗口按所见即所得保存：标题栏显示什么就原样写入 NFO
"""

from types import SimpleNamespace

import pytest
from lxml import etree

from mdcx.config.enums import Language, NfoInclude
from mdcx.core import nfo as nfo_module
from mdcx.core.naming import NameRenderOptions, NamingTarget, decompose_rendered_title
from mdcx.models.model_types import CrawlersResult, FileInfo

TEMPLATE = "{{release}} {{number}} {{title}}"
RELEASE = "2024-09-25"
NUMBER = "FC2-4541879"
PURE_TITLE = "【挑逗】"
RENDERED_TITLE = f"{RELEASE} {NUMBER} {PURE_TITLE}"


def _build_file_info(tmp_path) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = NUMBER
    file_info.file_path = tmp_path / f"{NUMBER}.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = NUMBER
    file_info.cd_part = ""
    return file_info


def _build_data(title: str = PURE_TITLE) -> CrawlersResult:
    data = CrawlersResult.empty()
    data.number = NUMBER
    data.title = title
    data.originaltitle = PURE_TITLE
    data.release = RELEASE
    data.outline = "简介"
    data.tags = ["标签"]
    return data


def _configure(monkeypatch: pytest.MonkeyPatch, main_mode: int = 1, template: str = TEMPLATE) -> None:
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", main_mode)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", template)
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", template)
    monkeypatch.setattr(nfo_module.manager.config, "release_rule", "YYYY-MM-DD")
    monkeypatch.setattr(
        nfo_module.manager.config,
        "nfo_include_new",
        [
            NfoInclude.PLOT_,
            NfoInclude.OUTLINE,
            NfoInclude.ORIGINALPLOT,
            NfoInclude.TAG,
            NfoInclude.GENRE,
            # 与 MDCx 默认一致：发行日期要写进 NFO，读取模式才能还原 {{release }}
            NfoInclude.RELEASE_,
            NfoInclude.RELEASEDATE,
            NfoInclude.PREMIERED,
        ],
    )
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tag_series", "系列: series")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")
    monkeypatch.setattr(nfo_module.manager.config, "read_mode", [])
    monkeypatch.setattr(
        nfo_module.manager.config.__class__,
        "get_field_config",
        lambda self, field: SimpleNamespace(language=Language.JP),
    )


def _read_title(nfo_file) -> str:
    root = etree.fromstring(nfo_file.read_text(encoding="utf-8").encode("utf-8"))
    return "".join(root.xpath("//title/text()"))


@pytest.mark.asyncio
async def test_nfo_title_not_duplicated_on_resave(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """读取/整理模式下反复保存 NFO，标题里的 release/number 不得重复叠加。"""
    _configure(monkeypatch, main_mode=5)
    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    nfo_file = tmp_path / f"{NUMBER}.nfo"

    # 首次刮削写入：标题按命名模板渲染
    await nfo_module.write_nfo(file_info, _build_data(), nfo_file, tmp_path, update=True, skip_merge=True)
    assert _read_title(nfo_file) == RENDERED_TITLE

    # 模拟「编辑 NFO」窗口：读回 → 用标题栏内容保存（所见即所得）
    for _ in range(3):
        loaded, _info = await nfo_module.get_nfo_data(file_info.file_path, NUMBER)
        assert loaded is not None
        # 读取模式拿到的 title 本身就是已渲染标题（含 release/number）
        assert loaded.title == RENDERED_TITLE
        # 原样记录 NFO 里的标题，供编辑窗口所见即所得展示
        assert loaded.nfo_title == RENDERED_TITLE
        await nfo_module.write_nfo(
            file_info,
            loaded,
            nfo_file,
            tmp_path,
            update=True,
            skip_merge=True,
            title_override=loaded.nfo_title,
        )
        assert _read_title(nfo_file) == RENDERED_TITLE, "标题里的 release/number 不允许重复出现"


@pytest.mark.asyncio
async def test_nfo_title_override_written_verbatim(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """title_override：标题栏显示什么就原样写入什么，不再套命名模板。"""
    _configure(monkeypatch)
    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    nfo_file = tmp_path / f"{NUMBER}.nfo"

    await nfo_module.write_nfo(
        file_info,
        _build_data(),
        nfo_file,
        tmp_path,
        update=True,
        skip_merge=True,
        title_override="我手动改的标题",
    )
    assert _read_title(nfo_file) == "我手动改的标题"


@pytest.mark.asyncio
async def test_nfo_title_without_override_stays_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """不传 title_override 时（NFO 文件管理等入口），已渲染的标题也不应被二次渲染。"""
    _configure(monkeypatch, main_mode=5)
    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    nfo_file = tmp_path / f"{NUMBER}.nfo"

    await nfo_module.write_nfo(file_info, _build_data(), nfo_file, tmp_path, update=True, skip_merge=True)
    loaded, _info = await nfo_module.get_nfo_data(file_info.file_path, NUMBER)
    assert loaded is not None

    # 已渲染的标题再次保存（走默认渲染路径）
    await nfo_module.write_nfo(file_info, loaded, nfo_file, tmp_path, update=True, skip_merge=True)
    assert _read_title(nfo_file) == RENDERED_TITLE


def test_build_nfo_title_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """build_nfo_title：已渲染标题原样返回，纯标题按模板渲染一次。"""
    _configure(monkeypatch)
    file_info = _build_file_info(tmp_path)

    # 纯标题 → 渲染成最终标题
    assert nfo_module.build_nfo_title(file_info, _build_data(PURE_TITLE)) == RENDERED_TITLE
    # 已渲染标题 → 原样返回（不再叠加 release/number）
    assert nfo_module.build_nfo_title(file_info, _build_data(RENDERED_TITLE)) == RENDERED_TITLE
    # 反复调用结果一致
    assert nfo_module.build_nfo_title(file_info, _build_data(RENDERED_TITLE)) == nfo_module.build_nfo_title(
        file_info, _build_data(RENDERED_TITLE)
    )


def test_decompose_rendered_title(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """decompose_rendered_title：按模板结构把已渲染标题还原成纯标题。"""
    _configure(monkeypatch)
    file_info = _build_file_info(tmp_path)
    data = _build_data()
    options = NameRenderOptions(target=NamingTarget.NFO_TITLE)

    assert decompose_rendered_title(RENDERED_TITLE, TEMPLATE, file_info, data, options) == PURE_TITLE
    # 与标题无关的文本原样返回
    assert decompose_rendered_title("随便一个标题", TEMPLATE, file_info, data, options) == "随便一个标题"


def test_editor_title_text_is_wysiwyg(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """编辑 NFO 窗口标题栏：优先展示 NFO 里已有的标题，否则展示当前标题数据。"""
    from mdcx.controllers.main_window.nfo_editor import NfoEditorMixin

    _configure(monkeypatch)
    file_info = _build_file_info(tmp_path)

    # NFO 里已有标题 → 原样展示（所见即所得）
    data = _build_data(RENDERED_TITLE)
    data.nfo_title = RENDERED_TITLE
    assert NfoEditorMixin._nfo_title_text(file_info, data) == RENDERED_TITLE

    # 没有已有标题（首次刮削）→ 展示当前标题数据，保存时再按命名模板渲染
    data = _build_data(PURE_TITLE)
    data.nfo_title = ""
    assert NfoEditorMixin._nfo_title_text(file_info, data) == PURE_TITLE


def test_editor_title_to_save_is_wysiwyg(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """编辑 NFO 窗口保存：NFO 里已有标题时原样回写，不重复叠加 release/number。"""
    from mdcx.controllers.main_window.nfo_editor import NfoEditorMixin

    _configure(monkeypatch)
    file_info = _build_file_info(tmp_path)

    # 已有标题 → 原样回写，绝不变成 "2024-09-25 FC2-4541879 2024-09-25 FC2-4541879 【挑逗】"
    data = _build_data(RENDERED_TITLE)
    data.nfo_title = RENDERED_TITLE
    assert NfoEditorMixin._nfo_title_to_save(file_info, data, RENDERED_TITLE) == RENDERED_TITLE

    # 用户改了标题 → 改后的内容原样写入
    assert NfoEditorMixin._nfo_title_to_save(file_info, data, "我手动改的标题") == "我手动改的标题"

    # 还没有 NFO 标题 → 按命名模板渲染一次（保留 release/number 前缀）
    data = _build_data(PURE_TITLE)
    data.nfo_title = ""
    assert NfoEditorMixin._nfo_title_to_save(file_info, data, PURE_TITLE) == RENDERED_TITLE


@pytest.mark.asyncio
async def test_editor_save_keeps_title_length(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """端到端：读回 NFO → 用标题栏内容保存 → 再读回，标题不得变长。"""
    from mdcx.controllers.main_window.nfo_editor import NfoEditorMixin

    _configure(monkeypatch, main_mode=5)
    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    nfo_file = tmp_path / f"{NUMBER}.nfo"

    await nfo_module.write_nfo(file_info, _build_data(), nfo_file, tmp_path, update=True, skip_merge=True)
    assert _read_title(nfo_file) == RENDERED_TITLE

    for _ in range(3):
        loaded, _info = await nfo_module.get_nfo_data(file_info.file_path, NUMBER)
        assert loaded is not None
        shown = NfoEditorMixin._nfo_title_text(file_info, loaded)
        assert shown == RENDERED_TITLE
        to_save = NfoEditorMixin._nfo_title_to_save(file_info, loaded, shown)
        assert to_save == RENDERED_TITLE
        await nfo_module.write_nfo(
            file_info,
            loaded,
            nfo_file,
            tmp_path,
            update=True,
            skip_merge=True,
            title_override=to_save,
        )
        assert _read_title(nfo_file) == RENDERED_TITLE, "反复保存后标题不允许重复出现"
