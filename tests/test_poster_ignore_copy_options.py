"""「不裁剪，直接复制缩略图」七个类型档位的结构与行为回归。

背景：设置页「下载」组里每一行都是「复选框 + 绿色提示词」的形式，默认只在有码 /
无码 / 个摄 / 欧美 / 国产五档提供「封面不裁剪，直接复制缩略图」。2.6.1 按用户诉求
补上短剧（FixedScrapingType.SUREN）与动漫（FixedScrapingType.DONGMAN）两档，
位置紧跟国产那一行下方。

这一组选项是「四处同源」的结构，任何一处漏改都会让界面与实际行为对不上：

1. MDCx.ui：复选框 + 绿色提示词两个控件，且必须排在国产行之后；
2. DownloadableFile 枚举：新选项要能存进 download_files 列表；
3. POSTER_COPY_POLICY_MAP：刮削类型 -> 枚举值的映射，命中即复制 thumb；
4. load_config / save_config：配置读写两端的绑定，缺一端就只写不读或只读不写。

这些测试纯离线（解析 XML / 调用纯函数），不依赖网络和完整应用启动。
"""

import json
from pathlib import Path

import pytest
from lxml import etree

from mdcx.config.enums import DownloadableFile, FixedScrapingType
from mdcx.core.web import POSTER_COPY_POLICY_MAP, _get_poster_copy_policy
from mdcx.models.model_types import CrawlersResult

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
TEMPLATE_PATH = REPO / "resources" / "config" / "default_config.json"

