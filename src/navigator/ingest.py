"""Add a website from the UI and ingest it in the background (POST /api/sources, #55).

The source's config lives in the database (`source.config`), not in config/sources.yaml, so it shows as
not validated. The ingest is the CLI pipeline for one source: crawl → embed → extract → resolve → judge.
Every URL the crawler meets is written to `crawl_url` as it goes, for the live crawl graph.

- One ingest at a time (process-wide lock); the API answers 409 while one runs.
- Server caps: MAX_PAGES pages, MAX_DEPTH link depth; robots.txt and the per-host delay as for every source.
- Only public hosts: the start URL must resolve to public IP addresses, and with `follow_outbound` the
  crawler only follows links to host names, never to IP addresses or `localhost`.
- A failure before resolve deletes the source's pages (and with them its chunks and raw rows), so no half
  source is left; the source row stays, with status "failed" and the error, so the UI can show it.
- resolve rebuilds the claims of every source, which resets every judge verdict, so the judge then runs
  on all sources, not only the new one (minutes on the shared DB). Judge errors do not fail the ingest.
"""

import asyncio
import ipaddress
import logging
import re
import socket
import threading
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

from navigator import chunks_db
from navigator.sources import CrawlDefaults, SourceConfig

log = logging.getLogger(__name__)

MAX_PAGES = 50
MAX_DEPTH = 4
PUBLIC_HOST = r"^(?!localhost$)(?!.*\.local$)(?=.*[a-z])[a-z0-9.-]+\.[a-z]{2,}$"  # a name with a TLD, not an IP

_lock = threading.Lock()


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


def try_start() -> bool:
    """Take the one ingest slot; False if an ingest is running."""
    return _lock.acquire(blocking=False)


def finish() -> None:
    _lock.release()


def add_source(conn: psycopg.Connection, url: str, name: str | None, max_depth: int, max_pages: int,
               follow_outbound: bool) -> str:
    """Store the source with status 'crawling' and return its id. A failed source added from the UI with
    the same id is replaced; anything else gets a new id. Call it holding the ingest slot (try_start)."""
    url = url.strip()
    host = check_url(url)
    # We hold the slot, so no ingest runs: a source still 'crawling' was cut off by an API restart
    conn.execute("UPDATE source SET status = 'failed', stage = NULL, error = 'interrupted: the API restarted' "
                 "WHERE status = 'crawling'")
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


def embed_source(conn: psycopg.Connection, source_id: str) -> int:
    """Chunk and embed the source's pages, as `navigator embed --source`."""
    from navigator.chunk import chunk_page
    from navigator.embed import embed_documents

    rows = [(page_id, i, text) for page_id, title, page_text in chunks_db.pages(conn, source_id)
            for i, text in enumerate(chunk_page(title, page_text))]
    vectors = embed_documents([text for _, _, text in rows])
    chunks_db.replace_chunks(conn, source_id, [(*row, vec) for row, vec in zip(rows, vectors)])
    return len(rows)


def run_ingest(database_url: str, source_id: str) -> None:
    """The background ingest. Releases the ingest slot when done."""
    from navigator import db
    from navigator.crawl import crawl_source
    from navigator.extract import extract_pages
    from navigator.judge import run_judge
    from navigator.llm import LLM
    from navigator.resolve import resolve
    from navigator.rules import apply_blocks, with_stored
    from navigator.settings import get_settings

    settings = get_settings()
    try:
        with chunks_db.connect(database_url) as conn:
            conn.autocommit = True  # each step and each crawl_url row is visible to the polling UI at once
            stage = "crawl"
            try:
                cfg = conn.execute("SELECT config FROM source WHERE id = %s", (source_id,)).fetchone()[0]
                source = with_stored(conn, SourceConfig(**cfg["source"]))  # rules edited in the UI (#79)
                conn.execute("DELETE FROM crawl_url WHERE source_id = %s", (source_id,))
                pages = asyncio.run(crawl_source(source, CrawlDefaults(max_depth=cfg["max_depth"]),
                                                 on_url=record_url(conn, source_id)))
                # URLs still queued when the page cap was reached were never fetched
                conn.execute("UPDATE crawl_url SET status = 'skipped' WHERE source_id = %s AND status = 'queued'",
                             (source_id,))
                if not pages:
                    raise SourceError("No page with enough text: the site may need JavaScript, block us in robots.txt, or not be HTML")
                db.replace_pages(conn, source_id, pages)
                apply_blocks(conn, source_id, source.exclude_patterns)

                stage = "embed"
                _set(conn, source_id, stage=stage)
                embed_source(conn, source_id)

                stage = "extract"
                _set(conn, source_id, stage=stage)
                rows = db.pages_for_extraction(conn, source_id, None)
                results = asyncio.run(extract_pages(LLM(settings, settings.extract_model), rows))
                db.replace_raw_extractions(conn, results)

                stage = "resolve"
                _set(conn, source_id, stage=stage)
                resolve(conn)  # one transaction: on an error the old claims stay
            except Exception as exc:
                log.exception("ingest of %s failed at %s", source_id, stage)
                conn.execute("DELETE FROM page WHERE source_id = %s", (source_id,))
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
        finish()
