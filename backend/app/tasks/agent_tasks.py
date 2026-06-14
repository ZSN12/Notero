"""Celery tasks for agent execution.

Replaces the previous threading-based task runner with a proper task queue.
"""

import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models import Task, User, Session as DBSession, Notebook
from app.agents import get_agent, AgentContext
from app.services.state_service import (
    set_running as set_state_running,
    set_ready as set_state_ready,
    set_error as set_state_error,
)
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


def _role_to_stage(role: str) -> str:
    return "quiz_bank" if role == "quiz" else role


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_agent(self, session_id: str, user_id: str, role: str, task_id: str) -> dict:
    """Run a single agent in a Celery worker with its own DB session.

    Retries up to 2 times on failure.
    """
    db = SessionLocal()
    stage = _role_to_stage(role)
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not task or not user:
            logger.error("agent_task_missing_prereqs task_id=%s user_id=%s", task_id, user_id)
            return {"status": "error", "error": "Missing prerequisites"}

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

        from app.models import Note
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
            return {"status": "error", "error": "Task lost"}

        if result.success:
            task.status = "success"
            task.progress = 1.0
            task.error_message = None
            current_hash = _compute_session_content_hash(note)
            set_state_ready(db, session_id, stage, content_hash=current_hash, commit=False)
            db.commit()
            return {"status": "success", "task_id": task.id, "data": result.data}

        task.status = "error"
        task.progress = 1.0
        task.error_message = result.error_message or "未知错误"
        set_state_error(db, session_id, stage, error_message=result.error_message or "未知错误", commit=False)
        db.commit()
        raise ValueError(task.error_message)

    except Exception as exc:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "error"
            task.progress = 1.0
            task.error_message = str(exc)
            db.commit()
        set_state_error(db, session_id, stage, error_message=str(exc), commit=False)
        db.commit()
        logger.exception("agent_task_failed session_id=%s role=%s", session_id, role)
        # Retry on transient failures
        try:
            self.retry(exc=exc)
        except Exception:
            return {"status": "error", "error": str(exc)}
    finally:
        db.close()
