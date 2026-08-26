"""Failure classification for agent self-healing.

Maps exceptions and error messages to a stable set of failure types so the
recovery planner can pick an appropriate fix strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class FailureType:
    """Stable failure type identifiers."""

    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    TRUNCATION = "truncation"
    INVALID_OUTPUT = "invalid_output"
    DEPENDENCY_MISSING = "dependency_missing"
    EMPTY_INPUT = "empty_input"
    UNKNOWN = "unknown"


@dataclass
class Failure:
    """Classified failure with raw error context."""

    type: str
    error: Exception
    message: str

    def is_retryable(self) -> bool:
        """Return True if this failure type can be retried."""
        return self.type in {
            FailureType.TIMEOUT,
            FailureType.UNAVAILABLE,
            FailureType.TRUNCATION,
            FailureType.INVALID_OUTPUT,
        }


class FailureClassifier:
    """Classify agent failures by inspecting exceptions and messages."""

    def classify(self, error: Exception) -> Failure:
        """Classify an exception into a Failure."""
        message = str(error).lower()
        raw = str(error)

        # Order matters: more specific signals before generic ones.
        if "没有可用的索引内容" in raw or "no indexable content" in message:
            return Failure(FailureType.EMPTY_INPUT, error, raw)
        if "没有可用的" in raw or "missing" in message and "依赖" in raw:
            return Failure(FailureType.DEPENDENCY_MISSING, error, raw)

        # DeepSeek / OpenAI specific unavailable signals.
        if "unavailable" in message or "connection" in message or "network" in message:
            return Failure(FailureType.UNAVAILABLE, error, raw)
        if "api key" in message or "apikey" in message or "认证" in raw or "鉴权" in raw:
            return Failure(FailureType.UNAVAILABLE, error, raw)

        # Timeout signals.
        if "timeout" in message or "timed out" in message or "超时" in raw:
            return Failure(FailureType.TIMEOUT, error, raw)

        # Truncation / length signals.
        if (
            "截断" in raw
            or "finish_reason=length" in message
            or "finish_reason='length'" in message
            or "too long" in message
        ):
            return Failure(FailureType.TRUNCATION, error, raw)

        # Invalid output / JSON / format errors.
        if (
            "json" in message
            or "格式无效" in raw
            or "schema" in message
            or "invalid output" in message
            or "parse" in message
        ):
            return Failure(FailureType.INVALID_OUTPUT, error, raw)

        # Dependency missing by content heuristics.
        if (
            "依赖" in raw
            or "upstream" in message
            or "prerequisite" in message
            or "not ready" in message
        ):
            return Failure(FailureType.DEPENDENCY_MISSING, error, raw)

        return Failure(FailureType.UNKNOWN, error, raw)
