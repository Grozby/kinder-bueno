"""Search, chat, stats and result feedback."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from navigator.api.deps import Conn, Embed, Expand, Explain, get_chat_model
from navigator.cases import state
from navigator.core.db import shown
from navigator.models import (
    ChatFilters,
    ChatRequest,
    ChatResponse,
    EntityType,
    FeedbackCounts,
    FeedbackRequest,
    FeedbackResponse,
    SearchResponse,
    SourceStats,
    StatsResponse,
)
from navigator.search import agent
from navigator.search.pipeline import run_search

router = APIRouter()


@router.get("/api/search")
def search(
    conn: Conn,
    embed: Embed,
    expand: Expand,
    explain: Explain,
    q: Annotated[str, Query(min_length=1)],
    source: Annotated[list[str], Query()] = [],
    type: Annotated[list[EntityType], Query()] = [],
) -> SearchResponse:
    """Stateless search. Filters repeat like the UI checkboxes: `?type=person&type=unit&source=dcb`.
    No source = all sources; no type = person and unit."""
    return run_search(conn, embed, expand, explain, q, source, type)


def chat_reply(n: int, query: str, filters: ChatFilters) -> str:
    """The template reply of plan 8.10: it states what was searched, never facts about entities."""
    used = [f"{k}: {v}" for k, v in (("source", filters.source), ("type", filters.type)) if v]
    return f"Showing {n} results for '{query}'" + (f" ({', '.join(used)})" if used else "") + "."


@router.post("/api/chat")
def chat(
    conn: Conn, embed: Embed, expand: Expand, explain: Explain, body: ChatRequest,
    chat_model: Annotated[object, Depends(get_chat_model)],
) -> ChatResponse:
    """The chat agent (plan 8.10, #97): the model picks tools (search, set_filters, more_like, related) and
    "#2" means the 2nd result of the previous turn. A blank message with new `filters` re-runs the last query
    without the model. Every turn is stored in `chat_turn` (#103), so any worker can answer the next message."""
    previous = state.last_turn(conn, body.session_id)

    def search_fn(q: str, f: ChatFilters) -> SearchResponse:
        return run_search(conn, embed, expand, explain, q, [f.source] if f.source else [], [f.type] if f.type else [])

    if not body.message.strip():
        if previous.query is None:
            raise HTTPException(status_code=422, detail="Type a search first")
        filters = body.filters or previous.filters
        found = search_fn(previous.query, filters)
        response = ChatResponse(
            reply=chat_reply(len(found.results), previous.query, filters), results=found.results, filters=filters,
            expansion=found.expansion, no_result=found.no_result,
        )
        query = previous.query
    else:
        turn = agent.Agent(conn, chat_model, search_fn).run(body.message, previous, body.filters)
        response = ChatResponse(reply=turn.reply, results=turn.results, filters=turn.filters,
                                expansion=turn.expansion, no_result=turn.no_result)
        query = turn.query
    state.save_turn(conn, body.session_id, body.message, query, response)
    return response


@router.get("/api/stats")
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


@router.post("/api/feedback")
def feedback(conn: Conn, body: FeedbackRequest) -> FeedbackResponse:
    """Log one feedback row with a text snapshot. Never changes results."""
    entity = conn.execute("SELECT name FROM entity WHERE id = %s", (body.entity_id,)).fetchone()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    claim_text = None
    if body.claim_id is not None:
        # The entity's own claim, or a unit topic on its card (the via_unit rows of results._unit_topics, #44)
        claim = conn.execute(
            f"""
            SELECT c.field, c.value, c.quote, c.entity_id, u.name FROM claim c JOIN entity u ON u.id = c.entity_id
            WHERE c.id = %s AND (c.entity_id = %s OR (c.field = 'expertise' AND {shown("c")} AND EXISTS (
                SELECT 1 FROM relation r WHERE r.from_id = %s AND r.to_id = c.entity_id
                  AND r.rel IN ('member_of', 'listed_in') AND {shown("r")})))
            """,
            (body.claim_id, body.entity_id, body.entity_id),
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim not found for this entity")
        via = "" if claim[3] == body.entity_id else f" (via {claim[4]})"
        claim_text = f"{claim[0]}: {claim[1]} — {claim[2]}{via}"
    conn.execute(
        "INSERT INTO feedback (session_id, query, entity_id, claim_id, entity_name, claim_text, rating, comment) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (body.session_id, body.query, body.entity_id, body.claim_id, entity[0], claim_text, body.rating, body.comment),
    )
    return FeedbackResponse()
