"""Default event handlers that wire agent events to orchestrator actions."""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.messaging.events import AgentEvent, EventType
from app.agents.messaging.bus import EventBus, get_event_bus
from app.agents.orchestrator import AgentWorkflowOrchestrator, on_agent_completed
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


class OrchestratorEventHandler:
    """Subscribes to agent events and drives workflow-level reactions.

    This handler runs inside the agent worker process. It can:
    - mark downstream roles as blocked when a hard failure occurs;
    - request upstream re-execution when a quality issue points to missing data;
    - escalate to human review when recovery repeatedly fails.
    """

    def __init__(self, bus: Optional[EventBus] = None):
        self.bus = bus or get_event_bus()

    def register(self) -> None:
        """Subscribe to all events the orchestrator cares about."""
        self.bus.subscribe(EventType.AGENT_FAILED, self._on_agent_failed)
        self.bus.subscribe(EventType.RECOVERY_FAILED, self._on_recovery_failed)
        self.bus.subscribe(EventType.QUALITY_ISSUE, self._on_quality_issue)
        self.bus.subscribe(EventType.HUMAN_ESCALATION, self._on_human_escalation)

    def unregister(self) -> None:
        """Unsubscribe from all events."""
        self.bus.unsubscribe(EventType.AGENT_FAILED, self._on_agent_failed)
        self.bus.unsubscribe(EventType.RECOVERY_FAILED, self._on_recovery_failed)
        self.bus.unsubscribe(EventType.QUALITY_ISSUE, self._on_quality_issue)
        self.bus.unsubscribe(EventType.HUMAN_ESCALATION, self._on_human_escalation)

    def _on_agent_failed(self, event: AgentEvent) -> None:
        """React to a hard agent failure.

        For now we let the existing workflow machinery block downstream roles.
        Future extensions can trigger upstream repair if the failure type is
        recoverable at the workflow level.
        """
        role = event.role
        workflow_id = event.workflow_id
        if not role:
            return
        logger.warning(
            "orchestrator_event_agent_failed session_id=%s role=%s workflow_id=%s error=%s",
            event.session_id,
            role,
            workflow_id,
            event.payload.get("error"),
        )
        if workflow_id:
            self._update_workflow_role(workflow_id, role, "error", event.payload)

    def _on_recovery_failed(self, event: AgentEvent) -> None:
        """Recovery has exhausted its budget.

        Mark the role as failed and block downstream. If configured, also
        publish a human escalation event.
        """
        role = event.role
        workflow_id = event.workflow_id
        if not role:
            return
        logger.warning(
            "orchestrator_event_recovery_failed session_id=%s role=%s workflow_id=%s",
            event.session_id,
            role,
            workflow_id,
        )
        if workflow_id:
            self._update_workflow_role(
                workflow_id,
                role,
                "error",
                {
                    "error": event.payload.get("error", "自动修复失败"),
                    "recovery_history": event.payload.get("recovery_history", []),
                },
            )
        # Optionally escalate to human after repeated recovery failure.
        self.bus.publish(
            AgentEvent(
                event_type=EventType.HUMAN_ESCALATION,
                session_id=event.session_id,
                role=role,
                workflow_id=workflow_id,
                task_id=event.task_id,
                user_id=event.user_id,
                payload={
                    "reason": "recovery_exhausted",
                    "error": event.payload.get("error"),
                },
            )
        )

    def _on_quality_issue(self, event: AgentEvent) -> None:
        """React to a quality issue reported by a review agent.

        If the issue is rooted in an upstream artifact (e.g. missing concepts in
        the organized transcript), mark the current role as pending and re-dispatch
        the upstream role so the artifact is refreshed.
        """
        role = event.role
        workflow_id = event.workflow_id
        upstream_role = event.payload.get("upstream_role")
        issue = event.payload.get("issue", "")
        if not role or not workflow_id:
            return

        logger.info(
            "orchestrator_event_quality_issue session_id=%s role=%s upstream=%s issue=%s",
            event.session_id,
            role,
            upstream_role,
            issue,
        )

        if upstream_role:
            # Reset the current role to pending and re-run the upstream agent.
            self._reset_role_for_upstream(workflow_id, role, upstream_role, event.payload)
        else:
            # No upstream root cause known; let the reflection loop handle it.
            pass

    def _on_human_escalation(self, event: AgentEvent) -> None:
        """Log human escalation events.

        In a full implementation this would update a task state to
        'awaiting_human' and notify the UI.
        """
        logger.warning(
            "orchestrator_event_human_escalation session_id=%s role=%s reason=%s",
            event.session_id,
            event.role,
            event.payload.get("reason"),
        )

    def _update_workflow_role(
        self,
        workflow_id: str,
        role: str,
        status: str,
        payload: dict,
    ) -> None:
        """Update a role's state in its workflow and drive downstream reactions."""
        db = SessionLocal()
        try:
            orchestrator = AgentWorkflowOrchestrator(workflow_id, db=db)
            workflow = orchestrator._get_workflow(db)
            if not workflow or role not in workflow.role_states:
                return
            # Reuse the existing completion hook so downstream blocking works.
            success = status == "success"
            error_message = None if success else payload.get("error", "任务失败")
            orchestrator.on_agent_completed(role, success, error_message, db=db)
        except Exception:
            logger.exception(
                "orchestrator_update_workflow_role_failed workflow_id=%s role=%s",
                workflow_id,
                role,
            )
        finally:
            db.close()

    def _reset_role_for_upstream(
        self,
        workflow_id: str,
        role: str,
        upstream_role: str,
        payload: dict,
    ) -> None:
        """Reset the current role and re-dispatch the upstream role."""
        db = SessionLocal()
        try:
            orchestrator = AgentWorkflowOrchestrator(workflow_id, db=db)
            workflow = orchestrator._get_workflow(db)
            if not workflow:
                return
            if role not in workflow.role_states or upstream_role not in workflow.role_states:
                return

            from sqlalchemy.orm.attributes import flag_modified

            # Limit the number of upstream repairs to avoid infinite loops.
            role_state = workflow.role_states[role]
            repair_count = role_state.get("upstream_repair_count", 0) + 1
            if repair_count > 2:
                logger.warning(
                    "orchestrator_upstream_repair_limit workflow_id=%s role=%s upstream=%s count=%s",
                    workflow_id,
                    role,
                    upstream_role,
                    repair_count,
                )
                self.bus.publish(
                    AgentEvent(
                        event_type=EventType.HUMAN_ESCALATION,
                        session_id=workflow.session_id,
                        role=role,
                        workflow_id=workflow_id,
                        user_id=workflow.user_id,
                        payload={
                            "reason": "upstream_repair_limit_reached",
                            "upstream_role": upstream_role,
                            "issue": payload.get("issue"),
                        },
                    )
                )
                return

            # Mark current role as pending again; it will re-run after upstream succeeds.
            role_state["status"] = "pending"
            role_state["upstream_repair_reason"] = payload.get("issue", "")
            role_state["upstream_repair_count"] = repair_count
            workflow.role_states = dict(workflow.role_states)
            flag_modified(workflow, "role_states")
            db.commit()

            # Mark upstream as pending and re-dispatch it.
            upstream_state = workflow.role_states[upstream_role]
            upstream_state["status"] = "pending"
            upstream_state["repair_triggered_by"] = role
            upstream_state["repair_count"] = upstream_state.get("repair_count", 0) + 1
            workflow.role_states = dict(workflow.role_states)
            flag_modified(workflow, "role_states")
            db.commit()

            logger.info(
                "orchestrator_upstream_repair workflow_id=%s role=%s upstream=%s repair_count=%s",
                workflow_id,
                role,
                upstream_role,
                repair_count,
            )

            # Dispatch the upstream role.
            orchestrator._dispatch_role(workflow, upstream_role, db)
            db.commit()
        except Exception:
            logger.exception(
                "orchestrator_reset_role_failed workflow_id=%s role=%s upstream=%s",
                workflow_id,
                role,
                upstream_role,
            )
        finally:
            db.close()


# Singleton handler instance registered at import time in worker processes.
_orchestrator_handler: Optional[OrchestratorEventHandler] = None


def register_orchestrator_handlers() -> None:
    """Register the orchestrator event handler on the global bus."""
    global _orchestrator_handler
    if _orchestrator_handler is None:
        _orchestrator_handler = OrchestratorEventHandler()
        _orchestrator_handler.register()
        logger.info("orchestrator_event_handlers_registered")
