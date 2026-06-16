"""Non-blocking agent workflow orchestrator.

Provides a lightweight DAG-based workflow engine for agent execution:
- A workflow captures the target roles and their dependencies.
- ``start_workflow`` creates Task rows for all agents whose dependencies are
  already satisfied and dispatches them.
- ``on_agent_completed`` is called whenever an agent finishes; it updates the
  workflow state and dispatches any downstream agents whose dependencies are
  now satisfied.

The orchestrator is intentionally simple: it reuses the existing Task table and
AgentRunner/dispatch machinery rather than introducing a separate worker queue.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.agents.dispatch import dispatch_agent_task
from app.core.database import SessionLocal
from app.models import AgentWorkflow, Task, User

logger = logging.getLogger(__name__)

# Upstream -> downstream dependencies for agent orchestration.
# An agent only starts after all of its upstream dependencies have succeeded.
AGENT_DEPENDENCIES: dict[str, list[str]] = {
    "mindmap": ["transcript"],
    "quiz": ["transcript"],
    "review": ["transcript"],
}


def _expand_roles(roles: list[str], dependencies: dict[str, list[str]]) -> list[str]:
    """Return ``roles`` plus any transitive upstream dependencies."""
    expanded: set[str] = set()
    stack = list(roles)
    while stack:
        role = stack.pop()
        if role in expanded:
            continue
        expanded.add(role)
        for dep in dependencies.get(role, []):
            if dep not in expanded:
                stack.append(dep)
    # Preserve original order and append dependencies at the end.
    result: list[str] = []
    seen: set[str] = set()
    for role in roles + [r for r in expanded if r not in roles]:
        if role not in seen:
            result.append(role)
            seen.add(role)
    return result


class AgentWorkflowOrchestrator:
    """Manage the lifecycle of an agent workflow."""

    def __init__(self, workflow_id: str, db: Optional[DBSession] = None):
        self.workflow_id = workflow_id
        self._db = db
        self._lock = threading.Lock()

    @classmethod
    def create(
        cls,
        session_id: str,
        user_id: str,
        roles: list[str],
        dependencies: Optional[dict[str, list[str]]] = None,
        role_states: Optional[dict[str, dict[str, Any]]] = None,
        db: Optional[DBSession] = None,
    ) -> "AgentWorkflowOrchestrator":
        """Create a new workflow record and return an orchestrator for it.

        ``role_states`` can be used to seed states for roles that are already
        running or already completed (e.g. reused active tasks or fresh cached
        output). Any role not present in ``role_states`` is initialized as
        ``pending``.
        """
        close_db = db is None
        db = db or SessionLocal()
        try:
            all_roles = _expand_roles(list(roles), dependencies or AGENT_DEPENDENCIES)
            merged_states: dict[str, dict[str, Any]] = {
                role: {"status": "pending"} for role in all_roles
            }
            if role_states:
                for role, state in role_states.items():
                    if role in merged_states:
                        merged_states[role] = dict(state)
            workflow = AgentWorkflow(
                session_id=session_id,
                user_id=user_id,
                roles=all_roles,
                dependencies=dict(dependencies or AGENT_DEPENDENCIES),
                role_states=merged_states,
                status="pending",
            )
            db.add(workflow)
            db.commit()
            db.refresh(workflow)
            logger.info(
                "workflow_created workflow_id=%s session_id=%s roles=%s",
                workflow.id,
                session_id,
                roles,
            )
            return cls(workflow.id, db=db if not close_db else None)
        except Exception:
            if close_db:
                db.close()
            raise

    def _get_workflow(self, db: DBSession) -> Optional[AgentWorkflow]:
        return db.query(AgentWorkflow).filter(AgentWorkflow.id == self.workflow_id).first()

    def start(self, db: Optional[DBSession] = None) -> Optional[AgentWorkflow]:
        """Mark workflow as running and dispatch all initially ready agents."""
        close_db = db is None
        db = db or SessionLocal()
        try:
            with self._lock:
                workflow = self._get_workflow(db)
                if not workflow:
                    logger.warning("workflow_start_not_found workflow_id=%s", self.workflow_id)
                    return None

                if workflow.status != "pending":
                    logger.info(
                        "workflow_start_skipped workflow_id=%s status=%s",
                        self.workflow_id,
                        workflow.status,
                    )
                    return workflow

                workflow.status = "running"
                db.commit()

                ready_roles = self._ready_roles(workflow)
                logger.info(
                    "workflow_start_dispatch workflow_id=%s ready_roles=%s",
                    self.workflow_id,
                    ready_roles,
                )
                for role in ready_roles:
                    self._dispatch_role(workflow, role, db)

                db.commit()
                db.refresh(workflow)
                return workflow
        finally:
            if close_db:
                db.close()

    def on_agent_completed(
        self,
        role: str,
        success: bool,
        error_message: Optional[str] = None,
        db: Optional[DBSession] = None,
    ) -> Optional[AgentWorkflow]:
        """Update workflow state after an agent completes and dispatch downstream."""
        close_db = db is None
        db = db or SessionLocal()
        try:
            with self._lock:
                workflow = self._get_workflow(db)
                if not workflow:
                    logger.warning(
                        "workflow_complete_not_found workflow_id=%s", self.workflow_id
                    )
                    return None

                if role not in workflow.role_states:
                    logger.warning(
                        "workflow_complete_unknown_role workflow_id=%s role=%s",
                        self.workflow_id,
                        role,
                    )
                    return workflow

                workflow.role_states[role]["status"] = "success" if success else "error"
                if error_message:
                    workflow.role_states[role]["error_message"] = error_message
                new_states = dict(workflow.role_states)
                workflow.role_states = new_states
                flag_modified(workflow, "role_states")
                db.commit()

                logger.info(
                    "workflow_role_completed workflow_id=%s role=%s success=%s",
                    self.workflow_id,
                    role,
                    success,
                )

                ready_roles = self._ready_roles(workflow)
                for ready_role in ready_roles:
                    self._dispatch_role(workflow, ready_role, db)

                self._update_workflow_status(workflow, db)
                db.commit()
                db.refresh(workflow)
                return workflow
        finally:
            if close_db:
                db.close()

    def _ready_roles(self, workflow: AgentWorkflow) -> list[str]:
        """Return roles that are pending and have all dependencies succeeded."""
        ready: list[str] = []
        for role in workflow.roles:
            state = workflow.role_states.get(role, {})
            if state.get("status") != "pending":
                continue
            deps = workflow.dependencies.get(role, [])
            if all(
                workflow.role_states.get(dep, {}).get("status") == "success"
                for dep in deps
            ):
                ready.append(role)
        return ready

    def _dispatch_role(
        self,
        workflow: AgentWorkflow,
        role: str,
        db: DBSession,
    ) -> Optional[Task]:
        """Create a Task for the role and dispatch it."""
        # Check for an existing active task to avoid duplicates.
        active = (
            db.query(Task)
            .filter(
                Task.session_id == workflow.session_id,
                Task.task_type == f"agent_{role}",
                Task.status.in_({"pending", "running"}),
            )
            .order_by(Task.created_at.desc())
            .first()
        )
        if active:
            logger.info(
                "workflow_dispatch_reused_task workflow_id=%s role=%s task_id=%s",
                self.workflow_id,
                role,
                active.id,
            )
            workflow.role_states[role]["task_id"] = active.id
            workflow.role_states = dict(workflow.role_states)
            flag_modified(workflow, "role_states")
            db.commit()
            return active

        task = Task(
            session_id=workflow.session_id,
            task_type=f"agent_{role}",
            status="pending",
            progress=0.0,
            error_message=None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        now = datetime.now(timezone.utc)
        workflow.role_states[role]["status"] = "running"
        workflow.role_states[role]["task_id"] = task.id
        workflow.role_states[role]["started_at"] = now.isoformat()
        workflow.role_states[role]["heartbeat_at"] = now.isoformat()
        workflow.role_states = dict(workflow.role_states)
        flag_modified(workflow, "role_states")
        workflow.last_heartbeat_at = now
        db.commit()

        logger.info(
            "workflow_dispatch workflow_id=%s role=%s task_id=%s",
            self.workflow_id,
            role,
            task.id,
        )
        dispatch_agent_task(workflow.session_id, workflow.user_id, role, task.id, db=db)
        return task

    def _update_workflow_status(
        self,
        workflow: AgentWorkflow,
        db: DBSession,
    ) -> None:
        """Transition workflow to success/error when all roles are terminal."""
        from datetime import datetime, timezone

        states = workflow.role_states.values()
        if not states:
            return

        all_terminal = all(s.get("status") in ("success", "error") for s in states)
        if not all_terminal:
            return

        any_error = any(s.get("status") == "error" for s in states)
        workflow.status = "error" if any_error else "success"
        workflow.finished_at = datetime.now(timezone.utc)
        logger.info(
            "workflow_finished workflow_id=%s status=%s",
            self.workflow_id,
            workflow.status,
        )


# Module-level convenience functions for callers that do not want to hold
# an orchestrator instance (e.g. dispatch threads and Celery tasks).

def _find_running_workflow(
    session_id: str,
    user_id: str,
    db: DBSession,
) -> Optional[AgentWorkflow]:
    """Return the most recent running workflow for the session/user."""
    return (
        db.query(AgentWorkflow)
        .filter(
            AgentWorkflow.session_id == session_id,
            AgentWorkflow.user_id == user_id,
            AgentWorkflow.status == "running",
        )
        .order_by(AgentWorkflow.created_at.desc())
        .first()
    )


def on_agent_completed(
    session_id: str,
    user_id: str,
    role: str,
    success: bool,
    error_message: Optional[str] = None,
    db: Optional[DBSession] = None,
) -> None:
    """Notify the most recent running workflow for a session that a role completed."""
    close_db = db is None
    db = db or SessionLocal()
    try:
        workflow = _find_running_workflow(session_id, user_id, db)
        if not workflow:
            logger.info(
                "on_agent_completed_no_running_workflow session_id=%s role=%s",
                session_id,
                role,
            )
            return
        AgentWorkflowOrchestrator(workflow.id, db=db).on_agent_completed(
            role, success, error_message, db=db
        )
    finally:
        if close_db:
            db.close()


def on_agent_heartbeat(
    session_id: str,
    user_id: str,
    role: str,
    db: Optional[DBSession] = None,
) -> None:
    """Update the heartbeat for ``role`` in the most recent running workflow."""
    close_db = db is None
    db = db or SessionLocal()
    try:
        workflow = _find_running_workflow(session_id, user_id, db)
        if not workflow or role not in workflow.role_states:
            return
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        workflow.role_states[role]["heartbeat_at"] = now.isoformat()
        workflow.role_states = dict(workflow.role_states)
        flag_modified(workflow, "role_states")
        workflow.last_heartbeat_at = now
        db.commit()
    finally:
        if close_db:
            db.close()


def start_workflow(
    session_id: str,
    user_id: str,
    roles: list[str],
    dependencies: Optional[dict[str, list[str]]] = None,
    role_states: Optional[dict[str, dict[str, Any]]] = None,
    db: Optional[DBSession] = None,
) -> Optional[AgentWorkflow]:
    """Create and start a workflow for the given roles."""
    orchestrator = AgentWorkflowOrchestrator.create(
        session_id, user_id, roles, dependencies, role_states, db
    )
    return orchestrator.start(db)
