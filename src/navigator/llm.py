"""Apertus client (Keera gateway, OpenAI-compatible): concurrency limit, retries, JSON parsing."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import openai
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from navigator.settings import Settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, message: str, text: str = ""):
        super().__init__(message)
        self.text = text  # the raw answer, so callers can salvage parts of it


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError)):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def parse_json_object(text: str) -> dict:
    """Parse a JSON object; if the model wrapped it in text, take the outermost {...}."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("no JSON object in response", text)
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"invalid JSON: {e}", text) from e
    if not isinstance(data, dict):
        raise LLMError("response is not a JSON object", text)
    return data


class LLM:
    def __init__(self, settings: Settings, model: str | None = None):
        self.client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.keera_api_key, timeout=120)
        self.model = model or settings.llm_model
        self.semaphore = asyncio.Semaphore(settings.llm_concurrency)
        self.json_mode = True  # switched off for the run if the gateway rejects response_format

    @retry(
        retry=retry_if_exception(_retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _complete(self, messages: list[dict], max_tokens: int) -> str:
        async with self.semaphore:
            try:
                return await self._stream(messages, max_tokens)
            except openai.BadRequestError:
                if not self.json_mode:
                    raise
                log.warning("gateway rejected JSON mode; continuing without it")
                self.json_mode = False
                return await self._stream(messages, max_tokens)

    async def _stream(self, messages: list[dict], max_tokens: int) -> str:
        """Streaming keeps the gateway connection busy: long answers otherwise end in 504 timeouts."""
        kwargs = {"response_format": {"type": "json_object"}} if self.json_mode else {}
        stream = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0, max_tokens=max_tokens, stream=True, **kwargs
        )
        parts, finish_reason = [], None
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta and choice.delta.content:
                parts.append(choice.delta.content)
            finish_reason = choice.finish_reason or finish_reason
        if finish_reason == "length":
            log.warning("answer cut off at max_tokens=%d", max_tokens)
        return "".join(parts)

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        """One JSON-object answer. A response that does not parse is retried once."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in (1, 2):
            text = await self._complete(messages, max_tokens)
            try:
                return parse_json_object(text)
            except LLMError:
                if attempt == 2:
                    raise
                log.info("unparseable JSON, retrying once")
        raise AssertionError("unreachable")


@dataclass
class Speed:
    model: str
    first_token_s: float | None
    tokens: int
    seconds: float

    @property
    def tokens_per_s(self) -> float:
        return self.tokens / self.seconds if self.seconds else 0.0


async def measure_speed(settings: Settings, model: str, max_tokens: int = 300) -> Speed:
    """One short streamed answer: time to first token and generation speed (#16).
    The shared gateway's speed changes a lot, so measure before choosing a model."""
    client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.keera_api_key, timeout=120)
    start, first, chunks, usage = time.monotonic(), None, 0, None
    stream = await client.chat.completions.create(
        model=model, temperature=0, max_tokens=max_tokens, stream=True,
        stream_options={"include_usage": True},
        messages=[{"role": "user", "content": "Write about 200 words on how heart valves work."}],
    )
    async for chunk in stream:
        if chunk.usage:
            usage = chunk.usage.completion_tokens
        if chunk.choices and chunk.choices[0].delta.content:
            first = first if first is not None else time.monotonic() - start
            chunks += 1
    return Speed(model, first, usage or chunks, time.monotonic() - start)
