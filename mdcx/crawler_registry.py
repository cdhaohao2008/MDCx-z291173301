"""爬虫站点注册表（中立层，零 mdcx 内部依赖）。

问题：`Website` 枚举与 `Config` 的 JSON Schema 需要在生成时列出「已注册的爬虫站点」，
而站点清单由 `mdcx/crawlers` 拥有。此前 config 层直接 `from mdcx.crawlers import ...`，
造成层级倒置（config 是被 crawlers 依赖的底层，却反向依赖 crawlers）。

做法：把「谁提供站点清单」变成一个可注入的钩子。
- `mdcx/crawlers/__init__.py` 在导入时调用 `register_site_values_provider(...)`；
- config 层只调用 `registered_site_values()`，读不到提供者时返回空列表
  （与此前 try/except 失败分支的行为完全一致）。

这样两侧都只依赖本模块，谁先导入都不会产生循环，且不改变任何对外行为。
"""

from __future__ import annotations

from collections.abc import Callable

# (include_hidden: bool) -> list[str]
_SiteValuesProvider = Callable[..., list[str]]

_provider: _SiteValuesProvider | None = None


def register_site_values_provider(provider: _SiteValuesProvider) -> None:
    """由 crawlers 层在导入时注册站点清单提供者。"""
    global _provider
    _provider = provider


def registered_site_values(*, include_hidden: bool = False) -> list[str]:
    """返回已注册的爬虫站点清单；未注册（crawlers 尚未导入）时返回空列表。"""
    if _provider is None:
        return []
    try:
        return list(_provider(include_hidden=include_hidden))
    except Exception:
        return []
