"""Case analysis (#53): read a business model with Apertus, find its references in Bern, score the fit.

1. Apertus reads the PDF text: company name, industry, a short summary and 3-6 needs (search queries).
2. Each need goes through the search (rank_entities, all four entity types).
3. The rankings are merged with reciprocal rank fusion and the fairness cap: the top 25 are the references.
4. A reference *matches* a need when one of its shown topic claims is close to it (bge-m3 cosine). Each claim
   counts only for its closest need: on Glucora, "non-invasive glucose monitoring" was also 0.60 from "AI for
   carbohydrate estimation". People have no topic claims of their own (only roles), so a person matches
   through their lab's topics.
5. The score counts matches only (plan 1: no invented facts). Each row names the matches behind it.
   Market access or an industry network would need data about companies and markets, which we do not have.

The analysis output (needs, references, score) is stored on the case in one UPDATE; any failure marks the
case "failed" instead, never half filled.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from navigator.explain import check_sentence, prompt_claims
from navigator.llm import LLM
from navigator.models import Result, ScoreItem
from navigator.rank import MAX_PER_UNIT, _units, fairness_cap, rank_entities
from navigator.results import build_results

log = logging.getLogger(__name__)

MAX_TEXT = 12_000     # characters of the PDF sent to Apertus; a business model's key facts are at the start
READ_TIMEOUT = 90.0   # seconds; in the background, so the 70B model may take its time
MAX_NEEDS = 6
MAX_NEED_LEN = 80
MAX_REFERENCES = 25
ALL_TYPES = ["person", "unit", "project", "infrastructure"]
RRF_K = 10            # small: each need's ranking has at most 10 entries
MATCH_SIM = 0.62      # bge-m3 cosine between a need and a claim value. On Glucora the right matches were 0.63+
                      # (CGM, insulin delivery); below were robotics or image segmentation for the wrong need
TOPIC_FIELDS = {"expertise", "description", "unit_expertise"}
NAME_TYPES = {"project", "infrastructure"}  # their names say what they are ("Cleanroom")

# criterion, weight, points per match (score = min(100, matches * points)); research fit is a share of needs
CRITERIA = [
    ("Research fit", 0.40, None),
    ("Expert pool", 0.20, 20),
    ("Research units", 0.15, 34),
    ("Infrastructure & labs", 0.15, 50),
    ("Running projects", 0.10, 50),
]

SYSTEM = """You read a company's business model and help find research partners in Bern, Switzerland.
Return ONLY JSON: {"company_name": "...", "industry": "...", "summary": "...", "needs": ["...", ...]}
- company_name: the company's name as written in the document.
- industry: 2-4 words, for example "Medical devices".
- summary: 1-2 sentences: what the company does and what it looks for. Use only the document.
- needs: 3 to 6 research topics the company needs from universities and research groups. Each is ONE topic
  as a short English search query of 2-5 words, for example "continuous glucose monitoring".
  No "and", no parentheses, no abbreviations. Topics only: no places, money, regulations or company names."""


@dataclass
class CaseInfo:
    company_name: str | None
    industry: str | None
    summary: str | None
    needs: list[str]


def _text(value: object, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:max_len] if text else None


def parse_case_info(data: dict) -> CaseInfo:
    """Clean the model's answer. No usable need -> ValueError (the analysis fails)."""
    needs: dict[str, str] = {}
    for value in data.get("needs") if isinstance(data.get("needs"), list) else []:
        need = _text(value, MAX_NEED_LEN)
        if need:
            needs.setdefault(need.lower(), need)
    if not needs:
        raise ValueError("no needs in the analysis")
    return CaseInfo(
        company_name=_text(data.get("company_name"), 120),
        industry=_text(data.get("industry"), 60),
        summary=_text(data.get("summary"), 600),
        needs=list(needs.values())[:MAX_NEEDS],
    )


async def read_case(llm: LLM, text: str, timeout: float = READ_TIMEOUT) -> CaseInfo:
    data = await asyncio.wait_for(llm.chat_json(SYSTEM, f"Business model:\n{text[:MAX_TEXT]}", max_tokens=600), timeout)
    return parse_case_info(data)


