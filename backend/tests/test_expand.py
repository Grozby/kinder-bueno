"""Query expansion tests with a fake LLM: no gateway needed."""

import asyncio

import pytest

from navigator import expand
from navigator.expand import Expansion, expand_query, parse_expansion
from navigator.llm import LLMError


class FakeLLM:
    def __init__(self, answer=None, error: Exception | None = None, delay: float = 0.0):
        self.answer, self.error, self.delay = answer, error, delay
        self.calls = 0

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture(autouse=True)
def empty_cache():
    expand._cache.clear()
    yield
    expand._cache.clear()


def test_parse_expansion_cleans_terms():
    data = {
        "en": ["  glucose   biosensors ", "Glucose Sensors", "glucose biosensors", 42, None, "", "continuous glucose monitoring (CGM)"],
        "de": "not a list",
    }
    assert parse_expansion(data, "glucose sensors") == Expansion(
        en=["glucose biosensors", "continuous glucose monitoring", "CGM"], de=[]
    )


def test_parse_expansion_caps_terms_per_language():
    data = {"en": [f"term {i}" for i in range(20)], "de": [f"Begriff {i}" for i in range(20)]}
    expansion = parse_expansion(data, "q")
    assert len(expansion.en) == len(expansion.de) == expand.MAX_TERMS
    assert expansion.terms[: expand.MAX_TERMS] == expansion.en  # English first, for the semantic query


def test_terms_are_english_first_without_duplicates_across_languages():
    expansion = Expansion(en=["CGM", "glucose sensor"], de=["cgm", "Glukosesensor"])
    assert expansion.terms == ["CGM", "glucose sensor", "Glukosesensor"]


def test_parse_expansion_handles_missing_keys():
    assert parse_expansion({}, "q") == Expansion()


def test_expand_query_caches_by_normalised_query():
    llm = FakeLLM({"en": ["CGM"], "de": ["Glukosesensor"]})
    first = asyncio.run(expand_query(llm, "Glucose sensors"))
    second = asyncio.run(expand_query(llm, "  glucose   SENSORS "))
    assert first == second == Expansion(en=["CGM"], de=["Glukosesensor"])
    assert llm.calls == 1


@pytest.mark.parametrize("error", [LLMError("no JSON object in response"), ConnectionError("gateway down")])
def test_expand_query_failure_gives_empty_expansion_and_is_not_cached(error):
    llm = FakeLLM(error=error)
    assert asyncio.run(expand_query(llm, "glucose sensors")) == Expansion()
    asyncio.run(expand_query(llm, "glucose sensors"))
    assert llm.calls == 2


def test_expand_query_times_out():
    llm = FakeLLM({"en": ["late"]}, delay=1.0)
    assert asyncio.run(expand_query(llm, "glucose sensors", timeout=0.05)) == Expansion()


def test_expand_query_skips_blank_query():
    llm = FakeLLM({"en": ["x"]})
    assert asyncio.run(expand_query(llm, "   ")) == Expansion()
    assert llm.calls == 0
