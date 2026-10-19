"""The search pipeline shared by /api/search, /api/chat and `navigator search`."""

from collections.abc import Callable

import psycopg

from navigator.models import EntityType, Expansion, SearchResponse
from navigator.search.explain import apply_why
from navigator.search.rank import rank_entities
from navigator.search.results import build_results


def run_search(
    conn: psycopg.Connection, embed: Callable, expand: Callable, explain: Callable,
    q: str, sources: list[str], types: list[EntityType],
) -> SearchResponse:
    """The search pipeline shared by /api/search and /api/chat: expand → rank → build → explain."""
    terms = expand(q)
    ranking = rank_entities(conn, q, sources=sources, types=types, extra_terms=terms.terms, embed=embed)
    results = build_results(conn, ranking.ranked)
    results = apply_why(results, explain(q, results)) if results else results
    expansion = Expansion(en=terms.en, de=terms.de) if terms.terms else None
    return SearchResponse(results=results, expansion=expansion, no_result=not results)
