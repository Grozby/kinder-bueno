"""The case board: cases, references, selection, review, notes, pitch and documents."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import Response

from navigator.api.deps import Analyze, Conn, MakeDocuments, WritePitch
from navigator.cases import analysis, documents, pitch, state, store
from navigator.models import (
    AddReference,
    Case,
    CaseChatTurn,
    CaseDocuments,
    CaseFeedback,
    CaseNote,
    CaseStatusUpdate,
    DocumentKind,
    NoteInput,
    Pitch,
    PitchRequest,
    Result,
    ReviewInput,
    Selection,
)
from navigator.search.results import build_results

router = APIRouter()


@router.post("/api/cases")
def upload_case(conn: Conn, analyze: Analyze, background: BackgroundTasks, file: UploadFile) -> Case:
    """Store a business model PDF's text and return the case at once; the analysis runs in the background."""
    data = file.file.read(store.MAX_PDF_BYTES + 1)
    if len(data) > store.MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF larger than 10 MB")
    try:
        text = store.pdf_text(data)
    except store.PdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    case = store.create_case(conn, file.filename or "upload.pdf", text)
    conn.commit()  # the background analysis reads it on another connection
    background.add_task(analyze, case.id)
    return case


@router.get("/api/cases")
def list_cases(conn: Conn) -> list[Case]:
    """Newest first."""
    return store.list_cases(conn)


@router.get("/api/cases/{case_id}")
def get_case(conn: Conn, case_id: str) -> Case:
    case = store.get_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/api/cases/{case_id}/references")
def case_references(conn: Conn, case_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 25) -> list[Result]:
    """The case's references, best first; empty until the analysis is done."""
    found = analysis.references(conn, case_id, limit)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@router.post("/api/cases/{case_id}/references")
