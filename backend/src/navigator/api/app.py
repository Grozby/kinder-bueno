"""HTTP API (plan 8.9). Run with `navigator serve`. The routes are in `routes/`, the dependencies in `deps`."""

import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from navigator.api.routes import cases, pages, search, sources
from navigator.core.llm import LLM
from navigator.core.settings import get_settings
from navigator.ingest import chunks_db
from navigator.search import agent
from navigator.search.rank import warm_topic_vectors

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


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    log.error("database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for routes in (search, sources, pages, cases):
    app.include_router(routes.router)
