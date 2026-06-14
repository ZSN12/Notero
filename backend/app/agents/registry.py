"""Agent registry.

Agents are registered lazily so that importing the registry does not
immediately import every agent implementation (avoiding heavy imports
and circular dependencies).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.agents.base import BaseAgent

# Mapping of role -> factory function that returns an agent instance.
_AGENT_FACTORIES: dict[str, Callable[[], "BaseAgent"]] = {}


def register_agent(role: str, factory: Callable[[], "BaseAgent"]) -> None:
    """Register an agent factory under its role name."""
    _AGENT_FACTORIES[role] = factory


def get_agent(role: str) -> "BaseAgent":
    """Instantiate the agent registered under the given role."""
    if role not in _AGENT_FACTORIES:
        raise ValueError(f"Unknown agent role: {role}. Registered: {list(_AGENT_FACTORIES.keys())}")
    return _AGENT_FACTORIES[role]()


def list_agents() -> list[str]:
    """Return all registered agent role names."""
    return list(_AGENT_FACTORIES.keys())


def _ensure_default_agents() -> None:
    """Lazy registration of the built-in agents."""
    if _AGENT_FACTORIES:
        return

    from app.agents.mindmap_agent import MindmapAgent
    from app.agents.quiz_agent import QuizAgent
    from app.agents.review_agent import ReviewPlannerAgent

    register_agent(MindmapAgent.role, MindmapAgent)
    register_agent(QuizAgent.role, QuizAgent)
    register_agent(ReviewPlannerAgent.role, ReviewPlannerAgent)
