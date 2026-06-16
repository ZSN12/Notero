"""Unified session processing state service.

Provides CRUD for session_processing_states and aggregation for UI recovery.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import SessionProcessingState, Task, VectorChunk, Note
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)

VALID_STAGES = {
    "upload_transcribe",
    "recording_finalize",
    "transcript_finalize",
    "transcript_organize",
    "vector_index",
    "mindmap",
    "quiz_bank",
}

VALID_STATUSES = {"idle", "running", "ready", "error", "stale", "fallback"}


_HEALABLE_STATUSES = {"error", "stale", "idle", "fallback"}


def _get_stored_output_hash(note: Note, stage: str) -> str | None:
    """Return the content_hash stored inside an agent output vocabulary entry."""
    if not note or not isinstance(note.vocabulary, list):
        return None
    kind = None
    if stage == "mindmap":
        kind = "mind_map"
    elif stage == "quiz_bank":
        kind = "quiz_bank"
    elif stage == "transcript_organize":
        kind = "organized_transcript"
    else:
        return None
    for item in note.vocabulary:
        if isinstance(item, dict) and item.get("kind") == kind:
            return item.get("content_hash") or None
    return None


def _heal_stage_state_if_fresh(
    db: Session, session_id: str, stage: str, note: Note
) -> SessionProcessingState | None:
    """Promote a stage to ready if fresh output exists, regardless of a stale/error state row.

    Fixes the common case where the agent task row ended in error (or the state
    row was never updated) but the actual output — mind map / quiz bank in
    note.vocabulary, or vector chunks in the vector_index table — was saved and
    matches the current note content hash.
    """
    if stage not in ("mindmap", "quiz_bank", "vector_index", "transcript_organize"):
        return None
    state = (
        db.query(SessionProcessingState)
        .filter(
            SessionProcessingState.session_id == session_id,
            SessionProcessingState.stage == stage,
        )
        .first()
    )
    if state and state.status not in _HEALABLE_STATUSES:
        return state

    current_hash = _compute_session_content_hash(note)
    is_fresh = False

    if stage == "vector_index":
        sample_chunk = (
            db.query(VectorChunk)
            .filter(VectorChunk.session_id == session_id)
            .first()
        )
        if sample_chunk and sample_chunk.chunk_meta:
            is_fresh = sample_chunk.chunk_meta.get("session_content_hash") == current_hash
    else:
        stored_hash = _get_stored_output_hash(note, stage)
        is_fresh = bool(stored_hash and stored_hash == current_hash)

    if is_fresh:
        if not state:
            state = SessionProcessingState(
                session_id=session_id,
                stage=stage,
                status="ready",
                progress=1.0,
                content_hash=current_hash,
            )
            db.add(state)
        else:
            state.status = "ready"
            state.progress = 1.0
            state.content_hash = current_hash
            state.error_message = None
            state.updated_at = datetime.now(timezone.utc)
        db.commit()
    return state


def _get_or_create_state(
    db: Session, session_id: str, stage: str
) -> SessionProcessingState:
    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}")
    state = (
        db.query(SessionProcessingState)
        .filter(
            SessionProcessingState.session_id == session_id,
            SessionProcessingState.stage == stage,
        )
        .first()
    )
    if not state:
        state = SessionProcessingState(
            session_id=session_id,
            stage=stage,
            status="idle",
            progress=0.0,
        )
        db.add(state)
        db.flush()
    return state


def set_running(
    db: Session,
    session_id: str,
    stage: str,
    progress: float = 0.0,
    message: Optional[str] = None,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "running"
    state.progress = progress
    state.message = message
    state.error_message = None
    state.started_at = datetime.now(timezone.utc)
    state.finished_at = None
    if commit:
        db.commit()
    logger.info("state_running session_id=%s stage=%s progress=%s", session_id, stage, progress)
    return state


def set_ready(
    db: Session,
    session_id: str,
    stage: str,
    content_hash: Optional[str] = None,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "ready"
    state.progress = 1.0
    state.message = None
    state.error_message = None
    state.content_hash = content_hash
    state.finished_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    logger.info("state_ready session_id=%s stage=%s", session_id, stage)
    return state


def set_error(
    db: Session,
    session_id: str,
    stage: str,
    error_message: str,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "error"
    state.progress = 1.0
    state.message = None
    state.error_message = error_message
    state.finished_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    logger.info("state_error session_id=%s stage=%s error=%s", session_id, stage, error_message)
    return state


def set_fallback(
    db: Session,
    session_id: str,
    stage: str,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "fallback"
    state.progress = 1.0
    state.message = message
    state.error_message = error_message
    state.finished_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    logger.info("state_fallback session_id=%s stage=%s", session_id, stage)
    return state


def set_stale(
    db: Session,
    session_id: str,
    stage: str,
    content_hash: Optional[str] = None,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "stale"
    state.progress = 0.0
    state.message = None
    state.error_message = None
    state.content_hash = content_hash
    state.finished_at = None
    if commit:
        db.commit()
    logger.info("state_stale session_id=%s stage=%s", session_id, stage)
    return state


def set_idle(
    db: Session,
    session_id: str,
    stage: str,
    commit: bool = True,
) -> SessionProcessingState:
    state = _get_or_create_state(db, session_id, stage)
    state.status = "idle"
    state.progress = 0.0
    state.message = None
    state.error_message = None
    state.finished_at = None
    if commit:
        db.commit()
    return state


def get_state(
    db: Session,
    session_id: str,
    stage: str,
) -> Optional[SessionProcessingState]:
    if stage not in VALID_STAGES:
        return None
    return (
        db.query(SessionProcessingState)
        .filter(
            SessionProcessingState.session_id == session_id,
            SessionProcessingState.stage == stage,
        )
        .first()
    )


def _stage_to_dict(state: Optional[SessionProcessingState]) -> dict:
    if not state:
        return {
            "status": "idle",
            "progress": 0.0,
            "message": None,
            "error_message": None,
            "content_hash": None,
            "started_at": None,
            "finished_at": None,
        }
    return {
        "status": state.status,
        "progress": float(state.progress or 0.0),
        "message": state.message,
        "error_message": state.error_message,
        "content_hash": state.content_hash,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
    }


def get_session_processing_status(db: Session, session_id: str) -> dict:
    """Aggregate processing status for a session.

    Returns:
        {
            "session_id": str,
            "overall_status": "idle" | "running" | "ready" | "error" | "fallback" | "stale",
            "stages": {stage: {...}},
            "can_auto_generate": bool,
            "can_ask_rag": bool,
            "needs_user_action": bool,
        }
    """
    states = (
        db.query(SessionProcessingState)
        .filter(SessionProcessingState.session_id == session_id)
        .all()
    )

    stage_map = {s.stage: s for s in states}

    # Self-heal stages: if actual output (mind map / quiz bank / vector chunks)
    # exists and matches the current content hash, promote the persisted state
    # row to ready even if it says error/stale/idle.
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if note:
        for stage_to_heal in ("vector_index", "mindmap", "quiz_bank", "transcript_organize"):
            healed = _heal_stage_state_if_fresh(db, session_id, stage_to_heal, note)
            if healed:
                stage_map[stage_to_heal] = healed

    stages = {}
    for stage in VALID_STAGES:
        stages[stage] = _stage_to_dict(stage_map.get(stage))

    # overall_status logic: be explicit about the core pipeline vs. auxiliary
    # learning-material stages so the UI never shows "ready" while something
    # critical is still missing or stale.
    core_stages = ["transcript_finalize", "vector_index"]
    auxiliary_stages = ["mindmap", "quiz_bank"]
    all_statuses = [s.status for s in stage_map.values()]

    if not stage_map or all(s == "idle" for s in all_statuses):
        overall_status = "idle"
    elif any(s == "running" for s in all_statuses):
        overall_status = "running"
    elif any(s == "error" for s in all_statuses):
        overall_status = "error"
    elif stages.get("transcript_finalize", {}).get("status") == "fallback":
        # Transcript used local fallback: not an error, but not fully AI ready.
        overall_status = "fallback"
    elif any(s == "stale" for s in all_statuses):
        # Core ready but some auxiliary material is stale → partial ready.
        overall_status = "stale"
    elif (
        all(stages.get(s, {}).get("status") in ("ready", "idle") for s in VALID_STAGES)
        and stages.get("transcript_finalize", {}).get("status") == "ready"
        and stages.get("vector_index", {}).get("status") == "ready"
    ):
        overall_status = "ready"
    else:
        overall_status = "idle"

    vector_stage = stages.get("vector_index", {})
    transcript_stage = stages.get("transcript_finalize", {})

    can_ask_rag = vector_stage.get("status") == "ready"
    can_auto_generate = (
        vector_stage.get("status") == "ready"
        and transcript_stage.get("status") == "ready"
    )
    needs_user_action = any(
        stages[s].get("status") in ("error", "fallback") for s in VALID_STAGES
    )

    # Aggregate auxiliary data to reduce front-end request fan-out
    latest_tasks = (
        db.query(Task)
        .filter(Task.session_id == session_id)
        .order_by(Task.created_at.desc())
        .limit(5)
        .all()
    )
    vector_chunks_count = (
        db.query(VectorChunk)
        .filter(VectorChunk.session_id == session_id)
        .count()
    )

    return {
        "session_id": session_id,
        "overall_status": overall_status,
        "stages": stages,
        "can_auto_generate": can_auto_generate,
        "can_ask_rag": can_ask_rag,
        "needs_user_action": needs_user_action,
        "latest_tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "status": t.status,
                "progress": float(t.progress or 0.0),
                "error_message": t.error_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in latest_tasks
        ],
        "vector_chunks_count": vector_chunks_count,
    }
