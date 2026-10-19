"""Add a website from the UI (POST /api/sources, #55) or re-crawl a source (POST /api/sources/{id}/crawl,
#80), and ingest it in the background.

A source added from the UI keeps its config in the database (`source.config`), not in
config/sources.yaml, so it shows as not validated. Either way, the crawl uses the rules edited in the UI
(#79). The ingest is the CLI pipeline for one source: crawl → embed → extract → resolve → judge. Every URL
the crawler meets is written to `crawl_url` as it goes, for the live crawl graph.

The slow steps (crawl, embeddings, LLM extraction) run in memory; the source's pages, chunks and raw rows
are then swapped in and resolved in one short transaction. So until the swap, search keeps serving the
previous data, and a failure anywhere (more than half the pages failing extraction counts as a failure)
leaves it untouched.

- One ingest at a time, across API workers and replicas: a Postgres advisory lock, held by the connection
  the background ingest runs on. The API answers 409 while one runs. If the process dies, Postgres closes
  the connection and frees the lock.
- Server caps: MAX_PAGES pages, MAX_DEPTH link depth; robots.txt and the per-host delay as for every source.
- Only public hosts: the start URL must resolve to public IP addresses, and with `follow_outbound` the
  crawler only follows links to host names, never to IP addresses or `localhost`.
- On a failure the source row gets status "failed" and the error, so the UI can show it; a first-time
  source then has no pages, a re-crawled one keeps its previous pages and facts.
- resolve rebuilds the claims of every source, which resets every judge verdict, so the judge then runs
  on all sources, not only the new one (minutes on the shared DB). Judge errors do not fail the ingest.
"""

import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

from navigator import chunks_db
from navigator.sources import CrawlDefaults, SourceConfig, SourcesFile

log = logging.getLogger(__name__)

MAX_PAGES = 50
MAX_DEPTH = 4
PUBLIC_HOST = r"^(?!localhost$)(?!.*\.local$)(?=.*[a-z])[a-z0-9.-]+\.[a-z]{2,}$"  # a name with a TLD, not an IP

INGEST_LOCK = 0x6B696E64  # advisory lock key of the one ingest slot (per database)


class SourceError(ValueError):
    """The URL cannot be added as a source."""


