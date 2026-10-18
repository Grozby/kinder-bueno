"""Chunk-level hybrid search: keyword + semantic, fused with Reciprocal Rank Fusion (plan 8.2-8.4 step 1)."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import psycopg

TOP_N = 50
RRF_K = 60


@dataclass
class ChunkHit:
    chunk_id: int
    page_id: int
    url: str
    text: str
    score: float  # RRF score
    similarity: float | None  # best cosine similarity to a query vector, if in a semantic top list


def _unique_terms(terms: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for t in terms:
        t = " ".join(t.split())
        if t and t.lower() not in seen:
            seen[t.lower()] = t
    return list(seen.values())


def query_words(conn: psycopg.Connection, query: str) -> list[str]:
    """The query's words, tokenised like `chunk.tsv`, without English/German stopwords (unless that leaves none)."""
    rows = conn.execute(
        "SELECT lexeme, ts_lexize('english_stem', lexeme) = '{}' OR ts_lexize('german_stem', lexeme) = '{}' "
        "FROM unnest(to_tsvector('simple', %s))",
        (query,),
    ).fetchall()
    content = [w for w, is_stopword in rows if not is_stopword]
    return content or [w for w, _ in rows]


def keyword_search(
    conn: psycopg.Connection, query: str, extra_terms: list[str] = [], limit: int = TOP_N
) -> list[int]:
    """Chunk ids ranked by ts_rank_cd for an OR of the query's words and the extra terms.

    The query is split into words: the 'simple' config does not stem, so requiring the whole
    query ("heart valve research") misses pages that say "valves". ts_rank_cd still ranks chunks
    with more of the words, closer together, first. Multi-word extra terms stay phrases.
    """
    terms = _unique_terms([*query_words(conn, query), *extra_terms])
    if not terms:
        return []
    parts = [
        "phraseto_tsquery('simple', %s)" if " " in t else "plainto_tsquery('simple', %s)" for t in terms
    ]
    sql = (
        f"SELECT id FROM chunk, (SELECT {' || '.join(parts)} AS q) AS query "
        "WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC, id LIMIT %s"
    )
    return [r[0] for r in conn.execute(sql, (*terms, limit)).fetchall()]


def semantic_search(conn: psycopg.Connection, vec: np.ndarray, limit: int = TOP_N) -> list[tuple[int, float]]:
    """(chunk id, cosine similarity), nearest first."""
    return conn.execute(
        "SELECT id, 1 - (embedding <=> %s) FROM chunk WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> %s LIMIT %s",
        (vec, vec, limit),
    ).fetchall()


def rrf(ranked_lists: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score = sum of 1 / (k + rank), rank starting at 1. Best first."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def search_chunks(
    conn: psycopg.Connection,
    query: str,
    extra_terms: list[str] = [],
    embed: Callable[[str], np.ndarray] | None = None,
    limit: int = TOP_N,
) -> list[ChunkHit]:
    """Fused chunk ranking for `query` plus optional expansion terms. `conn` needs pgvector registered."""
    if embed is None:
        from navigator.embed import embed_query  # imported lazily: loads torch

        embed = embed_query
    lists = [keyword_search(conn, query, extra_terms)]
    queries = [query] + ([f"{query}, {', '.join(extra_terms[:4])}"] if extra_terms else [])
    similarity: dict[int, float] = {}
    for q in queries:
        semantic = semantic_search(conn, embed(q))
        lists.append([cid for cid, _ in semantic])
        for cid, sim in semantic:
            similarity[cid] = max(sim, similarity.get(cid, -1.0))

    fused = rrf(lists)[:limit]
    rows = conn.execute(
        "SELECT c.id, c.page_id, p.url, c.text FROM chunk c JOIN page p ON p.id = c.page_id "
        "WHERE c.id = ANY(%s)",
        ([cid for cid, _ in fused],),
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    return [
        ChunkHit(cid, by_id[cid][1], by_id[cid][2], by_id[cid][3], score, similarity.get(cid))
        for cid, score in fused
        if cid in by_id
    ]
