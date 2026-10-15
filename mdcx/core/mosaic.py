"""Backwards-compatible alias for :mod:`mdcx.models.mosaic`.

The implementation lives in ``mdcx.models.mosaic`` because the mosaic label
vocabulary is shared data understood by the crawler layer, the core business
layer and the controllers.  Keeping it there means no layer has to import
upwards to reach it.

This module is intentionally kept so that existing importers of
``mdcx.core.mosaic`` keep working unchanged.
"""

from __future__ import annotations

from ..models.mosaic import (
    CENSORED_MOSAIC,
    GUOCHAN_MOSAIC,
    LEAK_MOSAIC,
    UMR_MOSAIC,
    UNCENSORED_LEAK_MOSAIC,
    UNCENSORED_MOSAIC,
    has_leak_mark,
    has_umr_mark,
    has_uncensored_mark,
    is_censored_mosaic,
    is_guochan_mosaic,
    is_plain_uncensored_mosaic,
    normalize_mosaic,
)

__all__ = [
    "CENSORED_MOSAIC",
    "GUOCHAN_MOSAIC",
    "LEAK_MOSAIC",
    "UMR_MOSAIC",
    "UNCENSORED_LEAK_MOSAIC",
    "UNCENSORED_MOSAIC",
    "has_leak_mark",
    "has_umr_mark",
    "has_uncensored_mark",
    "is_censored_mosaic",
    "is_guochan_mosaic",
    "is_plain_uncensored_mosaic",
    "normalize_mosaic",
]


def __getattr__(name: str):
    """把其余名字（含私有名）原样转发到实现模块。"""
    from ..models import mosaic as _impl

    return getattr(_impl, name)
