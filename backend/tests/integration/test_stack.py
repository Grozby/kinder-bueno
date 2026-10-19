"""End-to-end checks on the running stack (tests/integration/conftest.py): every route the UI uses, on real data.

LLM output varies, so the tests check shapes and the traceability rules, not exact names.
"""

import io
import re
import time

import httpx
import pytest
from docx import Document
from pptx import Presentation

from navigator.settings import REPO_ROOT

pytestmark = pytest.mark.integration

GLUCORA_PDF = REPO_ROOT / "docs" / "examples" / "glucora-business-model.pdf"
QUERY = "continuous glucose monitoring"
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
ANALYSIS_TIMEOUT = 600  # seconds; the frontend polls the same way


def cited(text: str) -> set[int]:
    return {int(i) for group in CITATION.findall(text) for i in group.split(",")}


def assert_traceable(db, results: list[dict]) -> None:
    """Every evidence row is a shown claim with its stored quote and page; every citation in `why` is on the card."""
    for r in results:
        assert r["evidence"], f"{r['name']} has no evidence"
        for e in r["evidence"]:
            row = db.execute(
                "SELECT c.quote, p.url, c.verified, c.judge_verdict FROM claim c JOIN page p ON p.id = c.page_id "
                "WHERE c.id = %s", (e["claim_id"],),
            ).fetchone()
            assert row is not None, f"claim {e['claim_id']} does not exist"
            assert row[:2] == (e["quote"], e["url"])
            assert row[2] is True and row[3] != "unsupported"
        assert cited(r["why"]) <= {e["claim_id"] for e in r["evidence"]}, f"{r['name']}: why cites another card"


# --- Infra ---

def test_token_is_required(stack):
    url = f"{stack.api.base_url}/api/stats"
    assert httpx.get(url).status_code == 401
    assert httpx.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_frontend_serves_the_app_and_proxies_with_the_token(stack):
    assert '<div id="app">' in httpx.get(stack.ui).text
    # No Authorization header from the browser: the Vite proxy adds BACKEND_TOKEN
    assert httpx.get(f"{stack.ui}/api/stats", timeout=30).status_code == 200


def test_openapi_lists_every_route_the_ui_calls(api):
    paths = api.get("/openapi.json").json()["paths"]
    for path in ["/api/search", "/api/chat", "/api/feedback", "/api/stats", "/api/sources", "/api/sources/{source_id}",
                 "/api/cases", "/api/cases/{case_id}", "/api/cases/{case_id}/references",
                 "/api/cases/{case_id}/pitch"]:
        assert path in paths


# --- Read routes on the checkpoint ---

def test_stats_match_the_checkpoint(api, db):
    body = api.get("/api/stats").json()
    pages = dict(db.execute("SELECT source_id, count(*) FROM page GROUP BY source_id").fetchall())
    assert {s["source"]: s["pages"] for s in body["sources"] if s["pages"]} == pages
    assert sum(s["shown_claims"] for s in body["sources"]) > 0


def test_sources(api):
    sources = api.get("/api/sources").json()
    assert sources and any(s["validated"] for s in sources)
    one = sources[0]
    assert api.get(f"/api/sources/{one['id']}").json()["pages"] == one["pages"]
    assert api.get("/api/sources/no-such-source").status_code == 404


def test_search_is_traceable(api, db):
    body = api.get("/api/search", params={"q": QUERY}).json()
    assert not body["no_result"] and 0 < len(body["results"]) <= 10
    assert body["expansion"] is None or body["expansion"]["en"] or body["expansion"]["de"]
    assert_traceable(db, body["results"])
    units = api.get("/api/search", params={"q": QUERY, "type": "unit"}).json()["results"]
    assert units and {r["type"] for r in units} == {"unit"}


def test_search_without_a_match_says_so(api):
    body = api.get("/api/search", params={"q": "xqzvw jjkqp"}).json()
    assert body["no_result"] is True and body["results"] == []


# --- Chat and feedback ---

def test_chat_refines_with_filters(api, db):
    first = api.post("/api/chat", json={"session_id": "it-chat", "message": QUERY}).json()
    # The agent (#97) writes its own one-sentence reply; any claim it cites must be on the cards shown (plan 8.10)
    assert first["results"] and first["reply"].strip()
    assert cited(first["reply"]) <= {e["claim_id"] for r in first["results"] for e in r["evidence"]}
    assert_traceable(db, first["results"])
    rerun = api.post("/api/chat", json={
        "session_id": "it-chat", "message": "", "filters": {"source": None, "type": "person"},
    }).json()
    assert rerun["filters"] == {"source": None, "type": "person"}
    assert rerun["results"] and {r["type"] for r in rerun["results"]} == {"person"}
    assert_traceable(db, rerun["results"])


