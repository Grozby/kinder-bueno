"""Case drawer state kept in the DB (#81): selection, chat-added references, chat history, feedback. Needs Postgres."""

import pytest
from fastapi.testclient import TestClient
from test_analysis import new_case, run
from test_api import fake_embed

from navigator.api import (
    ChatSessions,
    app,
    get_conn,
    get_embed,
    get_expand,
    get_explain,
    get_sessions,
)
from navigator.expand import Expansion


@pytest.fixture
def client(test_conn, graph):
    glucose = graph["bob_glucose"]
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_embed] = lambda: fake_embed
    app.dependency_overrides[get_expand] = lambda: lambda q: Expansion()
    # A checked sentence for Bob only, so the stored "why" can be told apart from the template
    app.dependency_overrides[get_explain] = lambda: lambda q, results: {
        r.entity_id: f"Works on glucose sensors [{glucose}]." for r in results if r.name == "Bob Beispiel"}
    sessions = ChatSessions()
    app.dependency_overrides[get_sessions] = lambda: sessions
    yield TestClient(app)
    app.dependency_overrides.clear()


def chat(client, case_id, message, **kwargs):
    return client.post("/api/chat", json={"session_id": f"case-{case_id}", "message": message, **kwargs}).json()


def test_selection_defaults_to_the_matching_references_then_is_stored(client, test_conn):
    case_id = new_case(test_conn)
    run(test_conn, case_id)
    listed = client.get(f"/api/cases/{case_id}/references").json()
    refs = [r["entity_id"] for r in listed]
    matching = [r["entity_id"] for r in listed if r["why"].startswith("Matches ")]
    assert 0 < len(matching) < len(refs)  # the fixture has both kinds
    assert client.get(f"/api/cases/{case_id}/selection").json() == {"entity_ids": matching}  # "Found for": not preselected

    res = client.put(f"/api/cases/{case_id}/selection", json={"entity_ids": [refs[1], refs[0], refs[1]]})
    assert res.json() == {"entity_ids": [refs[1], refs[0]]}
    assert client.get(f"/api/cases/{case_id}/selection").json() == {"entity_ids": [refs[1], refs[0]]}
    assert client.put(f"/api/cases/{case_id}/selection", json={"entity_ids": []}).json() == {"entity_ids": []}
    assert client.get(f"/api/cases/{case_id}/selection").json() == {"entity_ids": []}  # empty is not the default


def test_selection_errors_and_entities_gone_since(client, test_conn, graph):
    case_id = new_case(test_conn)
    assert client.get("/api/cases/nope/selection").status_code == 404
    assert client.put("/api/cases/nope/selection", json={"entity_ids": []}).status_code == 404
    assert client.put(f"/api/cases/{case_id}/selection", json={"entity_ids": [999999]}).status_code == 404
    client.put(f"/api/cases/{case_id}/selection", json={"entity_ids": [graph["bob"], graph["alice"]]})
    test_conn.execute("DELETE FROM entity WHERE id = %s", (graph["bob"],))  # gone after a re-ingest
    assert client.get(f"/api/cases/{case_id}/selection").json() == {"entity_ids": [graph["alice"]]}


def test_chat_result_added_as_reference(client, test_conn, graph):
    case_id = new_case(test_conn)  # not analysed: no references of its own
    chat(client, case_id, "glucose")
    res = client.post(f"/api/cases/{case_id}/references", json={"entity_id": graph["bob"]})
    assert res.status_code == 200
    assert res.json()["added"] is True
    assert res.json()["why"] == f"Works on glucose sensors [{graph['bob_glucose']}]."  # its chat sentence
    client.post(f"/api/cases/{case_id}/references", json={"entity_id": graph["bob"]})  # twice: kept once

    refs = client.get(f"/api/cases/{case_id}/references").json()
    assert [(r["name"], r["added"]) for r in refs] == [("Bob Beispiel", True)]
    assert refs[0]["why"] == res.json()["why"]

    # The sentence is checked again on every read: it is dropped once its claim is gone
    test_conn.execute("DELETE FROM claim WHERE id = %s", (graph["bob_glucose"],))
    assert "[" not in client.get(f"/api/cases/{case_id}/references").json()[0]["why"]


