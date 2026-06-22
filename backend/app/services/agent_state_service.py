"""Unified agent state synchronization and stale-task healing.

This module provides atomic updates across three representations of agent
progress:

- ``Task`` rows: per-execution tracking created by the API / orchestrator.
- ``SessionProcessingState`` rows: per-stage summary used by the frontend.
- ``AgentWorkflow.role_states``: in-flight workflow DAG state.

It also heals tasks/workflows/states that are stuck in ``running`` or
``pending`` after a backend restart or a crashed worker.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.config import AGENT_TIMEOUT_SECONDS, AGENT_HEARTBEAT_SECONDS
from app.models import AgentWorkflow, SessionProcessingState, Task
from app.services.state_service import (
    set_error as set_state_error,
    set_ready as set_state_ready,
    set_running as set_state_running,
    set_queued as set_state_queued,
    get_state as get_state_row,
    VALID_STAGES,
)

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "任务已中断，请重新生成"


def _role_to_stage(role: str) -> str:
    """Map agent role to its processing-state stage name."""
    if role == "quiz":
        return "quiz_bank"
    if role == "transcript":
        return "transcript_organize"
    return role


def _task_type_for_role(role: str) -> str:
    return f"agent_{role}"


# ── Public helpers for heartbeat (own SessionLocal) ──

def update_task_heartbeat(task_id: str) -> None:
    """Touch the task and matching processing-state rows using a fresh session.

    Must NOT reuse the caller's SQLAlchemy Session because this is called from
    a background heartbeat thread while the main thread may be committing.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.updated_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.exception("task_heartbeat_failed task_id=%s", task_id)
        db.rollback()
    finally:
        db.close()


def update_state_heartbeat(session_id: str, stage: str) -> None:
    """Touch a processing-state row using a fresh session."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        state = (
            db.query(SessionProcessingState)
            .filter(
                SessionProcessingState.session_id == session_id,
                SessionProcessingState.stage == stage,
            )
            .first()
        )
        if state:
            state.updated_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.exception("state_heartbeat_failed session_id=%s stage=%s", session_id, stage)
        db.rollback()
    finally:
        db.close()


def update_workflow_heartbeat(session_id: str, user_id: str, role: str) -> None:
    """Touch the most recent running workflow for the session using a fresh session."""
    from app.core.database import SessionLocal
    from sqlalchemy.orm.attributes import flag_modified

    db = SessionLocal()
    try:
        workflow = (
            db.query(AgentWorkflow)
            .filter(
                AgentWorkflow.session_id == session_id,
                AgentWorkflow.user_id == user_id,
                AgentWorkflow.status == "running",
            )
            .order_by(AgentWorkflow.created_at.desc())
            .first()
        )
        if workflow and role in workflow.role_states:
            now = datetime.now(timezone.utc).isoformat()
            workflow.role_states[role]["heartbeat_at"] = now
            new_states = dict(workflow.role_states)
            workflow.role_states = new_states
            flag_modified(workflow, "role_states")
            workflow.last_heartbeat_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.exception(
            "workflow_heartbeat_failed session_id=%s user_id=%s role=%s",
            session_id,
            user_id,
            role,
        )
        db.rollback()
    finally:
        db.close()


# ── Unified state transitions ──

def set_agent_queued(
    db: DBSession,
    session_id: str,
    role: str,
    task_id: str,
    message: str = "等待后台任务执行",
    user_id: Optional[str] = None,
    commit: bool = True,
) -> Task:
    """Expose a queued role to the UI without claiming the task is executing.

    Celery workers use ``Task.status == 'running'`` as an idempotency signal.
    Marking the task running before it reaches the worker makes the worker skip
    its own freshly-dispatched task. Keep the Task pending here; AgentRunner
    performs the real running transition after it acquires the task.
    """
    stage = _role_to_stage(role)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "pending"
        task.progress = 0.0
        task.error_message = None
        task.updated_at = datetime.now(timezone.utc)
        db.add(task)

    set_state_queued(db, session_id, stage, message=message, commit=False)
    _update_workflow_role_state(
        db,
        session_id,
        role,
        status="pending",
        task_id=task_id,
        progress=0.0,
        user_id=user_id,
    )
    if commit:
        db.commit()
    return task

def _find_running_workflow(
    db: DBSession, session_id: str, user_id: Optional[str] = None
) -> Optional[AgentWorkflow]:
    q = db.query(AgentWorkflow).filter(
        AgentWorkflow.session_id == session_id,
        AgentWorkflow.status == "running",
    )
    if user_id:
        q = q.filter(AgentWorkflow.user_id == user_id)
    return q.order_by(AgentWorkflow.created_at.desc()).first()


def _update_workflow_role_state(
    db: DBSession,
    session_id: str,
    role: str,
    status: str,
    task_id: Optional[str] = None,
    progress: Optional[float] = None,
    error_message: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Update the role state inside the most recent running workflow if one exists."""
    from sqlalchemy.orm.attributes import flag_modified

    workflow = _find_running_workflow(db, session_id, user_id=user_id)
    if not workflow or role not in workflow.role_states:
        return

    role_state = workflow.role_states[role]
    role_state["status"] = status
    if task_id is not None:
        role_state["task_id"] = task_id
    if progress is not None:
        role_state["progress"] = progress
    if error_message is not None:
        role_state["error_message"] = error_message
    new_states = dict(workflow.role_states)
    workflow.role_states = new_states
    flag_modified(workflow, "role_states")
    workflow.updated_at = datetime.now(timezone.utc)
    db.add(workflow)


