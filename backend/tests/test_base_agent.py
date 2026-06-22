"""Tests for BaseAgent shared helpers (call_llm, parse_json, etc.)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base import BaseAgent, AgentResult


class DummyAgent(BaseAgent):
    role = "dummy"
    task_type = "dummy"
    output_kind = "dummy"
    prompt_name = "dummy"

    def run(self, ctx) -> AgentResult:
        return AgentResult(success=True)


@pytest.fixture
def agent():
    return DummyAgent()


class TestCallLLM:
    def test_raises_when_no_provider_available(self, agent):
        provider = MagicMock()
        provider.available = False
        with patch("app.agents.base.get_default_chat_provider", return_value=provider):
            with pytest.raises(ValueError, match="未配置可用的 AI Provider"):
                agent.call_llm(MagicMock(system="sys"), "user")

    def test_passes_response_format_json_object(self, agent):
        provider = MagicMock()
        provider.available = True
        provider.__class__.__name__ = "MockProvider"
        provider.chat.return_value = MagicMock(
            choices=[MagicMock(finish_reason="stop", message=MagicMock(content='{"a":1}'))]
        )

        prompt_template = MagicMock(system="You are a dummy agent.")
        with patch("app.agents.base.get_default_chat_provider", return_value=provider):
            agent.call_llm(prompt_template, "hello")

        called_kwargs = provider.chat.call_args.kwargs
        assert called_kwargs.get("response_format") == {"type": "json_object"}

    def test_disables_thinking_for_deepseek_v4(self, agent):
        provider = MagicMock()
        provider.available = True
        provider.__class__.__name__ = "DeepSeekProvider"
        provider.chat.return_value = MagicMock(
            choices=[MagicMock(finish_reason="stop", message=MagicMock(content='{}'))]
        )

        with patch("app.agents.base.get_default_chat_provider", return_value=provider), \
             patch("app.config.DEEPSEEK_MODEL", "deepseek-v4-flash"):
            agent.call_llm(MagicMock(system="sys"), "hello")

        called_kwargs = provider.chat.call_args.kwargs
        assert called_kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}

    def test_raises_timeout_error(self, agent):
        provider = MagicMock()
        provider.available = True
        provider.__class__.__name__ = "MockProvider"
        provider.chat.side_effect = TimeoutError("request timed out")

        with patch("app.agents.base.get_default_chat_provider", return_value=provider):
            with pytest.raises(ValueError, match="请求 LLM 超时"):
                agent.call_llm(MagicMock(system="sys"), "hello")

    def test_raises_on_length_finish_reason(self, agent):
        provider = MagicMock()
        provider.available = True
        provider.__class__.__name__ = "MockProvider"
        provider.chat.return_value = MagicMock(
            choices=[MagicMock(finish_reason="length", message=MagicMock(content='{"a":1}'))]
        )

        with patch("app.agents.base.get_default_chat_provider", return_value=provider):
            with pytest.raises(ValueError, match="返回被截断"):
                agent.call_llm(MagicMock(system="sys"), "hello")


class TestParseJSON:
    def test_parses_clean_json(self, agent):
        assert agent.parse_json('{"x": 1}') == {"x": 1}

    def test_strips_markdown_fences(self, agent):
        raw = "```json\n{\"x\": 1}\n```"
        assert agent.parse_json(raw) == {"x": 1}

    def test_repairs_unterminated_string(self, agent):
        raw = '{"x": "hello'
        assert agent.parse_json(raw) == {"x": "hello"}

    def test_repairs_unbalanced_braces(self, agent):
        raw = '{"x": 1'
        assert agent.parse_json(raw) == {"x": 1}

    def test_raises_when_repair_fails(self, agent):
        with pytest.raises(ValueError, match="JSON 格式无效"):
            agent.parse_json("not json at all")
