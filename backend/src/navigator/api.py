"""HTTP API (plan 8.9). Run with `navigator serve`."""

import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import anyio
import numpy as np
import psycopg
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from navigator import analysis, case_state, cases, documents, pitch
from navigator.core.db import shown
from navigator.core.llm import LLM
from navigator.core.settings import get_settings
from navigator.core.sources import load_sources
from navigator.ingest import chunks_db, pages, pipeline, rules
from navigator.models import (
    AddReference,
    Case,
    CaseChatTurn,
    CaseDocuments,
    CaseFeedback,
    CaseNote,
    CaseStatusUpdate,
    ChatFilters,
    ChatRequest,
    ChatResponse,
    CrawledPage,
    CrawlRules,
    CrawlRulesUpdate,
    DocumentKind,
    EntityType,
    FeedbackCounts,
    FeedbackRequest,
    FeedbackResponse,
    NewSource,
    NoteInput,
    PageDetail,
    Pitch,
    PitchRequest,
    ResourcePage,
    Result,
    ReviewInput,
    SearchResponse,
    Selection,
    Source,
    SourceStats,
    StatsResponse,
)
from navigator.search import agent
from navigator.search.expand import Expansion as TermExpansion
from navigator.search.expand import expand_query
from navigator.search.explain import explain as explain_results
from navigator.search.pipeline import run_search
from navigator.search.rank import warm_topic_vectors
from navigator.search.results import build_results

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the embedding model at startup, not on the first search (plan 8.9). One LLM client for the
    whole process: it is bound to this event loop."""
    from navigator.core.embed import get_model

    get_model()
    settings = get_settings()
    try:  # topic vectors for ranking (#59): embedded once here, not inside a search's transaction
        with chunks_db.connect(settings.database_url) as conn:
            log.info("topic vectors embedded: %d", warm_topic_vectors(conn))
    except psycopg.Error as e:
        log.warning("topic vectors not embedded at startup (%s); the first search will do it", e)
    app.state.llm = LLM(settings)
    app.state.explain_llm = LLM(settings, settings.explain_model)  # its own model: 8B while the gateway is slow
    app.state.chat_model = agent.chat_model(settings)  # the chat agent's tool-calling model (plan 8.10, #97)
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
    from navigator.core.embed import embed_query

    return embed_query


def get_expand(request: Request) -> Callable[[str], TermExpansion]:
    """Query expansion (plan 8.1). Sync routes run in a worker thread, so the coroutine runs on the main loop."""
    llm = request.app.state.llm
    return lambda q: anyio.from_thread.run(expand_query, llm, q)


def get_chat_model(request: Request):
    """The chat agent's model (LangChain, tools bound). Sync: the chat route runs in a worker thread."""
    return request.app.state.chat_model


def get_explain(request: Request) -> Callable[[str, list[Result]], dict[int, str]]:
    """'Why it matches' sentences (plan 8.6), run on the main loop like get_expand."""
    llm = request.app.state.explain_llm
    return lambda q, results: anyio.from_thread.run(explain_results, llm, q, results)


def get_seeds() -> dict[str, str]:
    """First seed URL per source in config/sources.yaml (the validated sources)."""
    return {s.id: s.seeds[0] for s in load_sources(get_settings().sources_file).sources}


def get_page_rules(conn: Annotated[psycopg.Connection, Depends(get_conn, scope="function")]) -> dict[str, pages.SourceRules]:
    """Exclude and priority patterns per source: the stored rules (#79), else config/sources.yaml."""
    return rules.page_rules(conn, load_sources(get_settings().sources_file))


def get_analyze(request: Request) -> Callable[[str], None]:
    """The case analysis (#53), run after the upload response on its own connection (the request's is closed
    by then). Background tasks of sync routes run in a worker thread, so the LLM calls run on the main loop."""
    from navigator.core.embed import embed_documents, embed_query

    llm, explain_llm = request.app.state.llm, request.app.state.explain_llm

    def run(case_id: str) -> None:
        try:
            with chunks_db.connect(get_settings().database_url) as conn:
                conn.autocommit = True  # minutes of LLM calls: no transaction may stay open (it blocked init_db)
                analysis.analyze(
                    conn, case_id,
                    read=lambda text: anyio.from_thread.run(analysis.read_case, llm, text),
                    embed=embed_query,
                    embed_many=embed_documents,
                    rerank=analysis.rerank,
                    explain=lambda q, results: anyio.from_thread.run(explain_results, explain_llm, q, results),
                )
        except Exception:
            log.exception("case analysis failed: %s", case_id)

    return run