def test_added_reference_errors_and_removal(client, test_conn, graph):
    case_id = new_case(test_conn)
    assert client.post("/api/cases/nope/references", json={"entity_id": graph["bob"]}).status_code == 404
    assert client.post(f"/api/cases/{case_id}/references", json={"entity_id": graph["carol"]}).status_code == 404
    assert client.delete(f"/api/cases/{case_id}/references/{graph['bob']}").status_code == 404

    client.post(f"/api/cases/{case_id}/references", json={"entity_id": graph["bob"]})  # not from the chat: template
    client.put(f"/api/cases/{case_id}/selection", json={"entity_ids": [graph["bob"], graph["alice"]]})
    res = client.delete(f"/api/cases/{case_id}/references/{graph['bob']}")
    assert res.json() == {"entity_ids": [graph["alice"]]}  # also deselected
    assert client.get(f"/api/cases/{case_id}/references").json() == []


def test_chat_history_is_stored_for_case_sessions(client, test_conn, graph):
    case_id = new_case(test_conn)
    first = chat(client, case_id, "glucose")
    chat(client, case_id, "", filters={"source": "dcb", "type": None})  # re-runs "glucose" on dcb
    client.post("/api/chat", json={"session_id": "search-1", "message": "insulin"})  # not a case: not stored

    turns = client.get(f"/api/cases/{case_id}/chat").json()
    assert [t["message"] for t in turns] == ["glucose", ""]
    assert turns[0]["response"] == first
    assert [r["name"] for r in turns[1]["response"]["results"]] == ["Bob Beispiel"]
    assert turns[1]["response"]["filters"] == {"source": "dcb", "type": None}
    assert test_conn.execute("SELECT count(*) FROM chat_turn").fetchone()[0] == 2
    assert client.get("/api/cases/nope/chat").status_code == 404


def test_chat_session_restored_after_restart(client, test_conn, graph):
    case_id = new_case(test_conn)
    chat(client, case_id, "glucose", filters={"source": "dcb", "type": None})
    app.dependency_overrides[get_sessions] = lambda: ChatSessions()  # API restarted: memory is empty
    body = chat(client, case_id, "", filters={"source": None, "type": "person"})
    assert body["reply"].startswith("Showing 2 results for 'glucose'")


def test_case_feedback(client, test_conn, graph):
    case_id = new_case(test_conn)
    session = f"case-{case_id}"

    def rate(entity, rating, claim=None, session_id=session):
        client.post("/api/feedback", json={"session_id": session_id, "query": "Glucora", "entity_id": graph[entity],
                                           "claim_id": graph[claim] if claim else None, "rating": rating})

    rate("bob", "up")
    rate("bob", "down")  # the last one counts
    rate("alice", "up")
    rate("alice", "wrong_fact", "alice_glucose")
    rate("lab", "up", session_id="case-other")
    body = client.get(f"/api/cases/{case_id}/feedback").json()
    assert body == {"ratings": {str(graph["bob"]): "down", str(graph["alice"]): "up"},
                    "flagged": [graph["alice_glucose"]]}
    assert client.get("/api/cases/nope/feedback").status_code == 404


def test_zero_fit_case_lists_and_preselects_nothing(client, test_conn, graph):
    """#110: when no reference matches a need, the nearest entities are not shown as references nor selected."""
    case_id = new_case(test_conn)
    run(test_conn, case_id)
    test_conn.execute(
        """UPDATE "case" SET refs = (SELECT jsonb_agg(r || '{"needs": []}') FROM jsonb_array_elements(refs) r)
           WHERE id = %s""", (case_id,))
    assert client.get(f"/api/cases/{case_id}/references").json() == []
    assert client.get(f"/api/cases/{case_id}/selection").json() == {"entity_ids": []}
    added = client.post(f"/api/cases/{case_id}/references", json={"entity_id": graph["bob"]}).json()
    assert [r["entity_id"] for r in client.get(f"/api/cases/{case_id}/references").json()] == [added["entity_id"]]
