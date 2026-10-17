"""`cf_bypass_trusted_hosts`（设置页「Cloudfleare 校验服务」）输入校验的回归测试。

这个字段是**静默误伤**高发区：配错平时不报错，只有真走 Bypass 时才拒收响应，
用户看到的是「昨天能刮的站今天全 403」。所以校验逻辑必须与运行时
`AsyncWebClient._is_trusted_bypass_landing` 严格同源，旧 UI 示例也必须被当场拦下。

只测纯函数（`mdcx/utils/cf_bypass_hosts.py`），不碰 Qt。
"""

from mdcx.utils.cf_bypass_hosts import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_OK,
    entry_matches_host,
    split_host_entries,
    validate_cf_bypass_hosts,
)

_KNOWN = frozenset({"www.javbus.com", "javdb.com", "www.dmm.co.jp", "c0.jdbstatic.com"})


def _messages(report):
    return " | ".join(report.messages)


# ---------------------------------------------------------------- 解析规则


def test_split_matches_runtime_normalization():
    """绿：切分规则必须与 AsyncWebClient.__init__ 的三行一致（strip + lower + 丢空）。

    运行时是 `for entry in (text or "").split(",")`，再 `strip().lower()`，空串丢弃。
    这里若少一步归一化，就会出现「界面校验通过、运行时不认」。
    """
    assert split_host_entries(" JavBus.com , ,*.JavDB.com,,") == ["javbus.com", "*.javdb.com"]
    assert split_host_entries(None) == []
    assert split_host_entries("   ") == []


def test_entry_matches_host_mirrors_runtime_rule():
    """绿：匹配规则与 `_is_trusted_bypass_landing` 完全一致。

    通配 `*.example.com` 只匹配子域，**不含裸域名本身**；精确项只匹配全等，
    且落地域名按 `urlsplit().hostname` 取（无端口、已小写）。
    """
    assert entry_matches_host("*.javbus.com", "www.javbus.com") is True
    assert entry_matches_host("*.javbus.com", "javbus.com") is False
    assert entry_matches_host("javbus.com", "javbus.com") is True
    assert entry_matches_host("javbus.com", "www.javbus.com") is False
    assert entry_matches_host("javbus.com", "JAVBUS.COM") is True
    assert entry_matches_host("*.javbus.com", "WWW.JAVBUS.COM") is True
    assert entry_matches_host("javbus.com", "") is False


# ---------------------------------------------------------------- 空值 / 正常


def test_empty_input_is_ok():
    """绿：留空 = 不校验 = 默认合法，不该报任何问题。

    绝大多数用户就是留空，界面不该一上来就给警告。
    """
    report = validate_cf_bypass_hosts("", known_domains=_KNOWN)
    assert report.level == LEVEL_OK
    assert report.issues == []
    assert "留空" in report.text


def test_valid_entries_pass():
    """绿：裸域 + 通配两条齐全时零问题。"""
    report = validate_cf_bypass_hosts("javbus.com,*.javbus.com", known_domains=_KNOWN)
    assert report.level == LEVEL_OK, _messages(report)
    assert report.issues == []


# ---------------------------------------------------------------- 必抓的错


def test_wildcard_without_bare_domain_is_error():
    """红：只写 `*.javdb.com` 漏掉裸域名 → 报错。

    这是照抄旧 placeholder 的直接后果：裸域 `javdb.com`（mdcx/crawlers/javdb.py）
    会被拒收。历史上没有任何提示，用户只能等 Bypass 真拒收时才发现。
    """
    report = validate_cf_bypass_hosts("*.javdb.com", known_domains=_KNOWN)
    assert report.level == LEVEL_ERROR
    assert "不含javdb.com本身" in _messages(report), _messages(report)


def test_old_placeholder_example_is_now_rejected():
    """红：旧 UI 示例 `JavBus.com,*.JavDB.com` 必须被即时校验拦下。

    两条恰好都踩反：`JavBus.com` 漏掉实际用的 `www.javbus.com`，`*.JavDB.com`
    匹配不到裸域 `javdb.com`。用户是照着 placeholder 抄的，所以必须在输入时就红。
    """
    report = validate_cf_bypass_hosts("JavBus.com,*.JavDB.com", known_domains=_KNOWN)
    assert report.level == LEVEL_ERROR
    assert "*.javdb.com" in _messages(report)


def test_malformed_entries_are_errors():
    """红：带协议/路径/端口、单级域名、空通配、非法 label、数字顶级标签都当场报错。

    运行时只做 `host == pattern` / `host.endswith(...)` 比较，这些写法匹配不到任何
    真实落地域名，等于静默失效。
    """
    cases = [
        ("https://javbus.com", "协议"),
        ("javbus.com/en", "路径"),
        ("javbus.com:8080", "端口"),
        ("javbus", "两级"),
        ("*.", "通配符后面没有域名"),
        ("jav_bus.com", "不是合法域名字段"),
        ("javbus.123", "纯数字"),
    ]
    for text, expect in cases:
        report = validate_cf_bypass_hosts(text, known_domains=_KNOWN)
        assert report.level == LEVEL_ERROR, f"{text!r} 未报错：{_messages(report)}"
        assert expect in _messages(report), f"{text!r} 提示不含「{expect}」：{_messages(report)}"


def test_duplicate_entries_are_errors():
    """红：大小写/空格不同但归一化后相同的条目只生效一次，应提示重复。"""
    report = validate_cf_bypass_hosts("JavBus.com, javbus.com", known_domains=_KNOWN)
    assert report.level == LEVEL_ERROR
    assert "重复" in _messages(report)


# ---------------------------------------------------------------- 提醒级


def test_unknown_entry_is_info_not_error():
    """黄：对不上已知站点域名只能是提醒，不能是错误。

    Bypass 可能重定向到镜像/CDN（如 javdb 图片的 `jdbstatic.com`），这类域名不在
    爬虫默认域名里但完全合法；若把它判成错误，用户会为了消警告去删掉必要条目。
    """
    report = validate_cf_bypass_hosts("jdbstatic.com", known_domains=frozenset({"www.javbus.com"}))
    assert report.level == LEVEL_INFO, _messages(report)
    assert "jdbstatic.com" in _messages(report)


def test_no_known_domains_skips_the_info_hint():
    """绿：拿不到已知域名（crawlers 导入失败）时不做「未知条目」提示。

    宁可少提示，也不要把合法条目误报成错。
    """
    report = validate_cf_bypass_hosts("something.example", known_domains=frozenset())
    assert report.level == LEVEL_OK, _messages(report)


def test_broader_wildcard_still_counts_as_known():
    """绿：比已知域名更宽的通配也算对得上，不该被误报成「对不上已知站点域名」。

    `*.co.jp` 能命中已知域名 `www.dmm.co.jp`；这里配套写 `co.jp` 是因为通配本身
    不含裸域，缺了它会另报一条 ERROR（那是独立的一条反馈，见
    `test_wildcard_without_bare_domain_is_error`）。
    """
    report = validate_cf_bypass_hosts("co.jp,*.co.jp", known_domains=_KNOWN)
    assert report.level == LEVEL_OK, _messages(report)
