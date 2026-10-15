"""CF Bypass 落地域名校验名单（`cf_bypass_trusted_hosts`）的解析与输入校验。

定位：这个字段**不是**「哪些站点不走 Bypass」的名单，而是 Bypass 跑完之后用来校验
「响应最终落在哪个域名」的 allowlist（`AsyncWebClient._is_trusted_bypass_landing`）。
Bypass 对全局自动生效，本名单只在已经走完 Bypass 之后做减法：落地域名不命中就拒收。

所以配错的后果是**静默误伤**——平时不命中 CF 挑战页就不校验、不报错，只有真走
Bypass 时才拒收，症状是「昨天能刮的站今天全 403」。本模块把这层反馈提前到输入框：
改一个纯函数，不依赖 Qt，可直接单测。

两条要点（都与运行时 `_is_trusted_bypass_landing` 严格同源，改动务必同步）：
- `*.example.com` 只匹配子域，**不含裸域名本身**，要全覆盖得写两条；
- 落地域名来自 Bypass 服务的响应，第三方服务被劫持/投毒时会把恶意页面当数据写入
  NFO，这才是这个字段存在的理由。

已知站点域名只从爬虫类的静态属性拼（`_domains` / `base_url_()`），**全程不触网**：
动态域名站的 `check_urls()` 会去抓发布页/GitHub 首页，那是网络检测的活，不能放进
每次按键都会跑一次的路径。取不到就返回空集合，此时「未知条目」告警降级为不提示，
而不是把合法条目误报成错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# 单个主机名 label：字母数字与连字符，首尾不能是连字符，长度 1..63（RFC 1035 通用做法）。
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# 问题级别，按严重程度递增。
LEVEL_OK = "ok"
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"

_LEVEL_ORDER = {LEVEL_OK: 0, LEVEL_INFO: 1, LEVEL_WARN: 2, LEVEL_ERROR: 3}

# 已知站点域名缓存：爬虫注册表在进程内不变，算一次即可。
_known_domains_cache: frozenset[str] | None = None


@dataclass(frozen=True)
class CFBypassHostIssue:
    """一条校验反馈。

    entry: 命中的条目（去空格、小写后）；全局级问题为空串。
    message: 给人看的中文说明，直接可放进 QLabel。
    level: LEVEL_ERROR / LEVEL_WARN / LEVEL_INFO。
    """

    entry: str
    message: str
    level: str

    @property
    def weight(self) -> int:
        return _LEVEL_ORDER.get(self.level, 0)


@dataclass
class CFBypassHostsReport:
    """整框输入的校验结果。"""

    entries: list[str] = field(default_factory=list)
    issues: list[CFBypassHostIssue] = field(default_factory=list)
    known_domains: frozenset[str] = frozenset()

    @property
    def level(self) -> str:
        """整框最高级别；没有条目时回到 LEVEL_OK（留空 = 不校验 = 合法默认）。"""
        if not self.entries:
            return LEVEL_OK
        return max((i.level for i in self.issues), key=lambda lv: _LEVEL_ORDER.get(lv, 0), default=LEVEL_OK)

    @property
    def messages(self) -> list[str]:
        return [f"{i.entry}：{i.message}" if i.entry else i.message for i in self.issues]

    @property
    def text(self) -> str:
        """拼成 QLabel 的多行正文；无问题时给一句状态。"""
        if not self.entries:
            return "状态：留空不校验（默认）"
        if not self.issues:
            return f"状态：{len(self.entries)}条格式正确，均能对上已知站点域名"
        return "\n".join(f"· {m}" for m in self.messages)


def split_host_entries(text: str | None) -> list[str]:
    """按运行时同样的规则切分条目（逗号分隔 → strip → lower → 丢弃空串）。

    与 `AsyncWebClient.__init__` 里解析 `cf_bypass_trusted_hosts` 的三行保持一致：
    这里多返回一份「原始写法」用于报错定位，真正参与匹配的仍是归一化后的值。
    """
    return [normalized for _raw, normalized in split_host_entry_pairs(text)]


def split_host_entry_pairs(text: str | None) -> list[tuple[str, str]]:
    """切分条目并保留原始写法，返回 [(原始写法, 归一化条目)]。

    归一化规则必须与 `AsyncWebClient.__init__` 解析 `cf_bypass_trusted_hosts` 的三行
    完全一致（`split(",")` → `strip()` → `lower()` → 丢弃空串），否则这里校验通过、
    运行时却不认，等于白校验一次。
    """
    pairs: list[tuple[str, str]] = []
    for raw in (text or "").split(","):
        normalized = raw.strip().lower()
        if normalized:
            pairs.append((raw.strip(), normalized))
    return pairs


def is_wildcard(entry: str) -> bool:
    return entry.startswith("*.")


def entry_matches_host(entry: str, host: str) -> bool:
    """`entry` 能否命中 `host`，规则与 `_is_trusted_bypass_landing` 一致。

    `*.example.com` → host.endswith(".example.com")（不含裸域名）；
    `example.com`  → host == "example.com"。
    """
    host = (host or "").strip().lower()
    if not host:
        return False
    if is_wildcard(entry):
        return host.endswith(entry[1:])
    return host == entry


def host_of(url: str) -> str:
    """取 URL 的 hostname（小写）；解析失败或无主机名时返回空串。"""
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def known_site_domains(*, refresh: bool = False) -> frozenset[str]:
    """所有已注册爬虫的已知主机名（小写、去重）。

    只读静态属性：`_domains`（镜像域名列表）+ `base_url_()`（默认地址）。**不触网**——
    动态域名站的 `check_urls()` 要去抓发布页，那是网络检测的活。

    任意一步失败都退化为「少几个已知域名」而不是抛错：拿不到就返回空集合，此时
    `validate_cf_bypass_hosts` 会跳过「未知条目」提示，不会把合法条目误报成错。
    """
    global _known_domains_cache
    if _known_domains_cache is not None and not refresh:
        return _known_domains_cache

    domains: set[str] = set()

    def _add(url: str) -> None:
        host = host_of(url)
        if host:
            domains.add(host)

    try:
        from ..crawlers import get_crawler, get_registered_crawler_sites

        for site in get_registered_crawler_sites(include_hidden=True):
            crawler_cls = get_crawler(site)
            if crawler_cls is None:
                continue
            for url in getattr(crawler_cls, "_domains", None) or []:
                _add(str(url))
            try:
                _add(str(crawler_cls.base_url_()))
            except Exception:
                # Official 等路由类爬虫的 base_url_() 可能依赖实例状态，取不到就算了。
                pass
    except Exception:
        # crawlers 包导入失败（依赖缺失/裁剪安装）时静默降级为「没有已知站点」。
        pass

    _known_domains_cache = frozenset(domains)
    return _known_domains_cache


def _entry_problem(entry: str) -> str | None:
    """条目本身的写法问题（不涉及已知域名对照），返回错误说明或 None。"""
    body = entry[2:] if is_wildcard(entry) else entry
    if not body:
        return "通配符后面没有域名"
    if "://" in entry or "/" in entry or ":" in entry or "@" in entry:
        return "只填域名，不要带协议、路径、端口或账号"
    labels = body.split(".")
    if len(labels) < 2:
        return "至少需要两级域名，例如javbus.com"
    bad = [label for label in labels if not _HOST_LABEL.match(label)]
    if bad:
        return f"「{'.'.join(bad)}」不是合法域名字段"
    if labels[-1].isdigit():
        return "顶级标签不能是纯数字"
    return None


def _entry_matches_known(entry: str, known: frozenset[str]) -> bool:
    """条目能否在已知站点域名里找到对应的主机（允许条目比已知域名更宽）。

    - `javbus.com` 对上 `www.javbus.com`（裸域名是已知域名的父级）；
    - `*.javbus.com` 对上 `www.javbus.com`（通配命中子域）；
    - `*.co.jp` 对上 `www.dmm.co.jp`（更宽的通配也算对得上）。
    """
    body = entry[2:] if is_wildcard(entry) else entry
    for host in known:
        if host == body or host.endswith("." + body):
            return True
    return False


def validate_cf_bypass_hosts(
    text: str | None,
    *,
    known_domains: frozenset[str] | None = None,
) -> CFBypassHostsReport:
    """校验整框输入，返回结构化反馈。

    报什么：
    - ERROR  写法非法的条目（带协议/路径/端口、单级域名等）
    - ERROR  `*.x.com` 却没写 `x.com`——通配不含裸域名，这正是照抄错示例后
               「该拦的没拦住」的静默坑
    - ERROR  归一化后重复的条目（`JavBus.com` 与 `javbus.com` 同时出现）
    - INFO   对不上任何已知站点域名的条目——**只是提醒不是错误**：Bypass 可能
             重定向到镜像/CDN（如 javdb 图片的 `jdbstatic.com`），那不在爬虫
             默认域名里但完全合法
    """
    pairs = split_host_entry_pairs(text)
    report = CFBypassHostsReport(entries=[normalized for _raw, normalized in pairs])
    if not pairs:
        return report
    # 只在真有输入时才去解析已知站点域名：首次调用要 import 整个 crawlers 包，
    # 而设置页一开就刷新一次，空框不该为一句占位文案付这个开销。
    report.known_domains = known_domains if known_domains is not None else known_site_domains()

    seen: dict[str, str] = {}
    valid: list[str] = []
    for raw, entry in pairs:
        problem = _entry_problem(entry)
        if problem:
            report.issues.append(CFBypassHostIssue(entry=raw or entry, message=problem, level=LEVEL_ERROR))
            continue
        valid.append(entry)
        if entry in seen:
            report.issues.append(
                CFBypassHostIssue(
                    entry=entry,
                    message=f"与前面写的「{seen[entry]}」重复（大小写、空格不计），只会生效一次",
                    level=LEVEL_ERROR,
                )
            )
        else:
            seen[entry] = raw or entry

    # 通配缺裸域名：只在通配项本身写法合法时提示（否则叠一条噪音），且同一条目只报一次。
    reported = {i.entry for i in report.issues}
    for entry in valid:
        if not is_wildcard(entry) or entry in reported:
            continue
        base = entry[2:]
        if base in seen:
            continue
        report.issues.append(
            CFBypassHostIssue(
                entry=entry,
                message=f"通配只匹配子域不含{base}本身，若要一起覆盖请再补一条{base}",
                level=LEVEL_ERROR,
            )
        )

    unknown = [e for e in valid if not _entry_matches_known(e, report.known_domains)]
    if report.known_domains and unknown:
        report.issues.append(
            CFBypassHostIssue(
                entry="",
                message=f"{'、'.join(unknown)}这些条目对不上任何已知站点域名；"
                "如果它们是镜像/CDN域名可以忽略，否则该站走Bypass时会被拒收",
                level=LEVEL_INFO,
            )
        )

    return report
