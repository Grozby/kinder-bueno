"""Cases: business model PDFs uploaded on the board (docs/FRONTEND_API.md "Cases", #52).

The PDF is company data: only its text is stored, and it is only sent to the Apertus gateway (#53)."""

import io
import uuid
from pathlib import Path

import psycopg
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from navigator.models import Case, CaseStatus, ScoreItem

MAX_PDF_BYTES = 10 * 1024 * 1024

COLUMNS = (
    "id, company_name, file_name, uploaded_at, status, analysis_status, industry, score, score_breakdown, summary"
)


class PdfError(ValueError):
    """The upload is not a PDF we can read text from."""


def pdf_text(data: bytes) -> str:
    """Text of every page, pages separated by blank lines."""
    if not data.startswith(b"%PDF-"):
        raise PdfError("Not a PDF file")
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except (PdfReadError, ValueError, KeyError) as exc:
        raise PdfError(f"Unreadable PDF: {exc}") from exc
    if not text:
        raise PdfError("The PDF has no text (a scanned document?)")
    return text


def name_from_file(file_name: str) -> str:
    """'glucora-business-model.pdf' -> 'Glucora Business Model'. A placeholder until the analysis (#53)."""
    name = Path(file_name).name
    stem = (name[:-4] if name.lower().endswith(".pdf") else name).replace("_", " ").replace("-", " ")
    return " ".join(w[:1].upper() + w[1:] for w in stem.split()) or "Unnamed company"


def _case(row: tuple) -> Case:
    cid, company, file_name, uploaded, status, analysis, industry, score, breakdown, summary = row
    return Case(
        id=cid, company_name=company, file_name=file_name, uploaded_at=uploaded, status=status,
        analysis_status=analysis, industry=industry, score=score,
        score_breakdown=[ScoreItem(**b) for b in breakdown], summary=summary,
    )


def create_case(conn: psycopg.Connection, file_name: str, text: str) -> Case:
    row = conn.execute(
        f'INSERT INTO "case" (id, company_name, file_name, pdf_text) VALUES (%s, %s, %s, %s) RETURNING {COLUMNS}',
        (str(uuid.uuid4()), name_from_file(file_name), file_name, text),
    ).fetchone()
    return _case(row)


def list_cases(conn: psycopg.Connection) -> list[Case]:
    """Newest first."""
    return [_case(r) for r in conn.execute(f'SELECT {COLUMNS} FROM "case" ORDER BY uploaded_at DESC, id')]


def get_case(conn: psycopg.Connection, case_id: str) -> Case | None:
    row = conn.execute(f'SELECT {COLUMNS} FROM "case" WHERE id = %s', (case_id,)).fetchone()
    return _case(row) if row else None


def set_status(conn: psycopg.Connection, case_id: str, status: CaseStatus) -> Case | None:
    row = conn.execute(
        f'UPDATE "case" SET status = %s WHERE id = %s RETURNING {COLUMNS}', (status, case_id)
    ).fetchone()
    return _case(row) if row else None

