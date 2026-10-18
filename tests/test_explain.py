"""'Why it matches' tests with a fake LLM: no gateway needed."""

import asyncio

import pytest

from navigator.explain import (
    MAX_CLAIMS,
    apply_why,
    check_sentence,
    cited_ids,
    explain,
    format_results,
    parse_why,
    prompt_claims,
)
from navigator.models import Evidence, Result


def _ev(claim_id: int, field: str, value: str = "v", quote: str = "q") -> Evidence:
    return Evidence(claim_id=claim_id, field=field, value=value, quote=quote, url="https://u",
                    judge_verdict=None, judge_reason=None)


def _result(entity_id: int, name: str, evidence: list[Evidence]) -> Result:
    return Result(entity_id=entity_id, type="person", name=name, role=[], contact=[], affiliations=[], expertise=[],
                  projects=[], infrastructure=[], why="Matches on: v", score=0.5, sources=["https://u"],
                  evidence=evidence)


ANNA = _result(1, "Anna Muster", [_ev(11, "email", "a@unibe.ch"), _ev(12, "role", "Group Head"),
                                  _ev(13, "expertise", "glucose sensors", "works on glucose sensors")])
LAB = _result(2, "Diabetes Lab", [_ev(21, "expertise", "insulin pumps")])


class FakeLLM:
    def __init__(self, answer=None, error: Exception | None = None, delay: float = 0.0):
        self.answer, self.error, self.delay = answer, error, delay
        self.prompts: list[str] = []

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        self.prompts.append(user)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer


def test_prompt_claims_puts_explanatory_fields_first_and_skips_contacts():
    assert [e.claim_id for e in prompt_claims(ANNA.evidence)] == [13, 12]
    many = [_ev(i, "name") for i in range(30)]
    assert len(prompt_claims(many)) == MAX_CLAIMS


def test_format_results_numbers_claims():
    text = format_results("glucose", [ANNA])
    assert text == ('Query: glucose\nResults:\n1 Anna Muster (person)\n'
                    '  [13] expertise: glucose sensors — "works on glucose sensors"\n'
                    '  [12] role: Group Head — "q"')
    assert "a@unibe.ch" not in text


@pytest.mark.parametrize(
    "sentence, expected",
    [
        ("Works on glucose sensors [13].", "Works on glucose sensors [13]."),
        ("Group Head working on glucose sensors [12][13].", "Group Head working on glucose sensors [12][13]."),
        ("Group Head [12, 13].", "Group Head [12, 13]."),
        ("  Works   on sensors [13]. ", "Works on sensors [13]."),
        ("Works on glucose sensors.", None),                # no citation
        ("Works on glucose sensors [13][21].", None),       # 21 belongs to another result
        ("Works on glucose sensors [11].", None),           # email: not shown to the model
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_check_sentence(sentence, expected):
    assert check_sentence(sentence, {12, 13}) == expected


def test_cited_ids():
    assert cited_ids("a [1][2] b [3, 4] c [x] [5,6]") == {1, 2, 3, 4, 5, 6}


def test_parse_why_checks_each_result_and_accepts_id_name_keys():
    data = {
        "1 Anna Muster": "Works on glucose sensors [13].",
        "2": "Builds insulin pumps [13].",  # cites Anna's claim: rejected
        "99": "Unknown [1].",
    }
    assert parse_why(data, [ANNA, LAB]) == {1: "Works on glucose sensors [13]."}


def test_explain_returns_checked_sentences():
    llm = FakeLLM({"1": "Works on glucose sensors [13].", "2": "Builds insulin pumps [21]."})
    assert asyncio.run(explain(llm, "glucose", [ANNA, LAB])) == {
        1: "Works on glucose sensors [13].",
        2: "Builds insulin pumps [21].",
    }


def test_explain_asks_once_per_result():
    llm = FakeLLM({"1": "Works on glucose sensors [13].", "2": "Builds insulin pumps [21]."})
    asyncio.run(explain(llm, "glucose", [ANNA, LAB]))
    assert len(llm.prompts) == 2
    assert all(p.count("\n  [") >= 1 and p.count(" (person)") + p.count(" (unit)") == 1 for p in llm.prompts)


class SlowFor(FakeLLM):
    """Answers at once, except for prompts containing `slow_name`."""

    def __init__(self, answer, slow_name: str):
        super().__init__(answer)
        self.slow_name = slow_name

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        self.prompts.append(user)
        if self.slow_name in user:
            await asyncio.sleep(1.0)
        return self.answer


def test_explain_keeps_fast_answers_when_one_call_is_late():
    llm = SlowFor({"1": "Works on glucose sensors [13].", "2": "Builds insulin pumps [21]."}, "Diabetes Lab")
    assert asyncio.run(explain(llm, "glucose", [ANNA, LAB], timeout=0.2)) == {1: "Works on glucose sensors [13]."}


def test_explain_falls_back_on_error_timeout_or_nothing_to_explain():
    assert asyncio.run(explain(FakeLLM(error=ConnectionError("down")), "q", [ANNA])) == {}
    assert asyncio.run(explain(FakeLLM({"1": "x [13]."}, delay=1.0), "q", [ANNA], timeout=0.05)) == {}
    llm = FakeLLM({})
    contacts_only = _result(3, "C", [_ev(31, "email")])
    assert asyncio.run(explain(llm, "q", [contacts_only])) == {}
    assert llm.prompts == []  # no call when no result has an explanatory claim


def test_apply_why_keeps_template_for_missing_ids():
    out = apply_why([ANNA, LAB], {1: "Works on glucose sensors [13]."})
    assert [r.why for r in out] == ["Works on glucose sensors [13].", "Matches on: v"]
    assert ANNA.why == "Matches on: v"  # inputs unchanged
