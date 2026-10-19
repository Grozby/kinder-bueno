"""resolve: name normalisation (unit tests) and the merge rules on the run's own test database (tests/conftest.py)."""

from collections import Counter

import pytest
from psycopg import sql

from navigator.core import db
from navigator.ingest.resolve import (
    acronym_aliases,
    looks_like_person,
    norm_name,
    norm_unit,
    parent_url,
    project_code_aliases,
    resolve,
    site_name,
    unit_variant,
    variant_aliases,
)
from navigator.results import build_results


def test_looks_like_person():
    assert looks_like_person("Prof. Dr. Anna Muster") and looks_like_person("Stefan Bracher, MSc")
    assert not looks_like_person("Alumni") and not looks_like_person("Phone2") and not looks_like_person("Dr. Muster")


def test_norm_name_drops_titles_between_titles():
    assert norm_name("Dr. med. et phil. nat. Ruben Bill") == "ruben bill"  # #150
    assert norm_name("Prof. Dr. habil. Anna Muster") == "anna muster"


def test_norm_name_drops_titles_and_accents():
    assert norm_name("Prof. Dr. med. Johanna  Kremer Hovinga") == "johanna kremer hovinga"
    assert norm_name("PD Dr. Francesco Clavica") == "francesco clavica"
    assert norm_name("Dr. Martina Rothenbühler") == "martina rothenbuhler"
    assert norm_name("Dominik Obrist, PhD") == "dominik obrist"
    assert norm_name("Ass. Prof. Dr. Marco Osterwalder") == norm_name("Marco Osterwalder")
    assert norm_name("Prof. em. Dr.-Ing. Hans Muster") == "hans muster"
    assert norm_unit("The ARTORG Center") == "artorg center"


@pytest.fixture
def conn(test_database_url):
    """The run's test database (tests/conftest.py), emptied before each test."""
    with db.connect(test_database_url) as connection:
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


def test_same_name_in_other_source_merges_without_a_conflicting_email(conn):
    """#151 (owner's decision, 2026-10-19): no shared unit is needed. "Prof. Lilian Witthauer" on dcb and on artorg
    were two entities, each with half the evidence."""
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "dcb", "https://d/1")
    _claim(conn, p1, "person", "Prof. Dr. phil. Lilian Witthauer", "role", "Group Head")
    _claim(conn, p2, "person", "Prof. Lilian Witthauer", "role", "Tenure track professor")
    resolve(conn)
    assert _people(conn) == {"name:lilian witthauer": ["Group Head", "Tenure track professor"]}


def test_name_only_person_in_other_source_merges_into_the_one_email_person(conn):
    p1, p2 = _page(conn, "unibe", "https://u/1"), _page(conn, "dcb", "https://d/1")
    _claim(conn, p1, "person", "Prof. Dr. med., Dr. phil. nat. Maria Luisa Balmer", "email", "maria.balmer@unibe.ch")
    _claim(conn, p2, "person", "Prof. Dr. Maria Luisa Balmer", "role", "SNSF-Eccellenza Professor")
    resolve(conn)
    assert _people(conn) == {"email:maria.balmer@unibe.ch": ["maria.balmer@unibe.ch", "SNSF-Eccellenza Professor"]}


def test_all_personal_emails_of_a_person_join_and_shared_mailboxes_are_not_identities(conn):
    p1, p2, p3, p4 = (_page(conn, "artorg", f"https://a/{i}") for i in (1, 2, 3, 4))
    _claim(conn, p1, "person", "Raphael Andonie", "email", "raphael.andonie@unibe.ch")
    _claim(conn, p1, "person", "Raphael Andonie", "email", "raphael.andonie@insel.ch")
    _claim(conn, p2, "person", "Raphael Andonie", "email", "raphael.andonie@insel.ch")
    _claim(conn, p3, "person", "Raphael Schranz", "email", "3d-printing@artorg.unibe.ch")
    _claim(conn, p4, "person", "Raphael Schranz", "email", "e-lab.artorg@unibe.ch")
    resolve(conn)
    assert set(_people(conn)) == {"email:raphael.andonie@insel.ch", "name:raphael schranz"}


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


