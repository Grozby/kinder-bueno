"""Shared fixtures for integration tests on a separate `navigator_test` database."""

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from navigator import db
from navigator.settings import PROJECT_ROOT, get_settings
from navigator.sources import load_sources

TEST_DB = "navigator_test"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Create `navigator_test` if missing and run the schema on it. Skip when Postgres is not running."""
    base = conninfo_to_dict(get_settings().database_url)
    try:
        with psycopg.connect(make_conninfo(**{**base, "dbname": "postgres"}), autocommit=True) as admin:
            if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    url = make_conninfo(**{**base, "dbname": TEST_DB})
    with db.connect(url) as conn:
        db.init_db(conn, load_sources(PROJECT_ROOT / "config" / "sources.yaml"))
    return url


@pytest.fixture
def test_conn(test_database_url):
    """Connection to the test database, with every table emptied first."""
    with db.connect(test_database_url) as conn:
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(map(sql.Identifier, tables)))
        )
        yield conn


@pytest.fixture
def graph(test_conn) -> dict[str, int]:
    """Small graph: 2 units, 3 people, 1 project, 1 infrastructure. Returns ids by short name."""
    c = test_conn
    c.execute("INSERT INTO source (id, name) VALUES ('artorg', 'ARTORG'), ('dcb', 'DCB')")
    ids: dict[str, int] = {}

    def page(key: str, source: str, url: str) -> None:
        ids[key] = c.execute(
            "INSERT INTO page (source_id, url, title, text) VALUES (%s, %s, %s, 'text') RETURNING id",
            (source, url, key),
        ).fetchone()[0]

    def entity(key: str, type_: str, name: str) -> None:
        ids[key] = c.execute(
            "INSERT INTO entity (type, name, norm_key) VALUES (%s, %s, %s) RETURNING id", (type_, name, name.lower())
        ).fetchone()[0]

    def claim(key: str, ent: str, field: str, value: str, pg: str, verified=True, verdict=None, reason=None) -> None:
        ids[key] = c.execute(
            "INSERT INTO claim (entity_id, field, value, quote, page_id, verified, judge_verdict, judge_reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (ids[ent], field, value, f"quote for {value}", ids[pg], verified, verdict, reason),
        ).fetchone()[0]

    def relation(frm: str, rel: str, to: str, pg: str, verified=True, verdict=None) -> None:
        c.execute(
            "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified, judge_verdict) "
            "VALUES (%s, %s, %s, 'rel quote', %s, %s, %s)",
            (ids[frm], rel, ids[to], ids[pg], verified, verdict),
        )

    page("p1", "artorg", "https://artorg.example/alice")
    page("p2", "artorg", "https://artorg.example/lab")
    page("p3", "dcb", "https://dcb.example/bob")

    entity("center", "unit", "ARTORG Center")
    entity("lab", "unit", "Diabetes Lab")
    entity("alice", "person", "Alice Muster")
    entity("bob", "person", "Bob Beispiel")
    entity("carol", "person", "Carol Hidden")
    entity("pancreas", "project", "Artificial Pancreas")
    entity("cleanroom", "infrastructure", "Cleanroom")

    claim("center_name", "center", "name", "ARTORG Center", "p2")
    claim("lab_name", "lab", "name", "Diabetes Lab", "p2")
    claim("lab_expertise", "lab", "expertise", "insulin pumps", "p2")
    claim("alice_role", "alice", "role", "Professor", "p1")
    claim("alice_email", "alice", "email", "alice@example.org", "p1")
    claim("alice_phone", "alice", "phone", "+41 31 000 00 00", "p1")
    claim("alice_glucose", "alice", "expertise", "continuous glucose monitoring", "p1", verdict="supported")
    claim("alice_robotics", "alice", "expertise", "surgical robotics", "p2", verdict="unsupported")
    claim("alice_diabetes", "alice", "expertise", "diabetes technology", "p2", verdict="partial", reason="broader")
    claim("bob_role", "bob", "role", "Postdoc", "p3")
    claim("bob_glucose", "bob", "expertise", "glucose sensors", "p3")
    claim("carol_glucose", "carol", "expertise", "glucose", "p3", verified=False)
    claim("carol_role", "carol", "role", "Engineer", "p3", verified=False)
    claim("pancreas_name", "pancreas", "name", "Artificial Pancreas", "p2")
    claim("cleanroom_name", "cleanroom", "name", "Cleanroom", "p2")

    relation("lab", "part_of", "center", "p2")
    relation("lab", "provides", "cleanroom", "p2")
    relation("alice", "member_of", "lab", "p1")
    relation("alice", "member_of", "center", "p1", verified=False)
    relation("alice", "works_on", "pancreas", "p1")
    relation("bob", "member_of", "center", "p3")
    relation("bob", "member_of", "lab", "p3", verdict="unsupported")
    return ids
