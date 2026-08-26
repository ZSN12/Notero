"""Notero agents package."""

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.registry import get_agent, list_agents, register_agent
from app.agents.review import BaseReviewAgent, ReviewIssue, ReviewResult
from app.agents.recovery import (
    Failure,
    FailureClassifier,
    FailureType,
    RecoveryAction,
    RecoveryPlanner,
    RecoveryStrategy,
)
from app.agents.messaging import (
    AgentEvent,
    EventBus,
    EventType,
    get_event_bus,
    OrchestratorEventHandler,
    register_orchestrator_handlers,
)

# Trigger lazy registration of default agents on first import.
from app.agents import registry as _registry

_registry._ensure_default_agents()

# Register orchestrator event handlers so agents can signal workflow repairs.
register_orchestrator_handlers()

__all__ = [
    "BaseAgent",
    "AgentContext",
    "AgentResult",
    "get_agent",
    "list_agents",
    "register_agent",
    "BaseReviewAgent",
    "ReviewIssue",
    "ReviewResult",
    "Failure",
    "FailureClassifier",
    "FailureType",
    "RecoveryAction",
    "RecoveryPlanner",
    "RecoveryStrategy",
    "AgentEvent",
    "EventBus",
    "EventType",
    "get_event_bus",
    "OrchestratorEventHandler",
    "register_orchestrator_handlers",
]