def test_umbrella_topics_on_a_lab_page_move_to_the_lab(conn):
    _member_pages(conn)
    sub = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('artorg', %s, %s, 'Adaptive Diabetes Management') "
        "RETURNING id",
        (AIHN + "research_activities/diabetes/index_eng.html",
         "Research: Adaptive Diabetes Management - ARTORG Center for Biomedical Engineering Research"),
    ).fetchone()[0]
    other = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('artorg', %s, %s, 't') RETURNING id",
        ("https://www.artorg.unibe.ch/about/index_eng.html", "About - ARTORG Center for Biomedical Engineering Research"),
    ).fetchone()[0]
    _claim(conn, sub, "unit", "ARTORG Center", "expertise", "adaptive diabetes management")  # umbrella, lab page
    _claim(conn, sub, "unit", "ARTORG Center", "name", "ARTORG Center")  # not a topic: stays
    _claim(conn, sub, "unit", "MELISSA", "description", "an EU project")  # not the umbrella: stays
    _claim(conn, other, "unit", "ARTORG Center", "expertise", "biomedical engineering")  # not a lab page: stays
    counts = resolve(conn)
    rows = conn.execute(
        "SELECT e.name, c.field, c.value FROM claim c JOIN entity e ON e.id = c.entity_id "
        "WHERE e.type = 'unit' AND c.field <> 'name' ORDER BY c.value"
    ).fetchall()
    assert rows == [
        ("AI in Health and Nutrition", "expertise", "adaptive diabetes management"),
        ("MELISSA", "description", "an EU project"),
        ("ARTORG Center", "expertise", "biomedical engineering"),
    ]
    assert counts["lab topics moved from the umbrella"] == 1


def test_site_name():
    assert site_name("Research: X - ARTORG Center for Biomedical Engineering Research") == \
        "ARTORG Center for Biomedical Engineering Research"
    assert site_name("Research: Group Members") == ""


def test_dcb_team_page_uses_the_fixed_unit_name(conn):
    team = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('dcb', 'https://www.dcberne.com/en/team/', "
        "'Team - Diabetes Center Berne', 'Our team\nLea Weber\nData Scientist') RETURNING id"
    ).fetchone()[0]
    _claim(conn, team, "person", "Lea Weber", "role", "Data Scientist")
    resolve(conn)
    assert _listed(conn) == [("Lea Weber", "Diabetes Center Berne", "Lea Weber")]


def test_name_only_person_merges_into_email_person_of_the_same_source(conn):
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "artorg", "https://a/2")
    _claim(conn, p1, "person", "Prof. Dr. Dominik Muster", "email", "dominik.muster@unibe.ch")
    _claim(conn, p2, "person", "Dominik Muster", "role", "Professor")  # no shared unit, same source
    resolve(conn)
    assert _people(conn) == {"email:dominik.muster@unibe.ch": ["dominik.muster@unibe.ch", "Professor"]}


def test_two_email_people_of_the_same_name_stay_apart_from_a_name_only_one(conn):
    p1, p2, p3 = (_page(conn, "artorg", f"https://a/{i}") for i in (1, 2, 3))
    _claim(conn, p1, "person", "Anna Meier", "email", "anna.meier@unibe.ch")
    _claim(conn, p2, "person", "Anna Meier", "email", "a.meier@insel.ch")
    _claim(conn, p3, "person", "Anna Meier", "role", "Nurse")
    resolve(conn)
    assert set(_people(conn)) == {"email:anna.meier@unibe.ch", "email:a.meier@insel.ch", "name:anna meier"}


def test_acronym_unit_merges_into_its_one_full_name():
    names = {"dcb": "DCB", "diabetes center berne": "Diabetes Center Berne", "dcb research ag": "DCB Research AG",
             "nrg": "NRG", "neuro robotics group": "Neuro Robotics Group", "neuro rehab group": "Neuro Rehab Group",
             "artorg": "ARTORG"}
    # NRG fits two units: ambiguous, kept apart. ARTORG fits none. Lowercase or multi-word keys are never aliases.
    assert acronym_aliases(names) == {"dcb": "diabetes center berne"}


def test_acronym_unit_is_merged_in_resolve(conn):
    p1 = _page(conn, "dcb", "https://d/1")
    _claim(conn, p1, "unit", "DCB", "expertise", "insulin pumps")
    _claim(conn, p1, "unit", "Diabetes Center Berne", "name", "Diabetes Center Berne")
    resolve(conn)
    assert conn.execute("SELECT name, norm_key FROM entity WHERE type = 'unit'").fetchall() == [
        ("Diabetes Center Berne", "diabetes center berne")
    ]


