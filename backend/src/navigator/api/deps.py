"""Request dependencies: the connection, the embedding and LLM callables, and the background jobs. Tests
override them with `app.dependency_overrides`."""

import logging
from collections.abc import Callable, Iterator
from typing import Annotated

import anyio
import numpy as np
import psycopg
from fastapi import Depends, Request

from navigator.cases import analysis, documents, pitch
from navigator.core.settings import get_settings
from navigator.core.sources import load_sources
from navigator.ingest import chunks_db, pages, pipeline, rules
from navigator.models import (
    Result,
)
from navigator.search.expand import Expansion as TermExpansion
from navigator.search.expand import expand_query
from navigator.search.explain import explain as explain_results

log = logging.getLogger(__name__)


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


def get_ingest() -> Callable[[psycopg.Connection, str], None]:
    """The background ingest of a new (#55) or re-crawled (#80) source, on the ingest slot's connection."""
    return pipeline.run_ingest


def get_ingest_slot() -> Callable[[], psycopg.Connection | None]:
    """Takes the ingest slot (`pipeline.try_start`). Called inside the route, not as a dependency: a request that
    fails validation must not take it."""
    return lambda: pipeline.try_start(get_settings().database_url)


IngestSlot = Annotated[Callable[[], psycopg.Connection | None], Depends(get_ingest_slot)]
