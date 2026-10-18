"""HTTP API (plan 8.9). Run with `navigator serve`."""

import logging
from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from navigator import db
from navigator.models import (
    EntityType,
    FeedbackCounts,
    FeedbackRequest,
    FeedbackResponse,
    SearchResponse,
    SourceStats,
    StatsResponse,
)
from navigator.results import build_results, shown
from navigator.settings import get_settings

log = logging.getLogger(__name__)

app = FastAPI(title="Research & Expertise Navigator")

DEFAULT_TYPES = ["person", "unit"]  # plan 8.4: projects / infrastructure only when the filter asks
MAX_RESULTS = 10


def get_conn() -> Iterator[psycopg.Connection]:
    """One connection per request; commits on success."""
    with db.connect(get_settings().database_url) as conn:
        yield conn


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    log.error("database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _temporary_rank(
    conn: psycopg.Connection, q: str, source: str | None, type: EntityType | None
) -> list[tuple[int, float]]:
    """TEMPORARY ranker until search.py lands: entities ranked by how many shown claims match a query word."""
    words = [w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for w in q.lower().split()]
    if not words:
        return []
    rows = conn.execute(
        f"""
        SELECT c.entity_id, count(*) AS hits
        FROM claim c
        JOIN entity e ON e.id = c.entity_id
        JOIN page p ON p.id = c.page_id
        WHERE {shown("c")}
          AND c.value ILIKE ANY(%(patterns)s)
          AND e.type = ANY(%(types)s)
          AND (%(source)s::text IS NULL OR p.source_id = %(source)s)
        GROUP BY c.entity_id
        ORDER BY hits DESC, c.entity_id
        LIMIT %(limit)s
        """,
        {
            "patterns": [f"%{w}%" for w in words],
            "types": [type] if type else DEFAULT_TYPES,
            "source": source,
            "limit": MAX_RESULTS,
        },
    ).fetchall()
    return [(entity_id, float(hits)) for entity_id, hits in rows]


@app.get("/api/search")
def search(
    conn: Conn,
    q: Annotated[str, Query(min_length=1)],
    source: str | None = None,
    type: EntityType | None = None,
) -> SearchResponse:
    """Stateless search: ranked results with evidence."""
    results = build_results(conn, _temporary_rank(conn, q, source, type))
    return SearchResponse(results=results, expansion=None, no_result=not results)


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
