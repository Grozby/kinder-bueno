"""Postgres connection and schema setup."""

from pathlib import Path

import psycopg

from navigator.sources import SourcesFile

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def init_db(conn: psycopg.Connection, sources: SourcesFile) -> None:
    """Create tables (idempotent) and upsert one `source` row per configured source."""
    with conn.transaction():
        conn.execute(SCHEMA_FILE.read_text())
        for s in sources.sources:
            conn.execute(
                "INSERT INTO source (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                (s.id, s.name),
            )


def replace_pages(conn: psycopg.Connection, source_id: str, pages: list) -> None:
    """Delete a source's old pages (cascades to chunks and claims), then store the new ones."""
    with conn.transaction():
        conn.execute("DELETE FROM page WHERE source_id = %s", (source_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO page (source_id, url, title, text) VALUES (%s, %s, %s, %s)",
                [(source_id, p.url, p.title, p.text) for p in pages],
            )


def pages_for_extraction(
    conn: psycopg.Connection, source_id: str | None, limit: int | None, url_like: str | None = None
) -> list[tuple]:
    """(page_id, url, title, text), optionally filtered by source and by a SQL LIKE pattern on the URL."""
    return conn.execute(
        "SELECT id, url, coalesce(title, ''), text FROM page "
        "WHERE (%(source)s::text IS NULL OR source_id = %(source)s) "
        "AND (%(url_like)s::text IS NULL OR url LIKE %(url_like)s) "
        "ORDER BY id LIMIT %(limit)s",
        {"source": source_id, "limit": limit, "url_like": url_like},
    ).fetchall()


def replace_raw_extractions(conn: psycopg.Connection, results: list) -> None:
    """Store extraction results (extract.PageResult), replacing older rows of the same pages."""
    page_ids = [r.page_id for r in results]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM raw_claim WHERE page_id = ANY(%s)", (page_ids,))
        cur.execute("DELETE FROM raw_relation WHERE page_id = ANY(%s)", (page_ids,))
        cur.executemany(
            "INSERT INTO raw_claim (page_id, entity_type, entity_name, field, value, quote, verified, fail_reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.page_id, c.item.entity_type, c.item.entity_name, c.item.field, c.item.value,
                 c.quote, c.verified, c.fail_reason)
                for r in results for c in r.claims
            ],
        )
        cur.executemany(
            "INSERT INTO raw_relation (page_id, from_type, from_name, rel, to_type, to_name, quote, verified, fail_reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.page_id, x.item.from_type, x.item.from_name, x.item.rel, x.item.to_type, x.item.to_name,
                 x.quote, x.verified, x.fail_reason)
                for r in results for x in r.relations
            ],
        )


def stats(conn: psycopg.Connection) -> list[tuple]:
    """Counts per source: pages, chunks, entities with verified claims, verified claims."""
    return conn.execute(
        """
        SELECT s.id,
               count(DISTINCT p.id)                                   AS pages,
               count(DISTINCT ch.id)                                  AS chunks,
               count(DISTINCT cl.entity_id) FILTER (WHERE cl.verified) AS entities,
               count(DISTINCT cl.id) FILTER (WHERE cl.verified)        AS verified_claims
        FROM source s
        LEFT JOIN page p   ON p.source_id = s.id
        LEFT JOIN chunk ch ON ch.page_id = p.id
        LEFT JOIN claim cl ON cl.page_id = p.id
        GROUP BY s.id
        ORDER BY s.id
        """
    ).fetchall()
