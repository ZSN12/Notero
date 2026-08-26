"""Recovery planner: pick the right strategy for a given failure type."""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.base import AgentContext
from app.agents.recovery.classifier import Failure, FailureClassifier
from app.agents.recovery.strategies import (
    DependencyMissingRecoveryStrategy,
    EmptyInputRecoveryStrategy,
    InvalidOutputRecoveryStrategy,
    RecoveryAction,
    RecoveryStrategy,
    TimeoutRecoveryStrategy,
    TruncationRecoveryStrategy,
    UnavailableRecoveryStrategy,
    UnknownRecoveryStrategy,
)

logger = logging.getLogger(__name__)


class RecoveryPlanner:
    """Plans recovery actions for agent failures."""

    def __init__(self, strategies: Optional[list[RecoveryStrategy]] = None):
        self.classifier = FailureClassifier()
        self.strategies = strategies or self._default_strategies()

    @staticmethod
    def _default_strategies() -> list[RecoveryStrategy]:
        return [
            EmptyInputRecoveryStrategy(),
            DependencyMissingRecoveryStrategy(),
            TimeoutRecoveryStrategy(),
            UnavailableRecoveryStrategy(),
            TruncationRecoveryStrategy(),
            InvalidOutputRecoveryStrategy(),
            UnknownRecoveryStrategy(),
        ]

    def plan(
        self,
        ctx: AgentContext,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        """Classify the error and return a recovery action, or None if unrecoverable."""
        failure = self.classifier.classify(error)
        for strategy in self.strategies:
            if strategy.can_apply(failure.type):
                action = strategy.apply(ctx, failure.type, error, history)
                if action is not None:
                    logger.info(
                        "recovery_planned failure_type=%s strategy=%s retry=%s reason=%s",
                        failure.type,
                        action.strategy_name,
                        action.retry,
                        action.reason,
                    )
                    return action

        logger.warning(
            "recovery_no_strategy failure_type=%s message=%s",
            failure.type,
            failure.message,
        )
        return None