def test_feedback_is_counted(api):
    entity = api.get("/api/search", params={"q": QUERY}).json()["results"][0]["entity_id"]
    before = api.get("/api/stats").json()["feedback"]["up"]
    response = api.post("/api/feedback", json={"session_id": "it", "query": QUERY, "entity_id": entity, "rating": "up"})
    assert response.json() == {"ok": True}
    assert api.get("/api/stats").json()["feedback"]["up"] == before + 1


# --- The case flow of the board: upload → analysis → references → chat → status → pitch → restart ---

def test_upload_rejects_a_non_pdf(api):
    response = api.post("/api/cases", files={"file": ("notes.pdf", b"just text", "application/pdf")})
    assert response.status_code == 422


def test_case_flow(stack, api, db):
    with GLUCORA_PDF.open("rb") as f:
        case = api.post("/api/cases", files={"file": (GLUCORA_PDF.name, f, "application/pdf")}).json()
    assert case["analysis_status"] == "pending" and case["status"] == "new"
    case_id = case["id"]
    assert api.get("/api/cases").json()[0]["id"] == case_id  # newest first

    deadline = time.monotonic() + ANALYSIS_TIMEOUT
    while case["analysis_status"] == "pending":
        assert time.monotonic() < deadline, "analysis still pending"
        time.sleep(2)
        case = api.get(f"/api/cases/{case_id}").json()
    assert case["analysis_status"] == "done", case
    assert 0 <= case["score"] <= 100 and case["score_breakdown"]
    assert all(0 <= row["score"] <= 100 and row["criterion"] for row in case["score_breakdown"])

    refs = api.get(f"/api/cases/{case_id}/references", params={"limit": 25}).json()
    assert 0 < len(refs) <= 25
    assert_traceable(db, refs)

    chat = api.post("/api/chat", json={"session_id": f"case-{case_id}", "message": "insulin pump"}).json()
    assert chat["results"] and chat["reply"].strip()  # the agent writes its own reply (#97)

    for status in ["in_review", "accepted"]:
        assert api.patch(f"/api/cases/{case_id}", json={"status": status}).json()["status"] == status
    assert api.patch(f"/api/cases/{case_id}", json={"status": "archived"}).status_code == 422

    selected = refs[:3]
    pitch = api.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": [r["entity_id"] for r in selected]}).json()
    assert pitch["text"].strip()
    assert cited(pitch["text"]) <= {e["claim_id"] for r in selected for e in r["evidence"]}, "pitch cites other facts"
    assert api.get(f"/api/cases/{case_id}/pitch").json() == pitch
    assert api.post(f"/api/cases/{case_id}/pitch", json={"entity_ids": [-1]}).status_code == 404

    # Partner report and slides (#96), from the stored selection, in the background
    assert api.put(f"/api/cases/{case_id}/selection", json={"entity_ids": [r["entity_id"] for r in selected]}).is_success
    docs = api.post(f"/api/cases/{case_id}/documents").json()
    deadline = time.monotonic() + ANALYSIS_TIMEOUT
    while docs["status"] == "pending":
        assert time.monotonic() < deadline, "documents still pending"
        time.sleep(2)
        docs = api.get(f"/api/cases/{case_id}/documents").json()
    assert docs["status"] == "done", docs
    report = Document(io.BytesIO(api.get(f"/api/cases/{case_id}/documents/report").content))
    text = "\n".join(p.text for p in report.paragraphs)
    assert all(r["name"] in text for r in selected) and "5. Sources" in text
    links = {r.target_ref for r in report.part.rels.values() if r.is_external}
    assert {e["url"] for r in selected for e in r["evidence"]} >= links and links
    slides = Presentation(io.BytesIO(api.get(f"/api/cases/{case_id}/documents/slides").content))
    assert len(slides.slides) >= 6 + len(selected)

    # The case survives an API restart (#52): it is in Postgres, not in memory
    stack.compose("restart", "app")
    stack.compose("up", "-d", "--wait", "--wait-timeout", "600", "app")
    again = api.get(f"/api/cases/{case_id}").json()
    assert (again["status"], again["score"]) == ("accepted", case["score"])
    assert api.get(f"/api/cases/{case_id}/pitch").json()["text"] == pitch["text"]


def test_unknown_case_is_404(api):
    for response in [api.get("/api/cases/nope"), api.get("/api/cases/nope/references"),
                     api.patch("/api/cases/nope", json={"status": "new"})]:
        assert response.status_code == 404
