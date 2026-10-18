"""API routes with TestClient on the fixture graph (tests/conftest.py). Needs Postgres."""

import pytest
from fastapi.testclient import TestClient

from conftest import onehot
from navigator.api import (
    ChatSessions, app, get_conn, get_embed, get_expand, get_explain, get_page_rules, get_seeds, get_sessions,
)
from navigator.expand import Expansion
from navigator.pages import SourceRules, guess_kind


def fake_embed(query: str):
    """'glucose' is closest to page 3 (Bob), then page 1 (Alice); 'insulin' is page 2 (the lab); else nothing."""
    if "glucose" in query:
        return onehot({3: 0.8, 1: 0.6})
    if "insulin" in query:
        return onehot({2: 1.0})
    return onehot({10: 1.0})


@pytest.fixture
def client(test_conn, graph):
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_embed] = lambda: fake_embed
    app.dependency_overrides[get_expand] = lambda: lambda q: Expansion()  # expansion failed / disabled
    app.dependency_overrides[get_explain] = lambda: lambda q, results: {}  # explanations failed: template
    app.dependency_overrides[get_seeds] = lambda: {"artorg": "https://artorg.example/"}  # dcb is not validated
    app.dependency_overrides[get_page_rules] = lambda: {"artorg": SourceRules(exclude=[r"/alice$"], priority=[r"/lab"])}
    sessions = ChatSessions()  # fresh chat state per test
    app.dependency_overrides[get_sessions] = lambda: sessions
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search_hit(client, graph):
    body = client.get("/api/search", params={"q": "glucose"}).json()
    assert body["no_result"] is False
    assert body["expansion"] is None
    names = [r["name"] for r in body["results"]]
    assert set(names[:2]) == {"Alice Muster", "Bob Beispiel"}  # the units on page 2 match only semantically
    assert "Carol Hidden" not in names  # only unverified claims
    assert body["results"][0]["evidence"][0]["claim_id"]


def test_search_filters(client, graph):
    assert [r["name"] for r in client.get("/api/search", params={"q": "glucose", "source": "dcb"}).json()["results"]] \
        == ["Bob Beispiel"]
    units = client.get("/api/search", params={"q": "insulin", "type": "unit"}).json()["results"]
    assert {r["name"] for r in units} == {"Diabetes Lab", "ARTORG Center"}  # both named on the lab page


def test_search_multiple_filter_values(client, graph):
    params = {"q": "glucose insulin", "type": ["person", "unit"], "source": ["artorg", "dcb"]}
    names = {r["name"] for r in client.get("/api/search", params=params).json()["results"]}
    assert names == {"Alice Muster", "Bob Beispiel", "Diabetes Lab", "ARTORG Center"}
    params = {"q": "glucose insulin", "type": ["unit"], "source": ["dcb"]}
    assert client.get("/api/search", params=params).json()["no_result"] is True


def test_search_no_result(client):
    body = client.get("/api/search", params={"q": "zebrafish"}).json()
    assert body == {"results": [], "expansion": None, "no_result": True}


def test_search_needs_query(client):
    assert client.get("/api/search").status_code == 422


def test_stats_shape(client, graph):
    body = client.get("/api/stats").json()
    assert body["feedback"] == {"up": 0, "down": 0, "wrong_fact": 0}
    artorg = next(s for s in body["sources"] if s["source"] == "artorg")
    # artorg: center, lab, alice (robotics claim hidden), project, infrastructure
    assert artorg == {"source": "artorg", "pages": 2, "chunks": 2, "entities": 5, "shown_claims": 10}


def test_feedback_insert_with_snapshot(client, test_conn, graph):
    response = client.post("/api/feedback", json={
        "session_id": "s1", "query": "glucose", "entity_id": graph["alice"],
        "claim_id": graph["alice_glucose"], "rating": "wrong_fact", "comment": "old info",
    })
    assert response.json() == {"ok": True}
    row = test_conn.execute("SELECT session_id, entity_name, claim_text, rating, comment FROM feedback").fetchone()
    assert row == (
        "s1", "Alice Muster",
        "expertise: continuous glucose monitoring — quote for continuous glucose monitoring",
        "wrong_fact", "old info",
    )
    assert client.get("/api/stats").json()["feedback"]["wrong_fact"] == 1


