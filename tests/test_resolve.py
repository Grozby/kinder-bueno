"""resolve: name normalisation (unit tests) and the merge rules on a separate `navigator_test` database."""

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from navigator import db
from navigator.resolve import looks_like_person, norm_name, norm_unit, parent_url, resolve
from navigator.results import build_results
from navigator.settings import PROJECT_ROOT, get_settings
from navigator.sources import load_sources


def test_looks_like_person():
    assert looks_like_person("Prof. Dr. Anna Muster") and looks_like_person("Stefan Bracher, MSc")
    assert not looks_like_person("Alumni") and not looks_like_person("Phone2") and not looks_like_person("Dr. Muster")


def test_norm_name_drops_titles_and_accents():
    assert norm_name("Prof. Dr. med. Johanna  Kremer Hovinga") == "johanna kremer hovinga"
    assert norm_name("PD Dr. Francesco Clavica") == "francesco clavica"
    assert norm_name("Dr. Martina Rothenbühler") == "martina rothenbuhler"
    assert norm_name("Dominik Obrist, PhD") == "dominik obrist"
    assert norm_unit("The ARTORG Center") == "artorg center"


@pytest.fixture
def conn():
    """Test database (created if missing), emptied before each test. Skipped without Postgres."""
    base = conninfo_to_dict(get_settings().database_url)
    try:
        with psycopg.connect(make_conninfo(**{**base, "dbname": "postgres"}), autocommit=True) as admin:
            if not admin.execute("SELECT 1 FROM pg_database WHERE datname = 'navigator_test'").fetchone():
                admin.execute("CREATE DATABASE navigator_test")
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    with db.connect(make_conninfo(**{**base, "dbname": "navigator_test"})) as connection:
        db.init_db(connection, load_sources(PROJECT_ROOT / "config" / "sources.yaml"))
        tables = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        connection.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(map(sql.Identifier, tables)))
        )
        connection.execute("INSERT INTO source (id, name) VALUES ('artorg', 'A'), ('dcb', 'D'), ('unibe', 'U')")
        yield connection


def _page(conn, source: str, url: str) -> int:
    return conn.execute(
        "INSERT INTO page (source_id, url, text) VALUES (%s, %s, 't') RETURNING id", (source, url)
    ).fetchone()[0]


def _claim(conn, page: int, etype: str, name: str, field: str, value: str, verified: bool = True) -> None:
    conn.execute(
        "INSERT INTO raw_claim (page_id, entity_type, entity_name, field, value, quote, verified) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (page, etype, name, field, value, f"{name} {value}", verified),
    )


def _member(conn, page: int, person: str, unit: str) -> None:
    conn.execute(
        "INSERT INTO raw_relation (page_id, from_type, from_name, rel, to_type, to_name, quote, verified) "
        "VALUES (%s, 'person', %s, 'member_of', 'unit', %s, 'q', true)",
        (page, person, unit),
    )


def _people(conn) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT e.norm_key, c.value FROM entity e JOIN claim c ON c.entity_id = e.id "
        "WHERE e.type = 'person' ORDER BY e.norm_key, c.id"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for key, value in rows:
        out.setdefault(key, []).append(value)
    return out


def test_email_merges_across_pages_and_titles(conn):
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "dcb", "https://d/1")
    _claim(conn, p1, "person", "Prof. Dr. Anna Muster", "email", "anna.muster@unibe.ch")
    _claim(conn, p1, "person", "Prof. Dr. Anna Muster", "role", "Professor")
    _claim(conn, p2, "person", "Anna Muster", "email", "Anna.Muster@unibe.ch")
    _claim(conn, p2, "person", "Anna Muster", "role", "Group Leader")
    resolve(conn)
    # one entity; each page keeps its own evidence rows
    assert _people(conn) == {
        "email:anna.muster@unibe.ch": ["anna.muster@unibe.ch", "Professor", "Anna.Muster@unibe.ch", "Group Leader"]
    }


