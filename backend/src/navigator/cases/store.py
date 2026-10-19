"""Cases: business model PDFs uploaded on the board (docs/FRONTEND_API.md "Cases", #52).

The PDF is company data: only its text is stored, and it is only sent to the Apertus gateway (#53)."""

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from navigator.models import (
    Case,
    CaseNote,
    CaseStatus,
    NoteInput,
    Review,
    ReviewInput,
    ScoreItem,
    SimilarCase,
)

MAX_PDF_BYTES = 10 * 1024 * 1024

COLUMNS = (
    "id, company_name, file_name, uploaded_at, status, analysis_status, industry, score, score_breakdown, summary, "
    'review, (SELECT count(*) FROM case_note n WHERE n.case_id = "case".id)'
)
MIN_SIMILARITY = 0.6  # cosine of the summary + needs embeddings (#108)
MAX_SIMILAR = 3
# Earlier cases close to each of the given ones: same company (name without legal form) or same PDF text, or
# a similar profile. Duplicates first, then by similarity.
SIMILAR = r"""
WITH c AS (
  SELECT id, uploaded_at, company_name, status, score, review, profile, needs, refs, md5(pdf_text) AS pdf_hash,
         regexp_replace(lower(company_name), '\m(ag|gmbh|sa|sarl|ltd|inc|llc)\M|[^[:alnum:]]+', '', 'g') AS name_key
  FROM "case"
), pairs AS (
  SELECT a.id AS case_id, b.id, b.company_name, b.status, b.score, b.review,
         coalesce(1 - (a.profile <=> b.profile), 0) AS similarity,
         (a.name_key <> '' AND a.name_key = b.name_key) OR a.pdf_hash = b.pdf_hash AS duplicate,
         a.needs AS needs_a, b.needs AS needs_b, a.refs AS refs_a, b.refs AS refs_b
  FROM c a JOIN c b ON b.uploaded_at < a.uploaded_at
  WHERE a.id = ANY(%s)
)
SELECT * FROM pairs WHERE duplicate OR similarity >= %s ORDER BY case_id, duplicate DESC, similarity DESC
"""


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
    cid, company, file_name, uploaded, status, analysis, industry, score, breakdown, summary, review, notes = row
    return Case(
        id=cid, company_name=company, file_name=file_name, uploaded_at=uploaded, status=status,
        analysis_status=analysis, industry=industry, score=score,
        score_breakdown=[ScoreItem(**b) for b in breakdown], summary=summary,
        review=Review(**review) if review else None, notes_count=notes,
    )


def _norm(need: str) -> str:
    return " ".join(str(need).lower().split())


def similar_cases(conn: psycopg.Connection, case_ids: list[str]) -> dict[str, list[SimilarCase]]:
    """Up to 3 earlier cases per case (#108), duplicates first. Computed when read, so status and review are current."""
    found: dict[str, list[SimilarCase]] = {}
    for of, cid, company, status, score, review, sim, dup, needs_a, needs_b, refs_a, refs_b in conn.execute(
        SIMILAR, (case_ids, MIN_SIMILARITY)
    ):
        if len(found.setdefault(of, [])) == MAX_SIMILAR:
            continue
        other_needs = {_norm(n) for n in needs_b}
        found[of].append(SimilarCase(
            case_id=cid, company_name=company, status=status, score=score,
            review=Review(**review) if review else None,
            similarity=round(min(max(sim, 0.0), 1.0), 3), duplicate=dup,
            shared_needs=[str(n) for n in needs_a if _norm(n) in other_needs],
            shared_references=len({r["entity_id"] for r in refs_a} & {r["entity_id"] for r in refs_b}),
        ))
    return found


def _cases(conn: psycopg.Connection, rows: list[tuple]) -> list[Case]:
    cases = [_case(r) for r in rows]
    similar = similar_cases(conn, [c.id for c in cases]) if cases else {}
    return [c.model_copy(update={"similar_cases": similar.get(c.id, [])}) for c in cases]


def _one(conn: psycopg.Connection, row: tuple | None) -> Case | None:
    return _cases(conn, [row])[0] if row else None


def create_case(conn: psycopg.Connection, file_name: str, text: str) -> Case:
    row = conn.execute(
        f'INSERT INTO "case" (id, company_name, file_name, pdf_text) VALUES (%s, %s, %s, %s) RETURNING {COLUMNS}',
        (str(uuid.uuid4()), name_from_file(file_name), file_name, text),
    ).fetchone()
    return _one(conn, row)


def list_cases(conn: psycopg.Connection) -> list[Case]:
    """Newest first."""
    return _cases(conn, conn.execute(f'SELECT {COLUMNS} FROM "case" ORDER BY uploaded_at DESC, id').fetchall())


def get_case(conn: psycopg.Connection, case_id: str) -> Case | None:
    return _one(conn, conn.execute(f'SELECT {COLUMNS} FROM "case" WHERE id = %s', (case_id,)).fetchone())


def set_status(conn: psycopg.Connection, case_id: str, status: CaseStatus) -> Case | None:
    row = conn.execute(
        f'UPDATE "case" SET status = %s WHERE id = %s RETURNING {COLUMNS}', (status, case_id)
    ).fetchone()
    return _one(conn, row)


def set_review(conn: psycopg.Connection, case_id: str, review: ReviewInput | None) -> Case | None:
    """The reviewer's score (clamped to 0-100) and reason, or None to clear it. None if no such case."""
    stored = None
    if review is not None:
        stored = Jsonb(Review(
            score=min(100, max(0, round(review.score))), reason=review.reason, author=review.author,
            reviewed_at=datetime.now(UTC),
        ).model_dump(mode="json"))
    row = conn.execute(
        f'UPDATE "case" SET review = %s WHERE id = %s RETURNING {COLUMNS}', (stored, case_id)
    ).fetchone()
    return _one(conn, row)


def _exists(conn: psycopg.Connection, case_id: str) -> bool:
    return conn.execute('SELECT 1 FROM "case" WHERE id = %s', (case_id,)).fetchone() is not None


def list_notes(conn: psycopg.Connection, case_id: str) -> list[CaseNote] | None:
    """Oldest first; None if no such case. Notes are internal: no pitch, document or LLM prompt reads them."""
    if not _exists(conn, case_id):
        return None
    rows = conn.execute(
        "SELECT id, author, text, created_at FROM case_note WHERE case_id = %s ORDER BY id", (case_id,)
    )
    return [CaseNote(id=str(i), author=a, text=t, created_at=at) for i, a, t, at in rows]


def add_note(conn: psycopg.Connection, case_id: str, note: NoteInput) -> CaseNote | None:
    if not _exists(conn, case_id):
        return None
    i, at = conn.execute(
        "INSERT INTO case_note (case_id, author, text) VALUES (%s, %s, %s) RETURNING id, created_at",
        (case_id, note.author, note.text),
    ).fetchone()
    return CaseNote(id=str(i), author=note.author, text=note.text, created_at=at)


def delete_note(conn: psycopg.Connection, case_id: str, note_id: str) -> bool:
    if not note_id.isdigit() or len(note_id) > 18:  # not a bigint id
        return False
    return conn.execute(
        "DELETE FROM case_note WHERE case_id = %s AND id = %s", (case_id, int(note_id))
    ).rowcount == 1