def test_feedback_on_a_unit_claim_of_a_member(client, test_conn, graph):
    # Alice is a shown member_of the lab, so a "via Diabetes Lab" row on her card can be flagged.
    response = client.post("/api/feedback", json={
        "session_id": "s1", "entity_id": graph["alice"], "claim_id": graph["lab_expertise"], "rating": "wrong_fact",
    })
    assert response.json() == {"ok": True}
    row = test_conn.execute("SELECT entity_name, claim_text FROM feedback").fetchone()
    assert row == ("Alice Muster", "expertise: insulin pumps — quote for insulin pumps (via Diabetes Lab)")


@pytest.mark.parametrize("person, claim", [
    ("bob", "lab_expertise"),     # bob's member_of the lab is judged unsupported: not shown
    ("alice", "center_name"),     # alice's member_of the center is not verified (and a name is not a topic)
    ("alice", "bob_glucose"),     # another person's claim
])
def test_feedback_claim_of_another_entity_is_404(client, graph, person, claim):
    response = client.post("/api/feedback", json={
        "session_id": "s1", "entity_id": graph[person], "claim_id": graph[claim], "rating": "wrong_fact",
    })
    assert response.status_code == 404
    assert response.json() == {"detail": "Claim not found for this entity"}


def test_feedback_unknown_entity_is_404(client):
    response = client.post("/api/feedback", json={"session_id": "s1", "entity_id": 999999, "rating": "up"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Entity not found"}


def test_search_uses_and_returns_expansion(client, graph):
    # "zebrafish" alone has no result; the expansion term "insulin" finds the lab page.
    app.dependency_overrides[get_expand] = lambda: lambda q: Expansion(en=["insulin"], de=["Insulinpumpe"])
    body = client.get("/api/search", params={"q": "zebrafish", "type": "unit"}).json()
    assert body["expansion"] == {"en": ["insulin"], "de": ["Insulinpumpe"]}
    assert body["no_result"] is False
    assert "Diabetes Lab" in {r["name"] for r in body["results"]}


def test_search_uses_checked_explanations_and_keeps_the_template_otherwise(client, graph):
    seen = {}

    def fake_explain(q, results):
        seen["q"], seen["n"] = q, len(results)
        first = results[0]
        return {first.entity_id: f"Works on glucose [{first.evidence[0].claim_id}]."}

    app.dependency_overrides[get_explain] = lambda: fake_explain
    body = client.get("/api/search", params={"q": "glucose"}).json()
    assert seen == {"q": "glucose", "n": len(body["results"])}
    first, rest = body["results"][0], body["results"][1:]
    assert first["why"] == f"Works on glucose [{first['evidence'][0]['claim_id']}]."
    assert all(r["why"].startswith("Matches on: ") for r in rest)


def test_search_without_results_does_not_call_explain(client):
    def fail(q, results):
        raise AssertionError("explain called without results")

    app.dependency_overrides[get_explain] = lambda: fail
    assert client.get("/api/search", params={"q": "nothing here"}).json()["no_result"] is True


def test_sources_list(client, test_conn, graph):
    body = client.get("/api/sources").json()
    assert [s["id"] for s in body] == ["artorg", "dcb"]
    artorg, dcb = body
    stats = {s["source"]: s for s in client.get("/api/stats").json()["sources"]}
    assert (artorg["pages"], artorg["entities"], artorg["verified_claims"]) == (
        stats["artorg"]["pages"], stats["artorg"]["entities"], stats["artorg"]["shown_claims"],
    )
    assert artorg["root_url"] == "https://artorg.example/" and artorg["validated"] is True
    assert artorg["status"] == "ready" and artorg["last_crawled_at"] is not None
    assert {d["url"] for d in artorg["discovered"]} == {"https://artorg.example/alice", "https://artorg.example/lab"}
    assert artorg["discovered"][0] == {"url": "https://artorg.example/alice", "parent": None, "depth": 0, "status": "crawled"}
    # Not in sources.yaml: not validated, root_url falls back to its first page
    assert dcb["validated"] is False and dcb["root_url"] == "https://dcb.example/bob"


def test_source_get_and_unknown(client, graph):
    assert client.get("/api/sources/dcb").json()["pages"] == 1
    response = client.get("/api/sources/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Source not found"}


@pytest.fixture
def page_feedback(test_conn, graph):
    """3 raw claims on Bob's page (1 failed the quote check); 2 up on Bob, 1 down on Alice."""
    for verified in (True, True, False):
        test_conn.execute(
            "INSERT INTO raw_claim (page_id, entity_type, entity_name, field, value, quote, verified) "
            "VALUES (%s, 'person', 'Bob Beispiel', 'role', 'Postdoc', 'q', %s)", (graph["p3"], verified),
        )
    for entity, rating in (("bob", "up"), ("bob", "up"), ("alice", "down")):
        test_conn.execute(
            "INSERT INTO feedback (session_id, entity_id, rating) VALUES ('s', %s, %s)", (graph[entity], rating)
        )


def test_pages_list(client, graph, page_feedback):
    body = client.get("/api/pages").json()
    assert [p["id"] for p in body] == [graph["p1"], graph["p2"], graph["p3"]]
    alice, lab, bob = body
    # Alice's page: 4 shown claims, one judged and supported; mostly about a person
    assert (alice["verified_claims"], alice["entities"], alice["judge_supported"], alice["drop_rate"]) == (4, 1, 1.0, None)
    assert alice["kind"] == "team" and alice["status"] == "crawled" and alice["crawled_at"]
    assert (alice["feedback_up"], alice["feedback_down"]) == (0, 1)
    assert alice["blocked_by"] == "/alice$" and alice["prioritised_by"] is None
    # Lab page: the unsupported robotics claim is hidden but counts as judged; Alice's down vote cites it too
    assert (lab["verified_claims"], lab["entities"], lab["judge_supported"], lab["feedback_down"]) == (6, 5, 0.0, 1)
    assert lab["blocked_by"] is None and lab["prioritised_by"] == "/lab"
    # Bob's page (dcb: no rules): yield 5, no judged claims 0, 2 of 3 raw claims kept 67, feedback (2+1)/(2+2) 75
    assert [(i["criterion"], i["score"]) for i in bob["score_breakdown"]] == [
        ("Yield", 5), ("Precision", 0), ("Verification", 67), ("Feedback", 75),
    ]
    assert bob["score"] == 23 and bob["drop_rate"] == pytest.approx(1 / 3)
    assert bob["score_breakdown"][2]["rationale"] == "33% of the 3 extracted facts were dropped: their quote was not on the page."
    assert bob["blocked_by"] is None and bob["prioritised_by"] is None


def test_page_detail_and_unknown(client, graph):
    body = client.get(f"/api/pages/{graph['p2']}").json()
    assert body["verified_claims"] == len(body["facts"]) == 6
    assert "surgical robotics" not in {f["value"] for f in body["facts"]}  # unsupported: never shown
    names = [f["entity_name"] for f in body["facts"]]
    assert [n for i, n in enumerate(names) if i == 0 or n != names[i - 1]] == list(dict.fromkeys(names))  # grouped
    diabetes = next(f for f in body["facts"] if f["value"] == "diabetes technology")
    assert diabetes == {
        "claim_id": graph["alice_diabetes"], "entity_id": graph["alice"], "entity_name": "Alice Muster",
        "entity_type": "person", "field": "expertise", "value": "diabetes technology",
        "quote": "quote for diabetes technology", "judge_verdict": "partial",
    }
    response = client.get("/api/pages/999999")
    assert response.status_code == 404 and response.json() == {"detail": "Page not found"}


@pytest.mark.parametrize("url, kind", [
    ("https://www.dcberne.com/en/team/", "team"),
    ("https://www.artorg.unibe.ch/research/aihn/group_members/index_eng.html", "team"),
    ("https://www.artorg.unibe.ch/research/aihn/group_members/prof_em_dr_diem_peter/index_eng.html", "team"),
    ("https://www.dcberne.com/en/project/insulin-activity-project/", "project"),
    ("https://www.artorg.unibe.ch/research/aihn/research_activities/index_eng.html", "project"),
    ("https://www.artorg.unibe.ch/services/electronics_lab/index_eng.html", "infrastructure"),
    ("https://www.dbmr.unibe.ch/research/research_programs/allam_lab/index_eng.html", "lab"),
    ("https://www.artorg.unibe.ch/research/aihn/index_eng.html", "lab"),
    ("https://www.artorg.unibe.ch/index_eng.html", "other"),
])
def test_guess_kind_from_url(url, kind):
    assert guess_kind(url, person_claims=0, claims=10) == kind


def test_guess_kind_falls_back_on_entity_types():
    assert guess_kind("https://example.org/x", person_claims=6, claims=10) == "team"
    assert guess_kind("https://example.org/x", person_claims=0, claims=0) == "other"


def test_page_rules_from_sources_yaml(test_conn, graph):
    rules = get_page_rules(test_conn)  # no stored rules: the sources.yaml blocks of the sources in the DB
    assert rules.keys() == {"artorg", "dcb"}
    assert all(isinstance(r, SourceRules) for r in rules.values())


def test_seeds_from_sources_yaml():
    seeds = get_seeds()
    assert {"artorg", "dcb", "unibe"} <= seeds.keys()
    assert seeds["artorg"] == "https://www.artorg.unibe.ch/research/index_eng.html"


def chat(client, message, session_id="case-1", **kwargs):
    return client.post("/api/chat", json={"session_id": session_id, "message": message, **kwargs})


def test_chat_shape_matches_search(client, graph):
    body = chat(client, "glucose").json()
    assert set(body) == {"reply", "results", "filters", "expansion", "no_result"}
    assert body["filters"] == {"source": None, "type": None}
    search = client.get("/api/search", params={"q": "glucose"}).json()
    assert body["results"] == search["results"]
    assert body["reply"] == f"Showing {len(search['results'])} results for 'glucose'."
    assert body["no_result"] is False


def test_chat_filters_are_applied_and_kept(client, graph):
    body = chat(client, "glucose", filters={"source": "dcb", "type": None}).json()
    assert [r["name"] for r in body["results"]] == ["Bob Beispiel"]
    assert body["filters"] == {"source": "dcb", "type": None}
    assert body["reply"] == "Showing 1 results for 'glucose' (source: dcb)."
    # A next message without filters keeps the session's filters
    body = chat(client, "insulin").json()
    assert body["filters"] == {"source": "dcb", "type": None}
    assert {r["name"] for r in body["results"]} <= {"Bob Beispiel"}


def test_chat_filter_only_message_reruns_last_query(client, graph):
    chat(client, "insulin")
    body = chat(client, "  ", filters={"source": None, "type": "unit"}).json()
    assert {r["name"] for r in body["results"]} == {"Diabetes Lab", "ARTORG Center"}
    assert body["reply"] == "Showing 2 results for 'insulin' (type: unit)."


def test_chat_sessions_are_separate(client, graph):
    chat(client, "insulin", session_id="case-1")
    response = chat(client, "", session_id="case-2", filters={"source": None, "type": "unit"})
    assert response.status_code == 422  # unknown session starts empty: nothing to re-run
    assert response.json() == {"detail": "Type a search first"}


def test_chat_no_result(client):
    body = chat(client, "zebrafish").json()
    assert body["results"] == [] and body["no_result"] is True
    assert body["reply"] == "Showing 0 results for 'zebrafish'."


def test_chat_rejects_unknown_type(client):
    assert chat(client, "glucose", filters={"source": None, "type": "robot"}).status_code == 422


def test_chat_sessions_drop_the_oldest():
    sessions = ChatSessions(size=2)
    sessions.get("a").query = "glucose"
    sessions.get("b")
    sessions.get("a")  # a is used again: b is now the oldest
    sessions.get("c")
    assert sessions.get("a").query == "glucose"
    assert sessions.get("b").query is None  # dropped, starts empty