# 七档「不裁剪，直接复制缩略图」：(刮削类型, 枚举值, 复选框 objectName, 提示词 objectName, 类型中文名, 提示词文案)
IGNORE_COPY_ROWS = [
    (
        FixedScrapingType.YOUMA,
        DownloadableFile.IGNORE_YOUMA,
        "checkBox_ignore_youma",
        "label_326",
        "有码",
        "有码番号缩略图可以裁剪，如果不想被裁剪可以勾选",
    ),
    (
        FixedScrapingType.WUMA,
        DownloadableFile.IGNORE_WUMA,
        "checkBox_ignore_wuma",
        "label_273",
        "无码",
        "无码封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
    (
        FixedScrapingType.FC2,
        DownloadableFile.IGNORE_FC2,
        "checkBox_ignore_fc2",
        "label_292",
        "个摄",
        "个摄封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
    (
        FixedScrapingType.OUMEI,
        DownloadableFile.IGNORE_OUMEI,
        "checkBox_ignore_oumei",
        "label_ignore_oumei",
        "欧美",
        "欧美封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
    (
        FixedScrapingType.GUOCHAN,
        DownloadableFile.IGNORE_GUOCHAN,
        "checkBox_ignore_guochan",
        "label_305",
        "国产",
        "国产封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
    (
        FixedScrapingType.SUREN,
        DownloadableFile.IGNORE_SUREN,
        "checkBox_ignore_duanju",
        "label_ignore_duanju",
        "短剧",
        "短剧封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
    (
        FixedScrapingType.DONGMAN,
        DownloadableFile.IGNORE_DONGMAN,
        "checkBox_ignore_dongman",
        "label_ignore_dongman",
        "动漫",
        "动漫封面人脸位置不固定，建议手动裁剪或直接复制",
    ),
]

# 「下载」组里那七行复选框所在的垂直布局（新增两行必须插在这个布局里）。
DOWNLOAD_LAYOUT_NAME = "verticalLayout_2"
# 绿色提示词的内联样式，与已有七行完全同口径。
GREEN_LABEL_STYLESHEET = "color: rgb(8, 128, 128);"


def _parse_ui():
    """解析 MDCx.ui，返回 lxml 根元素。"""
    return etree.parse(str(UI_PATH)).getroot()


def _widget_by_name(root, name):
    """按 objectName 取单个控件，找不到返回 None。"""
    found = root.xpath(f"//widget[@name='{name}']")
    assert len(found) == 1, f"{name} 应在 MDCx.ui 中恰好出现一次，实际 {len(found)} 次"
    return found[0]


def _prop_text(widget, prop):
    """取控件某个 <property> 下的字符串值。"""
    nodes = widget.xpath(f"property[@name='{prop}']/string")
    assert len(nodes) == 1, f"{widget.get('name')} 缺少属性 {prop} 或存在多个"
    return nodes[0].text or ""


def _download_layout(root):
    """取「下载」组里的 verticalLayout_2。"""
    layouts = root.xpath(f"//layout[@name='{DOWNLOAD_LAYOUT_NAME}']")
    assert len(layouts) == 1, f"{DOWNLOAD_LAYOUT_NAME} 应恰好存在一次"
    return layouts[0]


@pytest.mark.parametrize(("_s_type", "_enum", "checkbox", "_label", "cn", "_hint"), IGNORE_COPY_ROWS)
def test_ignore_copy_row_shape(_s_type, _enum, checkbox, _label, cn, _hint):
    """每档一行：复选框文案、30px 最小宽度、Fixed/Fixed 尺寸策略。"""
    root = _parse_ui()

    box = _widget_by_name(root, checkbox)
    assert box.get("class") == "QCheckBox"
    assert _prop_text(box, "text") == f"{cn}封面不裁剪，直接复制缩略图"
    minimum = box.xpath("property[@name='minimumSize']/size")[0]
    assert minimum.xpath("string(width)") == "30"
    policy = box.xpath("property[@name='sizePolicy']/sizepolicy")[0]
    assert (policy.get("hsizetype"), policy.get("vsizetype")) == ("Fixed", "Fixed")


@pytest.mark.parametrize(("_s_type", "_enum", "_box", "label", "cn", "hint"), IGNORE_COPY_ROWS)
def test_ignore_copy_hint_style(_s_type, _enum, _box, label, cn, hint):
    """提示词与其它行同样大小格式：Minimum/Fixed + 同样的绿色内联样式 + 同样文案口吻。"""
    root = _parse_ui()

    node = _widget_by_name(root, label)
    assert node.get("class") == "QLabel"
    assert _prop_text(node, "text").strip() == hint
    assert _prop_text(node, "styleSheet") == GREEN_LABEL_STYLESHEET
    policy = node.xpath("property[@name='sizePolicy']/sizepolicy")[0]
    assert (policy.get("hsizetype"), policy.get("vsizetype")) == ("Minimum", "Fixed")
    # 除有码那一行（历史文案不同）外，其余六行统一是「…人脸位置不固定，建议手动裁剪或直接复制」。
    if cn != "有码":
        assert hint == f"{cn}封面人脸位置不固定，建议手动裁剪或直接复制"


def test_duanju_and_dongman_rows_follow_guochan():
    """短剧、动漫两行必须紧跟在国产行之后（用户明确要求的位置）。"""
    root = _parse_ui()
    layout = _download_layout(root)

    order = [item.find("layout").get("name") for item in layout.findall("item") if item.find("layout") is not None]
    assert "horizontalLayout_ignore_duanju" in order
    assert "horizontalLayout_ignore_dongman" in order
    guochan = order.index("horizontalLayout_94")
    assert order[guochan + 1 : guochan + 3] == [
        "horizontalLayout_ignore_duanju",
        "horizontalLayout_ignore_dongman",
    ]


def test_new_rows_hold_both_widgets():
    """两个新布局各含一个复选框 + 一个提示词，避免漏挂控件。"""
    root = _parse_ui()
    for layout_name, checkbox, label in [
        ("horizontalLayout_ignore_duanju", "checkBox_ignore_duanju", "label_ignore_duanju"),
        ("horizontalLayout_ignore_dongman", "checkBox_ignore_dongman", "label_ignore_dongman"),
    ]:
        layout = root.xpath(f"//layout[@name='{layout_name}']")[0]
        names = [w.get("name") for w in layout.xpath(".//widget")]
        assert names == [checkbox, label]


def test_copy_policy_map_covers_every_ignore_row():
    """映射表与七行一一对应，且不含 AUTO（自动判断没有对应复选框）。"""
    assert POSTER_COPY_POLICY_MAP == {s: e for s, e, *_ in IGNORE_COPY_ROWS}
    assert FixedScrapingType.AUTO not in POSTER_COPY_POLICY_MAP


@pytest.mark.parametrize(("scraping_type", "enum_value", "_b", "_l", "_c", "_h"), IGNORE_COPY_ROWS)
def test_get_poster_copy_policy(scraping_type, enum_value, _b, _l, _c, _h):
    """命中对应枚举即返回 True；未勾选（枚举不在列表里）返回 False。"""
    result = CrawlersResult.empty()
    result.scraping_type = scraping_type
    assert _get_poster_copy_policy(result, [enum_value]) is True
    assert _get_poster_copy_policy(result, [DownloadableFile.POSTER]) is False
    # 勾了别的档位不应串档。
    other = next(e for _s, e, *_ in IGNORE_COPY_ROWS if e is not enum_value)
    assert _get_poster_copy_policy(result, [other]) is False


def test_get_poster_copy_policy_auto_type_never_copies():
    """自动判断（AUTO）没有对应复选框，任何配置下都只走选优/直下，不复制缩略图。"""
    result = CrawlersResult.empty()
    result.scraping_type = FixedScrapingType.AUTO
    all_ignores = [enum for _s, enum, *_ in IGNORE_COPY_ROWS]
    assert _get_poster_copy_policy(result, all_ignores) is False


def test_enum_values_and_names_aligned():
    """枚举值、names() 中文名的顺序与七行顺序一致（names() 用于配置项展示）。"""
    values = [enum.value for _s, enum, *_ in IGNORE_COPY_ROWS]
    assert values == [
        "ignore_youma",
        "ignore_wuma",
        "ignore_fc2",
        "ignore_oumei",
        "ignore_guochan",
        "ignore_suren",
        "ignore_dongman",
    ]
    for enum_value in (DownloadableFile.IGNORE_SUREN, DownloadableFile.IGNORE_DONGMAN):
        assert enum_value in DownloadableFile
    assert "忽略短剧" in DownloadableFile.names()
    assert "忽略动漫" in DownloadableFile.names()
    # names() 与枚举成员数量必须一致，否则设置页勾选与展示会对不上。
    assert len(DownloadableFile.names()) == len(list(DownloadableFile))


def test_template_contains_new_options_and_validates():
    """出厂模板默认勾选两个新值，且整份模板仍能通过 Config 校验。"""
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    download_files = template["download_files"]
    assert "ignore_suren" in download_files
    assert "ignore_dongman" in download_files
    # 与国产相邻，保持阅读顺序。
    assert download_files.index("ignore_suren") == download_files.index("ignore_guochan") + 1
    assert download_files.index("ignore_dongman") == download_files.index("ignore_suren") + 1

    from mdcx.config.models import Config

    Config.model_validate(template)


def test_new_options_enabled_by_default():
    """两处出厂默认（Config 字段 default_factory 与出厂模板）都默认勾选短剧/动漫。

    缺任一处都会出问题：只改模板，代码里直接 new Config() 的路径仍是未勾选；
    只改 default_factory，点「重置配置」又会被模板覆盖回未勾选。
    """
    from mdcx.config.models import Config

    factory_defaults = Config().download_files
    for enum_value in (DownloadableFile.IGNORE_SUREN, DownloadableFile.IGNORE_DONGMAN):
        assert enum_value in factory_defaults, f"{enum_value} 未进 Config.download_files 的出厂默认"

    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))["download_files"]
    template_enums = [DownloadableFile(v) for v in template]
    for enum_value in (DownloadableFile.IGNORE_SUREN, DownloadableFile.IGNORE_DONGMAN):
        assert enum_value in template_enums, f"{enum_value} 未进出厂模板的 download_files"


@pytest.mark.parametrize(
    ("module_name", "marker"),
    [
        ("mdcx.controllers.main_window.load_config", "checkBox_ignore_duanju"),
        ("mdcx.controllers.main_window.save_config", "checkBox_ignore_dongman"),
    ],
)
def test_load_and_save_config_bindings(module_name, marker):
    """读写配置两端都要绑定新复选框，且与对应枚举成对出现。"""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module_name))
    assert marker in source
    for enum_name in ("DownloadableFile.IGNORE_SUREN", "DownloadableFile.IGNORE_DONGMAN"):
        assert enum_name in source
