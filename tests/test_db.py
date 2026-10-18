"""Integration tests. They need Postgres: `docker compose up -d db`. Skipped otherwise."""

import psycopg
import pytest

from navigator import db
from navigator.settings import PROJECT_ROOT, get_settings
from navigator.sources import load_sources


@pytest.fixture
def conn():
    try:
        connection = db.connect(get_settings().database_url)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    with connection:
        yield connection


def test_init_db_is_idempotent(conn):
    sources = load_sources(PROJECT_ROOT / "config" / "sources.yaml")
    db.init_db(conn, sources)
    db.init_db(conn, sources)
    ids = [r[0] for r in conn.execute("SELECT id FROM source ORDER BY id").fetchall()]
    assert ids == ["artorg", "dcb", "unibe"]
    assert conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()


def test_stats_lists_every_source(conn):
    db.init_db(conn, load_sources(PROJECT_ROOT / "config" / "sources.yaml"))
    assert {r[0] for r in db.stats(conn)} >= {"artorg", "dcb", "unibe"}
