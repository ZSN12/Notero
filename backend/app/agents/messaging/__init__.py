"""Messaging support for inter-agent communication."""

from app.agents.messaging.bus import EventBus, get_event_bus
from app.agents.messaging.events import AgentEvent, EventType
from app.agents.messaging.handlers import (
    OrchestratorEventHandler,
    register_orchestrator_handlers,
)

__all__ = [
    "AgentEvent",
    "EventBus",
    "EventType",
    "OrchestratorEventHandler",
    "get_event_bus",
    "register_orchestrator_handlers",
]
