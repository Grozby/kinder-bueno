"""Evaluation (plan 10.1-10.3): run the gold queries like /api/search and report the metrics as Markdown."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import psycopg
import yaml

from navigator.eval_judge import Verdict, judge_all, log_rows, precision
from navigator.expand import Expansion, expand_query
from navigator.llm import LLM
from navigator.models import Result
from navigator.rank import MAX_RESULTS, rank_entities
from navigator.resolve import norm_name, norm_unit
from navigator.results import build_results, shown

LAY_PHRASINGS = (1, 2)  # per use case: (a) site wording, (b) lay term, (c) synonym
MIN_JUDGE_AGREEMENT = 0.8  # below this the eval judge is not reliable (plan 10.2)
# "unit_topics" is reported on its own: the topics of a person's unit are not personal expertise (#44).
PERSON_FIELDS = ("role", "affiliations", "expertise", "unit_topics", "sources")


@dataclass(frozen=True)
class Expected:
    name: str
    type: str
    url: str


@dataclass(frozen=True)
class UseCase:
    id: str
    queries: list[str]
    expected: list[Expected]


def load_gold(path: Path) -> list[UseCase]:
    data = yaml.safe_load(path.read_text())
    return [
        UseCase(uc["id"], uc["queries"], [Expected(**e) for e in uc.get("expected") or []])
        for uc in data["use_cases"]
    ]


def matches(expected: Expected, etype: str, name: str) -> bool:
    """Units: same normalised name. People: every word of the expected name is in the result name
    (so "Stefan Weber" matches "Prof. Dr.-Ing. Stefan Weber", whose compound title norm_name keeps)."""
    if expected.type != etype:
        return False
    if etype == "person":
        return set(norm_name(expected.name).split()) <= set(norm_name(name).split())
    return norm_unit(expected.name) == norm_unit(name)


def found(expected: list[Expected], results: list[tuple[str, str]]) -> list[Expected]:
    """Expected entities that match at least one (type, name) result."""
    return [e for e in expected if any(matches(e, t, n) for t, n in results)]


def recall(expected: list[Expected], results: list[tuple[str, str]]) -> float | None:
    return len(found(expected, results)) / len(expected) if expected else None


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def mean_pairwise_jaccard(sets: list[set]) -> float | None:
    pairs = list(combinations(sets, 2))
    return sum(jaccard(a, b) for a, b in pairs) / len(pairs) if pairs else None


def mean(values: list[float | None]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def field_fill(results: list[Result]) -> dict[str, float | None]:
    """Share of person results with each field filled."""
    people = [r for r in results if r.type == "person"]
    return {f: (sum(bool(getattr(r, f)) for r in people) / len(people) if people else None) for f in PERSON_FIELDS}


def traceability(conn: psycopg.Connection, results: list[Result]) -> float | None:
    """Share of displayed claims that are shown (verified, not judged unsupported) and have a source URL."""
    evidence = [e for r in results for e in r.evidence]
    if not evidence:
        return None
    ok_ids = {
        row[0]
        for row in conn.execute(
            f"SELECT cl.id FROM claim cl WHERE cl.id = ANY(%s) AND {shown('cl')}", ([e.claim_id for e in evidence],)
        ).fetchall()
    }
    return sum(e.claim_id in ok_ids and bool(e.url) for e in evidence) / len(evidence)


def search(conn: psycopg.Connection, query: str, expansion: Expansion) -> list[Result]:
    """The same steps as /api/search, without the explanation call."""
    ranking = rank_entities(conn, query, extra_terms=expansion.terms)
    return build_results(conn, ranking.ranked)[:MAX_RESULTS]


async def expand_all(llm: LLM, queries: list[str]) -> dict[str, Expansion]:
    """All expansions on one event loop (an LLM instance is bound to the loop it first ran on)."""
    return {q: await expand_query(llm, q) for q in queries}


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def _db_rows(conn: psycopg.Connection) -> dict:
    return {
        "coverage": conn.execute(
            f"""SELECT s.id, count(DISTINCT p.id), count(DISTINCT cl.entity_id), count(DISTINCT cl.id)
                FROM source s LEFT JOIN page p ON p.source_id = s.id
                LEFT JOIN claim cl ON cl.page_id = p.id AND {shown('cl')}
                GROUP BY s.id ORDER BY s.id"""
        ).fetchall(),
        "raw": dict(conn.execute("SELECT verified, count(*) FROM raw_claim GROUP BY verified").fetchall()),
        "verdicts": conn.execute(
            "SELECT coalesce(judge_verdict, 'not judged'), count(*) FROM claim WHERE verified GROUP BY 1 ORDER BY 1"
        ).fetchall(),
        "feedback": conn.execute("SELECT rating, count(*) FROM feedback GROUP BY rating ORDER BY rating").fetchall(),
    }


def _judged(results: list[Result], verdicts: dict[int, Verdict] | None, judge_on: bool) -> str:
    if not judge_on:
        return "–"
    if verdicts is None:
        return "not judged"
    judged = [verdicts[r.entity_id].relevant for r in results if r.entity_id in verdicts]
    return f"{sum(judged)}/{len(judged)}"


def report(
    gold: list[UseCase],
    runs: dict[str, list[Result]],
    expansions: dict[str, Expansion],
    db: dict,
    conn,
    verdicts: dict[str, dict[int, Verdict] | None] | None = None,
) -> str:
    """Markdown report. `verdicts` (eval judge, per query) is None when the judge was not run."""
    judge_on = verdicts is not None
    verdicts = verdicts or {}
    lines = ["# Evaluation report", "", "## Queries", "",
             "| use case | query | results | expected found | recall@10 | judged relevant | expansion terms |",
             "|---|---|---|---|---|---|---|"]
    recalls, lay, overlaps, all_results = [], [], [], []
    precisions, gold_verdicts = [], []
    for uc in gold:
        sets = []
        for i, q in enumerate(uc.queries):
            results = runs[q]
            all_results += results
            pairs = [(r.type, r.name) for r in results]
            sets.append({(t, norm_name(n)) for t, n in pairs})
            r = recall(uc.expected, pairs)
            recalls.append(r)
            if i in LAY_PHRASINGS:
                lay.append(r)
            names = ", ".join(e.name for e in found(uc.expected, pairs)) or "–"
            v = verdicts.get(q)
            precisions.append(precision(results, v))
            gold_verdicts += [v[r.entity_id].relevant for r in results
                              if v and r.entity_id in v and found(uc.expected, [(r.type, r.name)])]
            lines.append(f"| {uc.id} | {q} | {len(results)} | {names} | {_pct(r)} | "
                         f"{_judged(results, v, judge_on)} | {len(expansions[q].terms)} |")
        overlaps.append((uc.id, mean_pairwise_jaccard(sets)))

    raw_total = sum(db["raw"].values())
    fill = field_fill(all_results)
    lines += ["", "## Metrics (plan 10.2)", "", "| metric | value | target |", "|---|---|---|",
              f"| recall@10 (mean of {len(recalls)} queries) | {_pct(mean(recalls))} | ≥ 80% |",
              f"| lay-term recall@10 (phrasings b, c) | {_pct(mean(lay))} | ≥ 80% |"]
    lines += [f"| phrasing overlap, {uc_id} (mean Jaccard of top-10 sets) | {_pct(o)} | report |" for uc_id, o in overlaps]
    lines += [f"| traceability (displayed claims shown + source URL) | {_pct(traceability(conn, all_results))} | 100% |"]
    lines += [f"| field fill, person results: {f} | {_pct(v)} | report |" for f, v in fill.items()]
    if judge_on:
        judged_n = sum(p is not None for p in precisions)
        agreement = sum(gold_verdicts) / len(gold_verdicts) if gold_verdicts else None
        note = ("judge not reliable" if agreement is not None and agreement < MIN_JUDGE_AGREEMENT
                else "report; < 80% = judge not reliable")
        lines += [f"| judged precision@10 [PoC] (mean of {judged_n} judged queries) | {_pct(mean(precisions))} | report |",
                  f"| judge gold agreement [PoC] (gold hits judged relevant) | {_pct(agreement)} "
                  f"({sum(gold_verdicts)} / {len(gold_verdicts)}) | {note} |"]
    lines += [f"| extraction drop rate (unverified raw claims) | "
              f"{_pct(db['raw'].get(False, 0) / raw_total if raw_total else None)} ({db['raw'].get(False, 0)} / {raw_total}) | report |"]
    lines += ["", "## Source coverage", "", "| source | pages | entities | shown claims |", "|---|---|---|---|"]
    lines += [f"| {s} | {p} | {e} | {c} |" for s, p, e, c in db["coverage"]]
    lines += ["", "## Judge verdicts [PoC] (verified claims)", "", "| verdict | claims |", "|---|---|"]
    lines += [f"| {v} | {n} |" for v, n in db["verdicts"]] or ["| – | 0 |"]
    lines += ["", "## Feedback [PoC]", "", "| rating | count |", "|---|---|"]
    lines += [f"| {r} | {n} |" for r, n in db["feedback"]] or ["| – | 0 |"]
    if judge_on:
        lines += ["", "The eval judge [PoC] is the same model family as the extractor, so it is biased (plan 3): "
                  "a precision signal, not ground truth. Verdicts and reasons: `eval/judge_log.jsonl`."]
    return "\n".join(lines) + "\n"


def run(
    conn: psycopg.Connection,
    make_llm: Callable[[], LLM],
    gold: list[UseCase],
    expand: bool = True,
    judge: bool = True,
) -> tuple[str, list[dict]]:
    """Run every gold query. Returns the Markdown report and the eval judge log rows.

    Expansion and judging each run in their own event loop, so each gets a fresh LLM
    (an LLM instance is bound to the loop it first ran on)."""
    queries = [q for uc in gold for q in uc.queries]
    expansions = asyncio.run(expand_all(make_llm(), queries)) if expand else {q: Expansion() for q in queries}
    runs = {q: search(conn, q, expansions[q]) for q in queries}
    verdicts = asyncio.run(judge_all(make_llm(), runs)) if judge else None
    text = report(gold, runs, expansions, _db_rows(conn), conn, verdicts)
    return text, log_rows(runs, verdicts) if verdicts else []
