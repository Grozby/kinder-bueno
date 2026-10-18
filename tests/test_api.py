"""API routes with TestClient on the fixture graph (tests/conftest.py). Needs Postgres."""

import pytest
from fastapi.testclient import TestClient

from conftest import onehot
from navigator.api import app, get_conn, get_embed, get_expand, get_explain
from navigator.expand import Expansion


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
