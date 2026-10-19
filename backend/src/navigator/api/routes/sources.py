"""Sources: list, add, re-crawl and their crawl rules."""

from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from navigator.api.deps import Conn, IngestSlot, Seeds, get_ingest
from navigator.core.db import shown
from navigator.core.settings import get_settings
from navigator.core.sources import load_sources
from navigator.ingest import pipeline, rules
from navigator.models import (
    CrawledPage,
    CrawlRules,
    CrawlRulesUpdate,
    NewSource,
    Source,
)

router = APIRouter()


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


@router.get("/api/sources")
def list_sources(conn: Conn, seeds: Seeds) -> list[Source]:
    """All sources with their counts; sources added from the UI carry their ingest status (#55)."""
    return _sources(conn, seeds)


@router.get("/api/sources/{source_id}")
def get_source(conn: Conn, seeds: Seeds, source_id: str) -> Source:
    found = _sources(conn, seeds, source_id)
    if not found:
        raise HTTPException(status_code=404, detail="Source not found")
    return found[0]


def take_ingest_slot(try_start: Callable[[], psycopg.Connection | None]) -> psycopg.Connection:
    """One ingest at a time, across workers: 409 while one runs."""
    slot = try_start()
    if slot is None:
        raise HTTPException(status_code=409, detail="Another source is being ingested; try again when it is ready")
    return slot


@router.post("/api/sources")
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


@router.post("/api/sources/{source_id}/crawl")
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


@router.get("/api/sources/{source_id}/rules")
def get_source_rules(conn: Conn, source_id: str) -> CrawlRules:
    """The source's crawl rules: the stored ones, else its block in config/sources.yaml."""
    found = rules.get_rules(conn, load_sources(get_settings().sources_file), source_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return found


@router.put("/api/sources/{source_id}/rules")
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
