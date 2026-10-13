"""Playwright + Edge（msedge 通道）CF bypass 后端。

async 原生实现：直接跑在事件循环里，不占用线程池。
``channel="msedge"`` 复用系统已安装的 Edge，无需 ``playwright install``
下载浏览器包（约 170MB）。

在 javlibrary 浏览器 bypass 链里是第二顺位：Selenium+Edge 先试，
失败（JS 重渲染页 / Selenium 顶不住的 challenge）再到这里。
playwright 与 tenacity 都是可选依赖，首次使用自动 pip 安装；
无 Edge 环境优雅降级，连续失败 3 次进入 5 分钟冷却。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
import time

from .selenium_adapter import _is_edge_available, is_cf_html

logger = logging.getLogger(__name__)

# 连续失败冷却配置（与 selenium_adapter 对齐）
_MAX_CONSECUTIVE_FAILURES = 3
_COOLDOWN_SECONDS = 300.0  # 5 分钟

_EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)

# 运行时状态
_consecutive_failures = 0
_cooldown_until = 0.0
_checked = False
_available = False
_state_lock = threading.Lock()


def _retry_twice():
    """tenacity 重试装饰器（goto 瞬时失败最多重放 1 次）。

    tenacity 是可选依赖：缺失时退化为直通（不重试），保证旧环境
    不装新依赖也能 import 本模块。
    """
    try:
        from tenacity import retry, stop_after_attempt, wait_fixed

        return retry(stop=stop_after_attempt(2), wait=wait_fixed(2), reraise=True)
    except ImportError:

        def _passthrough(fn):
            return fn

        return _passthrough


def _ensure_deps() -> bool:
    """确保 playwright 已安装，返回是否可用（缺失自动 pip 安装）。"""
    try:
        import playwright.async_api  # noqa: F401

        return True
    except ImportError:
        pass
    # tenacity 自身也可能缺失，这里不用它（鸡生蛋问题），手写两次尝试
    for attempt in (1, 2):
        try:
            logger.info("playwright 未安装，正在自动安装...（尝试 %d/2）", attempt)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "tenacity"])
            import playwright.async_api  # noqa: F401

            logger.info("playwright 安装完成")
            return True
        except Exception as e:
            logger.warning("playwright 自动安装失败: %s", e)
    return False


def is_available() -> bool:
    """检查 Playwright bypass 是否可用（Edge + playwright）。

    首次调用时检测，结果缓存。
    """
    global _checked, _available
    if not _checked:
        _available = _is_edge_available() and _ensure_deps()
        _checked = True
        if not _available:
            logger.info("Playwright bypass 不可用（无 Edge 或 playwright 安装失败）")
    return _available


async def _goto_once(page, url: str, timeout_ms: int) -> None:
    """打开页面（单次，不重试）。"""
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)


async def _goto(page, url: str, timeout_ms: int) -> None:
    """打开页面；导航层瞬时异常（超时/连接重置）由 tenacity 重放一次。

    重试装饰器每次调用时解析：tenacity 若在模块 import 后才装上（如自动安装），
    同进程后续调用同样生效（import 时固化的装饰器则不行，Bug 1）。
    """
    await _retry_twice()(_goto_once)(page, url, timeout_ms)


async def _get_html_async(url: str, timeout: int) -> tuple[str | None, dict[str, str]]:
    """用 Playwright+Edge 获取页面 HTML 与 cookie，轮询等待 CF 挑战消失。"""
    from playwright.async_api import async_playwright

    async with async_playwright() as driver:
        browser = await driver.chromium.launch(
            channel="msedge",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=_EDGE_UA,
                viewport={"width": 1920, "height": 1080},
                locale="ja-JP",
            )
            page = await context.new_page()
            # 总超时从导航开始起算：goto 与 CF 等待共享 timeout 预算（Bug 3）
            deadline = time.monotonic() + timeout
            try:
                remaining_ms = max(int(deadline - time.monotonic()) * 1000, 1000)
                await _goto(page, url, remaining_ms)
            except Exception as e:
                logger.debug("Playwright goto 失败: %s", e)
                return None, {}
            try:
                html = await page.content()
            except Exception as e:
                logger.debug("Playwright 首屏读取失败: %s", e)
                return None, {}
            while is_cf_html(html) and time.monotonic() < deadline:
                await asyncio.sleep(3)
                try:
                    html = await page.content()
                except Exception:
                    break
            cookies: dict[str, str] = {}
            try:
                for item in await context.cookies() or []:
                    name = str(item.get("name") or "")
                    if name:
                        cookies[name] = str(item.get("value") or "")
            except Exception as e:
                logger.debug("Playwright 取 cookie 失败: %s", e)
            return html, cookies
        finally:
            try:
                await browser.close()
            except Exception:
                pass


def _incr_failures() -> None:
    """记录一次失败；达到阈值进入冷却（并发安全）。"""
    global _consecutive_failures, _cooldown_until
    with _state_lock:
        _consecutive_failures += 1
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            _cooldown_until = time.monotonic() + _COOLDOWN_SECONDS
            logger.warning(
                "Playwright bypass 连续失败 %d 次，进入 %.0f 秒冷却期",
                _consecutive_failures,
                _COOLDOWN_SECONDS,
            )


def _reset_failures() -> None:
    """成功时清零失败计数（并发安全）。"""
    global _consecutive_failures
    with _state_lock:
        _consecutive_failures = 0


async def get_html(url: str, timeout: int = 90) -> str | None:
    """用 Playwright+Edge 获取页面 HTML，自动过 CF。

    Args:
        url: 目标 URL
        timeout: 页面加载 + 等待挑战消失总超时秒数

    Returns:
        过 CF 后的页面 HTML，失败返回 None
    """
    html, _ = await get_html_and_cookies(url, timeout)
    return html


async def get_html_and_cookies(url: str, timeout: int = 90) -> tuple[str | None, dict[str, str]]:
    """单次浏览器会话获取页面 HTML 与 cookie（供后续直连请求透传，省一次解挑战）。

    Returns:
        (过 CF 后的页面 HTML, 浏览器 cookie 字典)，失败返回 (None, {})
    """
    if not is_available():
        return None, {}

    now = time.monotonic()
    if now < _cooldown_until:
        logger.debug("Playwright bypass 冷却中，跳过")
        return None, {}

    try:
        html, cookies = await _get_html_async(url, timeout)
    except Exception as e:
        logger.warning("Playwright bypass 异常: %s", e)
        _incr_failures()
        return None, {}
    if not html or is_cf_html(html):
        logger.warning("Playwright bypass: CF 挑战未通过")
        _incr_failures()
        return None, {}
    _reset_failures()
    return html, cookies