def merge(rankings: dict[str, list[tuple[int, float]]]) -> list[tuple[int, float, list[str]]]:
    """Reciprocal rank fusion of the needs' rankings: (entity id, score, needs it was found for), best first."""
    score: dict[int, float] = defaultdict(float)
    needs: dict[int, list[str]] = defaultdict(list)
    for need, ranked in rankings.items():
        for rank, (entity_id, _) in enumerate(ranked, start=1):
            score[entity_id] += 1 / (RRF_K + rank)
            needs[entity_id].append(need)
    merged = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(e, s, needs[e]) for e, s in merged]


@dataclass
class Match:
    need: str
    value: str     # the claim value that matched
    via: str | None  # the person's unit, when the value is the unit's topic
    sim: float


def match_needs(
    results: list[Result], needs: list[str], embed_many: Callable[[list[str]], np.ndarray]
) -> dict[int, list[Match]]:
    """Per entity, the needs it matches, best claim per need."""
    candidates = [
        (r.entity_id, e.value, e.via_unit) for r in results for e in r.evidence
        if e.field in TOPIC_FIELDS or (e.field == "name" and r.type in NAME_TYPES)
    ]
    if not candidates:
        return {}
    values = list(dict.fromkeys(v for _, v, _ in candidates))
    sims = np.asarray(embed_many(values)) @ np.asarray(embed_many(needs)).T
    row = {v: i for i, v in enumerate(values)}
    best: dict[tuple[int, str], Match] = {}
    for entity_id, value, via in candidates:
        j = int(sims[row[value]].argmax())  # the claim's closest need only
        sim, key = float(sims[row[value], j]), (entity_id, needs[j])
        if sim >= MATCH_SIM and (key not in best or sim > best[key].sim):
            best[key] = Match(needs[j], value, via, sim)
    matches: dict[int, list[Match]] = defaultdict(list)
    for (entity_id, _), m in best.items():
        matches[entity_id].append(m)
    return {e: sorted(ms, key=lambda m: -m.sim) for e, ms in matches.items()}


def _names(names: list[str], limit: int = 3) -> str:
    more = len(names) - limit
    return ", ".join(names[:limit]) + (f" and {more} more" if more > 0 else "")


def score_case(
    needs: list[str], results: list[Result], matches: dict[int, list[Match]]
) -> tuple[int, list[ScoreItem]]:
    """Overall score (weighted mean) and one row per criterion, each naming its matches."""
    matched = [r for r in results if matches.get(r.entity_id)]
    by_type: dict[str, list[Result]] = defaultdict(list)
    for r in matched:
        by_type[r.type].append(r)

    by_need: dict[str, list[str]] = defaultdict(list)
    for r in matched:
        for m in matches[r.entity_id]:
            by_need[m.need].append(r.name)
    covered = [n for n in needs if by_need[n]]
    parts = [f"{n}: {_names(by_need[n], 2)}" for n in covered]
    missing = [n for n in needs if not by_need[n]]
    fit = f"{len(covered)} of {len(needs)} needs covered" + (". " + "; ".join(parts) if parts else "")
    fit += f". Not covered: {', '.join(missing)}" if missing else ""

    people = [f"{r.name} ({m.via})" if (m := matches[r.entity_id][0]).via else r.name for r in by_type["person"]]
    units = [r.name for r in by_type["unit"]]
    # Infrastructure: matching entries, and what the matching units provide (shown "provides" relations)
    infra = list(dict.fromkeys(
        [r.name for r in by_type["infrastructure"]]
        + [f"{i} ({r.name})" for r in by_type["unit"] for i in r.infrastructure]
    ))
    projects = list(dict.fromkeys(
        [r.name for r in by_type["project"]] + [p for r in by_type["unit"] + by_type["person"] for p in r.projects]
    ))
    counts = {
        "Expert pool": (people, "people in labs that work on your needs", "experts"),
        "Research units": (units, "research units", "research units"),
        "Infrastructure & labs": (infra, "infrastructure entries", "infrastructure"),
        "Running projects": (projects, "projects", "projects"),
    }
    rows = []
    for criterion, _, points in CRITERIA:
        if points is None:
            score = round(100 * len(covered) / len(needs)) if needs else 0
            rows.append(ScoreItem(criterion=criterion, score=score, rationale=fit))
            continue
        names, label, what = counts[criterion]
        rationale = f"{len(names)} {label}: {_names(names)}" if names else f"No matching {what} in our sources"
        rows.append(ScoreItem(criterion=criterion, score=min(100, len(names) * points), rationale=rationale))
    overall = round(sum(w * row.score for (_, w, _), row in zip(CRITERIA, rows)))
    return overall, rows


