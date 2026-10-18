"""Entity ranking on top of chunk search (plan 8.4 steps 2-4, 8.5, 8.7)."""

import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import psycopg

from navigator.results import shown
from navigator.search import ChunkHit, keyword_search, search_chunks
from navigator.verify import norm

DEFAULT_TYPES = ["person", "unit"]  # projects / infrastructure only when the filter asks (8.4 step 4)
MAX_RESULTS = 10
MAX_PER_UNIT = 3      # fairness cap (8.5)
MIN_SIM = 0.45        # below this, and with no keyword hit, there is no reliable result (8.7)
# Tuned on the eval set (#29, recall@10 14% -> 46%). Re-run `navigator eval` after changing any of these.
BEST_CHUNKS = 1       # plan 8.4 said the best 3: that favours entities on long pages with many matching chunks
PAGE_ONLY_WEIGHT = 0.25
USE_IDF = True        # an entity with claims on many pages ("ARTORG Center") is linked to every query on them
INHERIT = 0.5         # a person gets this share of their unit's score (people have almost no topic claims)
SENIOR_BOOST = 0.1    # heads and professors first among a unit's members
CHUNK_SHARE = 0.5     # a chunk's score is split among the entities it names: / (number named) ** CHUNK_SHARE
SENIOR_ROLE = re.compile(r"\b(head|director|professor|prof|chair|leader|lead|principal investigator|pi)\b", re.I)


@dataclass
class Ranking:
    ranked: list[tuple[int, float]]  # (entity id, score), best first
    no_result: bool


def idf(pages_with_claims: int, total_pages: int) -> float:
    """1.0 for an entity on one page, falling towards 0 for an entity on every page."""
    return math.log(1 + total_pages / max(pages_with_claims, 1)) / math.log(1 + total_pages)


def entity_scores(
    hits: list[ChunkHit], claims: list[tuple[int, int, str]], weight: dict[int, float] | None = None
) -> dict[int, float]:
    """Link chunks to entities through their shown claims (entity id, page id, quote) and score them.

    Full weight if one of the entity's quotes is in the chunk, PAGE_ONLY_WEIGHT if it is only on the same page;
    times the entity's `weight` (default 1). A chunk that names many entities (an overview page) counts less
    for each of them.
    """
    by_page: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for entity_id, page_id, quote in claims:
        by_page[page_id].append((entity_id, norm(quote)))
    chunk_scores: dict[int, list[float]] = defaultdict(list)
    for hit in hits:
        text = norm(hit.text)
        link: dict[int, float] = {}
        for entity_id, quote in by_page.get(hit.page_id, []):
            w = 1.0 if quote in text else PAGE_ONLY_WEIGHT
            link[entity_id] = max(w, link.get(entity_id, 0.0))
        named = sum(1 for w in link.values() if w == 1.0) or 1
        for entity_id, w in link.items():
            share = hit.score * w / named**CHUNK_SHARE
            chunk_scores[entity_id].append(share * (weight or {}).get(entity_id, 1.0))
    return {e: sum(sorted(s, reverse=True)[:BEST_CHUNKS]) for e, s in chunk_scores.items()}


def inherit(scores: dict[int, float], members: list[tuple[int, int]], share: float) -> dict[int, float]:
    """Add `share` of each unit's score to its members (person id, unit id); a person's best unit counts."""
    best: dict[int, float] = {}
    for person, unit in members:
        if unit in scores:
            best[person] = max(best.get(person, 0.0), scores[unit])
    out = dict(scores)
    for person, unit_score in best.items():
        out[person] = out.get(person, 0.0) + share * unit_score
    return out


def fairness_cap(
    ranked: list[tuple[int, float]], unit_of: dict[int, int], per_unit: int = MAX_PER_UNIT, limit: int = MAX_RESULTS
) -> list[tuple[int, float]]:
    """Top `limit` with at most `per_unit` results per unit. Results with no unit are not capped."""
    taken: dict[int, int] = defaultdict(int)
    out = []
    for entity_id, score in ranked:
        unit = unit_of.get(entity_id)
        if unit is not None:
            if taken[unit] >= per_unit:
                continue
            taken[unit] += 1
        out.append((entity_id, score))
        if len(out) == limit:
            break
    return out


