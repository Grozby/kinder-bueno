"""Reviewer score, notes and similar cases (#108) with TestClient. Needs Postgres."""

import pytest

from cases.test_pitch import template
from cases.test_store import GLUCORA, client, upload  # noqa: F401  (client is a fixture)
from navigator.api import app, get_write_pitch
from navigator.cases import documents

SECRET = "Internal: the CEO asked us not to mention the Basel offer."


@pytest.fixture
def case_id(client, graph) -> str:  # noqa: F811
    return upload(client, GLUCORA.read_bytes()).json()["id"]


def test_review_is_clamped_and_cleared(client, case_id):  # noqa: F811
    ai_score = client.get(f"/api/cases/{case_id}").json()["score"]
    res = client.put(f"/api/cases/{case_id}/review", json={"score": 140, "reason": " Strong lab fit ", "author": "M. Keller"})
    assert res.status_code == 200
    case = res.json()
    assert case["review"]["score"] == 100 and case["review"]["reason"] == "Strong lab fit"
    assert case["review"]["author"] == "M. Keller" and case["review"]["reviewed_at"]
    assert case["score"] == ai_score is not None  # the AI score is kept next to it
    assert client.put(f"/api/cases/{case_id}/review", json={"score": -3.6, "reason": "x"}).json()["review"]["score"] == 0
    assert client.get("/api/cases").json()[0]["review"]["score"] == 0

    assert client.delete(f"/api/cases/{case_id}/review").json()["review"] is None
    assert client.get(f"/api/cases/{case_id}").json()["review"] is None


@pytest.mark.parametrize("body", [{"score": 50, "reason": ""}, {"score": 50, "reason": "   "}, {"score": 50}])
def test_review_needs_a_reason(client, case_id, body):  # noqa: F811
    assert client.put(f"/api/cases/{case_id}/review", json=body).status_code == 422


def test_review_unknown_case(client):  # noqa: F811
    assert client.put("/api/cases/nope/review", json={"score": 50, "reason": "x"}).status_code == 404
    assert client.delete("/api/cases/nope/review").status_code == 404


def test_notes_oldest_first_counted_and_deleted(client, case_id):  # noqa: F811
    first = client.post(f"/api/cases/{case_id}/notes", json={"author": "L. Frei", "text": "Call on Thursday."}).json()
    second = client.post(f"/api/cases/{case_id}/notes", json={"author": "M. Keller", "text": SECRET}).json()
    assert isinstance(first["id"], str) and first["created_at"]
    notes = client.get(f"/api/cases/{case_id}/notes").json()
    assert [n["text"] for n in notes] == ["Call on Thursday.", SECRET]
    assert client.get(f"/api/cases/{case_id}").json()["notes_count"] == 2

    assert client.delete(f"/api/cases/{case_id}/notes/{first['id']}").json() == {"ok": True}
    assert client.delete(f"/api/cases/{case_id}/notes/{first['id']}").status_code == 404
    assert [n["id"] for n in client.get(f"/api/cases/{case_id}/notes").json()] == [second["id"]]
    assert client.get("/api/cases").json()[0]["notes_count"] == 1


def test_note_errors(client, case_id):  # noqa: F811
    assert client.post(f"/api/cases/{case_id}/notes", json={"author": "x", "text": "  "}).status_code == 422
    assert client.get("/api/cases/nope/notes").status_code == 404
    assert client.post("/api/cases/nope/notes", json={"text": "hi"}).status_code == 404
    assert client.delete(f"/api/cases/{case_id}/notes/abc").status_code == 404
    assert client.delete(f"/api/cases/{case_id}/notes/99999999999999999999").status_code == 404
    note = client.post(f"/api/cases/{case_id}/notes", json={"text": "hi"}).json()
    assert client.delete(f"/api/cases/other/notes/{note['id']}").status_code == 404  # another case's note