def find_references(
    conn: psycopg.Connection, needs: list[str], embed: Callable[[str], np.ndarray]
) -> list[tuple[int, float, list[str]]]:
    rankings = {n: rank_entities(conn, n, types=ALL_TYPES, embed=embed).ranked for n in needs}
    merged = merge(rankings)
    capped = fairness_cap(
        [(e, s) for e, s, _ in merged], _units(conn, [e for e, _, _ in merged]), MAX_PER_UNIT, MAX_REFERENCES
    )
    needs_of = {e: n for e, _, n in merged}
    return [(e, s, needs_of[e]) for e, s in capped]


def analyze(
    conn: psycopg.Connection,
    case_id: str,
    read: Callable[[str], CaseInfo],
    embed: Callable[[str], np.ndarray],
    embed_many: Callable[[list[str]], np.ndarray],
    explain: Callable[[str, list[Result]], dict[int, str]],
) -> None:
    """Run the analysis of a pending case and store it; on any error the case is marked failed."""
    row = conn.execute("""SELECT pdf_text FROM "case" WHERE id = %s AND analysis_status = 'pending'""", (case_id,))
    found = row.fetchone()
    if found is None:
        return
    try:
        info = read(found[0])
        refs = find_references(conn, info.needs, embed)
        results = build_results(conn, [(e, s) for e, s, _ in refs])
        matches = match_needs(results, info.needs, embed_many)
        score, rows = score_case(info.needs, results, matches)
        # The need each reference is explained with: its best match, else the first need it was found for
        found_for = {e: n for e, _, n in refs}
        need_of = {
            r.entity_id: matches[r.entity_id][0].need if matches.get(r.entity_id) else found_for[r.entity_id][0]
            for r in results
        }
        why: dict[int, str] = {}
        for need in info.needs:
            group = [r for r in results if need_of[r.entity_id] == need]
            if group:
                why.update(explain(need, group))
        stored = [
            {"entity_id": r.entity_id, "score": r.score, "need": need_of[r.entity_id],
             "needs": [m.need for m in matches.get(r.entity_id, [])], "why": why.get(r.entity_id)}
            for r in results
        ]
    except Exception:
        log.exception("case analysis failed: %s", case_id)
        conn.execute("""UPDATE "case" SET analysis_status = 'failed' WHERE id = %s""", (case_id,))
        conn.commit()
        return
    conn.execute(
        """UPDATE "case" SET analysis_status = 'done', company_name = coalesce(%s, company_name), industry = %s,
           summary = %s, needs = %s, refs = %s, score = %s, score_breakdown = %s WHERE id = %s""",
        (info.company_name, info.industry, info.summary, Jsonb(info.needs), Jsonb(stored), score,
         Jsonb([r.model_dump() for r in rows]), case_id),
    )
    conn.commit()
    log.info("case %s analysed: %d needs, %d references, score %d", case_id, len(info.needs), len(stored), score)


def references(conn: psycopg.Connection, case_id: str, limit: int) -> list[Result] | None:
    """The case's stored references, rebuilt from the current claims (entities gone since are dropped).
    None if the case does not exist. A stored sentence is kept only if its citations still check out."""
    row = conn.execute("""SELECT refs FROM "case" WHERE id = %s""", (case_id,)).fetchone()
    if row is None:
        return None
    refs = {r["entity_id"]: r for r in row[0]}
    results = build_results(conn, [(r["entity_id"], r["score"]) for r in row[0]])[:limit]
    out = []
    for r in results:
        ref = refs[r.entity_id]
        sentence = ref.get("why") and check_sentence(ref["why"], {e.claim_id: e for e in prompt_claims(r.evidence)})
        why = f"Matches '{ref['need']}': {sentence}" if sentence else f"Matches '{ref['need']}'. {r.why}"
        out.append(r.model_copy(update={"why": why}))
    return out
