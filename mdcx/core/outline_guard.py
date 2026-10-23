"""简介/原简介占位值识别与清理。

站点把「販売日（发行日期）」或「もっとみる（看更多）」当成简介文本返回时，
NFO 里就会出现 `发行日期 2025-11-13` / `看更多` 这种零信息量的"简介"。用户要求
（2026-10-24）：这类值一律视为没有简介——先去其他站点取真正的简介，取不到就
保持为空，绝不允许把发行日期或「看更多」写进 NFO。

判定采用"剥掉标签与日期后是否还剩实质内容"的方式，而不是写死几条完整文本：
站点的日期标签有繁简/日文/英文多种写法，日期本身也有 `2025-11-13`、
`2025/11/13`、`2025.11.13`、`2025年11月13日` 等变体，穷举字符串必然漏。
"""

import re
import unicodedata

# 发行日期类标签（简繁 + 日文 + 英文）。刻意不含裸 "日期"：中文简介里
# "发行日期" 已被覆盖，裸 "日期" 容易误伤正文。
_RELEASE_LABEL_PATTERN = (
    r"(?:发行日期|發行日期|发行日|發行日|发售日期|發售日期|发售日|發售日|上市日期|上架日期|"
    r"販売日|発売日|配信日|公開日|発売開始日|リリース日|リリース|"
    r"release\s*date|released\s*date|released|release|date)"
)

# 日期本体：年月日（含中文/斜杠/点/短横线分隔）、年-月、月/日/年
_DATE_PATTERN = (
    r"(?:\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
    r"|\d{4}\s*[-/.]\s*\d{1,2}"
    r"|\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{4})"
)

# 只剩这些字符时视为"没有实质内容"
_FILLER_CHARS = set(" \t\r\n\u3000:：,，.。;；-—_/\\|()（）[]【】<>《》\"'“”‘’·、~～!！?？*#")

# 「看更多」类占位（原文常见的"展开全文"链接文本）
_READ_MORE_LABELS = {
    "看更多",
    "查看更多",
    "查看更多内容",
    "查看更多內容",
    "看更多内容",
    "看更多內容",
    "展开全文",
    "展開全文",
    "もっとみる",
    "もっと見る",
    "続きを読む",
    "続きを見る",
    "see more",
    "read more",
    "show more",
    "weiterlesen",
}

# 长标签优先，避免「查看更多」先被「查看」类短标签吃掉（当前集合里无前缀冲突，
# 仍按长度倒序排列，后续加词不会踩坑）
_READ_MORE_PATTERN = (
    "(?:" + "|".join(re.escape(label) for label in sorted(_READ_MORE_LABELS, key=len, reverse=True)) + ")"
)


def _strip_placeholder_tokens(text: str) -> str:
    """剥掉发行日期标签、日期本体与「看更多」链接文本，返回剩余文本。

    三者一起去掉才能识别 `发行日期 2025-11-13\\n看更多` 这种"日期 + 展开链接"
    拼起来的简介——FC2 页面把两者放在同一个区块里，站点抓下来就是这两行。
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(_RELEASE_LABEL_PATTERN, " ", text, flags=re.IGNORECASE)
    text = re.sub(_DATE_PATTERN, " ", text)
    return re.sub(_READ_MORE_PATTERN, " ", text, flags=re.IGNORECASE)


def _has_substance(text: str) -> bool:
    return any(ch not in _FILLER_CHARS for ch in text)


def is_placeholder_outline(value: object) -> bool:
    """简介是否是「发行日期 + 日期」这类占位文本（空字符串不算占位）。"""
    text = str(value or "").strip()
    if not text:
        return False
    return not _has_substance(_strip_placeholder_tokens(text))


def is_placeholder_originalplot(value: object) -> bool:
    """原简介是否是「看更多」这类展开链接占位（空字符串不算占位）。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return False
    text = text.strip("：:>》>… .~～").strip().lower()
    return text in _READ_MORE_LABELS


def is_placeholder_plot(value: object) -> bool:
    """简介字段的合并判定：发行日期占位或「看更多」占位都算没有简介。"""
    return is_placeholder_outline(value) or is_placeholder_originalplot(value)


def clear_placeholder_plots(data: object) -> list[str]:
    """把对象上的占位简介/原简介清空，返回被清空的字段中文名（供日志与写回判定）。"""
    cleared: list[str] = []
    if is_placeholder_plot(getattr(data, "outline", "")):
        data.outline = ""  # type: ignore[attr-defined]
        cleared.append("简介")
    if is_placeholder_originalplot(getattr(data, "originalplot", "")):
        data.originalplot = ""  # type: ignore[attr-defined]
        cleared.append("原简介")
    return cleared