def check_url(url: str) -> str:
    """The URL's host, if the URL is http(s) and the host resolves to public addresses only."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise SourceError("The URL must start with http:// or https:// and name a host")
    if not re.match(PUBLIC_HOST, host):
        raise SourceError(f"Not a public host name: {host}")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parts.port or 443)}
    except socket.gaierror as exc:
        raise SourceError(f"Unknown host: {host}") from exc
    if not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise SourceError(f"Not a public host: {host}")
    return host


def source_id_for(host: str, taken: set[str]) -> str:
    """'www.example.unibe.ch' -> 'example_unibe' (no www, no TLD), with _2, _3 … if taken."""
    labels = host.removeprefix("www.").split(".")
    base = re.sub(r"[^a-z0-9]+", "_", "_".join(labels[:-1] if len(labels) > 1 else labels)).strip("_") or "site"
    sid, n = base, 1
    while sid in taken:
        n += 1
        sid = f"{base}_{n}"
    return sid


def source_config(source_id: str, name: str, url: str, host: str, follow_outbound: bool,
                  max_pages: int) -> SourceConfig:
    bare = host.removeprefix("www.")  # sites often redirect www <-> bare host: allow both
    allow = {"allow_hosts_regex": PUBLIC_HOST} if follow_outbound else {"allow_hosts": [bare, f"www.{bare}"]}
    return SourceConfig(id=source_id, name=name, seeds=[url], max_pages=min(max_pages, MAX_PAGES), **allow)


def try_start(database_url: str) -> psycopg.Connection | None:
    """Take the one ingest slot: a session advisory lock on a new connection, which the background ingest then
    runs on (`run_ingest`) and closes. None if an ingest is running, in this process or any other."""
    conn = chunks_db.connect(database_url)
    conn.autocommit = True  # each stage and each crawl_url row is visible to the polling UI at once
    if conn.execute("SELECT pg_try_advisory_lock(%s)", (INGEST_LOCK,)).fetchone()[0]:
        return conn
    conn.close()
    return None


def finish(slot: psycopg.Connection) -> None:
    """Free the slot: closing the connection releases the lock."""
    slot.close()


def _recover_interrupted(conn: psycopg.Connection) -> None:
    """Called holding the slot, so no ingest runs: a source still 'crawling' was cut off (an API restart or a
    worker that died)."""
    conn.execute("UPDATE source SET status = 'failed', stage = NULL, error = 'interrupted: the API restarted' "
                 "WHERE status = 'crawling'")


def add_source(conn: psycopg.Connection, url: str, name: str | None, max_depth: int, max_pages: int,
               follow_outbound: bool) -> str:
    """Store the source with status 'crawling' and return its id. A failed source added from the UI with
    the same id is replaced; anything else gets a new id. Call it holding the ingest slot (try_start)."""
    url = url.strip()
    host = check_url(url)
    _recover_interrupted(conn)
    rows = conn.execute("SELECT id, config IS NOT NULL AND status = 'failed' FROM source").fetchall()
    retry = source_id_for(host, set())
    reusable = dict(rows).get(retry, False)
    source_id = retry if reusable else source_id_for(host, {r[0] for r in rows})
    config = source_config(source_id, name or host, url, host, follow_outbound, max_pages)
    with conn.transaction():
        conn.execute("DELETE FROM source WHERE id = %s", (source_id,))  # only a failed one gets here
        conn.execute(
            "INSERT INTO source (id, name, config, root_url, status, stage) VALUES (%s, %s, %s, %s, 'crawling', 'crawl')",
            (source_id, config.name, Jsonb({"source": config.model_dump(), "max_depth": min(max_depth, MAX_DEPTH)}),
             url),
        )
    return source_id


def _set(conn: psycopg.Connection, source_id: str, **fields: str | None) -> None:
    cols = ", ".join(f"{k} = %s" for k in fields)
    conn.execute(f"UPDATE source SET {cols} WHERE id = %s", (*fields.values(), source_id))


def record_url(conn: psycopg.Connection, source_id: str):
    """A crawl_source `on_url` callback that writes each URL to crawl_url at once (autocommit)."""
    def on_url(url: str, parent: str | None, depth: int, status: str) -> None:
        conn.execute(
            """INSERT INTO crawl_url (source_id, url, parent, depth, status) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (source_id, url) DO UPDATE SET status = EXCLUDED.status""",
            (source_id, url, parent, depth, status),
        )
    return on_url


MAX_EXTRACT_FAILURES = 0.5  # share of pages whose extraction may fail (gateway errors) before the run fails


def crawl_config(conn: psycopg.Connection, sources: SourcesFile, source_id: str) -> tuple[SourceConfig, int] | None:
    """The source's crawl config with the stored rules (#79) and its link depth; None for an unknown source."""
    from navigator.rules import with_stored

    row = conn.execute("SELECT config FROM source WHERE id = %s", (source_id,)).fetchone()
    if row is None:
        return None
    if row[0]:
        return with_stored(conn, SourceConfig(**row[0]["source"])), row[0]["max_depth"]
    try:
        return with_stored(conn, sources.get(source_id)), sources.defaults.max_depth
    except KeyError:
        return None  # a source row without config and not in sources.yaml (e.g. removed from it)


def start_recrawl(conn: psycopg.Connection, sources: SourcesFile, source_id: str) -> bool:
    """Mark the source 'crawling' for a re-crawl; False for an unknown source. Call it holding the slot."""
    if crawl_config(conn, sources, source_id) is None:
        return False
    _recover_interrupted(conn)
    _set(conn, source_id, status="crawling", stage="crawl", error=None)
    return True


