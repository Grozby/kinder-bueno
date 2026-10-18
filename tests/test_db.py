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


def test_pages_for_extraction_filters(conn):
    db.init_db(conn, load_sources(PROJECT_ROOT / "config" / "sources.yaml"))
    with conn.transaction(force_rollback=True):  # test rows never reach the real data
        conn.execute("INSERT INTO source (id, name) VALUES ('t_src', 'Test')")
        for url in ("https://t.test/a/group_members/x", "https://t.test/a/index", "https://t.test/b/group_members/y"):
            conn.execute("INSERT INTO page (source_id, url, title, text) VALUES ('t_src', %s, 'T', 'text')", (url,))

        def urls(**kw):
            return [r[1] for r in db.pages_for_extraction(conn, kw.get("source", "t_src"), kw.get("limit"), kw.get("url_like"))]

        assert len(urls()) == 3
        assert urls(url_like="%/group_members/%") == ["https://t.test/a/group_members/x", "https://t.test/b/group_members/y"]
        assert urls(url_like="%/b/%") == ["https://t.test/b/group_members/y"]
        assert urls(url_like="%/group_members/%", limit=1) == ["https://t.test/a/group_members/x"]
        assert urls(url_like="%nothing%") == []
        assert urls(source="dcb", url_like="https://t.test/%") == []  # both filters apply


def test_relation_accepts_listed_in_and_rejects_unknown(conn):
    sources = load_sources(PROJECT_ROOT / "config" / "sources.yaml")
    db.init_db(conn, sources)
    db.init_db(conn, sources)  # re-creating the constraint is idempotent
    with conn.transaction(force_rollback=True):  # test rows never reach the real data
        conn.execute("INSERT INTO source (id, name) VALUES ('t_src', 'Test')")
        page_id = conn.execute(
            "INSERT INTO page (source_id, url, title, text) VALUES ('t_src', 'https://t.test/m', 'T', 'x') RETURNING id"
        ).fetchone()[0]
        person, unit = (
            conn.execute("INSERT INTO entity (type, name, norm_key) VALUES (%s, %s, %s) RETURNING id", row).fetchone()[0]
            for row in (("person", "Ann Lee", "t:ann"), ("unit", "Lab X", "t:labx"))
        )
        insert = "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) VALUES (%s, %s, %s, 'Ann Lee', %s, true)"
        conn.execute(insert, (person, "listed_in", unit, page_id))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(insert, (person, "friend_of", unit, page_id))