def test_notes_never_reach_the_pitch_or_the_documents(client, test_conn, case_id, graph):  # noqa: F811
    client.post(f"/api/cases/{case_id}/notes", json={"author": "M. Keller", "text": SECRET})
    calls = []

    def fake_write(context, results):
        calls.append(repr((context, results)))
        return template(context[0], results)

    app.dependency_overrides[get_write_pitch] = lambda: fake_write
    assert client.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": [graph["alice"]]}).status_code == 200
    assert calls and not any("Basel" in c for c in calls)
    assert "Basel" not in repr(documents.gather(test_conn, case_id))


def test_same_pdf_again_is_a_duplicate_of_the_earlier_case_only(client, case_id):  # noqa: F811
    again = upload(client, GLUCORA.read_bytes(), name="glucora-v2.pdf").json()["id"]
    later = client.get(f"/api/cases/{again}").json()["similar_cases"]
    assert len(later) == 1
    similar = later[0]
    assert similar["case_id"] == case_id and similar["duplicate"] is True
    assert similar["similarity"] == pytest.approx(1.0)  # same summary and needs
    assert similar["shared_needs"] and similar["shared_references"] > 0
    assert similar["status"] == "new" and similar["review"] is None
    assert client.get(f"/api/cases/{case_id}").json()["similar_cases"] == []  # only earlier cases count

    client.put(f"/api/cases/{case_id}/review", json={"score": 70, "reason": "Good"})
    client.patch(f"/api/cases/{case_id}", json={"status": "rejected"})
    similar = client.get(f"/api/cases/{again}").json()["similar_cases"][0]
    assert similar["status"] == "rejected" and similar["review"]["score"] == 70  # current, not a snapshot


def test_unrelated_earlier_case_is_not_similar(client, test_conn, case_id):  # noqa: F811
    profile = [0.0] * 1024
    profile[500] = 1.0  # orthogonal to the Glucora profile
    test_conn.execute(
        """INSERT INTO "case" (id, company_name, file_name, pdf_text, uploaded_at, analysis_status, profile)
           VALUES ('vinora', 'Vinora SA', 'vinora.pdf', 'vines', now() - interval '1 day', 'done', %s::vector)""",
        (str(profile),),
    )
    assert client.get(f"/api/cases/{case_id}").json()["similar_cases"] == []
    test_conn.execute("""UPDATE "case" SET company_name = 'Glucora Health AG' WHERE id = 'vinora'""")
    found = client.get(f"/api/cases/{case_id}").json()["similar_cases"]
    assert [(s["case_id"], s["duplicate"], s["similarity"]) for s in found] == [("vinora", True, 0.0)]


def test_delete_case_removes_everything_stored_for_it(client, test_conn, case_id, graph):  # noqa: F811
    """#134: the case row, its documents and notes (cascade), and its session's chat turns and feedback."""
    other = upload(client, GLUCORA.read_bytes(), name="other.pdf").json()["id"]
    client.put(f"/api/cases/{case_id}/review", json={"score": 70, "reason": "Good"})
    client.post(f"/api/cases/{case_id}/notes", json={"text": SECRET})
    test_conn.execute("INSERT INTO case_document (case_id, kind, content) VALUES (%s, 'report', 'x')", (case_id,))
    for session in (f"case-{case_id}", f"case-{other}", "search-1"):
        test_conn.execute(
            "INSERT INTO chat_turn (session_id, message, query, reply, filters) VALUES (%s, 'q', 'q', 'r', '{}')",
            (session,))
        client.post("/api/feedback", json={"session_id": session, "query": "q", "entity_id": graph["alice"],
                                           "rating": "up"})

    assert client.delete(f"/api/cases/{case_id}").json() == {"ok": True}
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    for table in ("case_document", "case_note"):
        assert test_conn.execute(f"SELECT count(*) FROM {table} WHERE case_id = %s", (case_id,)).fetchone()[0] == 0
    for table in ("chat_turn", "feedback"):
        sessions = {r[0] for r in test_conn.execute(f"SELECT session_id FROM {table}")}
        assert sessions == {f"case-{other}", "search-1"}  # other sessions are kept
    assert [c["id"] for c in client.get("/api/cases").json()] == [other]
    assert client.get(f"/api/cases/{other}").json()["similar_cases"] == []  # the deleted duplicate is gone

    assert client.delete(f"/api/cases/{case_id}").status_code == 404
