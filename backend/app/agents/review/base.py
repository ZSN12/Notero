"""Base classes for review agents.

A review agent examines the output of a generation agent and decides whether it
is good enough. If not, it produces an improvement prompt that can be fed back
into the generation agent for another attempt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ReviewIssue:
    """A single quality issue found by a review agent."""

    dimension: str
    description: str
    severity: str = "medium"  # low, medium, high, critical
    location: Optional[str] = None


@dataclass
class ReviewResult:
    """Result of reviewing a generation agent's output."""

    is_acceptable: bool = False
    score: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    issues: list[ReviewIssue] = field(default_factory=list)
    improvement_prompt: Optional[str] = None
    should_regenerate: bool = False
    should_stop: bool = False
    reasoning: Optional[str] = None

    def to_log_dict(self) -> dict[str, Any]:
        """Serialize for logging or persistence."""
        return {
            "is_acceptable": self.is_acceptable,
            "score": round(self.score, 4),
            "dimensions": {k: round(v, 4) for k, v in self.dimensions.items()},
            "issues": [
                {
                    "dimension": i.dimension,
                    "description": i.description,
                    "severity": i.severity,
                    "location": i.location,
                }
                for i in self.issues
            ],
            "should_regenerate": self.should_regenerate,
            "should_stop": self.should_stop,
            "improvement_prompt": self.improvement_prompt,
            "reasoning": self.reasoning,
        }


class BaseReviewAgent(ABC):
    """Abstract base class for review agents.

    Subclasses are paired with a specific generation agent (e.g.
    MindmapReviewAgent reviews MindmapAgent). They must be deterministic enough
    to run inside a reflection loop and cheap enough to invoke multiple times.
    """

    role: str = ""

    def __init__(self) -> None:
        if not self.role:
            raise ValueError(
                f"Review agent subclass {self.__class__.__name__} must define role"
            )

    @abstractmethod
    def review(
        self,
        source_material: str,
        output: dict[str, Any],
        history: list[ReviewResult],
    ) -> ReviewResult:
        """Review an output and decide whether it is acceptable.

        Args:
            source_material: The original input given to the generation agent.
            output: The structured output produced by the generation agent.
            history: Previous review results for the same task, if any.

        Returns:
            A ReviewResult describing quality, issues, and suggested fixes.
        """
        ...
