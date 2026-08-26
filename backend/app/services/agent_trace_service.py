"""Persistence helpers for agent execution trace events."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.models import AgentRunEvent

logger = logging.getLogger(__name__)


def record_agent_event(
    db: DBSession,
    *,
    session_id: str,
    user_id: str,
    event_type: str,
    role: Optional[str] = None,
    workflow_id: Optional[str] = None,
    task_id: Optional[str] = None,
    message: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> AgentRunEvent | None:
    """Add an agent trace event to the current DB session.

    The helper intentionally does not commit. Callers already have lifecycle
    commits around task/state updates, which keeps trace writes in the same unit
    of work while avoiding surprise commits inside nested test transactions.
    """
    try:
        event = AgentRunEvent(
            session_id=session_id,
            user_id=user_id,
            workflow_id=workflow_id,
            task_id=task_id,
            role=role,
            event_type=event_type,
            message=message,
            payload=_sanitize_payload(payload or {}),
        )
        db.add(event)
        return event
    except Exception:
        logger.exception(
            "agent_trace_record_failed session_id=%s role=%s event_type=%s",
            session_id,
            role,
            event_type,
        )
        return None


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep payload compact and avoid persisting full prompts or raw outputs."""
    blocked_keys = {
        "prompt",
        "messages",
        "raw",
        "raw_text",
        "content",
        "source_material",
        "assistant_answer",
    }
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in blocked_keys:
            sanitized[f"{key}_omitted"] = True
            continue
        sanitized[key] = _truncate_value(value)
    return sanitized


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "..."
    if isinstance(value, list):
        return [_truncate_value(v) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _truncate_value(v) for k, v in list(value.items())[:40]}
    return value
