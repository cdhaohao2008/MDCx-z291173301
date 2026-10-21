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
        # 这里不能立刻构造 AsyncOpenAI：它会在构造时建立 httpx.AsyncClient，
        # 而 httpx 直到建立传输层才导入 httpcore。配置加载路径上的 Computed()
        # 一旦因此抛 ModuleNotFoundError，会被 ConfigManager.load() 误判成
        # 「配置文件验证失败」并切到 _failed.json（2026-10-21 实测：
        # 未安装 httpcore 的环境下，仅改 UI 文案也会被误认为配置损坏）。
        # 因此统一推迟到第一次真正翻译时再建客户端；空 Key 时 ask() 会给出
        # 明确提示。这样配置加载不再依赖可选网络栈。
        self._api_key = api_key
        self._base_url = base_url
        self._proxy = proxy
        self._timeout = timeout
        self.client: AsyncOpenAI | None = None
        self._client_lock = threading.Lock()
        self.limiter = AsyncLimiter(*rate)
        self._closed = False
        self._close_requested = False
        self._active_requests = 0
        self._active_lock = asyncio.Lock()
        self._lease_lock = threading.Lock()
        self._leases = 0

    def _ensure_client(self) -> AsyncOpenAI | None:
        """首次翻译时才创建 OpenAI 客户端，避免配置加载阶段依赖 httpcore。

        AsyncOpenAI 构造时会建立 httpx.AsyncClient，而 httpx 在创建传输层时
        才导入 httpcore。把这一步推迟到真正发请求，可让缺少 httpcore 的环境
        仍能正常加载配置、浏览、刮削（只是翻译不可用），而不是误切 _failed.json。
        """
        if not self._api_key or not self._api_key.strip():
            return None
        if self.client is not None:
            return self.client
        if self._closed:
            raise RuntimeError("LLM 客户端已关闭")
        with self._client_lock:
            if self.client is None:
                self.client = AsyncOpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    http_client=AsyncClient(proxy=self._proxy, timeout=self._timeout, follow_redirects=True),
                    timeout=self._timeout,
                )
        return self.client

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
        try:
            client = self._ensure_client()
        except Exception as e:
            # httpcore/httpx 等网络栈缺失只影响翻译，不应影响配置加载和其他功能
            log_fn(f"❌ LLM 客户端初始化失败，已跳过本次翻译: {e}\n")
            return None
        if client is None:
            # 未配置密钥时给出可执行的提示，而不是让整轮翻译静默失败
            log_fn("💡 未配置 LLM API 密钥，已跳过本次翻译（请在设置页填写密钥后再试）")
            return None
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
