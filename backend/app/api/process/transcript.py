import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Note, Session as DBSession, Notebook, User
from app.config import DEEPSEEK_MODEL
from app.core.llm import ChatMessage, get_default_chat_provider
from app.services.prompt_loader import load_prompt
from app.services.term_corrector import corrector, CORRECTION_ERROR_CODES, classify_correction_exception
from app.services.course_terms_service import (
    build_shared_course_terms_for_session,
    build_terms_from_ppt,
    upsert_notebook_course_terms,
)
from app.services.state_service import set_running, set_ready, set_error, set_fallback, set_partial
from app.services.vector_service import build_session_index, _compute_session_content_hash
from app.services.vocabulary_service import save_vocabulary_entry

# Agent integration
from app.agents import AgentContext, get_agent

router = APIRouter()


def _extract_ppt_slides(note: Note) -> list[dict] | None:
    if isinstance(note.ppt_images, list) and note.ppt_images:
        last_ppt = note.ppt_images[-1]
        if isinstance(last_ppt, dict):
            slides = last_ppt.get("slides", [])
            return slides or None
    return None


def generate_summary(transcript_text: str, course_title: str):
    """Generate a summary for the session using the default chat provider."""
    provider = get_default_chat_provider()
    if not provider.available:
        return ""

    prompt_template = load_prompt("summary")
    prompt = prompt_template.render(
        course_title=course_title,
        text=transcript_text,
    )

    try:
        response = provider.chat(
            messages=[
                ChatMessage(role="system", content=prompt_template.system),
                ChatMessage(role="user", content=prompt),
            ],
            model=DEEPSEEK_MODEL,
            temperature=0.3,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("summary_generation_failed error=%s", e, exc_info=True)
        return ""


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


@router.post("/generate-summary")
def generate_summary_endpoint(
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a summary for the session using DeepSeek AI and save it to the session."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Verify session exists
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get transcript text from note
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise HTTPException(status_code=400, detail="No transcript available")
    transcript_text = get_transcript_text(note)
    if not transcript_text:
        raise HTTPException(status_code=400, detail="No transcript available")

    # Get course title
    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    course_title = notebook.title if notebook else ""

    # Try agent-based summary first; fall back to legacy function on failure.
    summary = ""
    try:
        agent = get_agent("summary")
        ctx = AgentContext(
            session_id=session_id,
            user=current_user,
            db=db,
            note=note,
            session=session,
            notebook=notebook,
        )
        result = agent.run(ctx)
        if result.success and result.data:
            summary = result.data.get("summary", "")
        elif result.error_message:
            logger.warning("summary_agent_failed error_message=%s", result.error_message)
    except Exception as e:
        logger.warning("summary_agent_exception error=%s", e, exc_info=True)

    if not summary:
        summary = generate_summary(transcript_text, course_title)

    if summary:
        session.summary = summary
        db.commit()

    return {"status": "success", "summary": summary}


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


def _load_previous_chunk_results(note: Note) -> list[dict] | None:
    """Return previously stored AI chunk results from note vocabulary, if any."""
    if not note or not isinstance(note.vocabulary, list):
        return None
    for item in note.vocabulary:
        if isinstance(item, dict) and item.get("kind") == "transcript_ai_chunks":
            return item.get("data") or item.get("chunks")
    return None


def _save_chunk_results(db: Session, note: Note, chunk_results: list) -> None:
    """Persist chunk results to note vocabulary for later retry-failed-only runs."""
    serializable = []
    for r in chunk_results:
        if isinstance(r, dict):
            serializable.append(r)
        else:
            serializable.append({
                "index": r.index,
                "input": r.input,
                "output": r.output,
                "success": r.success,
                "error_code": r.error_code,
                "error_message": r.error_message,
                "retryable": r.retryable,
                "elapsed": r.elapsed,
                "finish_reason": r.finish_reason,
                "input_length": r.input_length,
                "review_performed": r.review_performed,
                "review_repaired": r.review_repaired,
                "missing_facts": r.missing_facts,
                "review_error_code": r.review_error_code,
                "review_error_message": r.review_error_message,
            })
    entry = {
        "kind": "transcript_ai_chunks",
        "chunks": serializable,
    }
    save_vocabulary_entry(db, note.id, entry)


def finalize_session_transcript(
    session_id: str,
    db: Session,
    current_user: User,
    retry_failed_only: bool = False,
) -> dict:
    """Run DeepSeek finalization on a session's transcript and return note payload.

    This is the shared finalization logic used by:
      - the manual "restructure" endpoint
      - the audio-finish endpoint after real-time recording stops
    """
    request_id = str(uuid.uuid4())
    error_type: str | None = None
    set_running(db, session_id, "transcript_finalize", progress=0.0, commit=False)
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
        ppt_slides = _extract_ppt_slides(note)
        session_keywords = session.keywords or []
        keywords = build_shared_course_terms_for_session(
            db,
            session,
            course_title=course_title,
            current_keywords=session_keywords,
            ppt_slides=ppt_slides,
        )

        try:
            fresh_terms = build_terms_from_ppt(course_title, session_keywords, ppt_slides)
            if fresh_terms:
                upsert_notebook_course_terms(
                    db,
                    session.notebook_id,
                    fresh_terms,
                    source="transcript_finalize",
                    session_id=session_id,
                    weight=2.0,
                    commit=True,
                )
                keywords = build_shared_course_terms_for_session(
                    db,
                    session,
                    course_title=course_title,
                    current_keywords=session_keywords,
                    ppt_slides=ppt_slides,
                )
        except Exception:
            logger.warning("course_terms_update_failed session_id=%s", session_id, exc_info=True)

        # Build full text from ALL entries (sorted by chunk_index)
        sorted_entries = sorted(
            note.transcript,
            key=lambda e: e.get("chunk_index", 0) if isinstance(e, dict) else 0,
        )
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
        if not full_local_text:
            set_error(db, session_id, "transcript_finalize", error_message="Transcript text is empty")
            raise HTTPException(status_code=400, detail="Transcript text is empty")

        # Tier 2 — local deterministic cleanup
        try:
            local_display = corrector.clean_transcript_for_display(full_local_text).strip() or full_local_text
        except Exception:
            local_display = full_local_text

        display_text = local_display
        corrected_text = None
        is_ai_corrected = False
        correction_error = None
        correction_error_code: str | None = None
        correction_retryable = False
        ai_chunks_total = 0
        ai_chunks_succeeded = 0
        ai_chunks_failed = 0
        chunk_results: list = []

        # Collect timestamps once for the final entry
        all_timestamps = []
        for e in sorted_entries:
            if isinstance(e, dict):
                ts = e.get("timestamps", [])
                if ts:
                    all_timestamps.extend(ts)

        # Tier 3 — DeepSeek enhancement (best-effort, chunked for long transcripts)
        if not getattr(corrector, "has_llm", False):
            correction_error_code = "authentication"
            correction_error = "未配置 DeepSeek API，已使用本地整理稿"
        else:
            # Pre-compute chunks so we can persist ai_chunks_total before any request starts.
            chunks = corrector._split_natural_chunks(local_display)
            ai_chunks_total = len(chunks)

            previous = _load_previous_chunk_results(note) if retry_failed_only else None

            # If the caller asked to retry only failed chunks but we have no cached
            # chunk results (e.g. a previous "unknown" failure that didn't save them),
            # we must reprocess the whole transcript instead of doing nothing.
            if retry_failed_only and not previous:
                retry_failed_only = False
                previous = None

            # Persist the local-only baseline with ai_chunks_total up front.
            # If anything fails below, the user still sees local text and a valid total.
            preliminary_entry = {
                "chunk_index": 0,
                "text": local_display,
                "raw_text": full_raw_text,
                "display_text": local_display,
                "corrected_text": None,
                "timestamps": all_timestamps,
                "is_corrected": local_display != full_local_text,
                "is_ai_corrected": False,
                "correction_error": None,
                "correction_error_code": None,
                "correction_error_type": None,
                "correction_request_id": request_id,
                "correction_retryable": False,
                "ai_chunks_total": ai_chunks_total,
                "ai_chunks_succeeded": 0,
                "ai_chunks_failed": 0,
                "is_restructured": False,
                "correction_stage": "final",
            }
            note.transcript = [preliminary_entry]
            _persist_display_content(note, local_display)
            db.commit()

            def on_chunk_complete(completed_count: int, total: int) -> None:
                progress = round(completed_count / total, 2) if total else 1.0
                set_running(
                    db, session_id, "transcript_finalize",
                    progress=progress,
                    message=f"正在 AI 整理：{completed_count}/{total}",
                    commit=True,
                )

            try:
                result = corrector.restructure_transcript_chunked(
                    local_display,
                    course_title,
                    keywords,
                    ppt_slides,
                    previous_results=previous,
                    retry_failed_only=retry_failed_only,
                    on_chunk_complete=on_chunk_complete,
                )
                display_text = result.text
                corrected_text = result.text if result.is_ai_corrected else None
                is_ai_corrected = result.is_ai_corrected and result.chunks_failed == 0
                correction_error = result.error
                correction_error_code = result.error_code
                correction_retryable = result.retryable
                ai_chunks_total = result.chunks_total
                ai_chunks_succeeded = result.chunks_succeeded
                ai_chunks_failed = result.chunks_failed
                chunk_results = result.chunk_results
                _save_chunk_results(db, note, chunk_results)
            except Exception as exc:
                error_type = type(exc).__name__
                code, message, retryable = classify_correction_exception(exc)
                logger.exception(
                    "finalize_session_transcript_chunked_failed session_id=%s request_id=%s error_type=%s",
                    session_id, request_id, error_type,
                )
                correction_error_code = code
                correction_error = message
                correction_retryable = retryable

        # Build unified transcript entry
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
            "correction_error_code": correction_error_code,
            "correction_error_type": error_type,
            "correction_request_id": request_id,
            "correction_retryable": correction_retryable,
            "ai_chunks_total": ai_chunks_total,
            "ai_chunks_succeeded": ai_chunks_succeeded,
            "ai_chunks_failed": ai_chunks_failed,
            "is_restructured": False,
            "correction_stage": "final",
        }

        note.transcript = [updated_entry]
        _persist_display_content(note, display_text)

        db.commit()
        db.refresh(note)
        logger.info(
            "finalize_session_transcript_saved session_id=%s request_id=%s note_id=%s ai_corrected=%s chunks=%s/%s",
            session_id, request_id, note.id, is_ai_corrected, ai_chunks_succeeded, ai_chunks_total,
        )

        # Set state based on outcome — success clears any previous fallback/error state.
        if is_ai_corrected:
            set_ready(db, session_id, "transcript_finalize", commit=False)
        elif ai_chunks_succeeded > 0 and ai_chunks_failed > 0:
            set_partial(
                db, session_id, "transcript_finalize",
                message=correction_error or "AI 整理部分完成",
                error_message=correction_error,
                commit=False,
            )
        elif correction_error:
            # All failed or no API key — surface as fallback so user can retry.
            set_fallback(
                db, session_id, "transcript_finalize",
                message="已使用本地整理稿",
                error_message=correction_error,
                commit=False,
            )
        else:
            set_ready(db, session_id, "transcript_finalize", commit=False)

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
    except Exception as exc:
        error_type = type(exc).__name__
        code, message, _ = classify_correction_exception(exc)
        logger.exception(
            "finalize_session_transcript_unexpected session_id=%s request_id=%s error_type=%s",
            session_id, request_id, error_type,
        )
        set_error(db, session_id, "transcript_finalize", error_message=f"[{request_id}] {message}")
        raise


def _persist_display_content(note: Note, display_text: str) -> None:
    """Update note.content and layout_blocks from the current display transcript.

    Preserves manually inserted PPT pages and student notes by re-inserting
    non-transcript blocks at their previous relative positions.
    """
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

    old_blocks = [b for b in (note.layout_blocks or []) if isinstance(b, dict)]
    old_transcript_count = sum(1 for b in old_blocks if b.get("type") == "transcript")

    transcript_blocks = [
        {
            "id": f"transcript-{i + 1}",
            "type": "transcript",
            "content": part.strip(),
        }
        for i, part in enumerate(display_text.split("\n\n"))
        if part.strip()
    ]
    new_transcript_count = len(transcript_blocks)

    # Preserve PPT and note blocks, re-inserting PPT at approximately the same
    # relative position among transcript blocks.
    non_transcript_blocks = [b for b in old_blocks if b.get("type") in ("ppt", "note")]
    ppt_blocks = [b for b in non_transcript_blocks if b.get("type") == "ppt"]
    note_blocks = [b for b in non_transcript_blocks if b.get("type") == "note"]

    result = list(transcript_blocks)
    for ppt in ppt_blocks:
        # Find where this PPT was in the old layout.
        old_index = old_blocks.index(ppt)
        preceding_transcripts = sum(
            1 for b in old_blocks[:old_index] if b.get("type") == "transcript"
        )
        if old_transcript_count > 0 and new_transcript_count > 0:
            ratio = preceding_transcripts / old_transcript_count
            target = min(new_transcript_count, max(0, round(ratio * new_transcript_count)))
        else:
            target = 0
        # Avoid inserting past the end; if there are no transcript blocks,
        # PPTs are kept at the front.
        result.insert(target, ppt)

    note.layout_blocks = result + note_blocks


@router.post("/session/{session_id}/restructure")
def restructure_transcript_endpoint(
    session_id: str,
    body: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run DeepSeek restructure on a session's transcript.

    Returns the updated note with corrected_text / is_ai_corrected / correction_error.
    On failure, falls back to local clean text and records the error.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    retry_failed_only = bool(body and body.get("retry_failed_only"))
    return finalize_session_transcript(session_id, db, current_user, retry_failed_only=retry_failed_only)