def get_write_pitch(request: Request) -> Callable[[tuple, list[Result]], str]:
    """The pitch writer: (company, industry, summary, needs) and the references -> checked text or template.
    Runs on the explain LLM (EXPLAIN_MODEL), which is the fast one while the gateway is slow."""
    llm = request.app.state.explain_llm
    return lambda context, results: anyio.from_thread.run(pitch.write_pitch, llm, *context, results)


def get_make_documents(request: Request) -> Callable[[str], None]:
    """The partner report and slides (#96), made after the response on their own connection, like the analysis.
    The texts are written on the explain LLM, like the pitch."""
    llm = request.app.state.explain_llm

    def run(case_id: str) -> None:
        with chunks_db.connect(get_settings().database_url) as conn:
            conn.autocommit = True  # minutes of LLM calls: no transaction may stay open
            documents.generate(conn, case_id, write=lambda ctx: anyio.from_thread.run(documents.write_texts, llm, ctx))

    return run


# Commit before the response is sent (scope "function"): with the default, the commit runs after it, and the
# client's next request (save the selection, then make the documents) could read the old rows
Conn = Annotated[psycopg.Connection, Depends(get_conn, scope="function")]
Seeds = Annotated[dict[str, str], Depends(get_seeds)]
PageRules = Annotated[dict[str, pages.SourceRules], Depends(get_page_rules)]
Embed = Annotated[Callable[[str], np.ndarray], Depends(get_embed)]
Expand = Annotated[Callable[[str], TermExpansion], Depends(get_expand)]
Explain = Annotated[Callable[[str, list[Result]], dict[int, str]], Depends(get_explain)]
Analyze = Annotated[Callable[[str], None], Depends(get_analyze)]
WritePitch = Annotated[Callable[[tuple, list[Result]], str], Depends(get_write_pitch)]
MakeDocuments = Annotated[Callable[[str], None], Depends(get_make_documents)]


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
def chat(
    conn: Conn, embed: Embed, expand: Expand, explain: Explain, body: ChatRequest,
    chat_model: Annotated[object, Depends(get_chat_model)],
) -> ChatResponse:
    """The chat agent (plan 8.10, #97): the model picks tools (search, set_filters, more_like, related) and
    "#2" means the 2nd result of the previous turn. A blank message with new `filters` re-runs the last query
    without the model. Every turn is stored in `chat_turn` (#103), so any worker can answer the next message."""
    previous = case_state.last_turn(conn, body.session_id)

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


def get_ingest() -> Callable[[psycopg.Connection, str], None]:
    """The background ingest of a new (#55) or re-crawled (#80) source, on the ingest slot's connection."""
    return pipeline.run_ingest


def get_ingest_slot() -> Callable[[], psycopg.Connection | None]:
    """Takes the ingest slot (`pipeline.try_start`). Called inside the route, not as a dependency: a request that
    fails validation must not take it."""
    return lambda: pipeline.try_start(get_settings().database_url)


IngestSlot = Annotated[Callable[[], psycopg.Connection | None], Depends(get_ingest_slot)]


def take_ingest_slot(try_start: Callable[[], psycopg.Connection | None]) -> psycopg.Connection:
    """One ingest at a time, across workers: 409 while one runs."""
    slot = try_start()
    if slot is None:
        raise HTTPException(status_code=409, detail="Another source is being ingested; try again when it is ready")
    return slot


@app.post("/api/sources")
def add_source(conn: Conn, seeds: Seeds, background: BackgroundTasks, body: NewSource, try_start: IngestSlot,
               run: Annotated[Callable[[psycopg.Connection, str], None], Depends(get_ingest)]) -> Source:
    """Add a website and ingest it in the background (crawl, embed, extract, resolve, judge). Returns at once
    with status "crawling"; poll GET /api/sources/{id}. One ingest at a time: 409 while one runs."""
    slot = take_ingest_slot(try_start)
    try:
        source_id = pipeline.add_source(conn, body.url, body.name, body.max_depth, body.max_pages, body.follow_outbound)
    except pipeline.SourceError as exc:
        pipeline.finish(slot)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        pipeline.finish(slot)
        raise
    conn.commit()  # the background ingest reads the source on another connection
    background.add_task(run, slot, source_id)
    return _sources(conn, seeds, source_id)[0]


