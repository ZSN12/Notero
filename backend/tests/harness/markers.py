"""Pytest marker helpers and skip conditions."""

import os

import pytest

UNIT = "unit"
INTEGRATION = "integration"
SLOW = "slow"
LLM = "llm"
E2E = "e2e"


def _has_env_key(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


requires_api_key = pytest.mark.skipif(
    not _has_env_key("DEEPSEEK_API_KEY") and not _has_env_key("OPENAI_API_KEY"),
    reason="Requires DEEPSEEK_API_KEY or OPENAI_API_KEY",
)

requires_dashscope = pytest.mark.skipif(
    not _has_env_key("DASHSCOPE_API_KEY"),
    reason="Requires DASHSCOPE_API_KEY",
)
