"""Recovery strategies for agent self-healing.

Each strategy knows how to fix a specific failure type by mutating the
AgentContext (e.g. reducing input length, switching provider) so the next
attempt has a better chance of success.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from app.agents.base import AgentContext
from app.agents.recovery.classifier import FailureType
from app.core.llm import get_chat_provider

logger = logging.getLogger(__name__)


@dataclass
class RecoveryAction:
    """Action produced by a recovery strategy."""

    strategy_name: str
    retry: bool = True
    delay_seconds: float = 0.0
    context_updates: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class RecoveryStrategy(Protocol):
    """Protocol for a self-healing recovery strategy."""

    name: str

    def can_apply(self, failure_type: str) -> bool:
        ...

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        ...


class TimeoutRecoveryStrategy:
    """Exponential backoff for transient timeouts."""

    name = "timeout_backoff"

    def __init__(self, base_delay: float = 1.0, backoff: float = 2.0, max_delay: float = 30.0):
        self.base_delay = base_delay
        self.backoff = backoff
        self.max_delay = max_delay

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.TIMEOUT

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        attempt = sum(1 for a in history if a.strategy_name == self.name) + 1
        delay = min(self.base_delay * (self.backoff ** (attempt - 1)), self.max_delay)
        return RecoveryAction(
            strategy_name=self.name,
            retry=True,
            delay_seconds=delay,
            reason=f"第 {attempt} 次超时退避，等待 {delay:.1f} 秒后重试",
        )


class UnavailableRecoveryStrategy:
    """Switch to a backup chat provider when the primary one is unavailable."""

    name = "switch_provider"

    # Ordered list of provider names to try. The first available one wins.
    PROVIDER_FALLBACKS = ["deepseek", "dashscope"]

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.UNAVAILABLE

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        used_providers = {
            a.context_updates.get("provider_name")
            for a in history
            if a.context_updates.get("provider_name")
        }
        used_providers.add(getattr(ctx, "provider_name", None))

        for provider_name in self.PROVIDER_FALLBACKS:
            if provider_name in used_providers:
                continue
            try:
                provider = get_chat_provider(provider_name)
                if provider.available:
                    return RecoveryAction(
                        strategy_name=self.name,
                        retry=True,
                        context_updates={"provider_name": provider_name},
                        reason=f"切换到备用 provider: {provider_name}",
                    )
            except Exception:
                continue

        # No usable fallback provider; fall back to simple backoff.
        return TimeoutRecoveryStrategy(base_delay=2.0).apply(
            ctx, failure_type, error, history
        )


class TruncationRecoveryStrategy:
    """Reduce input length or request shorter output when response is truncated."""

    name = "reduce_input"

    DEFAULT_LIMITS = [12000, 8000, 4000]

    def __init__(self, limits: Optional[list[int]] = None):
        self.limits = limits or self.DEFAULT_LIMITS

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.TRUNCATION

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        previous_limits = [
            a.context_updates.get("input_length_limit")
            for a in history
            if a.context_updates.get("input_length_limit")
        ]
        current_limit = getattr(ctx, "input_length_limit", None)
        if current_limit is not None:
            previous_limits.append(current_limit)

        for limit in self.limits:
            if limit not in previous_limits:
                return RecoveryAction(
                    strategy_name=self.name,
                    retry=True,
                    context_updates={"input_length_limit": limit},
                    reason=f"响应被截断，将输入长度限制从 {current_limit or '默认'} 减少到 {limit}",
                )

        # No smaller limit available.
        return None


class InvalidOutputRecoveryStrategy:
    """Ask the agent to emit stricter, valid output when parsing fails."""

    name = "strict_output"

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.INVALID_OUTPUT

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        if any(a.strategy_name == self.name for a in history):
            # Already tried strict mode; backoff and hope for a different sample.
            return TimeoutRecoveryStrategy(base_delay=1.0).apply(
                ctx, failure_type, error, history
            )
        return RecoveryAction(
            strategy_name=self.name,
            retry=True,
            context_updates={"strict_output": True},
            reason="输出格式不合法，启用严格输出模式",
        )


class DependencyMissingRecoveryStrategy:
    """Signal that upstream dependency is missing; caller may need to wait/trigger it."""

    name = "dependency_missing"

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.DEPENDENCY_MISSING

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        # For now we do not auto-trigger upstream agents; we escalate after a few attempts.
        dep_attempts = sum(1 for a in history if a.strategy_name == self.name)
        if dep_attempts >= 2:
            return RecoveryAction(
                strategy_name=self.name,
                retry=False,
                reason="上游依赖缺失，已尝试等待，需要人工介入或手动触发上游任务",
            )
        return RecoveryAction(
            strategy_name=self.name,
            retry=True,
            delay_seconds=3.0,
            reason="上游依赖可能尚未就绪，等待后重试",
        )


class EmptyInputRecoveryStrategy:
    """Empty input cannot be recovered; fail fast."""

    name = "empty_input"

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.EMPTY_INPUT

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        return RecoveryAction(
            strategy_name=self.name,
            retry=False,
            reason="输入内容为空，无法生成资料",
        )


class UnknownRecoveryStrategy:
    """Last resort: one simple retry then give up."""

    name = "unknown_retry"

    def can_apply(self, failure_type: str) -> bool:
        return failure_type == FailureType.UNKNOWN

    def apply(
        self,
        ctx: AgentContext,
        failure_type: str,
        error: Exception,
        history: list[RecoveryAction],
    ) -> Optional[RecoveryAction]:
        if any(a.strategy_name == self.name for a in history):
            return RecoveryAction(
                strategy_name=self.name,
                retry=False,
                reason="未知错误已重试一次仍失败，不再自动修复",
            )
        return RecoveryAction(
            strategy_name=self.name,
            retry=True,
            delay_seconds=1.0,
            reason="未知错误，尝试一次重试",
        )
