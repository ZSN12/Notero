from unittest.mock import patch, MagicMock

from app.agents.rag_memory_agent import RAGMemoryAgent


def _make_provider_mock(raw_text: str):
    provider = MagicMock()
    choice = MagicMock()
    choice.message.role = "assistant"
    choice.message.content = raw_text
    response = MagicMock()
    response.choices = [choice]
    provider.chat.return_value = response
    return provider


def test_memory_agent_returns_empty_for_empty_input():
    agent = RAGMemoryAgent()
    assert agent.summarize_turn("", "", "answer", []) == ""
    assert agent.summarize_turn("", "query", "", []) == ""


def test_memory_agent_parses_summary():
    agent = RAGMemoryAgent()
    raw = '{"turn_summary": "讨论了单例模式的实现方式。"}'

    with patch("app.agents.rag_memory_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.return_value = _make_provider_mock(raw)
        summary = agent.summarize_turn(
            "",
            "单例模式有哪些实现方式？",
            "常见的有饿汉式、懒汉式、双重检查锁等。",
            [],
        )

    assert summary == "讨论了单例模式的实现方式。"


def test_memory_agent_falls_back_on_invalid_json():
    agent = RAGMemoryAgent()

    with patch("app.agents.rag_memory_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.return_value = _make_provider_mock("not json")
        summary = agent.summarize_turn(
            "",
            "单例模式有哪些实现方式？",
            "常见的有饿汉式、懒汉式。",
            [],
        )

    assert summary == ""


def test_memory_agent_falls_back_when_provider_unavailable():
    agent = RAGMemoryAgent()

    with patch("app.agents.rag_memory_agent.get_default_chat_provider") as mock_get_provider:
        mock_get_provider.side_effect = RuntimeError("No provider")
        summary = agent.summarize_turn(
            "",
            "单例模式有哪些实现方式？",
            "常见的有饿汉式、懒汉式。",
            [],
        )

    assert summary == ""
