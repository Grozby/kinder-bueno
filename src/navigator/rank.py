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
MIN_SIM = 0.50        # below this, and with no keyword hit, there is no reliable result (8.7). #99: gold queries
                      # 0.57-0.74, off-topic ones 0.32-0.47
# Tuned on the eval set (#29, recall@10 14% -> 46%; #59, 46% -> 59%; #99 sweep and #75 topic match in PLAN.md 10.2).
# Re-run `navigator eval` after changing any of these.
BEST_CHUNKS = 1       # plan 8.4 said the best 3: that favours entities on long pages with many matching chunks
PAGE_ONLY_WEIGHT = 0.25
USE_IDF = True        # an entity with claims on many pages ("ARTORG Center") is linked to every query on them
INHERIT = 0.5         # a person gets this share of their unit's score (people have almost no topic claims)
SENIOR_BOOST = 0.3    # heads and professors first among a unit's members
TOPIC_WEIGHT = 0.4    # entities whose own topic claims (expertise, description) match the query (#59)
TOPIC_MIN = 0.5       # cosine similarity below this adds nothing
PERSON_TOPIC = 0.25   # share of the topic bonus for a person's own topics (#75): they don't beat lab evidence
TOPIC_ALONE = 0.5     # share of the topic bonus for an entity without chunk evidence
TOPIC_TOPK = 2        # mean of an entity's best k topic similarities: one generic claim ("monitoring") is not enough
TOPIC_FIELDS = ("expertise", "description")
TOPICS_PER_PAGE = 8   # an entity's first topic claims per page: 8B sometimes loops into long generic lists
SECTION_WEIGHT = 1.0  # a unit with a member page owns the pages under its home folder (#59), as if named there
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


def home_folder(member_page_url: str) -> str:
    """".../research/aihn/group_members/index_eng.html" -> ".../research/aihn/": the folder above the member page's."""
    folder = member_page_url.rsplit("/", 1)[0]
    return folder.rsplit("/", 1)[0] + "/"


def section_scores(hits: list[ChunkHit], homes: list[tuple[int, str]], weight: float) -> dict[int, float]:
    """Score of each unit (unit id, home folder) from its best chunk on a page under its home folder.
    When folders nest, the deepest owner wins (a lab, not the whole site)."""
    out: dict[int, float] = {}
    for hit in hits:
        owners = [(len(home), unit) for unit, home in homes if hit.url.startswith(home)]
        if not owners:
            continue
        deepest = max(n for n, _ in owners)
        for n, unit in owners:
            if n == deepest:
                out[unit] = max(out.get(unit, 0.0), hit.score * weight)
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


def _embed_query(text: str) -> np.ndarray:
    from navigator.embed import embed_query  # imported lazily: loads torch

    return embed_query(text)


# Per process: embedding function (None = the real bge-m3 model) -> claim value -> vector. Keyed by function so
# test fakes never see the real model's vectors or each other's.
_topic_vecs: dict[Callable | None, dict[str, np.ndarray]] = {}


def _once(embed: Callable[[str], np.ndarray]) -> Callable[[str], np.ndarray]:
    """`embed` that computes each text once: chunk search and topic match embed the same query strings
    (~0.4 s each on the CPU-only Docker image)."""
    vecs: dict[str, np.ndarray] = {}

    def embed_once(text: str) -> np.ndarray:
        if text not in vecs:
            vecs[text] = embed(text)
        return vecs[text]

    return embed_once


def topic_scores(
    claims: list[tuple[int, str]], query_vecs: list[np.ndarray], vec_of: Callable[[str], np.ndarray]
) -> dict[int, float]:
    """Per entity, the mean of its best TOPIC_TOPK topic claims (entity id, value), each scored by its best cosine
    similarity to any query vector."""
    per: dict[int, list[float]] = {}
    for entity_id, value in claims:
        v = vec_of(value)
        per.setdefault(entity_id, []).append(max(float(np.dot(v, q)) for q in query_vecs))
    return {e: float(np.mean(sorted(sims, reverse=True)[:TOPIC_TOPK])) for e, sims in per.items()}


def _topic_claims(conn: psycopg.Connection, types: list[str], sources: list[str]) -> list[tuple[int, str]]:
    return conn.execute(
        f"""
        SELECT DISTINCT entity_id, value FROM (
          SELECT c.entity_id, c.value,
                 row_number() OVER (PARTITION BY c.entity_id, c.page_id, c.field ORDER BY c.id) AS n
          FROM claim c JOIN entity e ON e.id = c.entity_id JOIN page p ON p.id = c.page_id
          WHERE c.field = ANY(%s) AND {shown("c")} AND e.type = ANY(%s)
            AND (cardinality(%s::text[]) = 0 OR p.source_id = ANY(%s))
        ) t WHERE n <= %s
        """,
        (list(TOPIC_FIELDS), types, sources, sources, TOPICS_PER_PAGE),
    ).fetchall()


