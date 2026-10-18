"""API routes with TestClient on the fixture graph (tests/conftest.py). Needs Postgres."""

import pytest
from fastapi.testclient import TestClient

from navigator.api import app, get_conn


@pytest.fixture
def client(test_conn, graph):
    app.dependency_overrides[get_conn] = lambda: test_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search_hit(client, graph):
    body = client.get("/api/search", params={"q": "glucose"}).json()
    assert body["no_result"] is False
    assert body["expansion"] is None
    names = [r["name"] for r in body["results"]]
    assert set(names) == {"Alice Muster", "Bob Beispiel"}  # Carol has only unverified claims
    assert body["results"][0]["evidence"][0]["claim_id"]


def test_search_filters(client, graph):
    assert [r["name"] for r in client.get("/api/search", params={"q": "glucose", "source": "dcb"}).json()["results"]] \
        == ["Bob Beispiel"]
    units = client.get("/api/search", params={"q": "insulin", "type": "unit"}).json()["results"]
    assert [r["name"] for r in units] == ["Diabetes Lab"]


def test_search_multiple_filter_values(client, graph):
    params = {"q": "glucose insulin", "type": ["person", "unit"], "source": ["artorg", "dcb"]}
    names = {r["name"] for r in client.get("/api/search", params=params).json()["results"]}
    assert names == {"Alice Muster", "Bob Beispiel", "Diabetes Lab"}
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
    assert artorg == {"source": "artorg", "pages": 2, "chunks": 0, "entities": 5, "shown_claims": 10}


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
