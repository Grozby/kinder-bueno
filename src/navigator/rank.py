"""Entity ranking on top of chunk search (plan 8.4 steps 2-4, 8.5, 8.7)."""

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
BEST_CHUNKS = 3       # entity score = sum of its best 3 chunk scores (8.4 step 3)
PAGE_ONLY_WEIGHT = 0.5
MIN_SIM = 0.45        # below this, and with no keyword hit, there is no reliable result (8.7)


@dataclass
class Ranking:
    ranked: list[tuple[int, float]]  # (entity id, score), best first
    no_result: bool


def entity_scores(hits: list[ChunkHit], claims: list[tuple[int, int, str]]) -> dict[int, float]:
    """Link chunks to entities through their shown claims (entity id, page id, quote) and score them.

    Full weight if one of the entity's quotes is in the chunk, half weight if it is only on the same page.
    """
    by_page: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for entity_id, page_id, quote in claims:
        by_page[page_id].append((entity_id, norm(quote)))
    chunk_scores: dict[int, list[float]] = defaultdict(list)
    for hit in hits:
        text = norm(hit.text)
        weight: dict[int, float] = {}
        for entity_id, quote in by_page.get(hit.page_id, []):
            w = 1.0 if quote in text else PAGE_ONLY_WEIGHT
            weight[entity_id] = max(w, weight.get(entity_id, 0.0))
        for entity_id, w in weight.items():
            chunk_scores[entity_id].append(hit.score * w)
    return {e: sum(sorted(s, reverse=True)[:BEST_CHUNKS]) for e, s in chunk_scores.items()}


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
    claims = _shown_claims(conn, list({h.page_id for h in hits}), types or DEFAULT_TYPES, sources)
    scores = entity_scores(hits, claims)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    capped = fairness_cap(ranked, _units(conn, [e for e, _ in ranked]))
    return Ranking(capped, no_result=not capped)
