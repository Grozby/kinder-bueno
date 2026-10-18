"""Chunk storage: read pages, replace a source's chunks with embeddings."""

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from navigator import db


def connect(database_url: str) -> psycopg.Connection:
    """A connection that can send and receive pgvector values."""
    conn = db.connect(database_url)
    register_vector(conn)
    return conn


def pages(conn: psycopg.Connection, source_id: str) -> list[tuple[int, str | None, str]]:
    """(page id, title, text) of a source's pages."""
    return conn.execute(
        "SELECT id, title, text FROM page WHERE source_id = %s ORDER BY id", (source_id,)
    ).fetchall()


def replace_chunks(
    conn: psycopg.Connection, source_id: str, chunks: list[tuple[int, int, str, np.ndarray]]
) -> None:
    """Delete a source's old chunks, then store the new (page id, ord, text, embedding) rows."""
    with conn.transaction():
        conn.execute(
            "DELETE FROM chunk USING page WHERE chunk.page_id = page.id AND page.source_id = %s",
            (source_id,),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunk (page_id, ord, text, embedding) VALUES (%s, %s, %s, %s)", chunks
            )
