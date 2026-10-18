"""Case analysis (#53): parsing, merge, need matching, score, and the stored references. Needs Postgres
for the tests that use the fixture graph (tests/conftest.py)."""

import zlib

import numpy as np
import pytest
from conftest import onehot
from test_api import fake_embed

from navigator import analysis, cases
from navigator.analysis import CaseInfo, Match
from navigator.models import Result

NEEDS = ["glucose monitoring", "insulin delivery", "zebrafish genetics"]


def fake_embed_many(texts: list[str]) -> np.ndarray:
    """Like fake_embed for glucose / insulin; any other text gets its own dimension (unrelated to everything)."""
    def one(t: str) -> np.ndarray:
        if "glucose" in t or "insulin" in t:
            return fake_embed(t)
        return onehot({100 + zlib.crc32(t.encode()) % 900: 1.0})
    return np.array([one(t) for t in texts])


def fake_read(text: str) -> CaseInfo:
    return CaseInfo(company_name="Glucora Health", industry="Medical devices", summary="Glucose patches.", needs=NEEDS)


def no_explain(query: str, results: list[Result]) -> dict[int, str]:
    return {}


def run(conn, case_id: str, read=fake_read, explain=no_explain) -> None:
    analysis.analyze(conn, case_id, read=read, embed=fake_embed, embed_many=fake_embed_many, explain=explain)


def test_parse_case_info():
    info = analysis.parse_case_info({
        "company_name": "  Glucora   Health ", "industry": 7, "summary": "",
        "needs": ["glucose monitoring", "Glucose  Monitoring", "", 3, "a", "b", "c", "d", "e", "f"],
    })
    assert info.company_name == "Glucora Health"
    assert info.industry is None and info.summary is None  # wrong type, empty
    assert info.needs == ["glucose monitoring", "a", "b", "c", "d", "e"]  # deduplicated, at most 6


@pytest.mark.parametrize("data", [{}, {"needs": []}, {"needs": "glucose"}, {"needs": ["", None]}])
def test_parse_case_info_without_needs(data):
    with pytest.raises(ValueError):
        analysis.parse_case_info(data)


def test_merge_rewards_entities_found_for_several_needs():
    merged = analysis.merge({"a": [(1, 0.9), (2, 0.8)], "b": [(2, 0.7), (3, 0.6)]})
    assert [(e, needs) for e, _, needs in merged] == [(2, ["a", "b"]), (1, ["a"]), (3, ["b"])]


def result(entity_id: int, type_: str, name: str, **kw) -> Result:
    base = {"role": [], "contact": [], "affiliations": [], "expertise": [], "projects": [], "infrastructure": [],
            "why": "", "score": 1.0, "sources": [], "evidence": []}
    return Result(entity_id=entity_id, type=type_, name=name, **{**base, **kw})


def test_score_rows_name_their_matches():
    results = [
        result(1, "person", "Alice"), result(2, "unit", "Diabetes Lab", infrastructure=["Cleanroom"]),
        result(3, "project", "Artificial Pancreas"), result(4, "person", "Bob"),
    ]
    matches = {
        1: [Match("glucose monitoring", "insulin pumps", "Diabetes Lab", 0.9)],
        2: [Match("insulin delivery", "insulin pumps", None, 0.9)],
        3: [Match("insulin delivery", "artificial pancreas", None, 0.8)],
    }
    score, rows = analysis.score_case(NEEDS, results, matches)
    by = {r.criterion: r for r in rows}
    assert [r.criterion for r in rows] == [c for c, _, _ in analysis.CRITERIA]
    assert by["Research fit"].score == 67
    assert by["Research fit"].rationale == (
        "2 of 3 needs covered. glucose monitoring: Alice; insulin delivery: Diabetes Lab, Artificial Pancreas. "
        "Not covered: zebrafish genetics"
    )
    assert (by["Expert pool"].score, by["Expert pool"].rationale) == (
        20, "1 people in labs that work on your needs: Alice (Diabetes Lab)")  # Bob matches nothing
    assert by["Research units"].score == 34
    assert by["Infrastructure & labs"].rationale == "1 infrastructure entries: Cleanroom (Diabetes Lab)"
    assert by["Running projects"].score == 50
    assert score == round(0.4 * 67 + 0.2 * 20 + 0.15 * 34 + 0.15 * 50 + 0.1 * 50)


