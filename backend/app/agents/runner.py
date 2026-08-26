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
from app.agents.messaging import AgentEvent, EventType, get_event_bus
from app.agents.recovery import RecoveryPlanner, RecoveryAction
from app.agents.review import BaseReviewAgent, MindmapReviewAgent
from app.config import AGENTS_SYNC
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
from app.services.agent_trace_service import record_agent_event
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
    reflection_max_rounds: int = 3
    reflection_target_score: float = 0.80
    recovery_max_attempts: int = 3

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
            reflection_max_rounds=_env_int("AGENT_REFLECTION_MAX_ROUNDS", cls.reflection_max_rounds),
            reflection_target_score=_env_float("AGENT_REFLECTION_TARGET_SCORE", cls.reflection_target_score),
            recovery_max_attempts=_env_int("AGENT_RECOVERY_MAX_ATTEMPTS", cls.recovery_max_attempts),
        )


class AgentRunner:
    """Uniform execution harness for notero agents."""

    def __init__(self, config: Optional[AgentExecutionConfig] = None):
        self.config = config or AgentExecutionConfig.from_env()
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._semaphores_lock = threading.Lock()
        self.recovery_planner = RecoveryPlanner()

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
        from app.models import AgentWorkflow

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

        # Find the most recent running workflow for this session so events can
        # carry a workflow_id and the orchestrator can react to them.
        workflow = (
            db.query(AgentWorkflow)
            .filter(
                AgentWorkflow.session_id == session_id,
                AgentWorkflow.status == "running",
            )
            .order_by(AgentWorkflow.created_at.desc())
            .first()
        )
        workflow_id = workflow.id if workflow else None

        ctx = AgentContext(
            session_id=session_id,
            user=user,
            db=db,
            note=note,
            session=session,
            notebook=notebook,
            task=task,
        )
        ctx.workflow_id = workflow_id
        return ctx

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
        elif role == "study_planner":
            stage = "study_plan"

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
        agent.ctx = ctx
        # Pass the per-LLM timeout down to the agent instance.
        agent.timeout = self.config.per_llm_timeout
        sem = self._get_semaphore(role)
        if sem is None:
            return agent.run(ctx)
        with sem:
            return agent.run(ctx)

    def _publish_event(
        self,
        event_type: str,
        ctx: AgentContext,
        payload: dict,
    ) -> None:
        """Publish an agent event to the global event bus."""
        try:
            record_agent_event(
                ctx.db,
                session_id=ctx.session_id,
                user_id=ctx.user.id,
                workflow_id=getattr(ctx, "workflow_id", None),
                task_id=ctx.task.id if ctx.task else None,
                role=getattr(ctx, "_current_role", None),
                event_type=event_type,
                message=payload.get("message"),
                payload=payload,
            )
            get_event_bus().publish(
                AgentEvent(
                    event_type=event_type,
                    session_id=ctx.session_id,
                    role=getattr(ctx, "_current_role", None),
                    workflow_id=getattr(ctx, "workflow_id", None),
                    task_id=ctx.task.id if ctx.task else None,
                    user_id=ctx.user.id if ctx.user else None,
                    payload=payload,
                )
            )
        except Exception:
            logger.exception("agent_runner_publish_event_failed event_type=%s", event_type)

    def _apply_recovery_action(self, ctx: AgentContext, action) -> None:
        """Apply context mutations requested by a recovery strategy."""
        for key, value in action.context_updates.items():
            if hasattr(ctx, key):
                setattr(ctx, key, value)
                logger.info(
                    "recovery_context_update key=%s value=%s strategy=%s",
                    key,
                    value,
                    action.strategy_name,
                )
            else:
                logger.warning(
                    "recovery_context_update_ignored key=%s strategy=%s",
                    key,
                    action.strategy_name,
                )

    def _get_reviewer_for_role(self, role: str) -> Optional[BaseReviewAgent]:
        """Return a review agent for the given role, if reflection is supported."""
        if role == "mindmap":
            return MindmapReviewAgent()
        return None

    def _execute_with_reflection(
        self,
        ctx: AgentContext,
        role: str,
        force: bool,
    ) -> AgentResult:
        """Run an agent inside a review/reflection loop.

        Each generation attempt is reviewed. If the output is not acceptable,
        the reviewer's improvement prompt is fed back into the next attempt.
        The best-scoring output is returned and persisted.
        """
        reviewer = self._get_reviewer_for_role(role)
        if reviewer is None:
            return self._execute_once(ctx, role, force)

        agent = get_agent(role)
        agent.timeout = self.config.per_llm_timeout
        source_max_length = ctx.input_length_limit or 12000
        source_material = ctx.get_content_text_for_agent(max_length=source_max_length)

        history = []
        best_result: Optional[AgentResult] = None
        best_score = 0.0
        best_output: Optional[dict] = None

        for round_no in range(1, self.config.reflection_max_rounds + 1):
            set_agent_progress(
                db=ctx.db,
                session_id=ctx.session_id,
                stage=role,
                progress=min(0.95, 0.25 + 0.7 * (round_no / self.config.reflection_max_rounds)),
                message=f"生成并审查导图中（第 {round_no}/{self.config.reflection_max_rounds} 轮）",
                task_id=ctx.task.id if ctx.task else None,
                user_id=ctx.user.id,
            )

            result = self._execute_once(ctx, role, force)
            if not result.success or not result.data:
                logger.warning(
                    "agent_runner_reflection_generation_failed session_id=%s role=%s round=%s error=%s",
                    ctx.session_id,
                    role,
                    round_no,
                    result.error_message,
                )
                if best_result is not None:
                    break
                return result

            output = result.data
            review = reviewer.review(source_material, output, history)

            logger.info(
                "agent_runner_reflection_round session_id=%s role=%s round=%s score=%s acceptable=%s stop=%s",
                ctx.session_id,
                role,
                round_no,
                review.score,
                review.is_acceptable,
                review.should_stop,
            )

            # Detect upstream-rooted quality issues and broadcast them so the
            # orchestrator can trigger upstream repair.
            if not review.is_acceptable:
                coverage_issues = [
                    i for i in review.issues if i.dimension == "coverage"
                ]
                if coverage_issues:
                    self._publish_event(
                        EventType.QUALITY_ISSUE,
                        ctx,
                        {
                            "role": role,
                            "task_id": ctx.task.id if ctx.task else None,
                            "upstream_role": "transcript",
                            "issue": coverage_issues[0].description,
                            "score": review.score,
                            "round": round_no,
                        },
                    )

            if review.score > best_score:
                best_score = review.score
                best_output = output
                best_result = result

            if review.is_acceptable:
                return AgentResult(success=True, data=output)

            if review.should_stop or round_no >= self.config.reflection_max_rounds:
                break

            ctx.review_feedback = review.improvement_prompt
            history.append(review)

        # Persist the best output if it is not the last generated one.
        if best_output is not None:
            if best_output is not result.data:
                try:
                    content_hash = _compute_session_content_hash(ctx.note)
                    agent.save_to_vocabulary(
                        ctx,
                        best_output,
                        extra={"content_hash": content_hash},
                    )
                    ctx.db.commit()
                    logger.info(
                        "agent_runner_reflection_persisted_best session_id=%s role=%s score=%s",
                        ctx.session_id,
                        role,
                        best_score,
                    )
                except Exception:
                    logger.exception(
                        "agent_runner_reflection_persist_best_failed session_id=%s role=%s",
                        ctx.session_id,
                        role,
                    )
            return AgentResult(success=True, data=best_output)

        return AgentResult(
            success=False,
            error_message="Reflection loop did not produce a valid output",
        )

    def run(
        self,
        session_id: str,
        user_id: str,
        role: str,
        task_id: str,
        db: DBSession,
        force: bool = False,
        reflection: bool = False,
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

        # Stash the current role on context so event publishing can use it.
        ctx._current_role = role

        idempotent = self._check_idempotency(ctx, role)
        if idempotent is not None:
            record_agent_event(
                db,
                session_id=session_id,
                user_id=user_id,
                workflow_id=getattr(ctx, "workflow_id", None),
                task_id=task_id,
                role=role,
                event_type="agent_skipped",
                message=idempotent.error_message or "复用已有任务或新鲜输出",
                payload={
                    "role": role,
                    "task_id": task_id,
                    "skipped": True,
                    "success": idempotent.success,
                    "reason": idempotent.error_message or "fresh_output",
                },
            )
            db.commit()
            return idempotent

        self._publish_event(
            EventType.AGENT_STARTED,
            ctx,
            {
                "role": role,
                "task_id": task_id,
                "reflection": reflection,
                "message": "Agent 开始运行",
            },
        )

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
        recovery_attempts = 0
        recovery_history = []

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
                    if reflection:
                        result = self._execute_with_reflection(ctx, role, force)
                    else:
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
                            "attempts=%s recovery_attempts=%s elapsed_ms=%s",
                            session_id,
                            role,
                            task_id,
                            attempt,
                            recovery_attempts,
                            int((time.monotonic() - started) * 1000),
                        )
                        self._publish_event(
                            EventType.AGENT_COMPLETED,
                            ctx,
                            {
                                "role": role,
                                "task_id": task_id,
                                "attempts": attempt,
                                "recovery_attempts": recovery_attempts,
                                "reflection": reflection,
                            },
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
                    error = ValueError(result.error_message or "Agent returned failure")
                    last_error = str(error)
                    error_type = self.recovery_planner.classifier.classify(error).type
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

                    # Self-healing: ask the recovery planner for a fix strategy.
                    if recovery_attempts < self.config.recovery_max_attempts:
                        action = self.recovery_planner.plan(ctx, error, recovery_history)
                        if action:
                            recovery_attempts += 1
                            recovery_history.append(action)
                            logger.info(
                                "agent_runner_recovery_action session_id=%s role=%s task_id=%s "
                                "recovery_attempt=%s strategy=%s retry=%s reason=%s",
                                session_id,
                                role,
                                task_id,
                                recovery_attempts,
                                action.strategy_name,
                                action.retry,
                                action.reason,
                            )
                            self._publish_event(
                                EventType.RECOVERY_ATTEMPTED,
                                ctx,
                                {
                                    "role": role,
                                    "task_id": task_id,
                                    "recovery_attempt": recovery_attempts,
                                    "strategy": action.strategy_name,
                                    "retry": action.retry,
                                    "reason": action.reason,
                                    "context_updates": action.context_updates,
                                },
                            )
                            if action.delay_seconds:
                                time.sleep(action.delay_seconds)
                            if action.retry:
                                self._apply_recovery_action(ctx, action)
                                set_agent_progress(
                                    db,
                                    session_id,
                                    role,
                                    progress=min(0.9, 0.2 + 0.15 * recovery_attempts),
                                    message=f"自动修复中：{action.reason}",
                                    task_id=ctx.task.id if ctx.task else None,
                                    user_id=user_id,
                                )
                                continue
                            last_error = f"{last_error} (recovery stopped: {action.reason})"
                            break

                    # No recovery strategy or recovery refused to retry.
                    break

                except Exception as exc:
                    db.rollback()
                    error_type = self.recovery_planner.classifier.classify(exc).type
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

                    # Self-healing: ask the recovery planner for a fix strategy.
                    if recovery_attempts < self.config.recovery_max_attempts:
                        action = self.recovery_planner.plan(ctx, exc, recovery_history)
                        if action:
                            recovery_attempts += 1
                            recovery_history.append(action)
                            logger.info(
                                "agent_runner_recovery_action session_id=%s role=%s task_id=%s "
                                "recovery_attempt=%s strategy=%s retry=%s reason=%s",
                                session_id,
                                role,
                                task_id,
                                recovery_attempts,
                                action.strategy_name,
                                action.retry,
                                action.reason,
                            )
                            self._publish_event(
                                EventType.RECOVERY_ATTEMPTED,
                                ctx,
                                {
                                    "role": role,
                                    "task_id": task_id,
                                    "recovery_attempt": recovery_attempts,
                                    "strategy": action.strategy_name,
                                    "retry": action.retry,
                                    "reason": action.reason,
                                    "context_updates": action.context_updates,
                                },
                            )
                            if action.delay_seconds:
                                time.sleep(action.delay_seconds)
                            if action.retry:
                                self._apply_recovery_action(ctx, action)
                                set_agent_progress(
                                    db,
                                    session_id,
                                    role,
                                    progress=min(0.9, 0.2 + 0.15 * recovery_attempts),
                                    message=f"自动修复中：{action.reason}",
                                    task_id=ctx.task.id if ctx.task else None,
                                    user_id=user_id,
                                )
                                continue
                            last_error = f"{last_error} (recovery stopped: {action.reason})"
                            break

                    # No recovery strategy or recovery refused to retry.
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
                "attempts=%s recovery_attempts=%s error_type=%s error=%s",
                session_id,
                role,
                task_id,
                attempt,
                recovery_attempts,
                error_type,
                last_error,
            )
            failure_event_type = (
                EventType.RECOVERY_FAILED
                if recovery_attempts > 0
                else EventType.AGENT_FAILED
            )
            self._publish_event(
                failure_event_type,
                ctx,
                {
                    "role": role,
                    "task_id": task_id,
                    "attempts": attempt,
                    "recovery_attempts": recovery_attempts,
                    "error_type": error_type,
                    "error": last_error,
                    "recovery_history": [a.__dict__ for a in recovery_history],
                },
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
