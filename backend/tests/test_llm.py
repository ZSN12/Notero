"""Tests for the unified LLM provider abstraction."""

from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.llm

from app.core.llm import (
    ChatMessage,
    ChatResponse,
    DeepSeekProvider,
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    LLMProvider,
    get_chat_provider,
    get_embedding_provider,
    register_provider,
    get_default_chat_provider,
    get_default_embedding_provider,
)


class FakeChatEmbedProvider(LLMProvider, EmbeddingProvider):
    """A minimal concrete provider usable for both chat and embedding tests."""

    @property
    def available(self) -> bool:
        return True

    def chat(
        self,
        messages,
        model=None,
        temperature=0.3,
        max_tokens=None,
        response_format=None,
        stream=False,
        **kwargs,
    ) -> ChatResponse:
        return ChatResponse(choices=[])

    def chat_stream(self, *args, **kwargs):
        yield ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]


class TestDeepSeekProvider:
    def test_not_available_without_api_key(self):
        with patch("app.core.llm.os.getenv", return_value=""):
            provider = DeepSeekProvider(api_key="")
            assert provider.available is False

    def test_available_with_api_key(self):
        mock_client = MagicMock()
        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test")
            assert provider.available is True

    def test_chat_raises_when_unavailable(self):
        with patch("app.core.llm.os.getenv", return_value=""):
            provider = DeepSeekProvider(api_key="")
        assert provider.available is False
        try:
            provider.chat([ChatMessage(role="user", content="hello")])
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "not available" in str(e).lower()

    def test_chat_success(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(role="assistant", content="hi there")),
        ]
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test")
            resp = provider.chat([ChatMessage(role="user", content="hello")])
            assert len(resp.choices) == 1
            assert resp.choices[0].message.content == "hi there"

    def test_chat_stream_yields_chunks(self):
        mock_client = MagicMock()
        chunk1 = MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello"))])
        chunk2 = MagicMock(choices=[MagicMock(delta=MagicMock(content=" world"))])
        chunk3 = MagicMock(choices=[MagicMock(delta=MagicMock(content=None))])
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test")
            chunks = list(provider.chat_stream([ChatMessage(role="user", content="hello")]))
            assert chunks == ["Hello", " world"]

    def test_chat_uses_default_model(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(role="assistant", content="ok"))]
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test", default_model="custom-model")
            provider.chat([ChatMessage(role="user", content="hi")])
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == "custom-model"

    def test_chat_allows_override_model(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(role="assistant", content="ok"))]
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test", default_model="default")
            provider.chat([ChatMessage(role="user", content="hi")], model="override")
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == "override"

    def test_chat_forwards_json_mode_and_thinking_configuration(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(role="assistant", content="{}"))]
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DeepSeekProvider(api_key="sk-test", default_model="deepseek-v4-flash")
            provider.chat(
                [ChatMessage(role="user", content="return json")],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


class TestDashScopeEmbeddingProvider:
    def test_not_available_without_api_key(self):
        provider = DashScopeEmbeddingProvider(api_key="")
        assert provider.available is False

    def test_available_with_api_key(self):
        mock_client = MagicMock()
        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            assert provider.available is True

    def test_embed_all_empty_texts(self):
        mock_client = MagicMock()
        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            results = provider.embed(["", "  "])
            assert len(results) == 2
            assert all(len(v) == provider.EMBEDDING_DIM and all(x == 0.0 for x in v) for v in results)

    def test_embed_success(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_client.embeddings.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            results = provider.embed(["hello"])
            assert len(results) == 1
            assert results[0][0] == 0.1

    def test_embed_dimension_mismatch(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(embedding=[0.1] * 100)]  # wrong dim
        mock_client.embeddings.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            results = provider.embed(["hello"])
            assert results[0] is None

    def test_embed_api_failure(self):
        mock_client = MagicMock()
        mock_client.embeddings.create.side_effect = RuntimeError("API down")

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            results = provider.embed(["hello"])
            assert results == [None]

    def test_embed_mixed_empty_and_non_empty(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [
            MagicMock(embedding=[0.1] * 1536),
            MagicMock(embedding=[0.2] * 1536),
        ]
        mock_client.embeddings.create.return_value = mock_resp

        with patch("app.core.llm.OpenAI", return_value=mock_client):
            provider = DashScopeEmbeddingProvider(api_key="sk-test")
            results = provider.embed(["hello", "", "world"])
            assert len(results) == 3
            assert results[0][0] == 0.1
            assert all(x == 0.0 for x in results[1])
            assert results[2][0] == 0.2


class TestProviderFactory:
    def test_get_chat_provider_auto_detects_deepseek(self):
        with patch("app.core.llm.DeepSeekProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.available = True
            mock_cls.return_value = mock_instance
            provider = get_chat_provider()
            assert provider is mock_instance

    def test_get_chat_provider_raises_when_none_available(self):
        with patch("app.core.llm.DeepSeekProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.available = False
            mock_cls.return_value = mock_instance
            try:
                get_chat_provider()
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "No chat provider" in str(e)

    def test_get_embedding_provider_auto_detects_dashscope(self):
        with patch("app.core.llm.DashScopeEmbeddingProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.available = True
            mock_cls.return_value = mock_instance
            provider = get_embedding_provider()
            assert provider is mock_instance

    def test_register_and_retrieve_named_provider(self):
        provider = FakeChatEmbedProvider()
        register_provider("mock", provider)
        try:
            chat_result = get_chat_provider("mock")
            assert chat_result is provider

            emb_result = get_embedding_provider("mock")
            assert emb_result is provider
        finally:
            import app.core.llm as llm_mod
            llm_mod._PROVIDER_REGISTRY.pop("mock", None)

    def test_singleton_caches_provider(self):
        with patch("app.core.llm._chat_provider", None):
            with patch("app.core.llm._embedding_provider", None):
                with patch("app.core.llm.get_chat_provider") as mock_get:
                    mock_provider = MagicMock()
                    mock_get.return_value = mock_provider
                    p1 = get_default_chat_provider()
                    p2 = get_default_chat_provider()
                    assert p1 is p2
                    mock_get.assert_called_once()
