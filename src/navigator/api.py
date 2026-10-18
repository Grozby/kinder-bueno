"""HTTP API (plan 8.9). Run with `navigator serve`."""

import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import anyio
import numpy as np
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from navigator import chunks_db
from navigator.expand import Expansion as TermExpansion
from navigator.expand import expand_query
from navigator.llm import LLM
from navigator.models import (
    EntityType,
    Expansion,
    FeedbackCounts,
    FeedbackRequest,
    FeedbackResponse,
    SearchResponse,
    SourceStats,
    StatsResponse,
)
from navigator.rank import rank_entities
from navigator.results import build_results, shown
from navigator.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the embedding model at startup, not on the first search (plan 8.9). One LLM client for the
    whole process: it is bound to this event loop."""
    from navigator.embed import get_model

    get_model()
    app.state.llm = LLM(get_settings())
    yield


app = FastAPI(title="Research & Expertise Navigator", lifespan=lifespan)


@app.middleware("http")
async def require_token(request: Request, call_next: Callable) -> Response:
    """Shared bearer token for /api when API_TOKEN is set (sharing the server on the LAN)."""
    token = get_settings().api_token
    if token and request.url.path.startswith("/api"):
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not secrets.compare_digest(given.encode(), token.encode()):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing token"})
    return await call_next(request)


def get_conn() -> Iterator[psycopg.Connection]:
    """One connection per request (pgvector registered); commits on success."""
    with chunks_db.connect(get_settings().database_url) as conn:
        yield conn


def get_embed() -> Callable[[str], np.ndarray]:
    from navigator.embed import embed_query

    return embed_query


def get_expand(request: Request) -> Callable[[str], TermExpansion]:
    """Query expansion (plan 8.1). Sync routes run in a worker thread, so the coroutine runs on the main loop."""
    llm = request.app.state.llm
    return lambda q: anyio.from_thread.run(expand_query, llm, q)


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Embed = Annotated[Callable[[str], np.ndarray], Depends(get_embed)]
Expand = Annotated[Callable[[str], TermExpansion], Depends(get_expand)]


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    log.error("database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/search")
def search(
    conn: Conn,
    embed: Embed,
    expand: Expand,
    q: Annotated[str, Query(min_length=1)],
    source: Annotated[list[str], Query()] = [],
    type: Annotated[list[EntityType], Query()] = [],
) -> SearchResponse:
    """Stateless search. Filters repeat like the UI checkboxes: `?type=person&type=unit&source=dcb`.
    No source = all sources; no type = person and unit."""
    terms = expand(q)
    ranking = rank_entities(conn, q, sources=source, types=type, extra_terms=terms.terms, embed=embed)
    results = build_results(conn, ranking.ranked)
    expansion = Expansion(en=terms.en, de=terms.de) if terms.terms else None
    return SearchResponse(results=results, expansion=expansion, no_result=not results)


@app.get("/api/stats")
def stats(conn: Conn) -> StatsResponse:
    """Counts per source (shown claims only) and feedback counts by rating."""
    rows = conn.execute(
        f"""
        SELECT s.id,
               count(DISTINCT p.id),
               count(DISTINCT ch.id),
               count(DISTINCT cl.entity_id) FILTER (WHERE {shown("cl")}),
               count(DISTINCT cl.id) FILTER (WHERE {shown("cl")})
        FROM source s
        LEFT JOIN page p   ON p.source_id = s.id
        LEFT JOIN chunk ch ON ch.page_id = p.id
        LEFT JOIN claim cl ON cl.page_id = p.id
        GROUP BY s.id
        ORDER BY s.id
        """
    ).fetchall()
    ratings = dict(conn.execute("SELECT rating, count(*) FROM feedback GROUP BY rating").fetchall())
    return StatsResponse(
        sources=[
            SourceStats(source=r[0], pages=r[1], chunks=r[2], entities=r[3], shown_claims=r[4]) for r in rows
        ],
        feedback=FeedbackCounts(**{k: ratings.get(k, 0) for k in FeedbackCounts.model_fields}),
    )


@app.post("/api/feedback")
def feedback(conn: Conn, body: FeedbackRequest) -> FeedbackResponse:
    """Log one feedback row with a text snapshot. Never changes results."""
    entity = conn.execute("SELECT name FROM entity WHERE id = %s", (body.entity_id,)).fetchone()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    claim_text = None
    if body.claim_id is not None:
        claim = conn.execute(
            "SELECT field, value, quote FROM claim WHERE id = %s AND entity_id = %s",
            (body.claim_id, body.entity_id),
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim not found for this entity")
        claim_text = f"{claim[0]}: {claim[1]} — {claim[2]}"
    conn.execute(
        "INSERT INTO feedback (session_id, query, entity_id, claim_id, entity_name, claim_text, rating, comment) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (body.session_id, body.query, body.entity_id, body.claim_id, entity[0], claim_text, body.rating, body.comment),
    )
    return FeedbackResponse()
