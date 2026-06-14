"""Notero agents package."""

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.registry import get_agent, list_agents, register_agent

# Trigger lazy registration of default agents on first import.
from app.agents import registry as _registry

_registry._ensure_default_agents()

__all__ = [
    "BaseAgent",
    "AgentContext",
    "AgentResult",
    "get_agent",
    "list_agents",
    "register_agent",
]
