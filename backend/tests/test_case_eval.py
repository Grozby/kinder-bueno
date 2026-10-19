"""Case eval (#73): gold file, metrics and report. No database: the analysis output is built by hand."""

from pathlib import Path

from test_analysis import result

from navigator.analysis import Match, Scored
from navigator.case_eval import GoldCase, Outcome, load_cases, report
from navigator.cases import pdf_text
from navigator.core.settings import BACKEND_ROOT
from navigator.evaluate import Expected
from navigator.models import ScoreItem


def test_gold_file_loads_and_points_at_readable_pdfs():
    cases = load_cases(BACKEND_ROOT / "eval" / "cases.yaml")
    assert [c.id for c in cases] == ["glucora", "repolar", "precisa", "vinora"]
    for c in cases:
        assert c.needs, c.id  # pinned, so matching changes are measured on the same input
        assert pdf_text(Path(c.pdf).read_bytes())
        assert c.score[0] <= c.score[1]


def outcome() -> Outcome:
    case = GoldCase(
        id="demo", pdf="x.pdf", score=(50, 90), needs=["glucose", "insulin"],
        must_match=[Expected("Diabetes Lab", "unit", ""), Expected("Alice Muster", "person", ""),
                    Expected("Gone Lab", "unit", "")],
        must_not_match=[Expected("Rubin Lab", "unit", ""), Expected("Bob", "person", "")],
    )
    results = [result(1, "unit", "Diabetes Lab"), result(2, "person", "Prof. Alice Muster"),
               result(3, "unit", "Rubin Lab"), result(4, "person", "Bob")]
    matches = {1: [Match("glucose", "insulin pumps", None, 0.7, 0.9)],
               3: [Match("glucose", "bioinformatics", None, 0.64, 0.2)]}
    rows = [ScoreItem(criterion="Research fit", score=50, rationale="1 of 2 needs covered")]
    return Outcome(case, case.needs, Scored([], results, matches, 40, rows))


def test_metrics():
    o = outcome()
    assert [e.name for e in o.matched] == ["Diabetes Lab"]
    assert [e.name for e in o.in_references] == ["Diabetes Lab", "Alice Muster"]  # Alice is found but not matched
    assert [e.name for e in o.false_matches] == ["Rubin Lab"]  # Bob is a reference but matches nothing
    assert o.uncovered == ["insulin"]
    assert o.score_ok is False  # 40 is below 50


def test_report():
    text = report([outcome()])
    assert "| demo | 40 ✗ | 50–90 | 1/3 | 2/3 | 1 | 1 of 2 |" in text
    assert "Alice Muster (in references, no matching claim)" in text
    assert "Gone Lab (not in references)" in text
    assert "False matches: Rubin Lab" in text
    assert "| Rubin Lab | unit | glucose | bioinformatics | 0.20 | 0.64 |" in text