def _is_real_model(embed: Callable[[str], np.ndarray] | None) -> bool:
    """None or navigator.embed.embed_query (the API passes it explicitly), without importing torch here."""
    return embed is None or (getattr(embed, "__module__", ""), getattr(embed, "__name__", "")) == (
        "navigator.embed", "embed_query")


def _topic_vec_of(embed: Callable[[str], np.ndarray] | None, values: list[str]) -> Callable[[str], np.ndarray]:
    """Embeddings of topic values, cached per process and per embedding function. With the real model the missing
    ones are embedded in one batch; ~500 values take seconds, so `warm_topic_vectors` fills the cache at server
    start and searches do not embed while their transaction is open."""
    real = _is_real_model(embed)
    cache = _topic_vecs.setdefault(None if real else embed, {})
    missing = [v for v in dict.fromkeys(values) if v not in cache]
    if missing:
        if real:
            from navigator.embed import embed_documents  # imported lazily: loads torch

            cache.update(zip(missing, embed_documents(missing)))
        else:
            cache.update((v, embed(v)) for v in missing)
    return cache.__getitem__


def warm_topic_vectors(conn: psycopg.Connection) -> int:
    """Embed every topic value with the real model now (server start). Returns how many were new.
    Ends the read transaction before embedding, so no transaction stays open meanwhile."""
    values = [v for _, v in _topic_claims(conn, ["person", "unit", "project", "infrastructure"], [])]
    conn.rollback()
    before = len(_topic_vecs.get(None, {}))
    _topic_vec_of(None, values)
    return len(_topic_vecs[None]) - before


def _homes(conn: psycopg.Connection, sources: list[str]) -> list[tuple[int, str]]:
    """(unit id, home folder) for units with a member page (the pages their listed_in relations come from)."""
    rows = conn.execute(
        f"""
        SELECT DISTINCT r.to_id, p.url FROM relation r JOIN page p ON p.id = r.page_id
        WHERE r.rel = 'listed_in' AND {shown("r")}
          AND (cardinality(%s::text[]) = 0 OR p.source_id = ANY(%s))
        """,
        (sources, sources),
    ).fetchall()
    return [(unit, home_folder(url)) for unit, url in rows]


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
    embed_query_once = _once(embed or _embed_query)
    hits = search_chunks(conn, query, extra_terms, embed=embed_query_once, max_per_page=None)
    best_sim = max((h.similarity for h in hits if h.similarity is not None), default=0.0)
    if best_sim < MIN_SIM and not keyword_search(conn, query, extra_terms, limit=1):
        return Ranking([], no_result=True)
    types = types or DEFAULT_TYPES
    # Units are scored even when the filter hides them: their members inherit from them.
    claims = _shown_claims(conn, list({h.page_id for h in hits}), sorted({*types, "unit"}), sources)
    linked = list({c[0] for c in claims})
    weights = _idf_weights(conn, linked) if USE_IDF else None
    scores = entity_scores(hits, claims, weights)
    if TOPIC_WEIGHT:
        topic_claims = _topic_claims(conn, sorted({*types, "unit"}), sources)
        queries = [query] + ([f"{query}, {', '.join(extra_terms[:4])}"] if extra_terms else [])
        query_vecs = [embed_query_once(q) for q in queries]
        sims = topic_scores(topic_claims, query_vecs, _topic_vec_of(embed, [v for _, v in topic_claims]))
        topic_idf = _idf_weights(conn, list(sims)) if USE_IDF else {}
        people = {r[0] for r in conn.execute("SELECT id FROM entity WHERE id = ANY(%s) AND type = 'person'",
                                             (list(sims),))}
        for entity_id, sim in sims.items():
            if sim > TOPIC_MIN:
                bonus = TOPIC_WEIGHT * (sim - TOPIC_MIN) * topic_idf.get(entity_id, 1.0)
                if entity_id in people:
                    bonus *= PERSON_TOPIC
                if not scores.get(entity_id):
                    bonus *= TOPIC_ALONE
                scores[entity_id] = scores.get(entity_id, 0.0) + bonus
    if SECTION_WEIGHT:
        for unit, s in section_scores(hits, _homes(conn, sources), SECTION_WEIGHT).items():
            scores[unit] = max(scores.get(unit, 0.0), s)
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
