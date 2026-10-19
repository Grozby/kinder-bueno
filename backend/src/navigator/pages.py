"""Crawled pages ranked by what they give the search (FRONTEND_API "Resources", #78)."""

import re
from dataclasses import dataclass

import psycopg

from navigator.models import PageDetail, PageFact, PageKind, ResourcePage, ScoreItem
from navigator.results import shown

YIELD_FULL = 40  # shown claims for a full yield score

# (kind, URL pattern), first match wins; checked before the entity-type fallback
KIND_PATTERNS: list[tuple[PageKind, re.Pattern]] = [
    ("team", re.compile(r"/(team|group_members|members|people|staff|mitarbeitende)/")),
    ("project", re.compile(r"/(projects?|project_category|research_activities|focus-areas)/")),
    ("infrastructure", re.compile(r"/(services|offering|infrastructure|facilit(y|ies)|core_facilities)/")),
    ("lab", re.compile(r"_lab/|/lab/|/research/[a-z]+/index|/research_programs/")),
]


@dataclass
class SourceRules:
    """The URL patterns of one source that the pages list reports (config/sources.yaml until #79)."""

    exclude: list[str]
    priority: list[str]


def guess_kind(url: str, person_claims: int, claims: int) -> PageKind:
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(url):
            return kind
    return "team" if claims and person_claims * 2 > claims else "other"


def _first_match(patterns: list[str], url: str) -> str | None:
    return next((p for p in patterns if re.search(p, url)), None)


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _page(row: tuple, rules: dict[str, SourceRules]) -> ResourcePage:
    (pid, source_id, url, title, fetched_at, claims, entities, person_claims,
     judged, supported, raw, raw_verified, up, down) = row
    judge_supported = supported / judged if judged else None
    drop_rate = 1 - raw_verified / raw if raw else None
    yield_score = min(100, round(claims / YIELD_FULL * 100))
    precision = round(judge_supported * 100) if judge_supported is not None else 0
    survival = round((1 - drop_rate) * 100) if drop_rate is not None else 0
    feedback = round((up + 1) / (up + down + 2) * 100)
    breakdown = [
        ScoreItem(criterion="Yield", score=yield_score,
                  rationale=f"{claims} verified facts about {entities} people, units or projects."),
        ScoreItem(criterion="Precision", score=precision, rationale=(
            f"The judge found {_pct(judge_supported)} of the {judged} judged facts fully supported by their quote."
            if judge_supported is not None else "No facts judged yet.")),
        ScoreItem(criterion="Verification", score=survival, rationale=(
            f"{_pct(drop_rate)} of the {raw} extracted facts were dropped: their quote was not on the page."
            if drop_rate is not None else "Nothing was extracted.")),
        ScoreItem(criterion="Feedback", score=feedback, rationale=(
            f"{up} up and {down} down on results that cite this page." if up + down else "No feedback yet.")),
    ]
    source_rules = rules.get(source_id, SourceRules([], []))
    return ResourcePage(
        id=pid, source_id=source_id, url=url, title=title or url, kind=guess_kind(url, person_claims, claims),
        status="crawled",
        score=round(0.4 * yield_score + 0.3 * precision + 0.2 * survival + 0.1 * feedback),
        score_breakdown=breakdown, entities=entities, verified_claims=claims,
        judge_supported=judge_supported, drop_rate=drop_rate, feedback_up=up, feedback_down=down,
        crawled_at=fetched_at,
        blocked_by=_first_match(source_rules.exclude, url),
        prioritised_by=_first_match(source_rules.priority, url),
    )


def list_pages(conn: psycopg.Connection, rules: dict[str, SourceRules], page_id: int | None = None) -> list[ResourcePage]:
    """Every stored page with its score; all of them, or the one with `page_id`.
    Feedback counts 👍/👎 on entities that have a shown claim on the page (their result cites it)."""
    rows = conn.execute(
        f"""
        SELECT p.id, p.source_id, p.url, p.title, p.fetched_at,
               coalesce(c.claims, 0), coalesce(c.entities, 0), coalesce(c.person_claims, 0),
               coalesce(c.judged, 0), coalesce(c.supported, 0),
               coalesce(r.raw, 0), coalesce(r.raw_verified, 0),
               coalesce(f.up, 0), coalesce(f.down, 0)
        FROM page p
        LEFT JOIN LATERAL (
            SELECT count(*) FILTER (WHERE {shown("cl", include_blocked=True)}) AS claims,
                   count(DISTINCT cl.entity_id) FILTER (WHERE {shown("cl", include_blocked=True)}) AS entities,
                   count(*) FILTER (WHERE {shown("cl", include_blocked=True)} AND e.type = 'person') AS person_claims,
                   count(*) FILTER (WHERE cl.verified AND cl.judge_verdict IS NOT NULL) AS judged,
                   count(*) FILTER (WHERE cl.verified AND cl.judge_verdict = 'supported') AS supported
            FROM claim cl JOIN entity e ON e.id = cl.entity_id
            WHERE cl.page_id = p.id
        ) c ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS raw, count(*) FILTER (WHERE rc.verified) AS raw_verified
            FROM raw_claim rc WHERE rc.page_id = p.id
        ) r ON true
        LEFT JOIN LATERAL (
            SELECT count(*) FILTER (WHERE fb.rating = 'up') AS up, count(*) FILTER (WHERE fb.rating = 'down') AS down
            FROM feedback fb
            WHERE EXISTS (SELECT 1 FROM claim cl WHERE cl.entity_id = fb.entity_id AND cl.page_id = p.id
                            AND {shown("cl", include_blocked=True)})
        ) f ON true
        WHERE %(id)s::int IS NULL OR p.id = %(id)s
        ORDER BY p.id
        """,
        {"id": page_id},
    ).fetchall()
    return [_page(row, rules) for row in rows]


def get_page(conn: psycopg.Connection, rules: dict[str, SourceRules], page_id: int) -> PageDetail | None:
    """The page with its shown facts; None if it does not exist."""
    found = list_pages(conn, rules, page_id)
    if not found:
        return None
    facts = [
        PageFact(claim_id=cid, entity_id=eid, entity_name=name, entity_type=type_, field=field, value=value,
                 quote=quote, judge_verdict=verdict)
        for cid, eid, name, type_, field, value, quote, verdict in conn.execute(
            f"""
            SELECT cl.id, e.id, e.name, e.type, cl.field, cl.value, cl.quote, cl.judge_verdict
            FROM claim cl JOIN entity e ON e.id = cl.entity_id
            WHERE cl.page_id = %s AND {shown("cl", include_blocked=True)}
            ORDER BY e.name, cl.id
            """,
            (page_id,),
        )
    ]
    return PageDetail(**found[0].model_dump(), facts=facts)