@app.post("/api/sources/{source_id}/crawl")
def recrawl_source(conn: Conn, seeds: Seeds, background: BackgroundTasks, source_id: str, try_start: IngestSlot,
                   run: Annotated[Callable[[psycopg.Connection, str], None], Depends(get_ingest)]) -> Source:
    """Re-crawl a source with its current rules (#79) and ingest it in the background, as POST /api/sources.
    Returns at once with status "crawling". Until the new data is swapped in, and if the run fails, the
    source keeps its previous pages and facts. 409 while another ingest runs."""
    slot = take_ingest_slot(try_start)
    try:
        found = pipeline.start_recrawl(conn, load_sources(get_settings().sources_file), source_id)
    except Exception:
        pipeline.finish(slot)
        raise
    if not found:
        pipeline.finish(slot)
        raise HTTPException(status_code=404, detail="Source not found")
    conn.commit()  # the background ingest reads the source on another connection
    background.add_task(run, slot, source_id)
    return _sources(conn, seeds, source_id)[0]


@app.get("/api/sources/{source_id}/rules")
def get_source_rules(conn: Conn, source_id: str) -> CrawlRules:
    """The source's crawl rules: the stored ones, else its block in config/sources.yaml."""
    found = rules.get_rules(conn, load_sources(get_settings().sources_file), source_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return found


@app.put("/api/sources/{source_id}/rules")
def put_source_rules(conn: Conn, source_id: str, body: CrawlRulesUpdate) -> CrawlRules:
    """Store the rules. Exclude patterns apply at once: claims from matching pages are hidden everywhere.
    The other rules apply on the next crawl."""
    try:
        stored = rules.save_rules(conn, load_sources(get_settings().sources_file), source_id, body)
    except rules.RulesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if stored is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return stored


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


@app.delete("/api/cases/{case_id}")
def delete_case(conn: Conn, case_id: str) -> dict[str, bool]:
    """Delete the case and everything stored for it (#134): PDF text, analysis, notes, documents, its chat and
    feedback. Cannot be undone; snapshots taken before keep it."""
    if not case_state.delete_case(conn, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return {"ok": True}


@app.patch("/api/cases/{case_id}")
def update_case(conn: Conn, case_id: str, body: CaseStatusUpdate) -> Case:
    """Move the case to another board column."""
    case = cases.set_status(conn, case_id, body.status)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.put("/api/cases/{case_id}/review")
def set_review(conn: Conn, case_id: str, body: ReviewInput) -> Case:
    """The reviewer's own score (#108), clamped to 0-100, next to the AI score. `reason` is required."""
    case = cases.set_review(conn, case_id, body)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.delete("/api/cases/{case_id}/review")
def clear_review(conn: Conn, case_id: str) -> Case:
    case = cases.set_review(conn, case_id, None)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.get("/api/cases/{case_id}/notes")
def list_notes(conn: Conn, case_id: str) -> list[CaseNote]:
    """Internal notes (#108), oldest first. They never reach the pitch, the documents or an LLM prompt."""
    notes = cases.list_notes(conn, case_id)
    if notes is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return notes


@app.post("/api/cases/{case_id}/notes")
def add_note(conn: Conn, case_id: str, body: NoteInput) -> CaseNote:
    note = cases.add_note(conn, case_id, body)
    if note is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return note


@app.delete("/api/cases/{case_id}/notes/{note_id}")
def delete_note(conn: Conn, case_id: str, note_id: str) -> dict[str, bool]:
    if not cases.delete_note(conn, case_id, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}


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


@app.post("/api/cases/{case_id}/documents")
def generate_documents(conn: Conn, make: MakeDocuments, background: BackgroundTasks, case_id: str) -> CaseDocuments:
    """Start the partner report (.docx) and slides (.pptx) from the case's selected references, in the background.
    Only for accepted cases. While a job runs, returns it instead of starting another; poll GET .../documents."""
    case = cases.get_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "accepted":
        raise HTTPException(status_code=409, detail="Accept the case first")
    current = documents.status(conn, case_id)
    if current and current.status == "pending":
        return current
    selection = case_state.get_selection(conn, case_id) or []
    if not selection:
        raise HTTPException(status_code=422, detail="Select at least one reference")
    job = documents.start(conn, case_id, selection)
    conn.commit()  # the background job reads it on another connection
    background.add_task(make, case_id)
    return job


@app.get("/api/cases/{case_id}/documents")
def documents_status(conn: Conn, case_id: str) -> CaseDocuments:
    """The state of the documents job: none, pending, done or failed."""
    found = documents.status(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@app.get("/api/cases/{case_id}/documents/{kind}", response_class=Response,
         responses={200: {"content": {t: {} for t in documents.MEDIA_TYPES.values()}}})
def download_document(conn: Conn, case_id: str, kind: DocumentKind) -> Response:
    """The stored report (.docx) or slides (.pptx), as generated; 404 if not generated yet."""
    found = documents.load(conn, case_id, kind)
    if found is None:
        raise HTTPException(status_code=404, detail="Not generated yet")
    content, name = found
    return Response(content, media_type=documents.MEDIA_TYPES[kind],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