def test_same_name_in_other_source_without_shared_unit_stays_separate(conn):
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "unibe", "https://u/1")
    _claim(conn, p1, "person", "Peter Meier", "role", "Engineer")
    _claim(conn, p2, "person", "Dr. Peter Meier", "role", "Historian")
    resolve(conn)
    assert _people(conn) == {"name:peter meier#artorg": ["Engineer"], "name:peter meier#unibe": ["Historian"]}


def test_same_name_merges_on_shared_unit_or_same_source(conn):
    a1, a2, u1 = _page(conn, "artorg", "https://a/1"), _page(conn, "artorg", "https://a/2"), _page(conn, "unibe", "https://u/1")
    _claim(conn, a1, "person", "Lea Weber", "role", "PhD student")
    _claim(conn, a2, "person", "Lea Weber", "role", "Researcher")  # same source
    _claim(conn, u1, "person", "Lea Weber", "role", "Lecturer")
    _member(conn, a1, "Lea Weber", "Gait Lab")
    _member(conn, u1, "Lea Weber", "The Gait Lab")  # same unit key
    resolve(conn)
    assert _people(conn) == {"name:lea weber": ["PhD student", "Researcher", "Lecturer"]}


def test_name_only_person_merges_into_email_person_with_shared_unit(conn):
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "dcb", "https://d/1")
    _claim(conn, p1, "person", "Tom Huber", "email", "tom.huber@unibe.ch")
    _member(conn, p1, "Tom Huber", "Sensing Lab")
    _claim(conn, p2, "person", "Dr. Tom Huber", "role", "Postdoc")
    _member(conn, p2, "Dr. Tom Huber", "Sensing Lab")
    resolve(conn)
    assert _people(conn) == {"email:tom.huber@unibe.ch": ["tom.huber@unibe.ch", "Postdoc"]}


def test_unverified_dropped_duplicates_deduped_relations_linked(conn):
    p1 = _page(conn, "artorg", "https://a/1")
    for _ in range(3):  # the extractor sometimes repeats itself
        _claim(conn, p1, "unit", "Osterwalder Lab", "expertise", "cardiac morphogenesis")
    _claim(conn, p1, "unit", "Osterwalder Lab", "expertise", "made up", verified=False)
    _claim(conn, p1, "person", "Eva Roth", "role", "PI")
    _member(conn, p1, "Eva Roth", "the Osterwalder Lab")
    counts = resolve(conn)
    assert counts["claims"] == 2
    assert conn.execute("SELECT value FROM claim WHERE field = 'expertise'").fetchall() == [("cardiac morphogenesis",)]
    rel = conn.execute(
        "SELECT f.name, r.rel, t.name FROM relation r JOIN entity f ON f.id = r.from_id JOIN entity t ON t.id = r.to_id"
    ).fetchall()
    assert rel == [("Eva Roth", "member_of", "Osterwalder Lab")]


def test_rerun_is_idempotent_and_keeps_ids(conn):
    p1 = _page(conn, "artorg", "https://a/1")
    _claim(conn, p1, "person", "Eva Roth", "email", "eva.roth@unibe.ch")
    resolve(conn)
    first = conn.execute("SELECT id, norm_key FROM entity").fetchall()
    resolve(conn)
    assert conn.execute("SELECT id, norm_key FROM entity").fetchall() == first
    assert conn.execute("SELECT count(*) FROM claim").fetchone()[0] == 1


def test_entities_gone_from_raw_are_removed(conn):
    p1 = _page(conn, "artorg", "https://a/1")
    _claim(conn, p1, "project", "Old Project", "name", "Old Project")
    resolve(conn)
    conn.execute("DELETE FROM raw_claim")
    resolve(conn)
    assert conn.execute("SELECT count(*) FROM entity").fetchone()[0] == 0


def test_parent_url_of_member_pages():
    base = "https://www.artorg.unibe.ch/research/aihn/"
    assert parent_url(base + "group_members/index_eng.html") == base + "index_eng.html"
    assert parent_url("https://www.dbmr.unibe.ch/research/rov_lab/team/index_eng.html") == \
        "https://www.dbmr.unibe.ch/research/rov_lab/index_eng.html"
    assert parent_url("https://www.dcberne.com/en/team/") == "https://www.dcberne.com/en/"
    assert parent_url(base + "group_members/prof_dr_x/index_eng.html") is None  # a person's own page
    assert parent_url(base + "index_eng.html") is None


