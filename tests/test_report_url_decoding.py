"""报告/调试日志里的链接不该再是百分号转义的机器形态。

用户 2026-10-19 实测三处：

1. Getchu 探测行里带 `btnWordSearch=%B8%A1%BA%F7` 的搜索 URL（EUC-JP 转义）；
2. 爬虫调试行 `DL Getchu 搜索地址: …` 原样打印同一个 URL；
3. 页面指纹 `页面标题=…ご利用になれません。 - FANZA` 里夹着空格。

三条都在「给人看的文本」这一层收敛：链接统一 `unquote`（EUC-JP/Shift_JIS 这类
非 UTF-8 站点编码解不出汉字，得到 U+FFFD 替换符是既定口径，见
`mdcx/utils/url_display.py`），页面指纹的标题一律剔除空白。
"""

from types import SimpleNamespace

import pytest

from mdcx.config.enums import Website
from mdcx.core import network_check as nc
from mdcx.core.network_check import NetworkCheckSpec, NetworkCheckStatus
from mdcx.crawlers.base import Context, CrawlerException
from mdcx.crawlers.base.base import _page_fingerprint
from mdcx.models.model_types import CrawlerInput
from mdcx.utils.url_display import decode_url_escapes

_GETCHU_SEARCH_URL = (
    "https://dl.getchu.com/search/search_list.php?dojin=1&search_category_id="
    "&search_keyword=AIV&btnWordSearch=%B8%A1%BA%F7&action=search&set_category_flag=1"
)
_GETCHU_SEARCH_URL_DECODED = (
    "https://dl.getchu.com/search/search_list.php?dojin=1&search_category_id="
    "&search_keyword=AIV&btnWordSearch=\ufffd\ufffd\ufffd\ufffd&action=search&set_category_flag=1"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --------------------------------------------------------------------------- #
# decode_url_escapes 本体
# --------------------------------------------------------------------------- #
def test_decode_url_escapes_restores_getchu_search_url():
    """Getchu DL 搜索 URL：EUC-JP 转义还原成 U+FFFD 替换符（该口径即用户要的形态）。"""
    assert decode_url_escapes(_GETCHU_SEARCH_URL) == _GETCHU_SEARCH_URL_DECODED


def test_decode_url_escapes_restores_utf8_escapes():
    """UTF-8 转义（javbus/javdb 系）还原成真汉字。"""
    assert decode_url_escapes("https://x.test/s?keyword=%E3%83%A6%E3%83%8B%E3%82%B8") == (
        "https://x.test/s?keyword=ユニジ"
    )


def test_decode_url_escapes_restores_space_escape():
    """`%20` 还原成空格：faleno 实测的 `?s=fns%20165` 形态。"""
    assert decode_url_escapes("GET https://faleno.jp/top/?s=fns%20165 失败: HTTP 403") == (
        "GET https://faleno.jp/top/?s=fns 165 失败: HTTP 403"
    )


def test_decode_url_escapes_leaves_non_url_text_untouched():
    """只动链接：正文里的 `%XX`、Windows 路径、代理串原样保留。"""
    text = "命中 100% 命中率，见 D:\\%20cache 与 http://127.0.0.1:7890"
    assert decode_url_escapes(text) == text


def test_decode_url_escapes_is_identity_without_escapes():
    """无转义 / 空串都是恒等变换，调用方不必先判断。"""
    assert decode_url_escapes("") == ""
    assert decode_url_escapes("https://www.getchu.com/php/search.phtml?gc=gc") == (
        "https://www.getchu.com/php/search.phtml?gc=gc"
    )


def test_decode_url_escapes_handles_multiple_links_in_one_line():
    """一行里多个链接都要还原，不能只处理第一个。"""
    assert decode_url_escapes("a https://a.test/?k=%E3%81%82 b https://b.test/?k=%E3%81%84") == (
        "a https://a.test/?k=あ b https://b.test/?k=い"
    )


# --------------------------------------------------------------------------- #
# 网络检测报告行
# --------------------------------------------------------------------------- #
def test_clean_probe_error_decodes_url_escapes():
    """刮削探测行的「{方法} {url} 失败」段里，转义要还原。"""
    cleaned = nc._clean_probe_error(f"GET {_GETCHU_SEARCH_URL} 失败: HTTP 403")
    assert cleaned == f"GET {_GETCHU_SEARCH_URL_DECODED} 失败: HTTP 403"


def test_clean_probe_error_keeps_prefix_split_intact():
    """还原发生在拆前缀之后：带空格的解码结果不能把 `GET {url} 失败` 段拆散。"""
    cleaned = nc._clean_probe_error("GET https://faleno.jp/top/?s=fns%20165 失败: HTTP 403")
    assert cleaned == "GET https://faleno.jp/top/?s=fns 165 失败: HTTP 403"


def test_clean_probe_error_decodes_url_in_detail_part():
    """细节段里的链接（无 `{方法} {url} 失败` 前缀的那种）同样还原。"""
    cleaned = nc._clean_probe_error(f"搜索失败: 请求失败: GET {_GETCHU_SEARCH_URL} 失败: HTTP 403")
    assert _GETCHU_SEARCH_URL not in cleaned
    assert _GETCHU_SEARCH_URL_DECODED in cleaned


def test_compose_failed_message_decodes_url_escapes():
    """联网检测行（`{方法} {url} 失败：…` 版式）同样还原。"""
    composed = nc._compose_failed_message("连接超时，请检查网络或代理节点", f"GET {_GETCHU_SEARCH_URL} 失败: x")
    assert _GETCHU_SEARCH_URL_DECODED in composed
    assert "%B8%A1%BA%F7" not in composed


@pytest.mark.anyio
async def test_probe_crawler_by_run_decodes_search_url():
    """回退 `_run` 探测（Getchu 走的正是这条路）：聚合串里的链接还原后进报告。"""

    class _Crawler:
        async def run(self, input_data):
            error = f"请求错误:GET {_GETCHU_SEARCH_URL} 失败: HTTP 429"
            return SimpleNamespace(data=None, debug_info=SimpleNamespace(error=error))

    status, message = await nc._probe_crawler_by_run(_Crawler(), SimpleNamespace(number="AIV"), 30.0)

    assert status == NetworkCheckStatus.WARNING
    assert _GETCHU_SEARCH_URL_DECODED in message
    assert "%B8%A1%BA%F7" not in message


@pytest.mark.anyio
async def test_probe_crawler_capability_crawler_exception_decodes_url(monkeypatch: pytest.MonkeyPatch):
    """爬虫自抛的 CrawlerException 内嵌搜索 URL 时，探测行同样还原。"""

    class _Crawler:
        def __init__(self, client, base_url="", browser=None):
            self.base_url = base_url

        def new_context(self, input_data):
            return SimpleNamespace(input=input_data)

        async def _generate_search_url(self, ctx):
            raise CrawlerException(f"请求错误:GET {_GETCHU_SEARCH_URL} 失败: HTTP 403")

    monkeypatch.setattr("mdcx.crawlers.get_crawler", lambda site: _Crawler)
    spec = NetworkCheckSpec(
        name="Getchu", group="动漫里番", url="https://dl.getchu.com", site=Website.GETCHU, probe_number="AIV"
    )

    status, message = await nc._probe_crawler_capability(SimpleNamespace(), spec, 30.0)

    assert status == NetworkCheckStatus.WARNING
    assert message.startswith("站点可达但刮削探测失败: ")
    assert _GETCHU_SEARCH_URL_DECODED in message
    assert "%B8%A1%BA%F7" not in message


def test_probe_transient_markers_survive_decoding():
    """还原不破坏瞬时/确定性分类用的标记词。"""
    assert nc._is_transient_probe_result(f"站点可达但搜索页请求失败: GET {_GETCHU_SEARCH_URL_DECODED} 失败: HTTP 500")
    assert not nc._is_transient_probe_result(
        "站点可达但刮削探测失败: 番号搜索页被站点人机验证拦截，verifybot/reCAPTCHA"
    )


# --------------------------------------------------------------------------- #
# 爬虫调试日志
# --------------------------------------------------------------------------- #
def test_context_debug_decodes_url_escapes():
    """爬虫调试消息里的搜索 URL 还原（`DL Getchu 搜索地址: …` 走的正是这条路）。"""
    ctx = Context(input=CrawlerInput.empty())
    ctx.debug(f"DL Getchu 搜索地址: {_GETCHU_SEARCH_URL}")

    assert ctx.debug_info.logs == [f"DL Getchu 搜索地址: {_GETCHU_SEARCH_URL_DECODED}"]


def test_context_debug_keeps_plain_messages_untouched():
    """无链接的调试消息原样保留。"""
    ctx = Context(input=CrawlerInput.empty())
    ctx.debug("搜索页未找到 pro ID")

    assert ctx.debug_info.logs == ["搜索页未找到 pro ID"]


# --------------------------------------------------------------------------- #
# 页面指纹：标题不留空白
# --------------------------------------------------------------------------- #
def test_page_fingerprint_strips_whitespace_from_title():
    """DMM 地域封锁页标题 `…ません。 - FANZA` 的空格要被剔除。"""
    html = "<html><head><title>このページはお住まいの地域からご利用になれません。 - FANZA</title></head><body>x</body></html>"
    fingerprint = _page_fingerprint(html)

    assert "页面标题=このページはお住まいの地域からご利用になれません。-FANZA" in fingerprint
    assert " - " not in fingerprint


def test_page_fingerprint_strips_newlines_and_tabs():
    """换行/制表符同样剔除：指纹是单行标识，不能把报告面板撑成多行。"""
    html = "<html><head><title>\n\tMDX-0236 - Search \n</title></head><body>x</body></html>"
    assert _page_fingerprint(html).startswith("页面标题=MDX-0236-Search,")


def test_page_fingerprint_without_title_unchanged():
    """没有 `<title>` 的页面维持「无」。"""
    assert _page_fingerprint("<html>empty</html>") == "页面标题=无, 正文长度=18"


def test_page_fingerprint_keeps_body_length_and_truncation():
    """空白剔除不影响正文长度统计与 80 字截断。"""
    html = "<html><head><title>" + "a" * 200 + "</title></head><body>x</body></html>"
    fingerprint = _page_fingerprint(html)

    assert f"页面标题={'a' * 80}," in fingerprint
    assert f"正文长度={len(html)}" in fingerprint
