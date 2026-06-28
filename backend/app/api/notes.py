from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from urllib.parse import quote
from app.core.database import get_db
from app.core.auth import get_current_user
from app.api.schemas import NoteResponse, NoteUpdate
from app.models import Note, Session as DBSession, User
from app.services.session_service import get_user_session as _get_session_by_user
from app.services.state_service import get_state, set_stale
from app.services.vector_service import _compute_session_content_hash
from app.services.note_utils import _extract_transcript_from_content, get_canonical_transcript_text
from app.services.pdf_export_service import build_transcript_pdf

router = APIRouter(prefix="/api/notes", tags=["notes"])

_TRANSCRIPT_MARKER = "## 语音转文字"


def _sync_transcript_from_content(note: Note) -> None:
    """Sync transcript entries when the user edits the content markdown.

    Marks the previous authoritative entry as superseded and appends a
    ``user_edited`` entry preserving the original raw ASR text.
    """
    content = note.content or ""
    if not content.startswith(_TRANSCRIPT_MARKER):
        return

    extracted = _extract_transcript_from_content(content)
    entries = note.transcript if isinstance(note.transcript, list) else []

    # Find the latest authoritative entry.
    latest_idx = -1
    for i, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("correction_stage") in (
            "final",
            "local",
            "user_edited",
        ):
            latest_idx = i

    if latest_idx == -1:
        note.transcript = [
            {
                "chunk_index": 0,
                "text": extracted,
                "display_text": extracted,
                "raw_text": "",
                "timestamps": [],
                "correction_stage": "user_edited",
            }
        ]
        return

    latest = entries[latest_idx]
    latest_text = (latest.get("display_text") or latest.get("text") or "").strip()
    if latest_text == extracted:
        return

    new_entries = list(entries)
    stage = latest.get("correction_stage")
    raw_text = latest.get("raw_text", "") if isinstance(latest, dict) else ""
    chunk_index = latest.get("chunk_index", 0) if isinstance(latest, dict) else 0

    if stage in ("final", "local"):
        superseded = dict(latest)
        superseded["correction_stage"] = "superseded"
        new_entries[latest_idx] = superseded

    new_entries.append(
        {
            "chunk_index": chunk_index,
            "text": extracted,
            "display_text": extracted,
            "raw_text": raw_text,
            "timestamps": [],
            "correction_stage": "user_edited",
        }
    )
    note.transcript = new_entries


def _get_user_session(session_id: str, user: User, db: Session) -> DBSession:
    """Verify session exists and belongs to user."""
    session = _get_session_by_user(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def serialize_note(note: Note | None, session_id: str | None = None) -> dict:
    """Serialize a Note ORM object into a plain dict safe for FastAPI/JSON.

    - Filters out internal layout_blocks vocabulary items.
    - Normalizes None JSON columns to empty lists.
    """
    if note is None:
        now = datetime.now(timezone.utc)
        return {
            "id": session_id or "",
            "session_id": session_id or "",
            "content": "",
            "transcript": [],
            "ppt_images": [],
            "vocabulary": [],
            "layout_blocks": None,
            "annotations": None,
            "created_at": now,
        }

    vocabulary_raw = note.vocabulary if isinstance(note.vocabulary, list) else []
    layout_blocks = None
    vocabulary_items = []
    for item in vocabulary_raw:
        if isinstance(item, dict) and item.get("kind") == "layout_blocks":
            blocks = item.get("blocks")
            if isinstance(blocks, list):
                layout_blocks = blocks
        else:
            vocabulary_items.append(item)

    return {
        "id": note.id,
        "session_id": note.session_id,
        "content": note.content or "",
        "transcript": note.transcript if isinstance(note.transcript, list) else [],
        "ppt_images": note.ppt_images if isinstance(note.ppt_images, list) else [],
        "vocabulary": vocabulary_items,
        "layout_blocks": layout_blocks,
        "annotations": note.annotations if isinstance(note.annotations, dict) else None,
        "created_at": note.created_at or datetime.now(timezone.utc),
    }


@router.get("/session/{session_id}", response_model=NoteResponse)
def get_note_by_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_session(session_id, current_user, db)
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        # Auto-create an empty note so the frontend always has a stable record
        # to load and save into.
        note = Note(
            session_id=session_id,
            content="",
            transcript=[],
            ppt_images=[],
            vocabulary=[],
        )
        db.add(note)
        db.commit()
        db.refresh(note)
    return serialize_note(note, session_id)


@router.get("/session/{session_id}/export/pdf")
def export_session_transcript_pdf(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = _get_user_session(session_id, current_user, db)
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    transcript_text = get_canonical_transcript_text(note)
    if not transcript_text.strip():
        raise HTTPException(status_code=400, detail="没有可导出的转写内容")

    try:
        pdf_bytes, filename = build_transcript_pdf(
            title=session.title,
            notebook_title=session.notebook.title if session.notebook else "",
            duration=session.duration,
            transcript_text=transcript_text,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 导出失败：{e}") from e
    ascii_filename = "transcript.pdf"
    encoded_filename = quote(filename, safe="")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


def _mark_stale_if_changed(session_id: str, db: Session) -> None:
    """Mark derived outputs stale when note content changes."""
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        return
    current_hash = _compute_session_content_hash(note)
    for stage in ("vector_index", "summary", "mindmap", "quiz_bank"):
        state = get_state(db, session_id, stage)
        if state and state.status == "ready" and state.content_hash != current_hash:
            set_stale(db, session_id, stage, content_hash=current_hash)


@router.put("/session/{session_id}", response_model=NoteResponse)
def update_note(
    session_id: str,
    data: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_session(session_id, current_user, db)
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        note = Note(
            session_id=session_id,
            content=data.content or "",
            transcript=[],
            ppt_images=[],
            vocabulary=[],
        )
        db.add(note)
    else:
        note.content = data.content or ""
    update_payload = data.model_dump(exclude_unset=True)
    if data.layout_blocks is not None:
        note.layout_blocks = [b.model_dump() for b in data.layout_blocks]
    if 'annotations' in update_payload:
        note.annotations = data.annotations
    _sync_transcript_from_content(note)
    db.commit()
    db.refresh(note)
    _mark_stale_if_changed(session_id, db)
    return serialize_note(note, session_id)