AIHN = "https://www.artorg.unibe.ch/research/aihn/"


def _member_pages(conn, parent: bool = True) -> int:
    """An ARTORG-like lab page and its member page with two people. Returns the member page id."""
    if parent:
        conn.execute(
            "INSERT INTO page (source_id, url, title, text) VALUES ('artorg', %s, 'Research: AIHN', %s)",
            (AIHN + "index_eng.html", "\n  AI in Health and Nutrition\nWe study nutrition."),
        )
    member = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('artorg', %s, 'Research: Group Members', %s) "
        "RETURNING id",
        (AIHN + "group_members/index_eng.html", "Group Members\nProf. Dr. Anna Muster\nHead\nBen Kurz\nPhD student\nAlumni"),
    ).fetchone()[0]
    _claim(conn, member, "person", "Prof. Dr. Anna Muster", "role", "Head")
    _claim(conn, member, "person", "Ben Kurz", "role", "PhD student")
    _claim(conn, member, "person", "Alumni", "role", "Alumni")  # a heading the extractor took for a person
    return member


def _listed(conn) -> list[tuple]:
    return conn.execute(
        "SELECT f.name, t.name, r.quote FROM relation r JOIN entity f ON f.id = r.from_id "
        "JOIN entity t ON t.id = r.to_id WHERE r.rel = 'listed_in' ORDER BY f.name"
    ).fetchall()


def test_people_on_member_page_are_listed_in_the_lab(conn):
    member = _member_pages(conn)
    counts = resolve(conn)
    assert _listed(conn) == [
        ("Ben Kurz", "AI in Health and Nutrition", "Ben Kurz"),
        ("Prof. Dr. Anna Muster", "AI in Health and Nutrition", "Prof. Dr. Anna Muster"),
    ]
    assert counts["relations (listed_in)"] == 2  # not the heading "Alumni"
    # the lab gets a name claim quoting the first line of its own page
    unit_claim = conn.execute(
        "SELECT c.value, c.quote, p.url FROM claim c JOIN entity e ON e.id = c.entity_id JOIN page p ON p.id = c.page_id "
        "WHERE e.type = 'unit' AND c.field = 'name'"
    ).fetchone()
    assert unit_claim == ("AI in Health and Nutrition", "AI in Health and Nutrition", AIHN + "index_eng.html")
    # idempotent
    resolve(conn)
    assert len(_listed(conn)) == 2
    # the result card shows the lab and an evidence row linking the member page
    ben = conn.execute("SELECT id FROM entity WHERE name = 'Ben Kurz'").fetchone()[0]
    card = build_results(conn, [(ben, 1.0)])[0]
    assert card.affiliations == ["AI in Health and Nutrition"]
    row = next(e for e in card.evidence if e.field == "listed_in")
    assert (row.value, row.quote, row.url) == (
        "listed on the member page of AI in Health and Nutrition", "Ben Kurz", AIHN + "group_members/index_eng.html"
    )
    assert conn.execute("SELECT page_id FROM claim WHERE id = %s", (row.claim_id,)).fetchone()[0] == member


def test_member_page_without_parent_page_is_skipped(conn):
    _member_pages(conn, parent=False)
    counts = resolve(conn)
    assert _listed(conn) == []
    assert counts["member pages skipped (no parent page)"] == 1


def test_dcb_team_page_uses_the_fixed_unit_name(conn):
    team = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('dcb', 'https://www.dcberne.com/en/team/', "
        "'Team - Diabetes Center Berne', 'Our team\nLea Weber\nData Scientist') RETURNING id"
    ).fetchone()[0]
    _claim(conn, team, "person", "Lea Weber", "role", "Data Scientist")
    resolve(conn)
    assert _listed(conn) == [("Lea Weber", "Diabetes Center Berne", "Lea Weber")]
