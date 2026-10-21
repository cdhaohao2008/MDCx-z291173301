"""演员数据清洗规则与展示文本的纯业务逻辑（不依赖 Qt）。

从 :mod:`mdcx.tools.emby_actor_manager_ui` 抽出的无界面依赖部分：清洗替换规则的
默认值/归一化/持久化，详情列表格展示文本，以及「哪些演员的数据需要清洗」的判定。
替换规则同时作用于简介(Overview)与标签(Taglines)，两条路径共用同一清洗口径。

规则有三层，层层兜底：**生效规则**(用户点「确定」/编辑完成自动保存的
``actor_clean_rules``) ⊇ **用户默认**(规则窗点「保存默认」存下的
``actor_clean_rules_default``，没存过就是内置出厂 ``DEFAULT_CLEAN_RULES``)
⊇ 内置出厂。任何一层都不会让下一层的规则丢失，用户保存过默认之后他自定义的规则
也就跟着始终保留。两条 minnano 占位文案规则自 v2.7.2 起不再是内置默认，也不再把
用户删掉的行补回来。

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
    ("Japanese AV actress", "日本AV女优"),
    ("American pornographic actress", "美国色情女演员"),
    ("American pornographic performer", "美国色情演员"),
    ("Brazilian pornographic actress", "巴西色情女演员"),
]
"""**内置出厂**默认替换规则: 四条 wiki 源英文身份文案译为中文, 始终保留。

这四条是**译名**而非删噪声——wiki 源的 Overview/Taglines 会带
"Japanese AV actress" 这类英文身份短语, 中文界面读着别扭, 替换成对应中文词条,
故由 `_ensure_default_clean_rules` 统一兜底(用户删掉也会补回)。

两条 ``无维基百科信息, 从 minnano-av 数据库补全女优信息`` /
``无维基百科信息，从 minnano-av 数据库补全女优信息`` 曾经固定置顶并随默认保存,
自 v2.7.2 起按用户要求**不再是默认规则**: 既不进内置出厂、也不在「保存默认」时
补回或置顶, 用户删掉后不会再出现。存量配置里这两条由配置迁移一次性清理(只清
替换值为空的出厂形态, 用户改过替换值的保留)。

注意这是**出厂兜底**: 用户可在规则窗点「保存默认」覆盖成自己编辑的那一份
(存 `Config.actor_clean_rules_default`), 本常量始终只作兜底底座, 见
`load_default_clean_rules`。
"""


def _ensure_default_clean_rules(
    cleaned: list[tuple[str, str]],
    defaults: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """补齐默认规则: 缺失的默认原始数值追加到末尾, 已有条目保持原顺序与替换值不变。

    保证「默认规则始终保留」——用户误删后下次加载/保存自动补回(内置英文身份
    四条; 用户覆盖过默认则补的是他保存的那份, 故 `defaults` 传入
    `load_default_clean_rules` 的结果)。已有条目即便用户改过替换值也原样保留,
    只按「原始数值」判重, 故用户主动改写过的规则不会被默认值覆盖回去。
    """
    baseline = DEFAULT_CLEAN_RULES if defaults is None else defaults
    existing = {original for original, _ in cleaned}
    result = list(cleaned)
    for original, replacement in baseline:
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
        except TypeError, ValueError:
            continue
        if not isinstance(original, str) or not original.strip():
            continue
        if not isinstance(replacement, str):
            replacement = ""
        cleaned.append((original, replacement))
    return cleaned


def _dedupe_clean_rules(rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """按原始数值合并重复行: 保留首次出现的位置, 替换值取最后一条(``dict()`` 语义)。"""
    latest = dict(rules)
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for original, _ in rules:
        if original in seen:
            continue
        seen.add(original)
        result.append((original, latest[original]))
    return result


def _normalize_default_clean_rules(rules: object) -> list[tuple[str, str]]:
    """「保存默认」的归一化口径: 清洗入参 → 合并重复原始数值 → 补齐内置默认。

    即用户存下的默认规则里, 内置英文身份四条缺失也补齐(追加在用户自定义规则
    之后), 用户自建规则原样保留。两条 minnano 占位规则自 v2.7.2 起不再补回。
    """
    return _ensure_default_clean_rules(_dedupe_clean_rules(_sanitize_clean_rules(rules)))


def load_default_clean_rules(config: Config) -> list[tuple[str, str]]:
    """读出「恢复默认」该填的规则: 用户点过「保存默认」就用他保存的那份, 否则用内置出厂。

    存盘形态同样走 `_normalize_default_clean_rules` 归一化, 保证旧/非法/空存盘
    都能补齐内置英文四条; 读不到配置时兜底为 `DEFAULT_CLEAN_RULES`。
    """
    try:
        saved = _sanitize_clean_rules(config.actor_clean_rules_default)
    except Exception:
        return list(DEFAULT_CLEAN_RULES)
    if not saved:
        return list(DEFAULT_CLEAN_RULES)
    return _normalize_default_clean_rules(saved)


def save_default_clean_rules(rules: object, manager: ConfigManager) -> list[tuple[str, str]]:
    """把规则窗当前编辑的替换规则存成「默认规则」, 返回归一化后的结果。

    只改默认(`Config.actor_clean_rules_default`), **不动当前生效的**
    `actor_clean_rules`——生效规则由规则窗编辑完成时的自动保存或点「确定」写入。
    失败时静默返回归一化结果(与 `save_clean_rules` 同一口径)。
    """
    cleaned = _normalize_default_clean_rules(rules)
    try:
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_clean_rules_default = [[o, r] for o, r in cleaned]
        manager._replace_config(cfg)
        manager.save()
    except Exception:
        pass
    return cleaned


def load_clean_rules(config: Config) -> list[tuple[str, str]]:
    """读出上次保存的清洗替换规则; 无配置/非法时返回默认规则, 缺失的默认条目自动补齐。

    数据清洗窗口弹出时默认加载本函数返回值, 故首开即见内置英文身份四条。
    补齐的底座是 `load_default_clean_rules`(用户保存过默认就是他那份, 否则内置
    出厂), 故「保存默认」定的规则集在生效规则里同样始终保留。两条 minnano 占位
    规则自 v2.7.2 起不再参与补齐。
    """
    try:
        return _ensure_default_clean_rules(
            _sanitize_clean_rules(config.actor_clean_rules), load_default_clean_rules(config)
        )
    except Exception:
        return list(DEFAULT_CLEAN_RULES)


def save_clean_rules(rules: object, manager: ConfigManager) -> list[tuple[str, str]]:
    """持久化用户确认的清洗替换规则, 返回归一化后的规则。失败时静默返回归一化结果。

    保存时自动补齐缺失的默认规则, 保证默认规则(用户保存过就是他那份, 否则内置
    英文身份四条)始终保留。两条 minnano 占位规则自 v2.7.2 起不再自动补回。
    """
    cleaned = _ensure_default_clean_rules(_sanitize_clean_rules(rules), load_default_clean_rules(manager.config))
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
