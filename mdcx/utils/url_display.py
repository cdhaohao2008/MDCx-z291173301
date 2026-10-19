"""URL 展示用的转义还原（纯函数叶子模块）。

爬虫拼搜索 URL 时，查询串一律按站点编码做百分号转义（Getchu 系是 EUC-JP、
JavBus/JavDB 是 UTF-8），这些 URL 会原样进检测报告与调试日志。用户看到的是
`btnWordSearch=%B8%A1%BA%F7` 这种机器形态——同样的信息换成人能读的写法却是
`btnWordSearch=检索`。故凡是「给人看的文本」在成文时统一还原一次。

为什么用 `unquote` 的默认参数：EUC-JP / Shift_JIS 这类非 UTF-8 站点编码的字节
按 UTF-8 解不出来（`unquote` 默认 `errors="replace"`），得到的是一串 U+FFFD
替换符。这不是解码失败后的兜底蒙混，而是既定的展示口径——那串字节对用户本就
不可读，能对齐的只是「同一个链接、同一处转义」，比让人猜 `%B8%A1%BA%F7` 是
哪个汉字要强。

注意：本模块只用于**展示**。真正发出去的请求仍拿拼好的原始 URL（转义是站点
要求），改这里的输出不会影响任何一次实际请求。
"""

import re
from urllib.parse import unquote

# 只认 http(s) 链接：日志里还有代理地址、文件路径、正则片段等其他 `%XX` 形态，
# 那些不是链接编码，动了反而改坏原文。`\S+` 一路吃到空白为止（URL 本身不含空白），
# 结尾可能粘上中文标点，`unquote` 对它们是恒等变换，不影响。
_URL_RE = re.compile(r"https?://\S+")


def decode_url_escapes(text: str) -> str:
    """把文本里所有 http(s) 链接的百分号转义还原成字符，其余内容原样保留。

    命中不了链接（含空串）时是恒等变换，调用方无需先判断有没有链接。
    """
    if not text or "%" not in text:
        return text
    return _URL_RE.sub(lambda m: unquote(m.group(0)), text)
