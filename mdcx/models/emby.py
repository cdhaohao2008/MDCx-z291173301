import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

# 议题 #145: 宽松匹配各种合法生日写法（1990-1-2 / 1990/1/2 / 1990.1.2 / 1990年1月2日 / 19900102）。
# 允许非零填充，月/日交给 date() 做真实日历校验；不锚定结尾，忽略尾部时间等多余内容。
_DATE_TEXT_RE = re.compile(r"^(\d{4})\s*[-/.\s年]\s*(\d{1,2})\s*[-/.\s月]\s*(\d{1,2})\s*日?")
_DATE_COMPACT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


def normalize_premiere_date(value: object) -> str | None:
    """生日归一化为服务器可解析的 ISO 时间串，无法构成合法日期时返回 None。

    接受 1990-1-2 / 1990/1/2 / 1990.1.2 / 1990年1月2日 / 19900102 等写法（议题 #145），
    补零并用真实日历校验后输出 Emby/Jellyfin DTO 规范格式。哨兵 "0000-xx-xx"、
    空值、截断串、越界日期（13 月 / 2 月 30 等）返回 None，调用方据此省略 PremiereDate
    （议题 #126）。返回 None 而非空串，避免模型绑定 DateTime 时再报 400。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("0000"):
        return None
    match = _DATE_TEXT_RE.match(text) or _DATE_COMPACT_RE.match(text)
    if match is None:
        return None
    try:
        year, month, day = (int(part) for part in match.groups())
        date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00.0000000Z"


def normalize_production_year(value: object) -> int | None:
    """年份字段归一化为正整数；哨兵 "0000"、非数字、非正数一律视为空（议题 #126）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        year = int(value.strip())
        return year if year > 0 else None
    return None


# 议题 #149/#171: 演员简介历史噪声清洗。minnano 占位文案是「占位→判缺→重抓→
# 再写占位」死循环的根源, 需清除。`===== 个人资料/外部链接 =====` 段落标题与
# 换行是 wiki 源拼接的合法结构, 客户端(Emby/Jellyfin)按其渲染分行列表; #171
# 实证: 把换行/段标题一并压成逗号会毁掉 Jellyfin 端排版, 故仅清占位文案。
# 清洗出口收口在模型层, 管理器「数据清洗」按钮(存量)与 dump()/update_person_info
# (增量)共用, 保证未来写入不再产生占位噪声。
_OVERVIEW_PLACEHOLDER_RE = re.compile(r"无维基百科信息\s*[,，]\s*从\s*minnano-av\s*数据库补全女优信息")


def apply_overview_clean_rules(value: object, rules: object = None) -> str:
    """在 clean_overview_text 内置清洗之上, 再按用户自定义替换规则逐条做字面量子串替换。

    rules 为 (原始数值, 替换数值) 二元组序列(兼容 config 存盘的 list[list[str]] 形态);
    原始数值为空/非字符串的行视为无效直接跳过, 替换数值非字符串时按空串处理。
    无有效规则时等价于 clean_overview_text, 保证旧调用与测试口径不变。
    """
    return _apply_text_clean_rules(clean_overview_text(value), rules)


def _apply_text_clean_rules(text: str, rules: object = None) -> str:
    """按用户自定义替换规则对**已内置清洗**的文本逐条做字面量子串替换（公共实现）。

    拆分自 apply_overview_clean_rules：简介与标签共用同一条规则链，只是各自
    的「内置清洗」入口不同。非法规则行（无法解包 / 原始数值非空串 / 替换数值
    非字符串按空串）的跳过口径集中在这里, 保证两条路径行为一致。
    """
    if not isinstance(text, str) or not text or not rules:
        return text
    try:
        # rules 的静态类型刻意放宽为 object（config 存盘形态不可信，可能传标量/None）；
        # 可迭代性由下面的 TypeError 兜底在运行时判定，这里 cast 只是让类型检查
        # 接受 list() 调用，不改变任何运行时行为。
        items = list(cast("Iterable[Any]", rules))
    except TypeError:
        return text
    for item in items:
        try:
            original, replacement = item
        except TypeError, ValueError:
            continue
        if not isinstance(original, str) or not original:
            continue
        if not isinstance(replacement, str):
            replacement = ""
        if original in text:
            text = text.replace(original, replacement)
    return text


def apply_tagline_clean_rules(taglines: object, rules: object = None) -> list[str]:
    """按同一套替换规则清洗演员标签(Taglines), 语义与 apply_overview_clean_rules 一致。

    标签与简介共用清洗口径: 先过 clean_overview_text(内置 minnano 占位清洗,
    占位文案同样可能出现在标签里), 再叠加用户规则。清洗结果两端去空白——字面量
    替换常把「噪声词」连同其一侧空格吃掉, 留下「 标签」这种前导空格标签, 而标签
    是短词条, 首尾空白纯属噪声; 内部空白原样保留。清洗后为空/纯空白的标签直接
    丢弃——「替换数值为空即删除该片段」对标签而言就是整条删除, 写回服务器空标签
    会被当作脏数据。非字符串元素跳过; 入参非列表(字符串/None 等)一律返回空列表,
    调用方拿到的一定是可直接写入 payload 的 list[str]。
    """
    if not isinstance(taglines, (list, tuple)):
        return []
    result: list[str] = []
    for item in taglines:
        if not isinstance(item, str):
            continue
        cleaned = _apply_text_clean_rules(clean_overview_text(item), rules).strip()
        if cleaned:
            result.append(cleaned)
    return result


def clean_overview_text(value: object) -> str:
    """清洗演员简介历史噪声（议题 #149/#171），无噪声时原样返回；非字符串输入返回空串。

    仅删 minnano 占位文案（整段清除，占位前后若有合法内容则保留）。`<br>`/换行/
    `=====` 段标题属 wiki 源合法结构, 客户端按其渲染分行, 原样保留不压平。
    函数幂等：清洗结果再清洗不变。
    """
    if not isinstance(value, str):
        return ""
    return _OVERVIEW_PLACEHOLDER_RE.sub("", value)


@dataclass
class EMbyActressInfo:
    name: str
    server_id: str
    id: str
    birthday: str = "0000-00-00"
    year: str = "0000"
    overview: str = ""
    taglines: list = field(default_factory=list)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    provider_ids: dict = field(default_factory=dict)
    taglines_translate: bool = False
    locations: list = field(default_factory=list)

    def dump(self) -> dict:
        # 此处生成的 json 符合 emby/jellyfin 规范；
        # 日期/年份在模型层统一归一化，内置补全与管理器同步共用同一出口（议题 #126/#145）。
        return {
            "Name": self.name,
            "ServerId": self.server_id,
            "Id": self.id,
            "Genres": self.genres,
            "Tags": self.tags,
            "ProviderIds": self.provider_ids,
            "ProductionLocations": self.locations,
            "PremiereDate": normalize_premiere_date(self.birthday),
            "ProductionYear": normalize_production_year(self.year),
            # 议题 #149: 简介出口统一清洗(段落标题/<br>/占位文案), 增量写入不再产生噪声
            "Overview": clean_overview_text(self.overview),
            "Taglines": self.taglines,
        }
