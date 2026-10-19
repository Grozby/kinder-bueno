"""Eval judge tests with a fake LLM: no gateway needed."""

import asyncio

from navigator.evaluation.judge import (
    Verdict,
    format_results,
    judge_all,
    judge_query,
    log_rows,
    parse_verdicts,
    precision,
)
from navigator.models import Evidence, Result


def _result(entity_id: int, name: str, evidence: list[Evidence] = ()) -> Result:
    return Result(entity_id=entity_id, type="person", name=name, role=[], contact=[], affiliations=[], expertise=[],
                  projects=[], infrastructure=[], why="", score=0.5, sources=["https://secret.example/page"],
                  evidence=list(evidence))


def _evidence(field: str, value: str, quote: str, via_unit: str | None = None) -> Evidence:
    return Evidence(claim_id=1, field=field, value=value, quote=quote, url="https://secret.example/page",
                    judge_verdict=None, judge_reason=None, via_unit=via_unit)


class FakeLLM:
    def __init__(self, answer=None, error: Exception | None = None, delay: float = 0.0):
        self.answer, self.error, self.delay = answer, error, delay
        self.prompts: list[str] = []

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096, timeout: float | None = None) -> dict:
        self.prompts.append(user)
        await asyncio.wait_for(asyncio.sleep(self.delay), timeout)  # like LLM: the timeout is per request
        if self.error:
            raise self.error
        return self.answer


def test_format_results_shows_evidence_but_no_urls_or_scores():
    text = format_results([_result(7, "Anna Muster", [_evidence("role", "Group Head", "Anna Muster, Group Head")])])
    assert text == '7 Anna Muster (person)\n  - role: Group Head — "Anna Muster, Group Head"'
    assert "secret.example" not in text and "0.5" not in text


def test_parse_verdicts_keeps_only_known_ids_with_boolean_relevant():
    data = {
        "7": {"relevant": True, "reason": "works on CGM"},
        "8": {"relevant": "yes"},      # not a boolean
        "9": {"relevant": False},      # unknown id
        "x": {"relevant": True},       # not an id
        "10": "relevant",              # not an object
        "11 ARTORG Center": {"relevant": False, "reason": "too broad"},  # id followed by the name
        "12x": {"relevant": True},     # not a clean id
    }
    assert parse_verdicts(data, {7, 8, 10, 11, 12}) == {
        7: Verdict(True, "works on CGM"),
        11: Verdict(False, "too broad"),
    }


def test_judge_query_sends_query_and_results():
    llm = FakeLLM({"7": {"relevant": True, "reason": "r"}})
    verdicts = asyncio.run(judge_query(llm, "glucose sensors", [_result(7, "Anna")]))
    assert verdicts == {7: Verdict(True, "r")}
    assert llm.prompts[0].startswith("Query: glucose sensors\nResults:\n7 Anna (person)")


def test_judge_query_one_call_per_result():
    """Each result is judged on its own, so its verdict does not depend on the others or their order."""
    llm = FakeLLM({"7": {"relevant": True}, "8": {"relevant": False}})
    verdicts = asyncio.run(judge_query(llm, "q", [_result(7, "Anna"), _result(8, "Ben")]))
    assert verdicts == {7: Verdict(True, ""), 8: Verdict(False, "")}
    assert len(llm.prompts) == 2
    assert all(p.count("(person)") == 1 for p in llm.prompts)


def test_judge_query_not_judged_on_error_timeout_empty_or_no_results():
    results = [_result(7, "Anna")]
    assert asyncio.run(judge_query(FakeLLM(error=ConnectionError("down")), "q", results)) is None
    assert asyncio.run(judge_query(FakeLLM({"7": {"relevant": True}}, delay=1.0), "q", results, timeout=0.05)) is None
    assert asyncio.run(judge_query(FakeLLM({"99": {"relevant": True}}), "q", results)) is None
    llm = FakeLLM({})
    assert asyncio.run(judge_query(llm, "q", [])) is None
    assert llm.prompts == []  # no call without results


def test_judge_all_and_precision_and_log():
    runs = {"a": [_result(1, "One"), _result(2, "Two")], "b": []}
    llm = FakeLLM({"1": {"relevant": True, "reason": "fits"}, "2": {"relevant": False, "reason": "off topic"}})
    verdicts = asyncio.run(judge_all(llm, runs))
    assert verdicts["b"] is None
    assert precision(runs["a"], verdicts["a"]) == 0.5
    assert precision(runs["a"], None) is None
    assert log_rows(runs, verdicts) == [
        {"query": "a", "rank": 1, "entity_id": 1, "name": "One", "type": "person", "relevant": True, "reason": "fits"},
        {"query": "a", "rank": 2, "entity_id": 2, "name": "Two", "type": "person", "relevant": False, "reason": "off topic"},
    ]


def test_lab_topics_are_labelled_and_kept_by_the_cap():
    # Ten own rows (role, emails, …) used to push the lab's topics past the 8-row cap.
    own = [_evidence("email", f"a{i}@x.ch", "q") for i in range(9)] + [_evidence("role", "Group Head", "Anna, Group Head")]
    lab = [_evidence("unit_expertise", "cochlear implants", "The Hearing Lab builds cochlear implants.", "Hearing Lab")]
    text = format_results([_result(7, "Anna Muster", own + lab)])
    lines = text.splitlines()
    assert lines[1] == '  - lab topic (via Hearing Lab): cochlear implants — "The Hearing Lab builds cochlear implants."'
    assert lines[2] == '  - role: Group Head — "Anna, Group Head"'
    assert len(lines) == 1 + 8
