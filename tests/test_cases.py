"""Case routes (FRONTEND_API "Cases", #52) with TestClient. Needs Postgres."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from test_analysis import fake_embed_many, fake_read, fake_rerank, no_explain
from test_api import fake_embed

from navigator import analysis, cases
from navigator.api import app, get_analyze, get_conn
from navigator.settings import PROJECT_ROOT

GLUCORA = PROJECT_ROOT / "docs" / "examples" / "glucora-business-model.pdf"


@pytest.fixture
def client(test_conn):
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_analyze] = lambda: lambda case_id: analysis.analyze(
        test_conn, case_id, read=fake_read, embed=fake_embed, embed_many=fake_embed_many, rerank=fake_rerank,
        explain=no_explain)
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, data: bytes, name: str = "glucora-business-model.pdf"):
    return client.post("/api/cases", files={"file": (name, data, "application/pdf")})


def blank_pdf() -> bytes:
    writer, out = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=200, height=200)
    writer.write(out)
    return out.getvalue()


def test_upload_returns_pending_then_analysis_finishes(client, test_conn, graph):
    res = upload(client, GLUCORA.read_bytes())
    assert res.status_code == 200
    case = res.json()
    assert case["analysis_status"] == "pending"  # returned before the background step
    assert case["company_name"] == "Glucora Business Model"
    assert case["status"] == "new"
    assert case["score"] is None and case["score_breakdown"] == []
    assert "Glucora" in test_conn.execute('SELECT pdf_text FROM "case"').fetchone()[0]  # text only, no file

    stored = client.get(f"/api/cases/{case['id']}").json()
    assert stored["analysis_status"] == "done"  # TestClient runs background tasks after the response
    assert stored["file_name"] == "glucora-business-model.pdf"
    assert stored["company_name"] == "Glucora Health"  # read by the analysis
    assert len(stored["score_breakdown"]) == 5

    refs = client.get(f"/api/cases/{case['id']}/references", params={"limit": 2}).json()
    assert len(refs) == 2 and refs[0]["why"].startswith("Matches '")


def test_references_unknown_case(client):
    assert client.get("/api/cases/nope/references").status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [(b"hello, not a pdf", 422), (b"%PDF-1.7 broken", 422), (blank_pdf(), 422), (b"%PDF-" + b"x" * cases.MAX_PDF_BYTES, 413)],
)
def test_upload_rejected(client, test_conn, data, status):
    assert upload(client, data).status_code == status
    assert test_conn.execute('SELECT count(*) FROM "case"').fetchone()[0] == 0


def test_list_newest_first(client, test_conn):
    first = upload(client, GLUCORA.read_bytes(), "first.pdf").json()
    second = upload(client, GLUCORA.read_bytes(), "second.pdf").json()
    test_conn.execute("""UPDATE "case" SET uploaded_at = now() - interval '1 day' WHERE id = %s""", (first["id"],))
    assert [c["id"] for c in client.get("/api/cases").json()] == [second["id"], first["id"]]


def test_get_unknown(client):
    assert client.get("/api/cases/nope").status_code == 404


def test_patch_status(client):
    case = upload(client, GLUCORA.read_bytes()).json()
    res = client.patch(f"/api/cases/{case['id']}", json={"status": "in_review"})
    assert res.status_code == 200 and res.json()["status"] == "in_review"
    assert client.get(f"/api/cases/{case['id']}").json()["status"] == "in_review"
    assert client.patch(f"/api/cases/{case['id']}", json={"status": "archived"}).status_code == 422
    assert client.patch("/api/cases/nope", json={"status": "accepted"}).status_code == 404


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [("glucora-business-model.pdf", "Glucora Business Model"), ("acme_AG.pdf", "Acme AG"), (".pdf", "Unnamed company")],
)
def test_name_from_file(file_name, expected):
    assert cases.name_from_file(file_name) == expected