def set_agent_running(
    db: DBSession,
    session_id: str,
    role: str,
    task_id: str,
    progress: float = 0.1,
    message: Optional[str] = None,
    user_id: Optional[str] = None,
    commit: bool = True,
) -> Task:
    """Atomically mark a role as running across Task, State and Workflow."""
    stage = _role_to_stage(role)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "running"
        task.progress = progress
        task.error_message = None
        task.updated_at = datetime.now(timezone.utc)
        db.add(task)

    set_state_running(db, session_id, stage, progress=progress, message=message, commit=False)
    _update_workflow_role_state(
        db,
        session_id,
        role,
        status="running",
        task_id=task_id,
        progress=progress,
        user_id=user_id,
    )

    if commit:
        db.commit()
    return task


def set_agent_progress(
    db: DBSession,
    session_id: str,
    role: str,
    progress: float,
    message: Optional[str] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Update Task + State progress/message, and workflow heartbeat."""
    stage = _role_to_stage(role)
    if task_id:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.progress = progress
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)

    state = get_state_row(db, session_id, stage)
    if state and state.status in ("running", "pending"):
        state.progress = progress
        state.message = message
        state.updated_at = datetime.now(timezone.utc)
        db.add(state)

    _update_workflow_role_state(
        db,
        session_id,
        role,
        status="running",
        progress=progress,
        user_id=user_id,
    )

    if commit:
        db.commit()


def set_agent_ready(
    db: DBSession,
    session_id: str,
    role: str,
    task_id: str,
    content_hash: Optional[str] = None,
    message: Optional[str] = None,
    user_id: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Atomically mark a role as ready/success across Task, State and Workflow."""
    stage = _role_to_stage(role)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "success"
        task.progress = 1.0
        task.error_message = None
        task.updated_at = datetime.now(timezone.utc)
        db.add(task)

    set_state_ready(db, session_id, stage, content_hash=content_hash, commit=False)
    if message:
        state = get_state_row(db, session_id, stage)
        if state:
            state.message = message
            db.add(state)

    _update_workflow_role_state(
        db,
        session_id,
        role,
        status="success",
        progress=1.0,
        user_id=user_id,
    )

    if commit:
        db.commit()


def set_agent_error(
    db: DBSession,
    session_id: str,
    role: str,
    task_id: str,
    error_message: str,
    user_id: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Atomically mark a role as error across Task, State and Workflow."""
    stage = _role_to_stage(role)
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "error"
        task.progress = 1.0
        task.error_message = error_message
        task.updated_at = datetime.now(timezone.utc)
        db.add(task)

    set_state_error(db, session_id, stage, error_message=error_message, commit=False)

    _update_workflow_role_state(
        db,
        session_id,
        role,
        status="error",
        error_message=error_message,
        progress=1.0,
        user_id=user_id,
    )

    if commit:
        db.commit()


# ── Stale / stuck task healing ──

def heal_stuck_agent_states(
    db: DBSession,
    session_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Mark stuck running/pending Task/State/Workflow rows as error.

    Called on startup and from processing-status queries so a restarted backend
    never presents dead daemon threads as still running.
    """
    now = now or datetime.now(timezone.utc)
    timeout = timedelta(seconds=AGENT_TIMEOUT_SECONDS)
    heartbeat_timeout = timedelta(seconds=AGENT_HEARTBEAT_SECONDS)
    counts = {"tasks": 0, "states": 0, "workflows": 0}

    # Heal stuck tasks. Running tasks are kept alive by AgentRunner's heartbeat
    # (every 5s), so a running task older than the heartbeat window is fake-running.
    # Pending tasks may sit in the Celery queue, so use the full timeout.
    task_query = db.query(Task).filter(Task.status.in_(["pending", "running"]))
    if session_id:
        task_query = task_query.filter(Task.session_id == session_id)
    for task in task_query.all():
        updated_at = task.updated_at
        if updated_at is None:
            updated_at = task.created_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        task_timeout = heartbeat_timeout if task.status == "running" else timeout
        if now - updated_at > task_timeout:
            task.status = "error"
            task.progress = 1.0
            task.error_message = INTERRUPTED_MESSAGE
            task.updated_at = now
            counts["tasks"] += 1
            logger.warning(
                "healed_stuck_task task_id=%s session_id=%s age=%ss",
                task.id,
                task.session_id,
                int((now - updated_at).total_seconds()),
            )

    # Heal stuck processing states
    state_query = db.query(SessionProcessingState).filter(
        SessionProcessingState.status.in_(["pending", "running"])
    )
    if session_id:
        state_query = state_query.filter(SessionProcessingState.session_id == session_id)
    for state in state_query.all():
        updated_at = state.updated_at
        if updated_at is None:
            updated_at = state.created_at or now
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if now - updated_at > timeout:
            state.status = "error"
            state.progress = 1.0
            state.error_message = INTERRUPTED_MESSAGE
            state.message = None
            state.updated_at = now
            counts["states"] += 1
            logger.warning(
                "healed_stuck_state session_id=%s stage=%s age=%ss",
                state.session_id,
                state.stage,
                int((now - updated_at).total_seconds()),
            )

    # Heal stuck workflows
    workflow_query = db.query(AgentWorkflow).filter(
        AgentWorkflow.status.in_(["pending", "running"])
    )
    if session_id:
        workflow_query = workflow_query.filter(AgentWorkflow.session_id == session_id)
    for workflow in workflow_query.all():
        updated_at = workflow.updated_at
        if updated_at is None:
            updated_at = workflow.created_at or now
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        last_heartbeat = workflow.last_heartbeat_at
        if last_heartbeat and last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)

        # A running workflow is dead if it hasn't been touched at all for the
        # full timeout, or if it has a heartbeat but it is stale.
        stale_by_update = now - updated_at > timeout
        stale_by_heartbeat = (
            workflow.status == "running"
            and last_heartbeat is not None
            and now - last_heartbeat > heartbeat_timeout
            and now - updated_at > timeout
        )
        if stale_by_update or stale_by_heartbeat:
            workflow.status = "error"
            workflow.updated_at = now
            workflow.finished_at = now
            # Mark all still-running roles as interrupted
            from sqlalchemy.orm.attributes import flag_modified

            new_states = dict(workflow.role_states)
            for role, role_state in new_states.items():
                if role_state.get("status") in ("pending", "running"):
                    role_state["status"] = "error"
                    role_state["error_message"] = INTERRUPTED_MESSAGE
                    role_state["progress"] = 1.0
            workflow.role_states = new_states
            flag_modified(workflow, "role_states")
            counts["workflows"] += 1
            logger.warning(
                "healed_stuck_workflow workflow_id=%s session_id=%s age=%ss",
                workflow.id,
                workflow.session_id,
                int((now - updated_at).total_seconds()),
            )

    if any(counts.values()):
        db.commit()
    return counts
