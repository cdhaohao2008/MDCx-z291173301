"""演员数据清洗规则与展示文本的纯业务逻辑（不依赖 Qt）。

从 :mod:`mdcx.tools.emby_actor_manager_ui` 抽出的无界面依赖部分：清洗替换规则的
默认值/归一化/持久化，详情列表格展示文本，以及「哪些演员的数据需要清洗」的判定。
替换规则同时作用于简介(Overview)与标签(Taglines)，两条路径共用同一清洗口径。

UI 模块只保留同名薄壳并把自己的 ``manager`` 传进来，因此
``patch("mdcx.tools.emby_actor_manager_ui.manager", ...)`` 的既有约定不受影响。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..models.emby import apply_overview_clean_rules, apply_tagline_clean_rules, normalize_premiere_date
from .emby_actor_manager import ActorInfo

if TYPE_CHECKING:
    # 仅类型标注，不在运行时引入配置层，保持本模块可独立导入。
    from ..config.manager import ConfigManager
    from ..config.models import Config

DEFAULT_CLEAN_RULES: list[tuple[str, str]] = [
    ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
    ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
    ("Japanese AV actress", "日本AV女优"),
    ("American pornographic actress", "美国色情女演员"),
    ("American pornographic performer", "美国色情演员"),
    ("Brazilian pornographic actress", "巴西色情女演员"),
]
"""数据清洗默认替换规则: 两条 minnano 占位文案(半角/全角逗号)替换为空,
外加四条 wiki 源英文身份文案译为中文, 始终保留。

占位两条是删噪声(整段清空); 英文四条是**译名**而非删噪声——wiki 源的
Overview/Taglines 会带 "Japanese AV actress" 这类英文身份短语, 中文界面读着
别扭, 替换成对应中文词条。两条语义不同, 故合并在一份列表里由
`_ensure_default_clean_rules` 统一兜底(用户删掉也会补回)。
"""


def _ensure_default_clean_rules(
    cleaned: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """补齐默认规则: 缺失的默认原始数值追加到末尾, 已有条目保持原顺序与替换值不变。

    保证「默认规则始终保留」——用户误删后下次加载/保存自动补回(占位两条 +
    英文身份四条)。已有条目即便用户改过替换值也原样保留, 只按「原始数值」
    判重, 故用户主动改写过的规则不会被默认值覆盖回去。
    """
    existing = {original for original, _ in cleaned}
    result = list(cleaned)
    for original, replacement in DEFAULT_CLEAN_RULES:
        if original not in existing:
            result.append((original, replacement))
            existing.add(original)
    return result


def _sanitize_clean_rules(rules: object) -> list[tuple[str, str]]:
    """清洗规则归一化: config 存盘形态(list[list[str]])/用户输入统一成有效 (原始, 替换) 序列。

    原始数值为空或非字符串的行丢弃(空行视为未填完); 替换数值非字符串时按空串处理
    (即删除原始数值)。供对话框回读与扫描口径共用。
    """
    cleaned: list[tuple[str, str]] = []
    if not rules:
        return cleaned
    try:
        # 入参是任意形态（config 存盘 list[list[str]]、用户输入字符串、None），故按 Any 处理；
        # 下面的 try/except TypeError 与 isinstance 兜底才是真正的判据，运行行为不变。
        items: list[Any] = list(rules)  # type: ignore[call-overload]
    except TypeError:
        return cleaned
    for item in items:
        try:
            original, replacement = item
        except (TypeError, ValueError):
            continue
        if not isinstance(original, str) or not original.strip():
            continue
        if not isinstance(replacement, str):
            replacement = ""
        cleaned.append((original, replacement))
    return cleaned


def load_clean_rules(config: Config) -> list[tuple[str, str]]:
    """读出上次保存的清洗替换规则; 无配置/非法时返回默认规则, 缺失的默认条目自动补齐。

    数据清洗窗口弹出时默认加载本函数返回值, 故首开即见全部默认规则(占位两条
    + 英文身份四条)。老配置存盘只有占位两条时, 英文四条自动补齐追加到末尾。
    """
    try:
        return _ensure_default_clean_rules(_sanitize_clean_rules(config.actor_clean_rules))
    except Exception:
        return list(DEFAULT_CLEAN_RULES)


def save_clean_rules(rules: object, manager: ConfigManager) -> list[tuple[str, str]]:
    """持久化用户确认的清洗替换规则, 返回归一化后的规则。失败时静默返回归一化结果。

    保存时自动补齐缺失的默认规则, 保证默认规则(占位两条 + 英文身份四条)始终保留。
    """
    cleaned = _ensure_default_clean_rules(_sanitize_clean_rules(rules))
    try:
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_clean_rules = [[o, r] for o, r in cleaned]
        manager._replace_config(cfg)
        manager.save()
    except Exception:
        pass
    return cleaned


def format_detail_cell_text(overview: object) -> str:
    """详情列表格展示文本：去 <br>/残留标签/占位字符，仅展示层清洗，不改数据。

    - 空、纯空白、“(无)”/“（无）”一律置空（不再显示“（无）”）；
    - “<br>”变体先转空格，再剥除其余 <...> 标签（含截图中的截断“<b...”）；
    - 剥除“(无)”/“（无）”残留与“=”装饰线（“====== 个人资料 ======”只留文字）；
    - 空白坍缩后截断 80 字 + “...”，空结果返回空串。
    """
    if not isinstance(overview, str):
        return ""
    t = overview.strip()
    if not t or t in ("(无)", "（无）", "无"):
        return ""
    t = re.sub(r"(?i)<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]*>", "", t)
    # 残留字面 <br>（标签被截断时尖括号不完整，上面剥不掉）与行尾截断标签（如截图末尾“<b...”）
    t = re.sub(r"(?i)<br\s*/?", " ", t)
    t = re.sub(r"<[^>]*$", "", t)
    for token in ("(无)", "（无）"):
        t = t.replace(token, "")
    t = re.sub(r"={2,}", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or t in ("(无)", "（无）"):
        return ""
    return t[:80] + "..." if len(t) > 80 else t


def scan_actor_data_noise(
    actors: list[ActorInfo], rules: object | None = None
) -> list[tuple[ActorInfo, str, list[str], bool]]:
    """议题 #149: 扫描需要清洗的演员——简介/标签含历史噪声(清洗后有变化)或生日非法(0000-00-00 等)。

    返回 (actor, 清洗后简介, 清洗后标签, 是否重置生日) 四元组; 生日为 Emby 未设置
    零值 0001-01-01 或可被 normalize_premiere_date 正常解析时不算噪声。rules 为用户
    自定义 (原始数值, 替换数值) 序列, 对简介与标签同样生效(标签即表格「标签」列
    展示的 Taglines); 为空时仅走内置清洗(旧口径, 保证测试与兼容)。
    """
    dirty: list[tuple[ActorInfo, str, list[str], bool]] = []
    for a in actors:
        new_overview = apply_overview_clean_rules(a.existing_overview, rules)
        new_taglines = apply_tagline_clean_rules(a.existing_taglines, rules)
        raw_birth = (a.existing_premiere_date or "").strip()
        fix_birth = (
            bool(raw_birth) and not raw_birth.startswith("0001-01-01") and normalize_premiere_date(raw_birth) is None
        )
        if new_overview != (a.existing_overview or "") or new_taglines != list(a.existing_taglines or []) or fix_birth:
            dirty.append((a, new_overview, new_taglines, fix_birth))
    return dirty
