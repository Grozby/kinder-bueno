"""Evaluation metric tests: pure functions, no database or gateway."""

import pytest

from navigator.evaluate import (
    Expected,
    field_fill,
    found,
    jaccard,
    load_gold,
    matches,
    mean_pairwise_jaccard,
    recall,
    report,
)
from navigator.expand import Expansion
from navigator.models import Result
from navigator.settings import PROJECT_ROOT


def _result(name: str, type: str = "person", **fields) -> Result:
    base = dict(entity_id=1, type=type, name=name, role=[], contact=[], affiliations=[], expertise=[],
                projects=[], infrastructure=[], why="", score=1.0, sources=[], evidence=[])
    return Result(**{**base, **fields})


@pytest.mark.parametrize(
    "expected, etype, name, ok",
    [
        (Expected("Stefan Weber", "person", ""), "person", "Prof. Dr.-Ing. Stefan Weber", True),
        (Expected("Lilian Witthauer", "person", ""), "person", "Prof. Dr. phil. Lilian Witthauer", True),
        (Expected("Thomas Züger", "person", ""), "person", "PD Dr. med. Thomas Zuger", True),  # transliterated
        (Expected("Stefan Weber", "person", ""), "person", "Stefan Weibel", False),
        (Expected("Stefan Weber", "person", ""), "unit", "Stefan Weber", False),  # type must match
        (Expected("Odening Lab", "unit", ""), "unit", "odening  lab", True),
        (Expected("Neuro Robotics Group", "unit", ""), "unit", "The Neuro Robotics Group", True),
        (Expected("Odening Lab", "unit", ""), "unit", "Odening Lab Bern", False),  # units: whole name
    ],
)
def test_matches(expected, etype, name, ok):
    assert matches(expected, etype, name) is ok


def test_recall_counts_each_expected_entity_once():
    expected = [Expected("Odening Lab", "unit", ""), Expected("Dominik Obrist", "person", "")]
    results = [("person", "Prof. Dr. Dominik Obrist"), ("person", "Dominik Obrist"), ("unit", "Other Lab")]
    assert recall(expected, results) == 0.5
    assert [e.name for e in found(expected, results)] == ["Dominik Obrist"]
    assert recall([], results) is None


def test_jaccard_and_mean_pairwise():
    assert jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert jaccard(set(), set()) == 1.0
    assert mean_pairwise_jaccard([{1, 2}, {1, 2}, {3}]) == pytest.approx((1 + 0 + 0) / 3)
    assert mean_pairwise_jaccard([{1}]) is None


def test_field_fill_counts_person_results_only():
    results = [
        _result("A", role=["Group Head"], affiliations=["X Lab"], sources=["u"]),
        _result("B", role=["PhD"]),
        _result("X Lab", type="unit", expertise=["x"]),
    ]
    assert field_fill(results) == {"role": 1.0, "affiliations": 0.5, "expertise": 0.0, "sources": 0.5}
    assert field_fill([_result("X Lab", type="unit")])["role"] is None


def test_gold_file_follows_the_plan_rules():
    gold = load_gold(PROJECT_ROOT / "eval" / "gold.yaml")
    assert len(gold) == 3
    for uc in gold:
        assert len(uc.queries) == 3
        assert 3 <= len(uc.expected) <= 6
        assert all(e.type in ("person", "unit") and e.url.startswith("https://") for e in uc.expected)


def test_report_has_per_query_rows_and_metrics():
    gold = load_gold(PROJECT_ROOT / "eval" / "gold.yaml")
    queries = [q for uc in gold for q in uc.queries]
    runs = {q: [] for q in queries}
    runs["glucose sensors"] = [_result("Lilian Witthauer"), _result("Diabetes Center Berne", type="unit")]
    db = {"coverage": [("dcb", 30, 127, 352)], "raw": {True: 3, False: 1}, "verdicts": [], "feedback": []}
    text = report(gold, runs, {q: Expansion() for q in queries}, db, conn=None)
    assert "| glucose | glucose sensors | 2 | Diabetes Center Berne, Lilian Witthauer | 40% | 0 |" in text
    assert "| extraction drop rate (unverified raw claims) | 25% (1 / 4) | report |" in text
    assert "| dcb | 30 | 127 | 352 |" in text
