"""Celery tasks for agent execution.

The actual execution logic lives in ``app.agents.runner.AgentRunner``;
this module only adapts Celery retries to the runner.
"""

import logging

from celery.exceptions import Retry

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.agents.runner import AgentRunner

logger = logging.getLogger(__name__)


def _is_retryable_error(message: str | None) -> bool:
    """Return True when an error is likely transient and worth requeuing."""
    if not message:
        return False
    text = message.lower()
    return any(
        keyword in text
        for keyword in ("timeout", "timed out", "unavailable", "connection", "network")
    )


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_agent(self, session_id: str, user_id: str, role: str, task_id: str) -> dict:
    """Run a single agent in a Celery worker.

    Retries are handled at two levels:
    - AgentRunner performs in-process retries for transient LLM errors.
    - Celery requeues the task for worker-level failures (crash, kill, etc.).
    """
    db = SessionLocal()
    try:
        runner = AgentRunner()
        result = runner.run(session_id, user_id, role, task_id, db)

        # If the task was already running elsewhere, do not notify or retry.
        if result.skipped:
            logger.info(
                "celery_agent_task_skipped session_id=%s role=%s task_id=%s reason=%s",
                session_id, role, task_id, result.error_message,
            )
            return {"status": "skipped", "task_id": task_id, "reason": result.error_message}

        # Notify orchestrator regardless of success/failure.
        try:
            from app.agents.orchestrator import on_agent_completed
            on_agent_completed(
                session_id, user_id, role, result.success, result.error_message
            )
        except Exception:
            logger.exception(
                "celery_orchestrator_notify_failed session_id=%s role=%s task_id=%s",
                session_id, role, task_id,
            )

        if result.success:
            return {"status": "success", "task_id": task_id, "data": result.data}

        logger.warning(
            "celery_agent_task_failed session_id=%s role=%s task_id=%s error=%s",
            session_id, role, task_id, result.error_message,
        )

        # AgentRunner already retried transient errors internally. Non-retryable
        # failures (invalid output, bad input) should fail fast.
        if _is_retryable_error(result.error_message):
            self.retry(exc=ValueError(result.error_message))
        return {"status": "error", "task_id": task_id, "error": result.error_message}

    except Retry:
        raise
    except Exception as exc:
        logger.exception(
            "celery_agent_task_exception session_id=%s role=%s task_id=%s",
            session_id, role, task_id,
        )
        self.retry(exc=exc)
    finally:
        db.close()