def test_project_code_merges_into_its_one_titled_name():
    keys = {"spn-005", "spn-005 - pilot study on painless glucose monitoring", "better4u",
            "abc-1: first study", "abc-1 - second study", "abc-1", "xyz-9 - lonely title"}
    # ABC-1 fits two titled projects: ambiguous, kept apart. XYZ-9 has no code-only project. BETTER4U has no title.
    assert project_code_aliases(keys) == {"spn-005": "spn-005 - pilot study on painless glucose monitoring"}


def test_project_code_is_merged_in_resolve(conn):
    own = _page(conn, "dcb", "https://d/project/spn-005")
    listing = _page(conn, "dcb", "https://d/projects")
    _claim(conn, own, "project", "SPN-005", "expertise", "non-invasive glucose monitoring")
    _claim(conn, listing, "project", "SPN-005 – Pilot study on painless glucose monitoring", "name",
           "SPN-005 – Pilot study on painless glucose monitoring")
    _claim(conn, listing, "project", "SPN-005 – Pilot study on painless glucose monitoring", "expertise",
           "continuous glucose monitoring")
    resolve(conn)
    assert conn.execute("SELECT name FROM entity WHERE type = 'project'").fetchall() == [
        ("SPN-005 – Pilot study on painless glucose monitoring",)
    ]
    assert conn.execute("SELECT count(*) FROM claim").fetchone()[0] == 3



def test_umbrella_topics_on_a_profile_page_are_dropped(conn):
    """A person's profile under a lab: the extractor credits the person's topics to the site as well (#75)."""
    _member_pages(conn)
    profile = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('artorg', %s, %s, 'Kevin Debeire') RETURNING id",
        (AIHN + "group_members/persons/dr_debeire_kevin/index_eng.html",
         "Dr. Kevin Debeire - ARTORG Center for Biomedical Engineering Research"),
    ).fetchone()[0]
    _claim(conn, profile, "person", "Dr. Kevin Debeire", "expertise", "causal discovery")
    _claim(conn, profile, "unit", "ARTORG Center", "expertise", "causal discovery")
    counts = resolve(conn)
    rows = conn.execute(
        "SELECT e.type, e.name, c.value FROM claim c JOIN entity e ON e.id = c.entity_id WHERE c.field = 'expertise'"
    ).fetchall()
    assert rows == [("person", "Dr. Kevin Debeire", "causal discovery")]
    assert counts["umbrella topics dropped on profiles"] == 1
    assert counts["lab topics moved from the umbrella"] == 0


def test_unit_variant():
    assert unit_variant("acoustic robotic systems lab (arsl)") == unit_variant("acoustic robotics systems lab")
    assert unit_variant("neuro robotic group") == unit_variant("neuro robotics group")
    assert unit_variant("swiss tph") != unit_variant("swiss tphs lab")


def test_unit_spelling_variants_merge_into_the_most_mentioned():
    mentions = Counter({"acoustic robotics systems lab": 5, "acoustic robotic systems lab": 2,
                        "acoustic robotic systems lab (arsl)": 1, "neuro robotic group": 1, "neuro robotics group": 3,
                        "diabetes center berne": 9})
    assert variant_aliases(mentions) == {
        "acoustic robotic systems lab": "acoustic robotics systems lab",
        "acoustic robotic systems lab (arsl)": "acoustic robotics systems lab",
        "neuro robotic group": "neuro robotics group",
    }


def test_unit_spelling_variants_are_merged_in_resolve(conn):
    p1, p2 = _page(conn, "artorg", "https://a/1"), _page(conn, "artorg", "https://a/2")
    _claim(conn, p1, "unit", "Neuro Robotics Group", "expertise", "surgical robots")
    _claim(conn, p1, "unit", "Neuro Robotics Group", "name", "Neuro Robotics Group")
    _claim(conn, p2, "unit", "Neuro Robotic Group", "expertise", "cochlear implants")
    _claim(conn, p2, "person", "Ass. Prof. Dr. Anna Muster", "role", "Group head")
    _claim(conn, p1, "person", "Anna Muster", "role", "Group head")
    resolve(conn)
    assert conn.execute("SELECT type, count(*) FROM entity GROUP BY type ORDER BY type").fetchall() == [
        ("person", 1), ("unit", 1)
    ]
    assert conn.execute("SELECT name FROM entity WHERE type = 'unit'").fetchone()[0] == "Neuro Robotics Group"