def _swap_in(conn: psycopg.Connection, source_id: str, pages: list, chunks: list, results: list,
             exclude: list[str]) -> None:
    """Replace the source's pages, chunks and raw rows with the new ones, block pages and resolve, in one
    transaction. Pages, chunks and results carry the page's index in `pages` instead of its id."""
    from dataclasses import replace

    from navigator import db
    from navigator.resolve import resolve
    from navigator.rules import apply_blocks

    with conn.transaction():
        conn.execute("DELETE FROM page WHERE source_id = %s", (source_id,))  # cascades to chunks and raw rows
        ids = [conn.execute("INSERT INTO page (source_id, url, title, text) VALUES (%s, %s, %s, %s) RETURNING id",
                            (source_id, p.url, p.title, p.text)).fetchone()[0] for p in pages]
        chunks_db.replace_chunks(conn, source_id, [(ids[i], o, text, vec) for i, o, text, vec in chunks])
        db.replace_raw_extractions(conn, [replace(r, page_id=ids[r.page_id]) for r in results])
        apply_blocks(conn, source_id, exclude)
        resolve(conn)


def run_ingest(slot: psycopg.Connection, source_id: str) -> None:
    """The background ingest of a new or re-crawled source, on the slot's connection (`try_start`), which it
    closes when done."""
    from navigator.chunk import chunk_page
    from navigator.crawl import crawl_source
    from navigator.embed import embed_documents
    from navigator.extract import extract_pages
    from navigator.judge import run_judge
    from navigator.llm import LLM
    from navigator.settings import get_settings
    from navigator.sources import load_sources

    settings = get_settings()
    try:
        with slot as conn:
            stage = "crawl"
            try:
                source, max_depth = crawl_config(conn, load_sources(settings.sources_file), source_id)
                conn.execute("DELETE FROM crawl_url WHERE source_id = %s", (source_id,))
                pages = asyncio.run(crawl_source(source, CrawlDefaults(max_depth=max_depth),
                                                 on_url=record_url(conn, source_id)))
                # URLs still queued when the page cap was reached were never fetched
                conn.execute("UPDATE crawl_url SET status = 'skipped' WHERE source_id = %s AND status = 'queued'",
                             (source_id,))
                if not pages:
                    raise SourceError("No page with enough text: the site may need JavaScript, block us in robots.txt, or not be HTML")

                stage = "embed"
                _set(conn, source_id, stage=stage)
                rows = [(i, o, text) for i, p in enumerate(pages) for o, text in enumerate(chunk_page(p.title, p.text))]
                vectors = embed_documents([text for _, _, text in rows])
                chunks = [(*row, vec) for row, vec in zip(rows, vectors)]

                stage = "extract"
                _set(conn, source_id, stage=stage)
                results = asyncio.run(extract_pages(LLM(settings, settings.extract_model),
                                                    [(i, p.url, p.title, p.text) for i, p in enumerate(pages)]))
                failed = sum(r.error is not None for r in results)
                if failed > MAX_EXTRACT_FAILURES * len(results):
                    raise SourceError(f"{failed} of {len(results)} pages failed (is the LLM gateway up?)")

                stage = "resolve"
                _set(conn, source_id, stage=stage)
                _swap_in(conn, source_id, pages, chunks, results, source.exclude_patterns)
            except Exception as exc:
                log.exception("ingest of %s failed at %s", source_id, stage)
                _set(conn, source_id, status="failed", stage=None, error=f"{stage}: {exc}"[:500])
                return

            _set(conn, source_id, stage="judge")
            error = None
            if settings.judge_enabled:
                try:
                    run_judge(conn, LLM(settings, settings.judge_model))  # all sources: resolve reset every verdict
                except Exception as exc:
                    log.exception("judge after the ingest of %s failed", source_id)
                    error = f"judge: {exc}"[:500]
            _set(conn, source_id, status="ready", stage=None, error=error)
            log.info("ingest of %s done", source_id)
    finally:
        finish(slot)
