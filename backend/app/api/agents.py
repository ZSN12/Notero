"""API endpoints for the multi-agent pipeline.

Provides:
- Run all agents for a session in parallel
- Run a single agent
- Query agent task statuses
"""

from __future__ import annotations

import logging
import os
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents import AgentContext, get_agent, list_agents
from app.core.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.core.exceptions import (
    NoteroServiceError,
    ResourceNotFoundError,
    LLMUnavailableError,
    LLMTimeoutError,
    ProcessingError,
)
from app.models import Notebook, Note, Session as DBSession, Task, User
from app.tasks.agent_tasks import run_agent
from app.services.vector_service import _compute_session_content_hash
from app.services.state_service import (
    set_running as set_state_running,
    set_ready as set_state_ready,
    set_error as set_state_error,
    get_state,
    get_session_processing_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# Per-(session_id, task_type) lock to close the race window between checking for
# an active task and inserting a new one.
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


# In tests, run the agent synchronously so mocks are deterministic and threads
# cannot leak across test cases.
_RUN_AGENTS_SYNCHRONOUSLY = os.environ.get("AGENTS_SYNC", "0") == "1"
_USE_CELERY_FOR_AGENTS = os.environ.get("AGENTS_USE_CELERY", "0") == "1"


class RunAgentsRequest(BaseModel):
    roles: list[str] | None = None


# ── Helpers ──

def _dispatch_agent_task(session_id: str, user_id: str, role: str, task_id: str) -> None:
    """Start an agent task.

    Local development defaults to an in-process daemon thread. Celery is used
    only when AGENTS_USE_CELERY=1, because a reachable broker without a running
    worker would otherwise accept tasks that never execute.
    """
    if _RUN_AGENTS_SYNCHRONOUSLY:
        _run_agent_thread(session_id, user_id, role, task_id)
        return

    if not _USE_CELERY_FOR_AGENTS:
        thread = threading.Thread(
            target=_run_agent_thread,
            args=(session_id, user_id, role, task_id),
            daemon=True,
        )
        thread.start()
        return

    try:
        run_agent.delay(session_id, user_id, role, task_id)
    except Exception:
        logger.warning(
            "celery_dispatch_failed_falling_back_to_thread session_id=%s role=%s task_id=%s",
            session_id,
            role,
            task_id,
            exc_info=True,
        )
        thread = threading.Thread(
            target=_run_agent_thread,
            args=(session_id, user_id, role, task_id),
            daemon=True,
        )
        thread.start()

def _get_user_session(session_id: str, user: User, db: Session) -> DBSession | None:
    return (
        db.query(DBSession)
        .filter(DBSession.id == session_id)
        .join(Notebook)
        .filter(Notebook.user_id == user.id)
        .first()
    )


def _get_session_note(session_id: str, db: Session) -> Note | None:
    return db.query(Note).filter(Note.session_id == session_id).first()


def _user_for_note(note: Note, db: Session) -> User | None:
    if note.session and note.session.notebook:
        return db.query(User).filter(User.id == note.session.notebook.user_id).first()
    return None


def _notebook_for_note(note: Note, db: Session) -> Notebook | None:
    if note.session:
        return db.query(Notebook).filter(Notebook.id == note.session.notebook_id).first()
    return None


def _should_auto_trigger_agents(db: Session, session_id: str) -> bool:
    """Return True when transcript is finalized and vector index is ready.

    DeepSeek fallback (transcript_finalize.fallback) does NOT auto-trigger
    mindmap/quiz generation — only vector index is built automatically.
    """
    status = get_session_processing_status(db, session_id)
    stages = status.get("stages", {})
    vector_ok = stages.get("vector_index", {}).get("status") == "ready"
    transcript_ok = stages.get("transcript_finalize", {}).get("status") == "ready"
    return vector_ok and transcript_ok


def auto_run_agents(
    session_id: str,
    user_id: str,
    roles: list[str] | None = None,
    force: bool = False,
) -> dict | None:
    """Background trigger for agents after transcription completes.

    Owns its own DB session so it can be called safely from async generators
    or WebSocket handlers without inheriting the caller's session/transaction.
    When ``force`` is False, agents whose output is already fresh for the
    current content_hash are skipped.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(
                "auto_run_agents_user_not_found session_id=%s user_id=%s",
                session_id, user_id,
            )
            return None

        session = (
            db.query(DBSession)
            .filter(DBSession.id == session_id)
            .join(Notebook)
            .filter(Notebook.user_id == user_id)
            .first()
        )
        if not session:
            logger.warning(
                "auto_run_agents_session_not_found session_id=%s", session_id
            )
            return None

        note = _get_session_note(session_id, db)
        if not note:
            logger.warning(
                "auto_run_agents_note_not_found session_id=%s", session_id
            )
            return None

        if not _should_auto_trigger_agents(db, session_id):
            logger.info(
                "auto_run_agents_skipped session_id=%s reason=vector_or_transcript_not_ready",
                session_id,
            )
            return None

        if roles is None:
            target_roles = ["mindmap", "quiz"]
        else:
            target_roles = roles
        if not target_roles:
            return None

        # Validate roles up front.
        for role in target_roles:
            try:
                get_agent(role)
            except ValueError:
                logger.warning(
                    "auto_run_agents_unknown_role session_id=%s role=%s",
                    session_id, role,
                )
                return None

        notebook_obj = _notebook_for_note(note, db)

        lock = _get_start_lock(session_id, "run_all")
        with lock:
            db.expire_all()

            # Reuse active tasks and skip roles whose output is already fresh.
            tasks_to_start: list[str] = []
            for role in target_roles:
                task_type = f"agent_{role}"
                active = _get_active_task(session_id, task_type, db)
                if active:
                    continue
                agent = get_agent(role)
                ready = _maybe_return_ready_or_stale(
                    session_id, role, agent, note, db, user, notebook_obj, force=force
                )
                if ready:
                    _ensure_stage_ready_on_reuse(session_id, role, note, db)
                    continue
                tasks_to_start.append(role)

            if not tasks_to_start:
                logger.info(
                    "auto_run_agents_skipped session_id=%s reason=all_fresh_or_running",
                    session_id,
                )
                return {"session_id": session_id, "reused": True}

            tasks_info: list[dict] = []
            for role in tasks_to_start:
                task = Task(
                    session_id=session_id,
                    task_type=f"agent_{role}",
                    status="pending",
                    progress=0.0,
                    error_message=None,
                )
                db.add(task)
                tasks_info.append({"role": role, "task": task})
            db.commit()
            for info in tasks_info:
                db.refresh(info["task"])

        for info in tasks_info:
            role = info["role"]
            task_id = info["task"].id
            _dispatch_agent_task(session_id, user_id, role, task_id)
            logger.info(
                "auto_agent_task_started session_id=%s role=%s task_id=%s",
                session_id, role, task_id,
            )

        return {
            "session_id": session_id,
            "agents": [
                {
                    "role": info["role"],
                    "task_id": info["task"].id,
                    "status": info["task"].status,
                }
                for info in tasks_info
            ],
        }
    finally:
        db.close()


def _task_to_dict(task: Task) -> dict:
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "progress": float(task.progress or 0.0),
        "error": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _get_latest_task(session_id: str, task_type: str, db: Session) -> Task | None:
    return (
        db.query(Task)
        .filter(Task.session_id == session_id, Task.task_type == task_type)
        .order_by(Task.created_at.desc())
        .first()
    )


def _get_active_task(session_id: str, task_type: str, db: Session) -> Task | None:
    return (
        db.query(Task)
        .filter(
            Task.session_id == session_id,
            Task.task_type == task_type,
            Task.status.in_({"pending", "running"}),
        )
        .order_by(Task.created_at.desc())
        .first()
    )


def _maybe_return_ready_or_stale(
    session_id: str,
    role: str,
    agent,
    note: Note,
    db: Session,
    user: User,
    notebook: Notebook,
    force: bool,
) -> dict | None:
    """Return a ready dict if output exists and is fresh; None otherwise.

    When the stored content_hash is missing (legacy data), we treat it as stale
    so that the caller regenerates rather than returning potentially outdated
    results silently.
    """
    if force:
        return None
    existing = agent.get_existing_output(
        AgentContext(
            session_id=session_id,
            user=user,
            db=db,
            note=note,
            session=note.session,  # type: ignore[arg-type]
            notebook=notebook,
        )
    )
    if not existing:
        return None
    stored_hash = existing.get("content_hash")
    if not stored_hash:
        return None
    current_hash = _compute_session_content_hash(note)
    if stored_hash != current_hash:
        return None
    return {
        "session_id": session_id,
        "role": role,
        "status": "ready",
        "data": existing.get("data"),
    }


def _role_to_stage(role: str) -> str:
    return "quiz_bank" if role == "quiz" else role


def _ensure_stage_ready_on_reuse(
    session_id: str,
    role: str,
    note: Note,
    db: Session,
) -> None:
    stage = _role_to_stage(role)
    state = get_state(db, session_id, stage)
    # Promote stale/idle/fallback/error to ready whenever we have verified that
    # fresh output exists (the caller only invokes this after _maybe_return_ready_or_stale
    # returns a ready response). This heals cases where the state row was left in
    # error but the agent output was actually saved.
    if state and state.status in ("stale", "idle", "fallback", "error"):
        current_hash = _compute_session_content_hash(note)
        set_state_ready(db, session_id, stage, content_hash=current_hash, commit=True)


def _run_single_agent_sync(
    session_id: str,
    role: str,
    user: User,
    db: Session,
    force: bool = False,
) -> dict:
    """Synchronous runner for a single agent; commits the DB session on success."""
    session = _get_user_session(session_id, user, db)
    if not session:
        raise ValueError("Session not found or access denied")

    note = _get_session_note(session_id, db)
    if not note:
        raise ValueError("No note found for session")

    from app.services.note_utils import get_canonical_note_text
    content_text = get_canonical_note_text(note, include_ppt=True)
    if not content_text:
        raise ValueError("No indexable content in note")

    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    if not notebook:
        raise ValueError("Notebook not found")

    agent = get_agent(role)
    task_type = f"agent_{role}"
    stage = _role_to_stage(role)

    ready = _maybe_return_ready_or_stale(
        session_id, role, agent, note, db, user, notebook, force
    )
    if ready:
        _ensure_stage_ready_on_reuse(session_id, role, note, db)
        return ready

    # Create a tracking task.
    task = Task(
        session_id=session_id,
        task_type=task_type,
        status="running",
        progress=0.1,
        error_message=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    set_state_running(db, session_id, stage, progress=0.1, commit=False)

    ctx = AgentContext(
        session_id=session_id,
        user=user,
        db=db,
        note=note,
        session=session,
        notebook=notebook,
        force=force,
        task=task,
    )

    try:
        result = agent.run(ctx)
        task = db.query(Task).filter(Task.id == task.id).first()
        if not task:
            set_state_error(db, session_id, stage, error_message="Task lost", commit=False)
            db.commit()
            return {"session_id": session_id, "role": role, "status": "error", "error": "Task lost"}

        if result.success:
            task.status = "success"
            task.progress = 1.0
            task.error_message = None
            current_hash = _compute_session_content_hash(note)
            set_state_ready(db, session_id, stage, content_hash=current_hash, commit=False)
            db.commit()
            return {
                "session_id": session_id,
                "role": role,
                "status": "ready",
                "task_id": task.id,
                "data": result.data,
            }

        task.status = "error"
        task.progress = 1.0
        task.error_message = result.error_message or "未知错误"
        set_state_error(db, session_id, stage, error_message=result.error_message or "未知错误", commit=False)
        db.commit()
        raise ValueError(task.error_message)
    except Exception as e:
        db.rollback()
        task = db.query(Task).filter(Task.id == task.id).first()
        if task:
            task.status = "error"
            task.progress = 1.0
            task.error_message = str(e)
            db.commit()
        set_state_error(db, session_id, stage, error_message=str(e), commit=False)
        db.commit()
        logger.exception("single_agent_run_failed session_id=%s role=%s", session_id, role)
        raise ValueError(str(e))


def _run_agent_thread(
    session_id: str,
    user_id: str,
    role: str,
    task_id: str,
) -> None:
    """Thread worker: owns a fresh DB session and runs one agent to completion."""
    db = SessionLocal()
    stage = _role_to_stage(role)
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not task or not user:
            logger.error("agent_thread_missing_prereqs task_id=%s user_id=%s", task_id, user_id)
            return

        task.status = "running"
        task.progress = 0.1
        task.error_message = None
        db.commit()

        set_state_running(db, session_id, stage, progress=0.1, commit=False)
        db.commit()

        session = (
            db.query(DBSession)
            .filter(DBSession.id == session_id)
            .join(Notebook)
            .filter(Notebook.user_id == user_id)
            .first()
        )
        if not session:
            raise ValueError("Session not found or access denied")

        note = db.query(Note).filter(Note.session_id == session_id).first()
        if not note:
            raise ValueError("No note found for session")

        notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
        if not notebook:
            raise ValueError("Notebook not found")

        agent = get_agent(role)
        ctx = AgentContext(
            session_id=session_id,
            user=user,
            db=db,
            note=note,
            session=session,
            notebook=notebook,
            task=task,
        )
        result = agent.run(ctx)

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            set_state_error(db, session_id, stage, error_message="Task lost", commit=False)
            db.commit()
            return

        if result.success:
            task.status = "success"
            task.progress = 1.0
            task.error_message = None
            current_hash = _compute_session_content_hash(note)
            set_state_ready(db, session_id, stage, content_hash=current_hash, commit=False)
            db.commit()
            logger.info(
                "agent_task_success session_id=%s role=%s task_id=%s",
                session_id, role, task_id,
            )
        else:
            task.status = "error"
            task.progress = 1.0
            task.error_message = result.error_message or "未知错误"
            set_state_error(db, session_id, stage, error_message=result.error_message or "未知错误", commit=False)
            db.commit()
            logger.warning(
                "agent_task_error session_id=%s role=%s task_id=%s error=%s",
                session_id, role, task_id, task.error_message,
            )
    except Exception as e:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "error"
            task.progress = 1.0
            task.error_message = str(e)
            db.commit()
        set_state_error(db, session_id, stage, error_message=str(e), commit=False)
        db.commit()
        logger.exception(
            "agent_thread_failed session_id=%s role=%s task_id=%s",
            session_id, role, task_id,
        )
    finally:
        db.close()


# ── Endpoints ──

@router.post("/session/{session_id}/run")
def run_all_agents(
    session_id: str,
    body: RunAgentsRequest | None = None,
    response: Response = Response(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run all (or selected) agents in parallel for a session."""
    session = _get_user_session(session_id, current_user, db)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    note = _get_session_note(session_id, db)
    if not note:
        raise HTTPException(status_code=400, detail="No note found for session")

    has_content = bool(
        note.content
        or note.transcript
        or note.ppt_images
        or note.layout_blocks
    )
    if not has_content:
        raise HTTPException(status_code=400, detail="No indexable content in note")

    roles = body.roles if body and body.roles else list_agents()
    if not roles:
        raise HTTPException(status_code=400, detail="No agents available")

    # Validate roles up front.
    for role in roles:
        try:
            get_agent(role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown agent role: {role}")

    # Acquire a global-ish lock for this session so that checking for active
    # tasks and creating new ones is atomic. Without this, two concurrent calls
    # can both see no active task and each create one.
    lock = _get_start_lock(session_id, "run_all")
    with lock:
        db.expire_all()

        # Reuse active tasks and skip roles whose output is already fresh.
        active_tasks_info: list[dict] = []
        ready_agents_info: list[dict] = []
        tasks_to_start: list[str] = []
        notebook_obj = _notebook_for_note(note, db)
        for role in roles:
            task_type = f"agent_{role}"
            active = _get_active_task(session_id, task_type, db)
            if active:
                active_tasks_info.append({
                    "role": role,
                    "task_id": active.id,
                    "status": active.status,
                    "progress": float(active.progress or 0.0),
                    "error": active.error_message,
                })
                continue
            agent = get_agent(role)
            ready = _maybe_return_ready_or_stale(
                session_id, role, agent, note, db, current_user, notebook_obj, force=False
            )
            if ready:
                _ensure_stage_ready_on_reuse(session_id, role, note, db)
                ready_agents_info.append({
                    "role": role,
                    "status": "ready",
                    "data": ready.get("data"),
                })
                continue
            tasks_to_start.append(role)

        if not tasks_to_start:
            response.status_code = status.HTTP_200_OK
            return {
                "workflow_id": "reused",
                "session_id": session_id,
                "agents": active_tasks_info + ready_agents_info,
                "reused": True,
            }

        # Synchronously create Task rows inside the lock.
        tasks_info: list[dict] = []
        for role in tasks_to_start:
            task = Task(
                session_id=session_id,
                task_type=f"agent_{role}",
                status="pending",
                progress=0.0,
                error_message=None,
            )
            db.add(task)
            tasks_info.append({"role": role, "task": task})
        db.commit()
        for info in tasks_info:
            db.refresh(info["task"])

    # Launch threads outside the lock so the lock isn't held during slow LLM calls.
    for info in tasks_info:
        role = info["role"]
        task_id = info["task"].id
        _dispatch_agent_task(session_id, current_user.id, role, task_id)
        logger.info(
            "agent_task_started session_id=%s role=%s task_id=%s",
            session_id, role, task_id,
        )

    result = {
        "workflow_id": str(uuid.uuid4()),
        "session_id": session_id,
        "agents": [
            {
                "role": info["role"],
                "task_id": info["task"].id,
                "status": info["task"].status,
                "progress": float(info["task"].progress or 0.0),
                "error": info["task"].error_message,
            }
            for info in tasks_info
        ],
    }
    if active_tasks_info:
        result["agents"] = active_tasks_info + result["agents"]
        result["reused"] = True
    response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.get("/session/{session_id}/tasks")
def get_agent_tasks(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the latest task status for each registered agent on the session."""
    session = _get_user_session(session_id, current_user, db)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Latest task per agent role — use subquery to avoid loading all history
    subq = (
        db.query(
            Task.task_type,
            func.max(Task.created_at).label("max_created_at"),
        )
        .filter(Task.session_id == session_id)
        .filter(Task.task_type.like("agent_%"))
        .group_by(Task.task_type)
        .subquery()
    )
    tasks = (
        db.query(Task)
        .join(
            subq,
            (Task.task_type == subq.c.task_type) & (Task.created_at == subq.c.max_created_at),
        )
        .filter(Task.session_id == session_id)
        .all()
    )

    return {
        "session_id": session_id,
        "agents": [_task_to_dict(t) for t in tasks],
    }


@router.post("/session/{session_id}/run/{role}")
def run_single_agent(
    session_id: str,
    role: str,
    force: bool = False,
    response: Response = Response(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a single agent for a session.

    Returns 200 with ready data if output exists and is not stale.
    Returns 200 with active task info if an agent is already running.
    Returns 200 with result if forced regeneration completes synchronously.
    """
    session = _get_user_session(session_id, current_user, db)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        get_agent(role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown agent role: {role}")

    task_type = f"agent_{role}"

    # Reuse active task if one exists.
    if not force:
        active = _get_active_task(session_id, task_type, db)
        if active:
            return {
                "session_id": session_id,
                "role": role,
                "status": "generating",
                "task_id": active.id,
                "progress": float(active.progress or 0.0),
                "error": active.error_message,
            }

    try:
        result = _run_single_agent_sync(session_id, role, current_user, db, force=force)
        # ready / success both return 200 since this is a synchronous call.
        response.status_code = status.HTTP_200_OK
        return result
    except ValueError as e:
        error_msg = str(e)
        if "DEEPSEEK_API_KEY" in error_msg:
            raise HTTPException(status_code=503, detail=error_msg)
        if ("失败" in error_msg or "超时" in error_msg or "timeout" in error_msg.lower()
                or "截断" in error_msg or "length" in error_msg.lower()):
            raise HTTPException(status_code=502, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.exception("run_single_agent_failed session_id=%s role=%s", session_id, role)
        raise HTTPException(status_code=500, detail=f"运行 Agent 失败: {e}")
