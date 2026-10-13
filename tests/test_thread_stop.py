"""停止机制回归：ctypes 强杀已删除，协作式停止 + run(timeout) 语义锁定。"""

import asyncio
from concurrent.futures import TimeoutError

import pytest

from mdcx import utils
from mdcx.utils import AsyncBackgroundExecutor


def test_kill_helpers_removed():
    """_async_raise / kill_a_thread 必须不存在（协作式停止替代）。"""
    assert not hasattr(utils, "kill_a_thread")
    assert not hasattr(utils, "_async_raise")


def test_executor_run_without_timeout_keeps_old_semantics():
    executor = AsyncBackgroundExecutor()
    try:

        async def fast():
            await asyncio.sleep(0)
            return "ok"

        assert executor.run(fast()) == "ok"
    finally:
        executor._cleanup()


def test_executor_run_timeout_raises_and_keeps_coro_running():
    """run(timeout) 到期抛 TimeoutError，后台协程继续跑、不被取消。"""
    executor = AsyncBackgroundExecutor()
    try:

        async def hanging():
            await asyncio.sleep(30)
            return "done"

        with pytest.raises(TimeoutError):
            executor.run(hanging(), timeout=0.05)

        # 同语义显式验证：超时只解除等待，不取消任务
        fut = executor.submit(hanging())
        with pytest.raises(TimeoutError):
            fut.result(timeout=0.05)
        assert not fut.done()
        fut.cancel()
    finally:
        executor._cleanup()
