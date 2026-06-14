import json
import threading

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Note, Session as DBSession, Notebook, User, SessionProcessingState
from app.services.term_corrector import corrector
from app.services.state_service import set_running, set_ready, set_error, set_fallback
from app.services.vector_service import build_session_index, _compute_session_content_hash
from app.services.note_utils import _dedupe_append
from app.api.agents import auto_run_agents

router = APIRouter()

_TRANSCRIPT_MARKER = "## 语音转文字"
_NOTES_MARKER = "\n\n---\n\n"


def _extract_transcript_from_content(content: str | None) -> str:
    """Extract the transcript section from note.content (below marker, above notes)."""
    content = (content or "").strip()
    if not content.startswith(_TRANSCRIPT_MARKER):
        return ""
    body = content[len(_TRANSCRIPT_MARKER):]
    body = body.lstrip()
    if body.startswith("\n\n"):
        body = body[2:]
    if _NOTES_MARKER in body:
        body = body.split(_NOTES_MARKER, 1)[0]
    return body.strip()


def _strip_html(value: str | None) -> str:
    """Remove HTML tags and decode entities."""
    import html
    import re
    text = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(text).strip()


def _normalize_ws(value: str | None) -> str:
    """Collapse whitespace for comparison."""
    import re
    return re.sub(r"\s+", " ", (value or "")).strip()


# Per-session lock to prevent concurrent finalizations for the same session.
_FINALIZE_LOCKS: dict[str, threading.Lock] = {}
_FINALIZE_LOCKS_GUARD = threading.Lock()


def _get_finalize_lock(session_id: str) -> threading.Lock:
    lock = _FINALIZE_LOCKS.get(session_id)
    if lock is None:
        with _FINALIZE_LOCKS_GUARD:
            lock = _FINALIZE_LOCKS.get(session_id)
            if lock is None:
                lock = threading.Lock()
                _FINALIZE_LOCKS[session_id] = lock
    return lock


def get_transcript_text(note) -> str:
    """Extract full transcript text from a note.

    Tries note.content first (manual notes), falls back to transcript array (streaming ASR).
    """
    if note.content and note.content.strip():
        return note.content
    if note.transcript:
        texts = []
        for seg in note.transcript:
            if isinstance(seg, dict):
                # Use corrected text if available, otherwise use original
                text = seg.get("text", "")
            else:
                text = str(seg)
            if text:
                texts.append(text)
        return " ".join(texts)
    return ""


