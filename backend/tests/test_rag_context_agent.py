import json
from unittest.mock import patch, MagicMock

import pytest

from app.agents.rag_context_agent import RAGContextAgent


def _make_provider_mock(raw_text: str):
    provider = MagicMock()
    choice = MagicMock()
    choice.message.role = "assistant"
    choice.message.content = raw_text
    response = MagicMock()
    response.choices = [choice]
    provider.chat.return_value = response
    return provider


def test_context_agent_returns_original_query_without_history():
    agent = RAGContextAgent()
    result = agent.contextualize([], "什么是单例模式？")
    assert result["standalone_query"] == "什么是单例模式？"
    assert result["context_summary"] == ""


def test_context_agent_parses_json_response():
    agent = RAGContextAgent()
    raw = json.dumps({"standalone_query": "单例模式如何保证唯一实例？", "context_summary": "正在讨论设计模式中的单例模式。"})

    with patch("app.agents.rag_context_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.return_value = _make_provider_mock(raw)
        result = agent.contextualize(
            [{"role": "user", "content": "什么是单例模式？"}, {"role": "assistant", "content": "单例模式确保一个类只有一个实例。"}],
            "那它怎么保证唯一？",
        )

    assert result["standalone_query"] == "单例模式如何保证唯一实例？"
    assert result["context_summary"] == "正在讨论设计模式中的单例模式。"


def test_context_agent_falls_back_on_invalid_json():
    agent = RAGContextAgent()

    with patch("app.agents.rag_context_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.return_value = _make_provider_mock("not valid json")
        result = agent.contextualize(
            [{"role": "user", "content": "什么是单例模式？"}],
            "那它怎么保证唯一？",
        )

    assert result["standalone_query"] == "那它怎么保证唯一？"
    assert result["context_summary"] == ""


def test_context_agent_falls_back_when_provider_unavailable():
    agent = RAGContextAgent()

    with patch("app.agents.rag_context_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.side_effect = RuntimeError("No provider")
        result = agent.contextualize(
            [{"role": "user", "content": "什么是单例模式？"}],
            "那它怎么保证唯一？",
        )

    assert result["standalone_query"] == "那它怎么保证唯一？"
    assert result["context_summary"] == ""
