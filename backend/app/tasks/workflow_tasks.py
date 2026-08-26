"""Celery tasks for workflow maintenance.

These tasks are typically scheduled via Celery beat.
"""

import logging
from datetime import datetime, timezone

from celery.exceptions import Retry
from sqlalchemy.orm import Session as DBSession

from sqlalchemy.orm.attributes import flag_modified

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models import AgentWorkflow, Task
from app.services.agent_state_service import INTERRUPTED_MESSAGE

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    import os

    raw = os.getenv(name, "")
    try:
        return float(raw)
    except ValueError:
        return default


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def sweep_stale_workflows(self) -> dict:
    """Mark running workflow roles as error when their heartbeat is stale.

    A workflow or role is considered stale when no heartbeat has been received
    within ``AGENT_TIMEOUT_SECONDS`` (default 600s). This prevents workflows
    from remaining in ``running`` forever when a worker dies or an LLM call
    hangs.

    The Task row (source of truth) is marked error as well so the UI reads a
    consistent failure from either representation.
    """
    timeout_seconds = _env_float("AGENT_TIMEOUT_SECONDS", 600.0)
    now = datetime.now(timezone.utc)
    cutoff = now - __import__("datetime").timedelta(seconds=timeout_seconds)
    db = SessionLocal()
    try:
        stale_workflows = (
            db.query(AgentWorkflow)
            .filter(AgentWorkflow.status == "running")
            .filter(
                (AgentWorkflow.last_heartbeat_at == None)  # noqa: E711
                | (AgentWorkflow.last_heartbeat_at < cutoff)
            )
            .all()
        )

        fixed = 0
        for workflow in stale_workflows:
            changed = _mark_stale_roles(workflow, cutoff, db=db)
            if changed:
                db.commit()
                fixed += 1

        return {
            "status": "success",
            "scanned": len(stale_workflows),
            "fixed": fixed,
        }
    except Retry:
        raise
    except Exception as exc:
        logger.exception("sweep_stale_workflows_failed")
        self.retry(exc=exc)
    finally:
        db.close()


def _mark_stale_roles(
    workflow: AgentWorkflow,
    cutoff: datetime,
    db: DBSession,
) -> bool:
    """Mark stale running roles in ``workflow`` as error. Return True if changed.

    The role state keeps only DAG fields (status/task_id); the linked Task is
    the source of truth for the error detail, so it is marked error too.
    """
    changed = False
    for role, state in list(workflow.role_states.items()):
        if state.get("status") != "running":
            continue
        heartbeat_at = state.get("heartbeat_at")
        if heartbeat_at:
            try:
                heartbeat_dt = datetime.fromisoformat(heartbeat_at)
            except ValueError:
                heartbeat_dt = None
        else:
            heartbeat_dt = None

        stale = heartbeat_dt is None or heartbeat_dt < cutoff

        if stale:
            logger.warning(
                "workflow_role_stale workflow_id=%s role=%s last_heartbeat=%s",
                workflow.id,
                role,
                heartbeat_at,
            )
            workflow.role_states[role]["status"] = "error"
            workflow.role_states = dict(workflow.role_states)
            flag_modified(workflow, "role_states")

            # Mark the linked Task (source of truth) as error too.
            task_id = state.get("task_id")
            if task_id:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task and task.status in ("pending", "running"):
                    task.status = "error"
                    task.progress = 1.0
                    task.error_message = INTERRUPTED_MESSAGE
                    task.updated_at = now = datetime.now(timezone.utc)
                    db.add(task)
            changed = True

    if changed:
        # Finalize workflow status manually; no new roles should be dispatched
        # because stale roles are now in error state. Once any role fails the
        # workflow cannot fully succeed, so mark it as error.
        states = list(workflow.role_states.values())
        any_error = any(s.get("status") == "error" for s in states)
        all_terminal = all(s.get("status") in ("success", "error") for s in states)
        if any_error:
            workflow.status = "error"
            workflow.finished_at = cutoff
        elif all_terminal:
            workflow.status = "success"
            workflow.finished_at = cutoff

    return changed
