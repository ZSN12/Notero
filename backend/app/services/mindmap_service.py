"""Mind map generation service using DeepSeek.

Generates structured knowledge maps from session notes.
Stores results in Note.vocabulary with kind="mind_map".
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from app.agents import AgentContext, get_agent
from app.agents.normalizers import normalize_mind_map_data
from app.config import DEEPSEEK_API_KEY
from openai import OpenAI  # noqa: F401  kept for test compatibility
from app.core.database import SessionLocal
from app.core.task_runner import run_agent_task, wait_for_agent_threads
from app.models import Note, Session, Notebook, User, Task
from sqlalchemy.orm import Session as DBSessionType
from app.services.vector_service import _compute_session_content_hash
from app.services.state_service import set_running, set_ready, set_error, get_state
from app.services.note_utils import get_canonical_note_text


logger = logging.getLogger(__name__)

TASK_TYPE = "agent_mindmap"
ACTIVE_TASK_STATUSES = {"pending", "running"}

# Per-(session_id, task_type) lock to prevent races when checking for active
# tasks and creating new ones.
_START_LOCKS: dict[str, threading.Lock] = {}
_START_LOCKS_GUARD = threading.Lock()


def _get_start_lock(session_id: str, task_type: str) -> threading.Lock:
    key = f"{session_id}:{task_type}"
    lock = _START_LOCKS.get(key)
    if lock is None:
        with _START_LOCKS_GUARD:
            lock = _START_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _START_LOCKS[key] = lock
    return lock


# ── Mind map vocabulary helpers ──

def _get_mind_map_from_vocabulary(note: Note) -> Optional[dict]:
    """Read mind_map entry from note.vocabulary."""
    if not isinstance(note.vocabulary, list):
        return None
    for item in note.vocabulary:
        if isinstance(item, dict) and item.get("kind") == "mind_map":
            return item
    return None


def _set_mind_map_in_vocabulary(note: Note, data: dict, content_hash: str):
    """Write mind_map entry to note.vocabulary, preserving other kinds."""
    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    next_items = [
        item for item in existing
        if not (isinstance(item, dict) and item.get("kind") == "mind_map")
    ]
    next_items.append({
        "kind": "mind_map",
        "data": data,
        "content_hash": content_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    note.vocabulary = next_items


def _clear_mind_map_from_vocabulary(note: Note):
    """Remove mind_map entry from note.vocabulary."""
    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    next_items = [
        item for item in existing
        if not (isinstance(item, dict) and item.get("kind") == "mind_map")
    ]
    note.vocabulary = next_items


# ── Content extraction ──

def _extract_content_for_prompt(note: Note) -> str:
    """Extract all note content into a single text for the AI prompt.

    Uses the canonical note text (transcript + notes + PPT) so that user edits
    and deletions are respected and the same source is used across agents.
    """
    text = get_canonical_note_text(note, include_ppt=True)
    if text.strip():
        return text.strip()

    # Fallback: raw content if canonical extraction returned nothing.
    if note.content:
        return note.content.strip()

    return ""


# ── Generation ──

def _get_session_for_user(session_id: str, user: User, db: DBSessionType) -> Session | None:
    return db.query(Session).filter(
        Session.id == session_id
    ).join(Notebook).filter(Notebook.user_id == user.id).first()


def _get_latest_task(session_id: str, db: DBSessionType) -> Task | None:
    return db.query(Task).filter(
        Task.session_id == session_id,
        Task.task_type == TASK_TYPE,
    ).order_by(Task.created_at.desc()).first()


def _get_active_task(session_id: str, db: DBSessionType) -> Task | None:
    return db.query(Task).filter(
        Task.session_id == session_id,
        Task.task_type == TASK_TYPE,
        Task.status.in_(ACTIVE_TASK_STATUSES),
    ).order_by(Task.created_at.desc()).first()


def _task_payload(task: Task | None) -> dict:
    if not task:
        return {}
    return {
        "task_id": task.id,
        "progress": float(task.progress or 0.0),
        "error": task.error_message,
    }


def generate_mind_map(session_id: str, user: User, db: DBSessionType) -> dict:
    """Generate a mind map for a session via the MindmapAgent."""
    if not DEEPSEEK_API_KEY:
        raise ValueError("未配置 DEEPSEEK_API_KEY，无法生成知识导图")

    session = _get_session_for_user(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise ValueError("No note content found")

    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    if not notebook:
        raise ValueError("Notebook not found")

    content_text = _extract_content_for_prompt(note)
    if not content_text.strip():
        raise ValueError("No indexable content in note")

    agent = get_agent("mindmap")
    ctx = AgentContext(
        session_id=session_id,
        user=user,
        db=db,
        note=note,
        session=session,
        notebook=notebook,
    )
    result = agent.run(ctx)
    if not result.success:
        raise ValueError(result.error_message or "知识导图生成失败")

    return result.data if result.data else {}


def _run_mind_map_task(task_id: str, session_id: str, user_id: str):
    db = SessionLocal()
    started = time.monotonic()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not task or not user:
            return

        task.status = "running"
        task.progress = 0.1
        task.error_message = None
        db.commit()

        set_running(db, session_id, "mindmap", progress=0.1)

        generate_mind_map(session_id, user, db)

        # Re-fetch note before saving to reduce race window with other agents
        note = db.query(Note).filter(Note.session_id == session_id).first()
        if note:
            db.refresh(note)

        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "success"
            task.progress = 1.0
            task.error_message = None
            current_hash = _compute_session_content_hash(note) if note else ""
            set_ready(db, session_id, "mindmap", content_hash=current_hash)
            db.commit()
        logger.info(
            "mind_map_task_success task_id=%s session_id=%s user_id=%s elapsed_ms=%s",
            task_id,
            session_id,
            user_id,
            int((time.monotonic() - started) * 1000),
        )
    except Exception as e:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "error"
            task.progress = 1.0
            task.error_message = str(e)
            db.commit()
        set_error(db, session_id, "mindmap", error_message=str(e))
        logger.exception(
            "mind_map_task_failed task_id=%s session_id=%s user_id=%s",
            task_id,
            session_id,
            user_id,
        )
    finally:
        db.close()


def start_mind_map_generation(session_id: str, user: User, db: DBSessionType, force: bool = False) -> dict:
    """Start or reuse an async mind map generation task.

    Args:
        force: If True, regenerate even if a ready mind map exists.
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("未配置 DEEPSEEK_API_KEY，无法生成知识导图")

    session = _get_session_for_user(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise ValueError("No note content found")
    content_text = _extract_content_for_prompt(note)
    if not content_text.strip():
        raise ValueError("No indexable content in note")

    with _get_start_lock(session_id, TASK_TYPE):
        # Re-check inside the lock to close the race window.
        db.expire_all()
        status = get_mind_map_status(session_id, user, db)
        if status["status"] == "ready" and not force:
            return status
        if status["status"] == "generating":
            return status

        task = Task(
            session_id=session_id,
            task_type=TASK_TYPE,
            status="pending",
            progress=0.0,
            error_message=None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

    run_agent_task(
        target=lambda: _run_mind_map_task(task.id, session_id, user.id),
        daemon=True,
    )
    logger.info(
        "mind_map_task_started task_id=%s session_id=%s user_id=%s",
        task.id,
        session_id,
        user.id,
    )

    return {
        "session_id": session_id,
        "status": "generating",
        "mind_map": status.get("mind_map"),
        **_task_payload(task),
    }


# ── Status ──

def get_mind_map_status(session_id: str, user: User, db: DBSessionType) -> dict:
    """Get mind map status for a session."""
    session = _get_session_for_user(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    has_content = bool(note and (note.content or note.transcript or note.ppt_images or note.layout_blocks))

    if not has_content:
        return {"session_id": session_id, "status": "empty", "mind_map": None, "error": None}

    mm_entry = _get_mind_map_from_vocabulary(note) if note else None
    active_task = _get_active_task(session_id, db)

    def _build_mind_map(entry):
        if not entry:
            return None
        data = entry.get("data") or {}
        positions = entry.get("positions") or {}
        return {**data, "positions": positions}

    if active_task:
        return {
            "session_id": session_id,
            "status": "generating",
            "mind_map": _build_mind_map(mm_entry) if mm_entry else None,
            **_task_payload(active_task),
        }

    if not mm_entry:
        latest_task = _get_latest_task(session_id, db)
        if latest_task and latest_task.status == "error":
            return {
                "session_id": session_id,
                "status": "error",
                "mind_map": None,
                **_task_payload(latest_task),
            }
        return {"session_id": session_id, "status": "not_generated", "mind_map": None, "error": None}

    # Check stale
    current_hash = _compute_session_content_hash(note) if note else ""
    indexed_hash = mm_entry.get("content_hash", "")
    is_stale = indexed_hash != current_hash

    if is_stale:
        # Content changed since the mind map was generated. Keep the existing
        # map visible and mark as stale so the user can choose to regenerate;
        # don't treat an older failed attempt as a current error.
        return {
            "session_id": session_id,
            "status": "stale",
            "mind_map": _build_mind_map(mm_entry),
            "error": None,
        }

    current_state = get_state(db, session_id, "mindmap")
    if current_state and current_state.status != "ready":
        set_ready(db, session_id, "mindmap")

    return {
        "session_id": session_id,
        "status": "ready",
        "mind_map": _build_mind_map(mm_entry),
        "generated_at": mm_entry.get("generated_at"),
        "error": None,
    }


# ── Delete ──

def delete_mind_map(session_id: str, user: User, db: DBSessionType) -> dict:
    """Delete mind map for a session."""
    session = _get_session_for_user(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if note:
        _clear_mind_map_from_vocabulary(note)
        db.commit()

    return {"session_id": session_id, "status": "deleted"}


# ── Save positions ──

def save_mind_map_positions(
    session_id: str, positions: dict, user: User, db: DBSessionType
) -> dict:
    """Save node positions for a mind map (merged into vocabulary entry)."""
    session = _get_session_for_user(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise ValueError("No note found for session")

    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    next_items = []
    mm_item = None
    for item in existing:
        if isinstance(item, dict) and item.get("kind") == "mind_map":
            mm_item = dict(item)
            mm_item["positions"] = positions
            next_items.append(mm_item)
        else:
            next_items.append(item)

    if not mm_item:
        raise ValueError("No mind map found for session")

    note.vocabulary = next_items
    db.commit()
    return {"session_id": session_id, "status": "saved"}
