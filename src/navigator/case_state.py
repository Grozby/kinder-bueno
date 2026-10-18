"""What the user does in a case drawer, stored so that a reload or a teammate sees the same (#81): the references
chosen for the pitch, references added from the chat, the chat turns and the feedback of the case's chat session.

The chat session of a case is "case-<id>" (frontend/src/stores/cases.ts). Results are stored as ids, scores and
"why" sentences only, and rebuilt from the current claims when read, like the analysis' references."""

import psycopg
from psycopg.types.json import Jsonb

from navigator import analysis
from navigator.explain import recheck
from navigator.models import (
    CaseChatTurn,
    CaseFeedback,
    ChatFilters,
    ChatResponse,
    Expansion,
    Result,
)
from navigator.results import build_results

DEFAULT_SELECTION = 10  # references selected for the pitch until the user changes the selection
SESSION_PREFIX = "case-"


def session_id(case_id: str) -> str:
    return f"{SESSION_PREFIX}{case_id}"


def _exists(conn: psycopg.Connection, case_id: str) -> bool:
    return conn.execute('SELECT 1 FROM "case" WHERE id = %s', (case_id,)).fetchone() is not None


def get_selection(conn: psycopg.Connection, case_id: str) -> list[int] | None:
    """The stored selection without entities gone since, or the first 10 references; None if no such case."""
    row = conn.execute('SELECT selection FROM "case" WHERE id = %s', (case_id,)).fetchone()
    if row is None:
        return None
    if row[0] is None:
        return [r.entity_id for r in analysis.references(conn, case_id, DEFAULT_SELECTION) or []]
    found = {r[0] for r in conn.execute("SELECT id FROM entity WHERE id = ANY(%s)", (row[0],))}
    return [i for i in row[0] if i in found]


def set_selection(conn: psycopg.Connection, case_id: str, entity_ids: list[int]) -> list[int] | None:
    entity_ids = list(dict.fromkeys(entity_ids))
    row = conn.execute(
        'UPDATE "case" SET selection = %s WHERE id = %s RETURNING id', (Jsonb(entity_ids), case_id)
    ).fetchone()
    return entity_ids if row else None


def add_reference(conn: psycopg.Connection, case_id: str, entity_id: int) -> Result | None:
    """Add an entity to the case's references, with the score and sentence of its last chat result in the case
    session if any. None if the entity has no shown claims. The caller checks that the case exists."""
    found = conn.execute(
        "SELECT r FROM chat_turn t, jsonb_array_elements(t.results) r "
        "WHERE t.session_id = %s AND (r->>'entity_id')::int = %s ORDER BY t.id DESC LIMIT 1",
        (session_id(case_id), entity_id),
    ).fetchone()
    ref = found[0] if found else {"entity_id": entity_id, "score": 0.0, "why": None}
    built = build_results(conn, [(entity_id, ref["score"])])
    if not built:
        return None
    conn.execute(
        """UPDATE "case" SET added_refs = (SELECT coalesce(jsonb_agg(a), '[]') FROM jsonb_array_elements(added_refs) a
                                           WHERE (a->>'entity_id')::int <> %s) || %s
           WHERE id = %s""",
        (entity_id, Jsonb([ref]), case_id),
    )
    return built[0].model_copy(update={"why": recheck(ref["why"], built[0]) or built[0].why, "added": True})


def remove_reference(conn: psycopg.Connection, case_id: str, entity_id: int) -> bool:
    """Remove a chat-added reference and deselect it; False if the case has no such added reference."""
    row = conn.execute(
        """UPDATE "case" SET
             added_refs = (SELECT coalesce(jsonb_agg(a), '[]') FROM jsonb_array_elements(added_refs) a
                           WHERE (a->>'entity_id')::int <> %(e)s),
             selection = CASE WHEN selection IS NOT NULL THEN (  -- NULL stays NULL: the default selection
               SELECT coalesce(jsonb_agg(s), '[]') FROM jsonb_array_elements(selection) s WHERE s::int <> %(e)s) END
           WHERE id = %(id)s AND added_refs @> jsonb_build_array(jsonb_build_object('entity_id', %(e)s::int))
           RETURNING id""",
        {"e": entity_id, "id": case_id},
    ).fetchone()
    return row is not None


def save_turn(conn: psycopg.Connection, session: str, message: str, query: str, response: ChatResponse) -> None:
    results = [{"entity_id": r.entity_id, "score": r.score, "why": r.why} for r in response.results]
    conn.execute(
        "INSERT INTO chat_turn (session_id, message, query, reply, filters, expansion, results) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            session, message, query, response.reply, Jsonb(response.filters.model_dump()),
            Jsonb(response.expansion.model_dump()) if response.expansion else None, Jsonb(results),
        ),
    )


def last_query(conn: psycopg.Connection, session: str) -> tuple[str, ChatFilters] | None:
    """The last query and filters of a stored session: restores it after an API restart."""
    row = conn.execute(
        "SELECT query, filters FROM chat_turn WHERE session_id = %s ORDER BY id DESC LIMIT 1", (session,)
    ).fetchone()
    return (row[0], ChatFilters(**row[1])) if row else None


def chat_history(conn: psycopg.Connection, case_id: str) -> list[CaseChatTurn] | None:
    """The case's chat turns, oldest first, each result rebuilt from the current claims; None if no such case."""
    if not _exists(conn, case_id):
        return None
    turns = []
    for message, reply, filters, expansion, stored, created in conn.execute(
        "SELECT message, reply, filters, expansion, results, created_at FROM chat_turn "
        "WHERE session_id = %s ORDER BY id",
        (session_id(case_id),),
    ).fetchall():
        why = {r["entity_id"]: r["why"] for r in stored}
        results = [
            r.model_copy(update={"why": recheck(why[r.entity_id], r) or r.why})
            for r in build_results(conn, [(r["entity_id"], r["score"]) for r in stored])
        ]
        response = ChatResponse(
            reply=reply, results=results, filters=ChatFilters(**filters),
            expansion=Expansion(**expansion) if expansion else None, no_result=not results,
        )
        turns.append(CaseChatTurn(message=message, response=response, created_at=created))
    return turns


def feedback(conn: psycopg.Connection, case_id: str) -> CaseFeedback | None:
    """The last 👍/👎 per entity and the claims flagged as wrong facts in the case's session; None if no such case."""
    if not _exists(conn, case_id):
        return None
    session = session_id(case_id)
    ratings = conn.execute(
        "SELECT DISTINCT ON (entity_id) entity_id, rating FROM feedback "
        "WHERE session_id = %s AND rating IN ('up', 'down') AND entity_id IS NOT NULL ORDER BY entity_id, id DESC",
        (session,),
    ).fetchall()
    flagged = conn.execute(
        "SELECT DISTINCT claim_id FROM feedback WHERE session_id = %s AND rating = 'wrong_fact' "
        "AND claim_id IS NOT NULL ORDER BY claim_id",
        (session,),
    ).fetchall()
    return CaseFeedback(ratings=dict(ratings), flagged=[r[0] for r in flagged])
