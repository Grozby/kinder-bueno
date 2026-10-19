"""LLM client: the request timeout does not count the wait for a concurrency slot (#148)."""

import asyncio

import pytest

from navigator.core.llm import LLM
from navigator.core.settings import Settings


def _slow_llm(seconds: float, concurrency: int) -> LLM:
    llm = LLM(Settings(llm_concurrency=concurrency, keera_api_key="x"))

    async def stream(messages, max_tokens):
        await asyncio.sleep(seconds)
        return '{"ok": true}'

    llm._stream = stream
    return llm


def test_queued_calls_do_not_time_out_while_waiting_for_a_slot():
    """Four 0.1 s calls through one slot take 0.4 s in all; each request is within its 0.25 s timeout."""
    llm = _slow_llm(0.1, concurrency=1)

    async def run():
        return await asyncio.gather(*(llm.chat_json("s", "u", timeout=0.25) for _ in range(4)))

    assert asyncio.run(run()) == [{"ok": True}] * 4


def test_a_slow_request_times_out():
    llm = _slow_llm(0.5, concurrency=1)
    with pytest.raises(TimeoutError):
        asyncio.run(llm.chat_json("s", "u", timeout=0.05))
