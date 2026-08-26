"""Event model for inter-agent communication.

Agents communicate by publishing typed events to a shared bus rather than
calling each other directly. This decouples producers from consumers and lets
the orchestrator react to runtime conditions (failures, quality issues, etc.)
without hard-coding agent relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class EventType:
    """Stable event type identifiers."""

    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    RECOVERY_ATTEMPTED = "recovery_attempted"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_FAILED = "recovery_failed"

    QUALITY_ISSUE = "quality_issue"
    UPSTREAM_REQUEST = "upstream_request"

    HUMAN_ESCALATION = "human_escalation"


@dataclass
class AgentEvent:
    """A single event published by an agent or the runner."""

    event_type: str
    session_id: str
    role: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_log_dict(self) -> dict[str, Any]:
        """Serialize for logging or persistence."""
        return {
            "event_type": self.event_type,
            "session_id": self.session_id,
            "role": self.role,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }
