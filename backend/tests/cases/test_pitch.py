"""Sales pitch tests (#54): citation check and template with a fake LLM; the routes need Postgres."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from navigator.api import app
from navigator.api.deps import get_conn, get_write_pitch
from navigator.cases.pitch import check_pitch, format_prompt, template, write_pitch
from navigator.models import Evidence, Result


def _ev(claim_id: int, field: str, value: str = "v", via_unit: str | None = None) -> Evidence:
    return Evidence(claim_id=claim_id, field=field, value=value, quote=f"quote {value}", url="https://u",
                    judge_verdict=None, judge_reason=None, via_unit=via_unit)


def _result(entity_id: int, name: str, type_: str, evidence: list[Evidence]) -> Result:
    return Result(entity_id=entity_id, type=type_, name=name, role=[], contact=[], affiliations=[], expertise=[],
                  projects=[], infrastructure=[], why="", score=0.0, sources=["https://u"], evidence=evidence)


ANNA = _result(1, "Anna Muster", "person", [
    _ev(11, "email", "a@unibe.ch"), _ev(12, "role", "Group Head"), _ev(13, "expertise", "glucose sensors"),
    _ev(14, "expertise", "type 1 diabetes", via_unit="Diabetes Lab"),
])
LAB = _result(2, "Diabetes Lab", "unit", [_ev(21, "description", "diabetes technology research")])
REFS = [ANNA, LAB]


class FakeLLM:
    def __init__(self, answer=None, error: Exception | None = None, delay: float = 0.0):
        self.answer, self.error, self.delay = answer, error, delay
        self.prompts: list[str] = []

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        self.prompts.append(user)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer


def test_prompt_has_case_and_claims_without_contacts():
    text = format_prompt("Glucora", "medtech", "A needle-free patch.", ["glucose sensors"], REFS)
    assert "Company: Glucora (medtech)" in text and "Needs: glucose sensors" in text
    assert "[13] expertise: glucose sensors" in text
    assert "[14] lab topic (via Diabetes Lab): type 1 diabetes" in text
    assert "a@unibe.ch" not in text


def test_valid_pitch_is_kept_with_paragraphs():
    text = ("Dear Glucora team,\n\nAnna Muster develops glucose sensors [13]. "
            "The Diabetes Lab does diabetes technology research [21].\n\nWe would be happy to introduce you.")
    assert check_pitch(text, REFS) == text


def test_sentence_citing_another_entity_or_unknown_id_is_removed():
    text = "Anna Muster develops glucose sensors [13]. She also builds robots [99]. Bern is great."
    assert check_pitch(text, REFS) == "Anna Muster develops glucose sensors [13]. Bern is great."


def test_contact_rows_cannot_be_cited():
    assert check_pitch("Write to Anna Muster [11].", REFS) is None


def test_reference_named_without_citation_is_removed():
    text = "Anna Muster develops glucose sensors [13]. Dr. Muster is a world leader. The Diabetes Lab is famous."
    assert check_pitch(text, REFS) == "Anna Muster develops glucose sensors [13]."


def test_citation_after_the_full_stop_stays_with_its_sentence():
    assert check_pitch("Anna Muster develops glucose sensors. [13] Welcome.", REFS) == \
        "Anna Muster develops glucose sensors. [13] Welcome."


def test_lab_topic_must_name_the_lab():
    assert check_pitch("Anna Muster works on type 1 diabetes [14].", REFS) is None
    ok = "Anna Muster works in the Diabetes Lab, which works on type 1 diabetes [14]."
    assert check_pitch(ok, REFS) == ok


def test_no_citation_at_all_is_none():
    assert check_pitch("Bern is a great place for you.", REFS) is None
    assert check_pitch(None, REFS) is None


def test_template_lists_references_with_cited_topics():
    text = template("Glucora", REFS)
    assert "- Anna Muster: glucose sensors [13]" in text
    assert "- Diabetes Lab: diabetes technology research [21]" in text
    assert text.startswith("Dear Glucora team,")


def test_write_pitch_uses_checked_answer():
    llm = FakeLLM({"pitch": "Anna Muster develops glucose sensors [13]."})
    assert asyncio.run(write_pitch(llm, "Glucora", None, None, [], REFS)) == "Anna Muster develops glucose sensors [13]."


@pytest.mark.parametrize("llm", [
    FakeLLM(error=RuntimeError("gateway down")),
    FakeLLM({"pitch": "Bern is great."}),
    FakeLLM({"pitch": "Anna Muster develops glucose sensors [13]."}, delay=1.0),
])
def test_write_pitch_falls_back_to_template(llm):
    assert asyncio.run(write_pitch(llm, "Glucora", None, None, [], REFS, timeout=0.1)) == template("Glucora", REFS)


def test_write_pitch_without_claims_does_not_call_the_llm():
    llm = FakeLLM(error=AssertionError("called"))
    empty = [_result(3, "Nobody", "person", [_ev(31, "email", "n@x.ch")])]
    assert asyncio.run(write_pitch(llm, "Glucora", None, None, [], empty)) == template("Glucora", empty)


# --- routes ---

@pytest.fixture
def client(test_conn):
    calls = []
    app.dependency_overrides[get_conn] = lambda: test_conn

    def fake_write(context, results):
        calls.append((context, [r.entity_id for r in results]))
        return template(context[0], results)

    app.dependency_overrides[get_write_pitch] = lambda: fake_write
    yield TestClient(app), calls
    app.dependency_overrides.clear()


@pytest.fixture
def case_id(test_conn) -> str:
    test_conn.execute(
        """INSERT INTO "case" (id, company_name, file_name, pdf_text, summary, needs)
           VALUES ('c1', 'Glucora', 'glucora.pdf', 'text', 'A patch.', '["glucose sensors"]')"""
    )
    return "c1"


def test_pitch_is_generated_stored_and_returned(client, graph, case_id):
    http, calls = client
    ids = [graph["alice"], graph["lab"], graph["alice"]]
    res = http.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": ids})
    assert res.status_code == 200
    body = res.json()
    assert body["entity_ids"] == [graph["alice"], graph["lab"]]  # duplicates dropped, order kept
    assert f"[{graph['alice_glucose']}]" in body["text"]
    assert calls == [(("Glucora", None, "A patch.", ["glucose sensors"]), [graph["alice"], graph["lab"]])]
    assert http.get(f"/api/cases/{case_id}/pitch").json() == body


def test_pitch_errors(client, graph, case_id):
    http, calls = client
    assert http.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": []}).status_code == 422
    assert http.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": [graph["alice"], -5]}).status_code == 404
    assert http.post("/api/cases/nope/pitch", json={"entity_ids": [graph["alice"]]}).status_code == 404
    assert http.get(f"/api/cases/{case_id}/pitch").status_code == 404  # none yet
    assert http.get("/api/cases/nope/pitch").status_code == 404
    assert calls == []

