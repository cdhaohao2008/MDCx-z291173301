import asyncio
import contextlib
import logging
import re
import threading
import time
from collections.abc import Callable
from urllib.parse import urlparse

from aiolimiter import AsyncLimiter
from httpx import AsyncClient, Timeout
from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletionMessageParam

logger = logging.getLogger(__name__)

# 各服务商「关闭思考」参数（翻译类任务无需慢思考，且部分服务商默认开启极烧 token）
# key 为 hostname 子串匹配，value 为注入到 extra_body 的参数字典。
# 未收录的服务商不下发任何参数，跟随模型默认行为。
_DISABLE_THINKING_PARAMS: list[tuple[str, dict]] = [
    ("siliconflow.cn", {"enable_thinking": False}),  # 硅基流动
    ("dashscope.aliyuncs.com", {"enable_thinking": False}),  # 阿里百炼 compatible-mode
    ("aliyuncs.com", {"enable_thinking": False}),
    ("volces.com", {"thinking": {"type": "disabled"}}),  # 火山方舟
    ("ollama", {"think": False}),  # Ollama openai-compat
    ("generativelanguage.googleapis.com", {"reasoning_effort": "none"}),  # Gemini openai-compat
]


def get_disable_thinking_extra_body(base_url: str) -> dict | None:
    """按服务商地址返回关闭思考的 extra_body 参数；未收录的服务商返回 None（不下发）。"""
    host = urlparse(base_url).hostname or ""
    host = host.lower()
    for pattern, params in _DISABLE_THINKING_PARAMS:
        if pattern in host:
            return dict(params)
    return None


def _is_unsupported_param_error(e: Exception, extra_body: object) -> bool:
    """判断 4xx 是否为 extra_body 参数不支持（用于去参重试）。

    仅在返回体里出现参数名时确认，避免把普通的 400（如超长输入）误判为参数问题。
    """
    if not isinstance(e, BadRequestError) or not extra_body:
        return False
    text = str(e).lower()
    try:
        params = list(extra_body) if isinstance(extra_body, dict) else []  # type: ignore[arg-type]
    except Exception:
        params = []
    if any(str(k).lower() in text for k in params):
        return True
    # 常见兼容性表述
    return any(k in text for k in ("unknown parameter", "unsupported parameter", "unexpected keyword", "extra_body"))


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,  # https://api.openai.com/v1
        proxy: str | None = None,
        timeout: Timeout,
        rate: tuple[float, float],
    ):
        # 未填 API Key 时**绝不能**构造 AsyncOpenAI：OpenAI SDK 会当场抛
        # OpenAIError("Missing credentials")，而本对象是在 Computed() 里、
        # 即 ConfigManager 加载配置的路径上同步构造的——一旦抛错，第一次会被
        # load() 的 except Exception 抓住并回退到 _replace_config(Config())，
        # 那里又用同样的空 Key 再抛一次，而这次已无人接管，整个
        # `manager = ConfigManager()` 模块级实例化直接失败，软件连启动都进不去
        # （用户 2026-10-19 实测：源码运行 main.py 即崩）。改为惰性留空，
        # 真正用到翻译时再在 ask() 里明确报「未配置密钥」。
        self.client: AsyncOpenAI | None = None
        if api_key and api_key.strip():
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True),
                timeout=timeout,
            )
        self.limiter = AsyncLimiter(*rate)
        self._closed = False
        self._close_requested = False
        self._active_requests = 0
        self._active_lock = asyncio.Lock()
        self._lease_lock = threading.Lock()
        self._leases = 0

    def retain(self) -> None:
        with self._lease_lock:
            if self._closed:
                raise RuntimeError("LLM 客户端已关闭")
            self._leases += 1

    async def release(self) -> None:
        with self._lease_lock:
            if self._leases > 0:
                self._leases -= 1
        if self._close_requested:
            await self._close_if_idle()

    def _lease_count(self) -> int:
        with self._lease_lock:
            return self._leases

    async def _begin_request(self) -> None:
        async with self._active_lock:
            if self._closed:
                raise RuntimeError("LLM 客户端已关闭")
            self._active_requests += 1

    async def _end_request(self) -> None:
        async with self._active_lock:
            self._active_requests = max(self._active_requests - 1, 0)

    async def _is_idle(self) -> bool:
        async with self._active_lock:
            return self._active_requests == 0 and self._lease_count() == 0

    async def _close_if_idle(self) -> bool:
        if not await self._is_idle():
            return False
        await self.close()
        return True

    async def close_when_idle(self, *, poll_interval: float = 0.2, timeout: float = 300.0) -> None:
        """等待进行中的请求与持有方结束后关闭。

        `timeout` 是兜底上限，避免租约泄漏时无限轮询导致旧客户端永久驻留（议题 #55）。
        """
        self._close_requested = True
        deadline = time.monotonic() + timeout if timeout > 0 else None
        while not await self._is_idle():
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning(
                    "LLM 客户端等待空闲超过 %.0f 秒仍未空闲（残留租约 %d），强制关闭",
                    timeout,
                    self._lease_count(),
                )
                break
            await asyncio.sleep(poll_interval)
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._close_requested = True
        self._closed = True
        with contextlib.suppress(Exception):
            if self.client is not None:
                await self.client.close()

    async def ask(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        max_try: int,
        log_fn: Callable[[str], None] = lambda _: None,
        extra_body: object | None = None,
    ) -> str | None:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.client is None:
            # 未配置密钥时给出可执行的提示，而不是让整轮翻译静默失败
            log_fn("💡 未配置 LLM API 密钥，已跳过本次翻译（请在设置页填写密钥后再试）")
            return None
        client = self.client
        wait = 1
        body = extra_body
        chat = None
        await self._begin_request()
        try:
            async with self.limiter:
                for _ in range(max(0, max_try)):
                    try:
                        chat = await client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            extra_body=body,
                        )
                        break
                    except Exception as e:
                        # 参数兼容性错误（如服务商不支持 enable_thinking）：去掉参数重试一次
                        if body is not None and _is_unsupported_param_error(e, body):
                            log_fn(f"⚠️ LLM 参数不被支持 ({e})，去掉 extra_body 重试")
                            body = None
                            continue
                        log_fn(f"⚠️ LLM API 请求失败: {e}, {wait}s 后重试")
                        await asyncio.sleep(wait)
                        wait *= 2
                else:
                    log_fn("❌ LLM API 请求失败, 已达最大重试次数\n")
                    return None
        finally:
            await self._end_request()
        # reasoning_content = getattr(chat.choices[0].message, "reasoning_content", None)
        try:
            choices = getattr(chat, "choices", None) or []
            if not choices:
                log_fn("❌ LLM 返回为空（choices 为空）\n")
                return None
            text = choices[0].message.content
        except Exception as e:
            log_fn(f"❌ LLM 返回解析失败: {e}\n")
            return None
        # 移除 cot
        if text:
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text
