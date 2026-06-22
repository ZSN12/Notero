"""Agent execution harness.

Provides a unified runner around ``BaseAgent.run()`` that handles:
- context loading and validation
- task / processing-state / workflow lifecycle
- configurable retries with exponential backoff
- per-role concurrency limiting
- execution-time metrics and structured logging
- error classification

This keeps agent subclasses focused on prompt/render/parse logic.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.agents import AgentContext, AgentResult, get_agent
from app.agents.base import BaseAgent
from app.config import AGENTS_SYNC
from app.core.exceptions import LLMTimeoutError, LLMUnavailableError
from app.middleware.metrics import observe_agent_error, observe_agent_execution
from app.models import Notebook, Note, Session as DBSessionModel, Task, User
from app.services.agent_state_service import (
    INTERRUPTED_MESSAGE,
    set_agent_error,
    set_agent_progress,
    set_agent_ready,
    set_agent_running,
    update_state_heartbeat,
    update_task_heartbeat,
    update_workflow_heartbeat,
)
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class AgentExecutionConfig:
    """Runtime configuration for agent execution."""

    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    retry_backoff: float = 2.0
    max_total_timeout: Optional[float] = 300.0
    per_llm_timeout: float = 120.0
    max_concurrency_per_role: Optional[int] = None

    @classmethod
    def from_env(cls) -> "AgentExecutionConfig":
        """Load configuration from environment variables."""
        return cls(
            max_retries=_env_int("AGENT_MAX_RETRIES", cls.max_retries),
            retry_delay_seconds=_env_float("AGENT_RETRY_DELAY_SECONDS", cls.retry_delay_seconds),
            retry_backoff=_env_float("AGENT_RETRY_BACKOFF", cls.retry_backoff),
            max_total_timeout=_env_float("AGENT_MAX_TOTAL_TIMEOUT", cls.max_total_timeout) if os.getenv("AGENT_MAX_TOTAL_TIMEOUT") else cls.max_total_timeout,
            per_llm_timeout=_env_float("AGENT_PER_LLM_TIMEOUT", cls.per_llm_timeout),
            max_concurrency_per_role=_env_int("AGENT_MAX_CONCURRENCY_PER_ROLE", 0) or None,
        )


class AgentRunner:
    """Uniform execution harness for notero agents."""

    def __init__(self, config: Optional[AgentExecutionConfig] = None):
        self.config = config or AgentExecutionConfig.from_env()
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._semaphores_lock = threading.Lock()

    def _get_semaphore(self, role: str) -> Optional[threading.Semaphore]:
        """Return a per-role semaphore if concurrency limiting is enabled."""
        limit = self.config.max_concurrency_per_role
        if not limit:
            return None
        sem = self._semaphores.get(role)
        if sem is None:
            with self._semaphores_lock:
                sem = self._semaphores.get(role)
                if sem is None:
                    sem = threading.Semaphore(limit)
                    self._semaphores[role] = sem
        return sem

    def _classify_error(self, exc: Exception) -> str:
        """Classify an exception for metrics/logging."""
        msg = str(exc).lower()
        raw = str(exc)
        if isinstance(exc, LLMTimeoutError) or "timeout" in msg or "timed out" in msg or "超时" in raw:
            return "timeout"
        if isinstance(exc, LLMUnavailableError) or "unavailable" in msg:
            return "unavailable"
        if "截断" in raw or "finish_reason=length" in msg or "length" in msg:
            return "truncation"
        if "json" in msg or "格式无效" in raw:
            return "invalid_output"
        return "unknown"

    def _is_retryable(self, error_type: str) -> bool:
        """Return True if the error type warrants a retry."""
        return error_type in {"timeout", "unavailable"}

    def _load_context(
        self,
        db: DBSession,
        session_id: str,
        user_id: str,
        task_id: str,
    ) -> Optional[AgentContext]:
        """Load and validate all prerequisites for running an agent.

        Returns None if any prerequisite is missing, after logging the reason.
        """
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning("agent_runner_task_not_found task_id=%s", task_id)
            return None

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(
                "agent_runner_user_not_found session_id=%s user_id=%s",
                session_id,
                user_id,
            )
            return None

        session = (
            db.query(DBSessionModel)
            .filter(DBSessionModel.id == session_id)
            .join(Notebook)
            .filter(Notebook.user_id == user_id)
            .first()
        )
        if not session:
            logger.warning(
                "agent_runner_session_not_found session_id=%s user_id=%s",
                session_id,
                user_id,
            )
            return None

        note = db.query(Note).filter(Note.session_id == session_id).first()
        if not note:
            logger.warning(
                "agent_runner_note_not_found session_id=%s", session_id
            )
            return None

        notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
        if not notebook:
            logger.warning(
                "agent_runner_notebook_not_found session_id=%s", session_id
            )
            return None

        return AgentContext(
            session_id=session_id,
            user=user,
            db=db,
            note=note,
            session=session,
            notebook=notebook,
            task=task,
        )

    def _start_keepalive_heartbeat(
        self,
        task_id: str,
        session_id: str,
        role: str,
        user_id: str,
    ) -> tuple[threading.Event, threading.Thread]:
        """Start a background heartbeat that only keeps the task/state alive.

        The heartbeat runs in its own SQLAlchemy session so it never interferes
        with the main agent thread's transaction.
        """
        stop_event = threading.Event()
        stage = role
        if role == "quiz":
            stage = "quiz_bank"
        elif role == "transcript":
            stage = "transcript_organize"

        def _heartbeat():
            while not stop_event.wait(5.0):
                update_task_heartbeat(task_id)
                update_state_heartbeat(session_id, stage)
                update_workflow_heartbeat(session_id, user_id, role)

        thread = threading.Thread(target=_heartbeat, daemon=True)
        thread.start()
        return stop_event, thread

    def _check_idempotency(
        self,
        ctx: AgentContext,
        role: str,
    ) -> Optional[AgentResult]:
        """Return a result if the task should be skipped (already fresh or running).

        Returns ``None`` when the caller should proceed with execution.
        """
        agent = get_agent(role)
        heartbeat_seconds = _env_float("AGENT_HEARTBEAT_SECONDS", 60.0)
        now = datetime.now(timezone.utc)

        # If another worker is actively executing this task, do not duplicate it.
        if ctx.task.status == "running":
            updated_at = ctx.task.updated_at
            if updated_at and (now - updated_at).total_seconds() < heartbeat_seconds:
                logger.info(
                    "agent_runner_task_already_running session_id=%s role=%s task_id=%s",
                    ctx.session_id, role, ctx.task.id,
                )
                return AgentResult(
                    success=False,
                    error_message="Task is already running",
                    skipped=True,
                )

        # If the task already succeeded and the output is still fresh, reuse it.
        if ctx.task.status == "success":
            existing = agent.get_existing_output(ctx)
            if existing:
                stored_hash = existing.get("content_hash")
                if stored_hash:
                    current_hash = _compute_session_content_hash(ctx.note)
                    if stored_hash == current_hash:
                        logger.info(
                            "agent_runner_fresh_output_reused session_id=%s role=%s task_id=%s",
                            ctx.session_id, role, ctx.task.id,
                        )
                        return AgentResult(
                            success=True,
                            data=existing.get("data"),
                            skipped=True,
                        )

        return None

    def _execute_once(self, ctx: AgentContext, role: str, force: bool) -> AgentResult:
        """Invoke the agent once inside an optional concurrency limit."""
        agent = get_agent(role)
        ctx.force = force
        # Pass the per-LLM timeout down to the agent instance.
        agent.timeout = self.config.per_llm_timeout
        sem = self._get_semaphore(role)
        if sem is None:
            return agent.run(ctx)
        with sem:
            return agent.run(ctx)

    def run(
        self,
        session_id: str,
        user_id: str,
        role: str,
        task_id: str,
        db: DBSession,
        force: bool = False,
    ) -> AgentResult:
        """Run a single agent to completion with retries and metrics.

        The caller is responsible for opening/closing ``db``.
        """
        started = time.monotonic()
        ctx = self._load_context(db, session_id, user_id, task_id)
        if ctx is None:
            return AgentResult(
                success=False,
                error_message="Agent prerequisites missing",
            )

        idempotent = self._check_idempotency(ctx, role)
        if idempotent is not None:
            return idempotent

        set_agent_running(
            db,
            session_id,
            role,
            task_id,
            progress=0.1,
            message="准备内容",
            user_id=user_id,
        )

        # Keep-alive heartbeat so a long LLM call is not marked stale.
        # Disabled in synchronous/test mode where the caller shares a transaction.
        heartbeat_stop: Optional[threading.Event] = None
        heartbeat_thread: Optional[threading.Thread] = None
        if not AGENTS_SYNC:
            heartbeat_stop, heartbeat_thread = self._start_keepalive_heartbeat(
                task_id, session_id, role, user_id
            )

        def _stop_heartbeat():
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)

        last_error = "Unknown error"
        error_type = "unknown"
        attempt = 0

        try:
            while attempt <= self.config.max_retries:
                attempt += 1

                # Enforce the global wall-clock timeout before each attempt.
                if (
                    self.config.max_total_timeout is not None
                    and (time.monotonic() - started) > self.config.max_total_timeout
                ):
                    last_error = INTERRUPTED_MESSAGE
                    error_type = "timeout"
                    logger.warning(
                        "agent_runner_total_timeout session_id=%s role=%s task_id=%s elapsed=%s",
                        session_id,
                        role,
                        task_id,
                        int(time.monotonic() - started),
                    )
                    break

                try:
                    result = self._execute_once(ctx, role, force)
                    if result.success:
                        observe_agent_execution(
                            role=role,
                            duration_seconds=time.monotonic() - started,
                            status="success",
                            retries=attempt - 1,
                        )
                        logger.info(
                            "agent_runner_success session_id=%s role=%s task_id=%s "
                            "attempts=%s elapsed_ms=%s",
                            session_id,
                            role,
                            task_id,
                            attempt,
                            int((time.monotonic() - started) * 1000),
                        )
                        set_agent_ready(
                            db,
                            session_id,
                            role,
                            task_id,
                            content_hash=_compute_session_content_hash(ctx.note),
                            message=result.warning_message or "完成",
                            user_id=user_id,
                        )
                        return result

                    # Agent returned failure without raising.
                    last_error = result.error_message or "Agent returned failure"
                    error_type = self._classify_error(ValueError(last_error))
                    logger.warning(
                        "agent_runner_attempt_failed session_id=%s role=%s task_id=%s "
                        "attempt=%s error=%s error_type=%s",
                        session_id,
                        role,
                        task_id,
                        attempt,
                        last_error,
                        error_type,
                    )
                    if self._is_retryable(error_type) and attempt <= self.config.max_retries:
                        delay = self.config.retry_delay_seconds * (
                            self.config.retry_backoff ** (attempt - 1)
                        )
                        time.sleep(delay)
                        continue
                    break

                except Exception as exc:
                    db.rollback()
                    error_type = self._classify_error(exc)
                    last_error = str(exc)
                    logger.warning(
                        "agent_runner_attempt_failed session_id=%s role=%s task_id=%s "
                        "attempt=%s error=%s error_type=%s",
                        session_id,
                        role,
                        task_id,
                        attempt,
                        last_error,
                        error_type,
                    )
                    if self._is_retryable(error_type) and attempt <= self.config.max_retries:
                        delay = self.config.retry_delay_seconds * (
                            self.config.retry_backoff ** (attempt - 1)
                        )
                        time.sleep(delay)
                        continue
                    break

            observe_agent_error(role=role, error_type=error_type)
            observe_agent_execution(
                role=role,
                duration_seconds=time.monotonic() - started,
                status="error",
                retries=attempt - 1,
            )
            logger.error(
                "agent_runner_failed session_id=%s role=%s task_id=%s "
                "attempts=%s error_type=%s error=%s",
                session_id,
                role,
                task_id,
                attempt,
                error_type,
                last_error,
            )
            set_agent_error(db, session_id, role, task_id, last_error, user_id=user_id)
            return AgentResult(success=False, error_message=last_error)

        except Exception as exc:
            # Safety net for unexpected runner-internal errors.
            logger.exception(
                "agent_runner_unexpected_error session_id=%s role=%s task_id=%s",
                session_id,
                role,
                task_id,
            )
            observe_agent_error(role=role, error_type="runner_internal")
            observe_agent_execution(
                role=role,
                duration_seconds=time.monotonic() - started,
                status="error",
                retries=attempt - 1,
            )
            try:
                set_agent_error(db, session_id, role, task_id, f"Runner error: {exc}", user_id=user_id)
                return AgentResult(success=False, error_message=f"Runner error: {exc}")
            except Exception:
                return AgentResult(success=False, error_message=f"Runner error: {exc}")
        finally:
            _stop_heartbeat()
