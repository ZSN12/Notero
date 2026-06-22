"""Agent dispatch utilities shared by API endpoints and orchestrator.

This module exists to break the circular dependency between the orchestrator
(which needs to dispatch agents) and the agent thread runner (which needs to
notify the orchestrator when an agent completes).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.core.database import SessionLocal
from app.models import Task

logger = logging.getLogger(__name__)

from app.config import AGENTS_SYNC, AGENTS_USE_CELERY
from app.core.task_runner import run_agent_task

# In tests, run the agent synchronously so mocks are deterministic and threads
# cannot leak across test cases.
_RUN_AGENTS_SYNCHRONOUSLY = AGENTS_SYNC
# Production defaults to Celery/Redis; set AGENTS_USE_CELERY=0 to force threads.
_USE_CELERY_FOR_AGENTS = AGENTS_USE_CELERY


def _celery_workers_available(timeout: float = 1.0) -> bool:
    """Return True if at least one Celery worker is online.

    ``run_agent.delay()`` only means the task was accepted by the broker; if no
    worker is running the task will sit in the queue forever. This check is
    used to fall back to local threads when Celery is configured but not staffed.
    """
    try:
        from app.core.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=timeout)
        stats = inspector.stats()
        return bool(stats)
    except Exception:
        return False


def _run_agent_thread(
    session_id: str,
    user_id: str,
    role: str,
    task_id: str,
    db: Optional[DBSession] = None,
) -> None:
    """Thread worker: owns a fresh DB session and runs one agent to completion.

    When ``db`` is provided (e.g. synchronous inline execution from the
    orchestrator) the caller's session is reused and not closed. This keeps
    nested-transaction test harnesses and the orchestrator in the same
    transaction context.
    """
    owned_session = db is None
    db = db or SessionLocal()
    try:
        from app.agents.runner import AgentRunner
        runner = AgentRunner()
        result = runner.run(session_id, user_id, role, task_id, db)

        # Notify orchestrator unless the task was skipped as already running.
        # Skipped tasks will notify via the original execution path.
        if not result.skipped:
            try:
                from app.agents.orchestrator import on_agent_completed
                on_agent_completed(
                    session_id, user_id, role, result.success, result.error_message,
                    db=db if not owned_session else None,
                )
            except Exception:
                logger.exception(
                    "orchestrator_notify_failed session_id=%s role=%s task_id=%s",
                    session_id, role, task_id,
                )
    except Exception as e:
        logger.exception(
            "agent_thread_failed session_id=%s role=%s task_id=%s",
            session_id, role, task_id,
        )
        # Last-resort notification so the workflow does not hang.
        try:
            from app.agents.orchestrator import on_agent_completed
            on_agent_completed(
                session_id, user_id, role, False, str(e),
                db=db if not owned_session else None,
            )
        except Exception:
            logger.exception(
                "orchestrator_notify_failed session_id=%s role=%s task_id=%s",
                session_id, role, task_id,
            )
    finally:
        if owned_session:
            db.close()


def dispatch_agent_task(
    session_id: str,
    user_id: str,
    role: str,
    task_id: str,
    db: Optional[DBSession] = None,
) -> None:
    """Start an agent task.

    Production defaults to Celery/Redis so that slow LLM calls do not block the
    API process. Set ``AGENTS_USE_CELERY=0`` to force in-process daemon threads,
    or ``AGENTS_SYNC=1`` for synchronous inline execution (used in tests).

    ``db`` is only used for synchronous inline execution (e.g. from the
    orchestrator or tests); async paths always create their own session.
    """
    if _RUN_AGENTS_SYNCHRONOUSLY:
        _run_agent_thread(session_id, user_id, role, task_id, db=db)
        return

    if _USE_CELERY_FOR_AGENTS:
        if _celery_workers_available():
            try:
                from app.tasks.agent_tasks import run_agent
                run_agent.delay(session_id, user_id, role, task_id)
                logger.info(
                    "agent_dispatched_to_celery session_id=%s role=%s task_id=%s",
                    session_id, role, task_id,
                )
                return
            except Exception:
                logger.warning(
                    "celery_dispatch_failed_falling_back_to_thread session_id=%s role=%s task_id=%s",
                    session_id,
                    role,
                    task_id,
                    exc_info=True,
                )
        else:
            logger.warning(
                "no_celery_workers_available_falling_back_to_thread session_id=%s role=%s task_id=%s",
                session_id,
                role,
                task_id,
            )

    run_agent_task(
        target=lambda: _run_agent_thread(session_id, user_id, role, task_id),
        daemon=True,
    )
