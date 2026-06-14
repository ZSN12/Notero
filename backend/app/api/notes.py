from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.auth import get_current_user
from app.api.schemas import NoteResponse, NoteUpdate
from app.models import Note, Session as DBSession, Notebook, User
from app.services.state_service import get_state, set_stale
from app.services.vector_service import _compute_session_content_hash
from app.services.note_utils import (
    _extract_transcript_from_content,
    _latest_authoritative_transcript_entry,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])

_TRANSCRIPT_MARKER = "## 语音转文字"


def _sync_transcript_from_content(note: Note) -> None:
    """Sync note.transcript with the transcript area of note.content.

    When the user edits the visible transcript in the editor, create or update
    a 'user_edited' transcript entry so that later ASR chunks and finalization
    do not restore text the user has deleted.
    """
    if not isinstance(note.transcript, list):
        note.transcript = []

    content = note.content or ""
    if not content.startswith(_TRANSCRIPT_MARKER):
        return

    edited_text = _extract_transcript_from_content(content)

    # Find the best raw_text donor among existing entries for audit.
    existing_raw_text = ""
    for entry in note.transcript:
        if isinstance(entry, dict) and not existing_raw_text:
            existing_raw_text = entry.get("raw_text") or entry.get("text") or ""

    # Compute current canonical text from the latest authoritative entry. We
    # check key membership so an intentionally empty user edit ("") is not
    # compared against the older raw_text fallback.
    latest = _latest_authoritative_transcript_entry(note.transcript)
    current_text = ""
    if latest is not None:
        for key in ("display_text", "corrected_text", "text"):
            if key in latest:
                current_text = str(latest[key] or "").strip()
                break
        else:
            current_text = str(latest.get("raw_text") or "").strip()

    if edited_text == current_text:
        return

    # Mark every prior authoritative entry as superseded so that canonical
    # readers never join an older version with this new user edit.
    for entry in note.transcript:
        if isinstance(entry, dict) and entry.get("correction_stage") in ("final", "local", "user_edited"):
            entry["correction_stage"] = "superseded"

    note.transcript.append({
        "chunk_index": 0,
        "text": edited_text,
        "display_text": edited_text,
        "raw_text": existing_raw_text,
        "timestamps": [],
        "correction_stage": "user_edited",
    })


def _get_user_session(session_id: str, user: User, db: Session) -> DBSession:
    """Verify session exists and belongs to user."""
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(Notebook.user_id == user.id).first()
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


def _mark_stale_if_changed(session_id: str, db: Session) -> None:
    """Mark derived outputs stale when note content changes."""
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        return
    current_hash = _compute_session_content_hash(note)
    for stage in ("vector_index", "mindmap", "quiz_bank"):
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
    if data.layout_blocks is not None:
        note.layout_blocks = [b.model_dump() for b in data.layout_blocks]
    _sync_transcript_from_content(note)
    db.commit()
    db.refresh(note)
    _mark_stale_if_changed(session_id, db)
    return serialize_note(note, session_id)