def test_score_without_matches():
    score, rows = analysis.score_case(NEEDS, [result(1, "person", "Alice")], {})
    assert score == 0 and all(r.score == 0 for r in rows)
    assert rows[1].rationale == "No matching experts in our sources"


def test_claim_counts_for_its_closest_need_only():
    alice = result(1, "person", "Alice", evidence=[
        {"claim_id": 1, "field": "expertise", "value": "glucose sensors", "quote": "q", "url": "u",
         "judge_verdict": None, "judge_reason": None},
        {"claim_id": 2, "field": "role", "value": "glucose professor", "quote": "q", "url": "u",
         "judge_verdict": None, "judge_reason": None},  # roles are not topics
    ])
    matches = analysis.match_needs([alice], ["glucose monitoring", "glucose insulin"], fake_embed_many)
    assert [(m.need, m.value) for m in matches[1]] == [("glucose monitoring", "glucose sensors")]


def new_case(conn) -> str:
    return cases.create_case(conn, "glucora-business-model.pdf", "Glucora Health builds glucose patches.").id


def test_analyze_stores_needs_references_and_score(test_conn, graph):
    case_id = new_case(test_conn)
    run(test_conn, case_id)
    case = cases.get_case(test_conn, case_id)
    assert case.analysis_status == "done"
    assert (case.company_name, case.industry, case.summary) == ("Glucora Health", "Medical devices", "Glucose patches.")
    assert case.score is not None and len(case.score_breakdown) == 5
    assert case.score_breakdown[0].rationale.startswith("2 of 3 needs covered")
    refs = analysis.references(test_conn, case_id, 25)
    names = [r.name for r in refs]
    assert {"Alice Muster", "Bob Beispiel", "Diabetes Lab"} <= set(names)
    assert "Carol Hidden" not in names
    bob = next(r for r in refs if r.name == "Bob Beispiel")
    assert bob.why.startswith("Matches 'glucose monitoring'. ")  # explanation failed: template


def test_analysis_failure_marks_case_failed(test_conn, graph):
    case_id = new_case(test_conn)

    def broken(text: str) -> CaseInfo:
        raise ValueError("gateway down")

    run(test_conn, case_id, read=broken)
    case = cases.get_case(test_conn, case_id)
    assert case.analysis_status == "failed"
    assert case.company_name == "Glucora Business Model" and case.score is None and case.score_breakdown == []
    assert analysis.references(test_conn, case_id, 25) == []


def test_references_keep_checked_sentences_and_drop_missing_entities(test_conn, graph):
    case_id = new_case(test_conn)
    glucose = graph["bob_glucose"]

    def explain(query: str, results: list[Result]) -> dict[int, str]:
        return {r.entity_id: f"Works on glucose sensors [{glucose}]." for r in results}  # only valid for Bob

    run(test_conn, case_id, explain=explain)
    refs = {r.name: r for r in analysis.references(test_conn, case_id, 25)}
    assert refs["Bob Beispiel"].why == f"Matches 'glucose monitoring': Works on glucose sensors [{glucose}]."
    assert refs["Alice Muster"].why.startswith("Matches 'glucose monitoring'. ")  # cites Bob's claim: dropped

    test_conn.execute("DELETE FROM entity WHERE id = %s", (graph["bob"],))  # gone after a re-ingest
    names = [r.name for r in analysis.references(test_conn, case_id, 25)]
    assert "Bob Beispiel" not in names and "Alice Muster" in names
    assert len(analysis.references(test_conn, case_id, 1)) == 1


def test_references_unknown_case(test_conn):
    assert analysis.references(test_conn, "nope", 25) is None