def add_case_reference(conn: Conn, case_id: str, body: AddReference) -> Result:
    """Add a chat result to the case's references (#81); it then comes after the top 25, marked `added`."""
    if store.get_case(conn, case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    added = state.add_reference(conn, case_id, body.entity_id)
    if added is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return added


@router.delete("/api/cases/{case_id}/references/{entity_id}")
def remove_case_reference(conn: Conn, case_id: str, entity_id: int) -> Selection:
    """Remove a chat-added reference; it is also deselected. Returns the selection."""
    if not state.remove_reference(conn, case_id, entity_id):
        raise HTTPException(status_code=404, detail="No such added reference")
    return Selection(entity_ids=state.get_selection(conn, case_id) or [])


@router.get("/api/cases/{case_id}/selection")
def get_selection(conn: Conn, case_id: str) -> Selection:
    """The references chosen for the pitch (#81); the first 10 until the user changes it."""
    found = state.get_selection(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return Selection(entity_ids=found)


@router.put("/api/cases/{case_id}/selection")
def set_selection(conn: Conn, case_id: str, body: Selection) -> Selection:
    if unknown := pitch.unknown_entities(conn, body.entity_ids):
        raise HTTPException(status_code=404, detail=f"Unknown entity ids: {unknown}")
    found = state.set_selection(conn, case_id, body.entity_ids)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return Selection(entity_ids=found)


@router.get("/api/cases/{case_id}/chat")
def case_chat(conn: Conn, case_id: str) -> list[CaseChatTurn]:
    """The chat turns of the case's session `case-<id>`, oldest first (#81)."""
    turns = state.chat_history(conn, case_id)
    if turns is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return turns


@router.get("/api/cases/{case_id}/feedback")
def case_feedback(conn: Conn, case_id: str) -> CaseFeedback:
    """The 👍/👎 and flagged facts given in the case's session (#81)."""
    found = state.feedback(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@router.delete("/api/cases/{case_id}")
def delete_case(conn: Conn, case_id: str) -> dict[str, bool]:
    """Delete the case and everything stored for it (#134): PDF text, analysis, notes, documents, its chat and
    feedback. Cannot be undone; snapshots taken before keep it."""
    if not state.delete_case(conn, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return {"ok": True}


@router.patch("/api/cases/{case_id}")
def update_case(conn: Conn, case_id: str, body: CaseStatusUpdate) -> Case:
    """Move the case to another board column."""
    case = store.set_status(conn, case_id, body.status)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.put("/api/cases/{case_id}/review")
def set_review(conn: Conn, case_id: str, body: ReviewInput) -> Case:
    """The reviewer's own score (#108), clamped to 0-100, next to the AI score. `reason` is required."""
    case = store.set_review(conn, case_id, body)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.delete("/api/cases/{case_id}/review")
def clear_review(conn: Conn, case_id: str) -> Case:
    case = store.set_review(conn, case_id, None)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/api/cases/{case_id}/notes")
def list_notes(conn: Conn, case_id: str) -> list[CaseNote]:
    """Internal notes (#108), oldest first. They never reach the pitch, the documents or an LLM prompt."""
    notes = store.list_notes(conn, case_id)
    if notes is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return notes


@router.post("/api/cases/{case_id}/notes")
def add_note(conn: Conn, case_id: str, body: NoteInput) -> CaseNote:
    note = store.add_note(conn, case_id, body)
    if note is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return note


@router.delete("/api/cases/{case_id}/notes/{note_id}")
def delete_note(conn: Conn, case_id: str, note_id: str) -> dict[str, bool]:
    if not store.delete_note(conn, case_id, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}


@router.post("/api/cases/{case_id}/pitch")
def generate_pitch(conn: Conn, write: WritePitch, case_id: str, body: PitchRequest) -> Pitch:
    """A sales pitch from the selected references only; every sentence about one cites its claims. Stored on the case."""
    context = pitch.case_context(conn, case_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Case not found")
    entity_ids = list(dict.fromkeys(body.entity_ids))
    if unknown := pitch.unknown_entities(conn, entity_ids):
        raise HTTPException(status_code=404, detail=f"Unknown entity ids: {unknown}")
    results = build_results(conn, [(i, 0.0) for i in entity_ids])
    return pitch.save_pitch(conn, case_id, write(context, results), entity_ids)


@router.get("/api/cases/{case_id}/pitch")
def get_pitch(conn: Conn, case_id: str) -> Pitch:
    """The last pitch generated for the case; 404 if the case does not exist or has none yet."""
    if pitch.case_context(conn, case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    stored = pitch.load_pitch(conn, case_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No pitch yet")
    return stored


@router.post("/api/cases/{case_id}/documents")
def generate_documents(conn: Conn, make: MakeDocuments, background: BackgroundTasks, case_id: str) -> CaseDocuments:
    """Start the partner report (.docx) and slides (.pptx) from the case's selected references, in the background.
    Only for accepted cases. While a job runs, returns it instead of starting another; poll GET .../documents."""
    case = store.get_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "accepted":
        raise HTTPException(status_code=409, detail="Accept the case first")
    current = documents.status(conn, case_id)
    if current and current.status == "pending":
        return current
    selection = state.get_selection(conn, case_id) or []
    if not selection:
        raise HTTPException(status_code=422, detail="Select at least one reference")
    job = documents.start(conn, case_id, selection)
    conn.commit()  # the background job reads it on another connection
    background.add_task(make, case_id)
    return job


@router.get("/api/cases/{case_id}/documents")
def documents_status(conn: Conn, case_id: str) -> CaseDocuments:
    """The state of the documents job: none, pending, done or failed."""
    found = documents.status(conn, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return found


@router.get("/api/cases/{case_id}/documents/{kind}", response_class=Response,
         responses={200: {"content": {t: {} for t in documents.MEDIA_TYPES.values()}}})
def download_document(conn: Conn, case_id: str, kind: DocumentKind) -> Response:
    """The stored report (.docx) or slides (.pptx), as generated; 404 if not generated yet."""
    found = documents.load(conn, case_id, kind)
    if found is None:
        raise HTTPException(status_code=404, detail="Not generated yet")
    content, name = found
    return Response(content, media_type=documents.MEDIA_TYPES[kind],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
