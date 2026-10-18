"""HTTP API (plan 8.9). Run with `navigator serve`."""

import logging
import secrets
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated

import anyio
import numpy as np
import psycopg
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from navigator import analysis, case_state, cases, chunks_db, ingest, pages, pitch
from navigator.explain import apply_why, explain as explain_results
from navigator.expand import Expansion as TermExpansion
from navigator.expand import expand_query
from navigator.llm import LLM
from navigator.models import (
    AddReference,
    Case,
    CaseChatTurn,
    CaseFeedback,
    CaseStatusUpdate,
    ChatFilters,
    ChatRequest,
    ChatResponse,
    CrawledPage,
    EntityType,
    Expansion,
    FeedbackCounts,
    FeedbackRequest,
    FeedbackResponse,
    PageDetail,
    Pitch,
    PitchRequest,
    ResourcePage,
    Result,
    SearchResponse,
    NewSource,
    Selection,
    Source,
    SourceStats,
    StatsResponse,
)
from navigator.rank import rank_entities
from navigator.results import build_results, shown
from navigator.settings import get_settings
from navigator.sources import load_sources

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the embedding model at startup, not on the first search (plan 8.9). One LLM client for the
    whole process: it is bound to this event loop."""
    from navigator.embed import get_model

    get_model()
    settings = get_settings()
    app.state.llm = LLM(settings)
    app.state.explain_llm = LLM(settings, settings.explain_model)  # its own model: 8B while the gateway is slow
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


def get_explain(request: Request) -> Callable[[str, list[Result]], dict[int, str]]:
    """'Why it matches' sentences (plan 8.6), run on the main loop like get_expand."""
    llm = request.app.state.explain_llm
    return lambda q, results: anyio.from_thread.run(explain_results, llm, q, results)


def get_seeds() -> dict[str, str]:
    """First seed URL per source in config/sources.yaml (the validated sources)."""
    return {s.id: s.seeds[0] for s in load_sources(get_settings().sources_file).sources}


def get_page_rules() -> dict[str, pages.SourceRules]:
    """Exclude and priority patterns per source in config/sources.yaml (stored rules: #79)."""
    return {
        s.id: pages.SourceRules(s.exclude_patterns, s.priority_patterns)
        for s in load_sources(get_settings().sources_file).sources
    }


def get_analyze(request: Request) -> Callable[[str], None]:
    """The case analysis (#53), run after the upload response on its own connection (the request's is closed
    by then). Background tasks of sync routes run in a worker thread, so the LLM calls run on the main loop."""
    from navigator.embed import embed_documents, embed_query

    llm, explain_llm = request.app.state.llm, request.app.state.explain_llm

    def run(case_id: str) -> None:
        try:
            with chunks_db.connect(get_settings().database_url) as conn:
                analysis.analyze(
                    conn, case_id,
                    read=lambda text: anyio.from_thread.run(analysis.read_case, llm, text),
                    embed=embed_query,
                    embed_many=embed_documents,
                    explain=lambda q, results: anyio.from_thread.run(explain_results, explain_llm, q, results),
                )
        except Exception:
            log.exception("case analysis failed: %s", case_id)

    return run


@dataclass
class ChatSession:
    query: str | None = None
    filters: ChatFilters = field(default_factory=ChatFilters)
    results: list[Result] = field(default_factory=list)  # for "#2" / "her" in the agent follow-up (plan 8.10)


class ChatSessions:
    """Chat state in process memory (one worker, plan 8.9): lost on restart. The oldest are dropped past `size`."""

    def __init__(self, size: int = 1000) -> None:
        self.size = size
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()
        self._lock = threading.Lock()  # sync routes run in a thread pool

    def get(self, session_id: str) -> ChatSession:
        with self._lock:
            session = self._sessions.pop(session_id, None) or ChatSession()
            self._sessions[session_id] = session
            while len(self._sessions) > self.size:
                self._sessions.popitem(last=False)
            return session


chat_sessions = ChatSessions()


def get_sessions() -> ChatSessions:
    return chat_sessions


def get_write_pitch(request: Request) -> Callable[[tuple, list[Result]], str]:
    """The pitch writer: (company, industry, summary, needs) and the references -> checked text or template.
    Runs on the explain LLM (EXPLAIN_MODEL), which is the fast one while the gateway is slow."""
    llm = request.app.state.explain_llm
    return lambda context, results: anyio.from_thread.run(pitch.write_pitch, llm, *context, results)


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Seeds = Annotated[dict[str, str], Depends(get_seeds)]
PageRules = Annotated[dict[str, pages.SourceRules], Depends(get_page_rules)]
Embed = Annotated[Callable[[str], np.ndarray], Depends(get_embed)]
Expand = Annotated[Callable[[str], TermExpansion], Depends(get_expand)]
Explain = Annotated[Callable[[str, list[Result]], dict[int, str]], Depends(get_explain)]
Analyze = Annotated[Callable[[str], None], Depends(get_analyze)]
Sessions = Annotated[ChatSessions, Depends(get_sessions)]
WritePitch = Annotated[Callable[[tuple, list[Result]], str], Depends(get_write_pitch)]


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    log.error("database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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


@app.get("/api/search")
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


@app.post("/api/chat")
def chat(conn: Conn, embed: Embed, expand: Expand, explain: Explain, sessions: Sessions, body: ChatRequest) -> ChatResponse:
    """Plain refinement chat (#50): each message is a new search with the session's filters; a blank
    message with new `filters` re-runs the last query. The LangGraph agent (plan 8.10) is a follow-up."""
    session = sessions.get(body.session_id)
    stored = body.session_id.startswith(case_state.SESSION_PREFIX)  # case drawer chats are kept in the DB (#81)
    if stored and session.query is None and (last := case_state.last_query(conn, body.session_id)):
        session.query, session.filters = last  # after an API restart
    query = body.message.strip() or session.query
    if query is None:
        raise HTTPException(status_code=422, detail="Type a search first")
    filters = body.filters or session.filters
    found = run_search(
        conn, embed, expand, explain, query,
        [filters.source] if filters.source else [], [filters.type] if filters.type else [],
    )
    session.query, session.filters, session.results = query, filters, found.results
    response = ChatResponse(
        reply=chat_reply(len(found.results), query, filters), results=found.results, filters=filters,
        expansion=found.expansion, no_result=found.no_result,
    )
    if stored:
        case_state.save_turn(conn, body.session_id, body.message, query, response)
    return response


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


DISCOVERED_SAMPLE = 60  # pages per source for the crawl graph


def _sources(conn: psycopg.Connection, seeds: dict[str, str], source_id: str | None = None) -> list[Source]:
    """Sources with the /api/stats counts; all of them, or the one with `source_id`."""
    rows = conn.execute(
        f"""
        SELECT s.id, s.name, s.status, s.stage, s.error, s.root_url,
               count(DISTINCT p.id),
               count(DISTINCT cl.entity_id) FILTER (WHERE {shown("cl")}),
               count(DISTINCT cl.id) FILTER (WHERE {shown("cl")}),
               max(p.fetched_at)
        FROM source s
        LEFT JOIN page p   ON p.source_id = s.id
        LEFT JOIN claim cl ON cl.page_id = p.id
        WHERE %(id)s::text IS NULL OR s.id = %(id)s
        GROUP BY s.id
        ORDER BY s.id
        """,
        {"id": source_id},
    ).fetchall()
    discovered: dict[str, list[CrawledPage]] = {r[0]: [] for r in rows}
    # The crawl tree where the crawler recorded it (#55); otherwise the stored pages, as flat seeds
    for sid, url, parent, depth, status in conn.execute(
        """
        SELECT source_id, url, parent, depth, status FROM (
            SELECT source_id, url, parent, depth, status, row_number() OVER (PARTITION BY source_id ORDER BY id) n
            FROM crawl_url WHERE source_id = ANY(%(ids)s)
            UNION ALL
            SELECT source_id, url, NULL, 0, 'crawled', row_number() OVER (PARTITION BY source_id ORDER BY id)
            FROM page WHERE source_id = ANY(%(ids)s)
              AND NOT EXISTS (SELECT 1 FROM crawl_url c WHERE c.source_id = page.source_id)
        ) u WHERE n <= %(n)s ORDER BY source_id, n
        """,
        {"ids": list(discovered), "n": DISCOVERED_SAMPLE},
    ):
        discovered[sid].append(CrawledPage(url=url, parent=parent, depth=depth, status=status))
    return [
        Source(
            id=sid, name=name, root_url=seeds.get(sid) or root or next((d.url for d in discovered[sid]), ""),
            validated=sid in seeds, status=status, stage=stage, error=error, pages=pages, entities=entities,
            verified_claims=claims, last_crawled_at=crawled, discovered=discovered[sid],
        )
        for sid, name, status, stage, error, root, pages, entities, claims, crawled in rows
    ]


@app.get("/api/sources")
def list_sources(conn: Conn, seeds: Seeds) -> list[Source]:
    """All sources with their counts; sources added from the UI carry their ingest status (#55)."""
    return _sources(conn, seeds)


@app.get("/api/sources/{source_id}")
def get_source(conn: Conn, seeds: Seeds, source_id: str) -> Source:
    found = _sources(conn, seeds, source_id)
    if not found:
        raise HTTPException(status_code=404, detail="Source not found")
    return found[0]


def get_ingest() -> Callable[[str], None]:
    """The background ingest of a source added from the UI, on its own connection."""
    return lambda source_id: ingest.run_ingest(get_settings().database_url, source_id)


@app.post("/api/sources")
def add_source(conn: Conn, seeds: Seeds, background: BackgroundTasks, body: NewSource,
               run: Annotated[Callable[[str], None], Depends(get_ingest)]) -> Source:
    """Add a website and ingest it in the background (crawl, embed, extract, resolve, judge). Returns at once
    with status "crawling"; poll GET /api/sources/{id}. One ingest at a time: 409 while one runs."""
    if not ingest.try_start():
        raise HTTPException(status_code=409, detail="Another source is being ingested; try again when it is ready")
    try:
        source_id = ingest.add_source(conn, body.url, body.name, body.max_depth, body.max_pages, body.follow_outbound)
    except ingest.SourceError as exc:
        ingest.finish()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        ingest.finish()
        raise
    conn.commit()  # the background ingest reads the source on another connection
    background.add_task(run, source_id)
    return _sources(conn, seeds, source_id)[0]


@app.get("/api/pages")
def list_pages(conn: Conn, rules: PageRules) -> list[ResourcePage]:
    """Every crawled page with its score, by id (the UI sorts)."""
    return pages.list_pages(conn, rules)


@app.get("/api/pages/{page_id}")
def get_page(conn: Conn, rules: PageRules, page_id: int) -> PageDetail:
    """One page with the shown facts extracted from it."""
    found = pages.get_page(conn, rules, page_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return found


@app.post("/api/cases")
def upload_case(conn: Conn, analyze: Analyze, background: BackgroundTasks, file: UploadFile) -> Case:
    """Store a business model PDF's text and return the case at once; the analysis runs in the background."""
    data = file.file.read(cases.MAX_PDF_BYTES + 1)
    if len(data) > cases.MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF larger than 10 MB")
    try:
        text = cases.pdf_text(data)
    except cases.PdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    case = cases.create_case(conn, file.filename or "upload.pdf", text)
    conn.commit()  # the background analysis reads it on another connection
    background.add_task(analyze, case.id)
    return case


@app.get("/api/cases")
def list_cases(conn: Conn) -> list[Case]:
    """Newest first."""
    return cases.list_cases(conn)


@app.get("/api/cases/{case_id}")
def get_case(conn: Conn, case_id: str) -> Case:
    case = cases.get_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.get("/api/cases/{case_id}/references")
def case_references(conn: Conn, case_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 25) -> list[Result]:
    """The case's references, best first; empty until the analysis is done."""
    found = analysis.references(conn, case_id, limit)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@app.post("/api/cases/{case_id}/references")
def add_case_reference(conn: Conn, case_id: str, body: AddReference) -> Result:
    """Add a chat result to the case's references (#81); it then comes after the top 25, marked `added`."""
    if cases.get_case(conn, case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    added = case_state.add_reference(conn, case_id, body.entity_id)
    if added is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return added


@app.delete("/api/cases/{case_id}/references/{entity_id}")
def remove_case_reference(conn: Conn, case_id: str, entity_id: int) -> Selection:
    """Remove a chat-added reference; it is also deselected. Returns the selection."""
    if not case_state.remove_reference(conn, case_id, entity_id):
        raise HTTPException(status_code=404, detail="No such added reference")
    return Selection(entity_ids=case_state.get_selection(conn, case_id) or [])


@app.get("/api/cases/{case_id}/selection")
def get_selection(conn: Conn, case_id: str) -> Selection:
    """The references chosen for the pitch (#81); the first 10 until the user changes it."""
    found = case_state.get_selection(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return Selection(entity_ids=found)


@app.put("/api/cases/{case_id}/selection")
def set_selection(conn: Conn, case_id: str, body: Selection) -> Selection:
    if unknown := pitch.unknown_entities(conn, body.entity_ids):
        raise HTTPException(status_code=404, detail=f"Unknown entity ids: {unknown}")
    found = case_state.set_selection(conn, case_id, body.entity_ids)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return Selection(entity_ids=found)


@app.get("/api/cases/{case_id}/chat")
def case_chat(conn: Conn, case_id: str) -> list[CaseChatTurn]:
    """The chat turns of the case's session `case-<id>`, oldest first (#81)."""
    turns = case_state.chat_history(conn, case_id)
    if turns is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return turns


@app.get("/api/cases/{case_id}/feedback")
def case_feedback(conn: Conn, case_id: str) -> CaseFeedback:
    """The 👍/👎 and flagged facts given in the case's session (#81)."""
    found = case_state.feedback(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@app.patch("/api/cases/{case_id}")
def update_case(conn: Conn, case_id: str, body: CaseStatusUpdate) -> Case:
    """Move the case to another board column."""
    case = cases.set_status(conn, case_id, body.status)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/api/cases/{case_id}/pitch")
def generate_pitch(conn: Conn, write: WritePitch, case_id: str, body: PitchRequest) -> Pitch:
    """A sales pitch from the selected references only; every sentence about one cites its claims. Stored on the case."""
    context = pitch.case_context(conn, case_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Case not found")
    entity_ids = list(dict.fromkeys(body.entity_ids))
    if unknown := pitch.unknown_entities(conn, entity_ids):
        raise HTTPException(status_code=404, detail=f"Unknown entity ids: {unknown}")
    results = build_results(conn, [(i, 0.0) for i in entity_ids])
    return pitch.save_pitch(conn, case_id, write(context, results), entity_ids)


@app.get("/api/cases/{case_id}/pitch")
def get_pitch(conn: Conn, case_id: str) -> Pitch:
    """The last pitch generated for the case; 404 if the case does not exist or has none yet."""
    if pitch.case_context(conn, case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    stored = pitch.load_pitch(conn, case_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No pitch yet")
    return stored
