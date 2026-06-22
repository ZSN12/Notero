"""API endpoints for the multi-agent pipeline.

Provides:
- Run all agents for a session in parallel
- Run a single agent
- Query agent task statuses
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents import AgentContext, get_agent, list_agents
from app.core.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.core.locks import get_session_task_lock
from app.models import AgentWorkflow, Notebook, Note, Session as DBSession, Task, User
from app.config import AGENT_HEARTBEAT_SECONDS, AGENT_TIMEOUT_SECONDS
from app.services.vector_service import _compute_session_content_hash
from app.services.note_utils import get_canonical_note_text
from app.services.state_service import (
    set_running as set_state_running,
    set_ready as set_state_ready,
    set_error as set_state_error,
    set_queued as set_state_queued,
    get_state,
    get_session_processing_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


from app.agents.orchestrator import (
    AgentWorkflowOrchestrator,
    AGENT_DEPENDENCIES,
    start_workflow,
    _expand_roles,
)


class RunAgentsRequest(BaseModel):
    roles: list[str] | None = None
    force: bool = False


# ── Helpers ──

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
    """Return True when an AI-finalized transcript and vector index are ready."""
    status = get_session_processing_status(db, session_id)
    stages = status.get("stages", {})
    vector_ok = stages.get("vector_index", {}).get("status") == "ready"
    transcript_status = stages.get("transcript_finalize", {}).get("status")
    transcript_ok = transcript_status == "ready"
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
            target_roles = ["transcript", "mindmap", "quiz"]
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

        lock = get_session_task_lock(session_id, "run_all")
        with lock:
            db.expire_all()

            # Reuse active tasks and skip roles whose output is already fresh.
            initial_role_states: dict[str, dict] = {}

            # Include upstream dependencies so the orchestrator can dispatch them
            # before downstream agents.
            expanded_roles = _expand_roles(target_roles, AGENT_DEPENDENCIES)
            for role in expanded_roles:
                task_type = f"agent_{role}"
                active = _get_active_task(session_id, task_type, db)
                if active and _is_active_task_usable(active):
                    initial_role_states[role] = {"status": "running", "task_id": active.id}
                    continue
                if active:
                    _mark_task_stale(db, active, role, session_id)
                agent = get_agent(role)
                role_force = force and role in target_roles
                ready = _maybe_return_ready_or_stale(
                    session_id, role, agent, note, db, user, notebook_obj, force=role_force
                )
                if ready:
                    _ensure_stage_ready_on_reuse(session_id, role, note, db)
                    initial_role_states[role] = {"status": "success"}
                    continue
                initial_role_states[role] = {"status": "pending"}

            has_pending = any(
                state.get("status") == "pending" for state in initial_role_states.values()
            )
            has_running = any(
                state.get("status") == "running" for state in initial_role_states.values()
            )
            if not has_pending and not has_running:
                logger.info(
                    "auto_run_agents_skipped session_id=%s reason=all_fresh",
                    session_id,
                )
                return {"session_id": session_id, "reused": True}

            workflow = start_workflow(
                session_id,
                user_id,
                expanded_roles,
                dependencies=AGENT_DEPENDENCIES,
                role_states=initial_role_states,
                db=db,
            )
            if not workflow:
                logger.error("auto_run_agents_workflow_create_failed session_id=%s", session_id)
                return None

        db.expire_all()
        workflow_states = dict(workflow.role_states)
        agents_by_role: dict[str, dict] = {}
        # Only report the roles the caller originally requested; upstream
        # dependencies expanded by the orchestrator are an implementation detail.
        for role in target_roles:
            state = workflow_states.get(role, {})
            task_id = state.get("task_id")
            task = None
            if task_id:
                task = db.query(Task).filter(Task.id == task_id).first()
            agents_by_role[role] = {
                "role": role,
                "task_id": task_id,
                "status": state.get("status", "pending"),
                "progress": float(task.progress or 0.0) if task else 0.0,
                "error": task.error_message if task else None,
            }

        result = {
            "workflow_id": workflow.id,
            "session_id": session_id,
            "agents": list(agents_by_role.values()),
        }
        return result
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


def _is_active_task_usable(task: Task) -> bool:
    """Return True if an active task is still likely being worked on.

    A running task without a recent heartbeat is a stale/fake-running task
    left behind by a crashed worker or a pre-fix deployment. A pending task
    that has sat for the full timeout is also considered lost.
    """
    updated_at = task.updated_at or task.created_at
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - updated_at
    if task.status == "running":
        return age <= timedelta(seconds=AGENT_HEARTBEAT_SECONDS)
    return age <= timedelta(seconds=AGENT_TIMEOUT_SECONDS)


def _mark_task_stale(db: Session, task: Task, role: str, session_id: str) -> None:
    """Mark a stale active task as error so the user can retry."""
    from app.services.agent_state_service import INTERRUPTED_MESSAGE, set_agent_error

    task.status = "error"
    task.progress = 1.0
    task.error_message = INTERRUPTED_MESSAGE
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    # Best-effort state update; the role may not have a state row yet.
    try:
        set_agent_error(
            db,
            session_id,
            role,
            task.id,
            INTERRUPTED_MESSAGE,
            commit=False,
        )
    except Exception:
        logger.exception(
            "mark_task_stale_state_failed session_id=%s role=%s task_id=%s",
            session_id,
            role,
            task.id,
        )
    db.commit()


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
    if role == "quiz":
        return "quiz_bank"
    if role == "transcript":
        return "transcript_organize"
    return role


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

    content_text = get_canonical_note_text(note, include_ppt=True)
    if not content_text.strip():
        raise HTTPException(status_code=400, detail="No indexable content in note")

    roles = body.roles if body and body.roles else list_agents()
    force = body.force if body else False
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
    lock = get_session_task_lock(session_id, "run_all")
    with lock:
        db.expire_all()

        # Reuse active tasks and skip roles whose output is already fresh.
        active_tasks_info: list[dict] = []
        ready_agents_info: list[dict] = []
        initial_role_states: dict[str, dict] = {}
        notebook_obj = _notebook_for_note(note, db)

        # Include upstream dependencies so the orchestrator can dispatch them
        # before downstream agents.
        expanded_roles = _expand_roles(roles, AGENT_DEPENDENCIES)
        for role in expanded_roles:
            task_type = f"agent_{role}"
            active = _get_active_task(session_id, task_type, db)
            if active and _is_active_task_usable(active):
                active_tasks_info.append({
                    "role": role,
                    "task_id": active.id,
                    "status": active.status,
                    "progress": float(active.progress or 0.0),
                    "error": active.error_message,
                })
                initial_role_states[role] = {"status": "running", "task_id": active.id}
                continue
            if active:
                _mark_task_stale(db, active, role, session_id)
            agent = get_agent(role)
            role_force = force and role in roles
            ready = _maybe_return_ready_or_stale(
                session_id, role, agent, note, db, current_user, notebook_obj, force=role_force
            )
            if ready:
                _ensure_stage_ready_on_reuse(session_id, role, note, db)
                ready_agents_info.append({
                    "role": role,
                    "status": "ready",
                    "data": ready.get("data"),
                })
                initial_role_states[role] = {"status": "success"}
                continue
            initial_role_states[role] = {"status": "pending"}

        has_pending = any(
            state.get("status") == "pending" for state in initial_role_states.values()
        )
        has_running = any(
            state.get("status") == "running" for state in initial_role_states.values()
        )
        if not has_pending and not has_running:
            response.status_code = status.HTTP_200_OK
            return {
                "workflow_id": "reused",
                "session_id": session_id,
                "agents": active_tasks_info + ready_agents_info,
                "reused": True,
            }

        workflow = start_workflow(
            session_id,
            current_user.id,
            expanded_roles,
            dependencies=AGENT_DEPENDENCIES,
            role_states=initial_role_states,
            db=db,
        )
        if not workflow:
            raise HTTPException(status_code=500, detail="Failed to create agent workflow")

        # Mark roles that are pending only because they are waiting for upstream
        # dependencies as queued, so the UI can show "waiting" instead of a fake
        # "running" spinner. Roles that are ready to execute immediately will be
        # dispatched by the orchestrator and transitioned to running by AgentRunner.
        pending_roles = [
            role for role, state in initial_role_states.items()
            if state.get("status") == "pending"
        ]
        for role in pending_roles:
            set_state_queued(
                db,
                session_id,
                _role_to_stage(role),
                message="等待前置任务执行",
                commit=False,
            )
        if pending_roles:
            db.commit()

    # Build response from the workflow state. Task rows are created by the
    # orchestrator; refresh our view so we can include their IDs.
    db.expire_all()
    workflow_states = dict(workflow.role_states)
    agents_by_role: dict[str, dict] = {}
    for role in expanded_roles:
        state = workflow_states.get(role, {})
        task_id = state.get("task_id")
        task = None
        if task_id:
            task = db.query(Task).filter(Task.id == task_id).first()
        agents_by_role[role] = {
            "role": role,
            "task_id": task_id,
            "status": state.get("status", "pending"),
            "progress": float(task.progress or 0.0) if task else 0.0,
            "error": task.error_message if task else None,
        }

    # Reused active/ready entries take precedence so the caller sees the most
    # accurate state for roles that were already in progress or cached.
    for info in ready_agents_info + active_tasks_info:
        agents_by_role[info["role"]] = info

    result = {
        "workflow_id": workflow.id,
        "session_id": session_id,
        "agents": list(agents_by_role.values()),
    }
    if active_tasks_info or ready_agents_info:
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


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the state of a single agent workflow."""
    workflow = (
        db.query(AgentWorkflow)
        .filter(AgentWorkflow.id == workflow_id)
        .filter(AgentWorkflow.user_id == current_user.id)
        .first()
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "workflow_id": workflow.id,
        "session_id": workflow.session_id,
        "status": workflow.status,
        "roles": workflow.roles,
        "dependencies": workflow.dependencies,
        "role_states": workflow.role_states,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        "finished_at": workflow.finished_at.isoformat() if workflow.finished_at else None,
        "last_heartbeat_at": workflow.last_heartbeat_at.isoformat() if workflow.last_heartbeat_at else None,
    }


@router.get("/session/{session_id}/workflows")
def get_session_workflows(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return agent workflows for a session, newest first."""
    session = _get_user_session(session_id, current_user, db)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    workflows = (
        db.query(AgentWorkflow)
        .filter(AgentWorkflow.session_id == session_id)
        .filter(AgentWorkflow.user_id == current_user.id)
        .order_by(AgentWorkflow.created_at.desc())
        .all()
    )

    return {
        "session_id": session_id,
        "workflows": [
            {
                "workflow_id": w.id,
                "status": w.status,
                "roles": w.roles,
                "role_states": w.role_states,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "finished_at": w.finished_at.isoformat() if w.finished_at else None,
            }
            for w in workflows
        ],
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
