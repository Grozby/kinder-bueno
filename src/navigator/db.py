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
