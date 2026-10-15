"""LLM 翻译缓存的兼容再导出（保留旧导入路径）。

实现已下沉到 `mdcx/utils/llm_translate_cache.py`——该模块是不依赖任何 mdcx
内部模块的纯叶子。调用方 `mdcx/base/translate.py` 属于 base 层，此前从
core 层取用属于层级倒置。

新代码请直接 `from mdcx.utils.llm_translate_cache import LLMTranslateCache`；
此处的转出仅为兼容既有导入（含 `tests/test_llm_translate_cache.py`）。
"""

from __future__ import annotations

from ..utils.llm_translate_cache import LLMTranslateCache

__all__ = ["LLMTranslateCache"]


def __getattr__(name: str):
    """把其余名字（含私有名）原样转发到实现模块。"""
    from ..utils import llm_translate_cache as _impl

    return getattr(_impl, name)