@router.put("/transcript")
def update_transcript(
    session_id: str = "",
    content: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the transcript text of a session."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Parse the content as JSON array of transcript entries
    try:
        transcript_data = json.loads(content) if content else note.transcript
    except (json.JSONDecodeError, TypeError):
        transcript_data = note.transcript

    note.transcript = transcript_data
    db.commit()

    return {"status": "success"}


def _auto_build_vector_index_sync(session_id: str, user: User, db: Session) -> None:
    """Auto-trigger vector index build after transcript finalization."""
    try:
        set_running(db, session_id, "vector_index", commit=False)
        db.commit()
        chunk_count = build_session_index(session_id, user, db)
        note = db.query(Note).filter(Note.session_id == session_id).first()
        current_hash = _compute_session_content_hash(note) if note else ""
        set_ready(db, session_id, "vector_index", content_hash=current_hash, commit=False)
        db.commit()
    except Exception as e:
        set_error(db, session_id, "vector_index", error_message=str(e), commit=False)
        db.commit()


def finalize_session_transcript(
    session_id: str,
    db: Session,
    current_user: User,
) -> dict:
    """Run DeepSeek finalization on a session's transcript and return note payload.

    This is the shared finalization logic used by:
      - the manual "restructure" endpoint
      - the upload-based audio processing endpoints
      - the manual "transcript-finalize" endpoint after real-time recording stops
    """
    # Prevent concurrent finalizations for the same session.
    lock = _get_finalize_lock(session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Transcript finalization is already in progress")

    existing = db.query(SessionProcessingState).filter(
        SessionProcessingState.session_id == session_id,
        SessionProcessingState.stage == "transcript_finalize",
    ).first()
    if existing and existing.status == "running":
        lock.release()
        raise HTTPException(status_code=409, detail="Transcript finalization is already in progress")

    set_running(db, session_id, "transcript_finalize", commit=False)
    try:
        session = db.query(DBSession).filter(
            DBSession.id == session_id
        ).join(Notebook).filter(
            Notebook.user_id == current_user.id
        ).first()
        if not session:
            set_error(db, session_id, "transcript_finalize", error_message="Session not found")
            raise HTTPException(status_code=404, detail="Session not found")

        note = db.query(Note).filter(Note.session_id == session_id).first()
        if not note or not note.transcript:
            set_error(db, session_id, "transcript_finalize", error_message="No transcript available")
            raise HTTPException(status_code=400, detail="No transcript available")

        notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
        course_title = notebook.title if notebook else ""
        keywords = session.keywords or []

        # Sort entries by chunk_index for deterministic processing.
        sorted_entries = sorted(
            note.transcript,
            key=lambda e: e.get("chunk_index", 0) if isinstance(e, dict) else 0,
        )

        # If the user has edited the transcript, note.transcript contains a
        # 'user_edited' entry. Use the latest user_edited entry as the baseline
        # and append any ASR entries that came after it (by sort order). This
        # preserves user deletions while still incorporating new speech recorded
        # after the edit.
        latest_user_edited_idx = -1
        for i, e in enumerate(sorted_entries):
            if isinstance(e, dict) and e.get("correction_stage") == "user_edited":
                latest_user_edited_idx = i

        used_user_edit = False
        if latest_user_edited_idx >= 0:
            baseline_entry = sorted_entries[latest_user_edited_idx]
            baseline_text = (baseline_entry.get("display_text") or baseline_entry.get("text") or "").strip()

            post_texts = []
            post_raw_texts = []
            for e in sorted_entries[latest_user_edited_idx + 1:]:
                if not isinstance(e, dict):
                    continue
                text = (e.get("display_text") or e.get("text") or e.get("raw_text") or "").strip()
                raw = (e.get("raw_text") or e.get("text") or "").strip()
                if text:
                    post_texts.append(text)
                if raw:
                    post_raw_texts.append(raw)

            full_local_text = baseline_text
            for text in post_texts:
                full_local_text = _dedupe_append(full_local_text, text)

            # Preserve the old raw_text from the user_edited entry (if any) plus
            # raw text from any subsequent ASR entries.
            baseline_raw = (baseline_entry.get("raw_text") or baseline_entry.get("text") or "").strip()
            raw_parts = ([baseline_raw] if baseline_raw else []) + post_raw_texts
            full_raw_text = "\n\n".join(t for t in raw_parts if t)
            used_user_edit = True
        else:
            local_texts = [
                (e.get("display_text") or e.get("text") or e.get("raw_text") or "").strip()
                for e in sorted_entries
                if isinstance(e, dict)
            ]
            full_local_text = "\n\n".join(t for t in local_texts if t)

            # Preserve original raw_text for audit
            raw_texts = [
                (e.get("raw_text") or e.get("text") or "").strip()
                for e in sorted_entries
                if isinstance(e, dict)
            ]
            full_raw_text = "\n\n".join(t for t in raw_texts if t)

        # If the transcript is empty because the user intentionally cleared it, we
        # still finalize to an empty transcript rather than raising an error or
        # restoring deleted ASR text.
        is_intentionally_empty = used_user_edit and not full_local_text
        if not full_local_text and not is_intentionally_empty:
            set_error(db, session_id, "transcript_finalize", error_message="Transcript text is empty")
            raise HTTPException(status_code=400, detail="Transcript text is empty")

        # Fallback: if content has a user-edited transcript that differs from the
        # computed ASR text, prefer the user's version.
        if not used_user_edit:
            user_edited_transcript = _extract_transcript_from_content(note.content)
            user_edited_plain = _strip_html(user_edited_transcript)
            if user_edited_plain:
                asr_normalized = _normalize_ws(full_local_text)
                user_normalized = _normalize_ws(user_edited_plain)
                if user_normalized and user_normalized != asr_normalized:
                    full_local_text = user_edited_plain
                    used_user_edit = True

        # Tier 2 — local deterministic cleanup
        try:
            local_display = corrector.clean_transcript_for_display(full_local_text).strip() or full_local_text
        except Exception:
            local_display = full_local_text

        display_text = local_display
        corrected_text = None
        is_ai_corrected = False
        correction_error = None

        # Tier 3 — DeepSeek enhancement (best-effort)
        if not getattr(corrector, "has_llm", False):
            correction_error = "AI 整理失败，已使用本地整理稿"
        else:
            try:
                ai_text = corrector.restructure_transcript(
                    local_display,
                    course_title,
                    keywords,
                )
                ai_text = (ai_text or "").strip()
                if not ai_text:
                    raise ValueError("DeepSeek returned empty text")

                ai_display = corrector.clean_transcript_for_display(ai_text).strip() or ai_text
                display_text = ai_display
                corrected_text = ai_display
                is_ai_corrected = True
            except Exception:
                correction_error = "AI 整理失败，已使用本地整理稿"

        # Build unified transcript entry
        all_timestamps = []
        if not used_user_edit:
            # Timestamps from ASR only make sense when we are finalizing the raw
            # ASR text. If the user has edited the transcript, word-level timings
            # are no longer reliable, so we drop them to avoid misleading audio
            # highlighting.
            for e in sorted_entries:
                if isinstance(e, dict):
                    ts = e.get("timestamps", [])
                    if ts:
                        all_timestamps.extend(ts)

        updated_entry = {
            "chunk_index": 0,
            "text": display_text,
            "raw_text": full_raw_text,
            "display_text": display_text,
            "corrected_text": corrected_text,
            "timestamps": all_timestamps,
            "is_corrected": display_text != full_local_text,
            "is_ai_corrected": is_ai_corrected,
            "correction_error": correction_error,
            "is_restructured": False,
            "correction_stage": "final",
        }

        note.transcript = [updated_entry]

        # Update content and layout_blocks
        existing_content = (note.content or "").strip()
        notes_content = ""
        if existing_content.startswith("## 语音转文字"):
            marker = "\n\n---\n\n"
            if marker in existing_content:
                notes_content = existing_content.split(marker, 1)[1].strip()

        if notes_content:
            note.content = f"## 语音转文字\n\n{display_text}\n\n---\n\n{notes_content}".strip()
        else:
            note.content = f"## 语音转文字\n\n{display_text}".strip()

        # Preserve all non-transcript blocks (ppt, image, audio, note, etc.).
        # Replace only the old transcript blocks in-place so that PPT images and
        # user-inserted layouts are not lost during AI finalization.
        existing_blocks = list(note.layout_blocks or [])
        transcript_blocks = [
            {
                "id": f"transcript-{i + 1}",
                "type": "transcript",
                "content": part.strip(),
            }
            for i, part in enumerate(display_text.split("\n\n"))
            if part.strip()
        ]
        new_blocks: list[dict] = []
        replaced_transcript = False
        for block in existing_blocks:
            if isinstance(block, dict) and block.get("type") == "transcript":
                if not replaced_transcript:
                    new_blocks.extend(transcript_blocks)
                    replaced_transcript = True
                continue
            new_blocks.append(block)
        if not replaced_transcript:
            new_blocks = transcript_blocks + new_blocks
        note.layout_blocks = new_blocks

        db.commit()
        db.refresh(note)

        # Set state based on outcome
        current_hash = _compute_session_content_hash(note)
        if is_ai_corrected:
            set_ready(db, session_id, "transcript_finalize", content_hash=current_hash, commit=False)
        else:
            set_fallback(db, session_id, "transcript_finalize", message="已使用本地整理稿", error_message=correction_error, commit=False)

        # Auto-trigger vector index
        _auto_build_vector_index_sync(session_id, current_user, db)

        return {
            "note": {
                "id": note.id,
                "session_id": note.session_id,
                "content": note.content or "",
                "transcript": note.transcript,
                "ppt_images": note.ppt_images or [],
                "vocabulary": note.vocabulary or [],
                "layout_blocks": note.layout_blocks or [],
                "created_at": note.created_at.isoformat() if note.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        set_error(db, session_id, "transcript_finalize", error_message=str(e))
        raise
    finally:
        lock.release()


@router.post("/session/{session_id}/restructure")
def restructure_transcript_endpoint(
    session_id: str,
    body: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run DeepSeek restructure on a session's transcript.

    Returns `{ note: {...}, agents: {...} | null }` so the frontend can refresh
    the transcript and show started agent tasks. On failure, falls back to local
    clean text and records the error.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    result = finalize_session_transcript(session_id, db, current_user)
    note_payload = result.get("note", result)

    agents_result = None
    auto_generate = bool(body.get("auto_generate", True)) if body else True
    if auto_generate:
        force = bool(body.get("force", False)) if body else False
        agents_result = auto_run_agents(session_id, current_user.id, force=force)

    return {"note": note_payload, "agents": agents_result}