def _shown_claims(conn: psycopg.Connection, page_ids: list[int], types: list[str], sources: list[str]) -> list:
    return conn.execute(
        f"""
        SELECT c.entity_id, c.page_id, c.quote
        FROM claim c JOIN entity e ON e.id = c.entity_id JOIN page p ON p.id = c.page_id
        WHERE c.page_id = ANY(%s) AND {shown("c")} AND e.type = ANY(%s)
          AND (cardinality(%s::text[]) = 0 OR p.source_id = ANY(%s))
        """,
        (page_ids, types, sources, sources),
    ).fetchall()


def _idf_weights(conn: psycopg.Connection, entity_ids: list[int]) -> dict[int, float]:
    total = conn.execute("SELECT count(*) FROM page").fetchone()[0]
    rows = conn.execute(
        f"SELECT c.entity_id, count(DISTINCT c.page_id) FROM claim c "
        f"WHERE c.entity_id = ANY(%s) AND {shown('c')} GROUP BY c.entity_id",
        (entity_ids,),
    )
    return {entity_id: idf(pages, total) for entity_id, pages in rows}


def _members(conn: psycopg.Connection, unit_ids: list[int], sources: list[str]) -> list[tuple[int, int]]:
    """(person, unit) for shown member_of / listed_in relations into these units."""
    return conn.execute(
        f"""
        SELECT r.from_id, r.to_id FROM relation r JOIN page p ON p.id = r.page_id
        WHERE r.to_id = ANY(%s) AND r.rel IN ('member_of', 'listed_in') AND {shown("r")}
          AND (cardinality(%s::text[]) = 0 OR p.source_id = ANY(%s))
        """,
        (unit_ids, sources, sources),
    ).fetchall()


def _senior(conn: psycopg.Connection, person_ids: list[int]) -> set[int]:
    roles = conn.execute(
        f"SELECT c.entity_id, c.value FROM claim c WHERE c.entity_id = ANY(%s) AND c.field = 'role' AND {shown('c')}",
        (person_ids,),
    )
    return {entity_id for entity_id, role in roles if SENIOR_ROLE.search(role)}


def _units(conn: psycopg.Connection, entity_ids: list[int]) -> dict[int, int]:
    """Unit of each entity: a person's first member_of unit (else listed_in, #23), a unit itself."""
    unit_of = {
        r[0]: r[0] for r in conn.execute("SELECT id FROM entity WHERE id = ANY(%s) AND type = 'unit'", (entity_ids,))
    }
    for person, unit in conn.execute(
        f"SELECT DISTINCT ON (r.from_id) r.from_id, r.to_id FROM relation r "
        f"WHERE r.from_id = ANY(%s) AND r.rel IN ('member_of', 'listed_in') AND {shown('r')} "
        f"ORDER BY r.from_id, r.rel <> 'member_of', r.id",
        (entity_ids,),
    ):
        unit_of[person] = unit
    return unit_of


def rank_entities(
    conn: psycopg.Connection,
    query: str,
    sources: list[str] = [],
    types: list[str] = [],
    extra_terms: list[str] = [],
    embed: Callable[[str], np.ndarray] | None = None,
) -> Ranking:
    """Ranked entity ids for a query. `conn` needs pgvector registered (chunks_db.connect)."""
    hits = search_chunks(conn, query, extra_terms, embed=embed, max_per_page=None)
    best_sim = max((h.similarity for h in hits if h.similarity is not None), default=0.0)
    if best_sim < MIN_SIM and not keyword_search(conn, query, extra_terms, limit=1):
        return Ranking([], no_result=True)
    types = types or DEFAULT_TYPES
    # Units are scored even when the filter hides them: their members inherit from them.
    claims = _shown_claims(conn, list({h.page_id for h in hits}), sorted({*types, "unit"}), sources)
    linked = list({c[0] for c in claims})
    scores = entity_scores(hits, claims, _idf_weights(conn, linked) if USE_IDF else None)
    if INHERIT and "person" in types:
        scores = inherit(scores, _members(conn, list(scores), sources), INHERIT)
    if SENIOR_BOOST:
        for person in _senior(conn, list(scores)):
            scores[person] *= 1 + SENIOR_BOOST
    allowed = {r[0] for r in conn.execute("SELECT id FROM entity WHERE id = ANY(%s) AND type = ANY(%s)",
                                          (list(scores), types))}
    ranked = sorted(((e, s) for e, s in scores.items() if e in allowed), key=lambda kv: (-kv[1], kv[0]))
    capped = fairness_cap(ranked, _units(conn, [e for e, _ in ranked]))
    return Ranking(capped, no_result=not capped)
