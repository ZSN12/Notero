"""Tests for embedding service with mocked API calls."""

import os
import sys
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.services.embedding_service import (
    EmbeddingService,
    get_embedding_service,
    neural_embedding,
    neural_embedding_batch,
    EMBEDDING_DIM,
)


class TestEmbeddingService:
    def test_available_when_api_key_set(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI"):
                svc = EmbeddingService()
                assert svc.available is True

    def test_not_available_when_no_api_key(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", ""):
            svc = EmbeddingService()
            assert svc.available is False

    def test_embed_empty_text_returns_zero_vector(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI"):
                svc = EmbeddingService()
                result = svc.embed("")
                assert result is not None
                vec = struct.unpack(f"{EMBEDDING_DIM}f", result)
                assert all(v == 0.0 for v in vec)

    def test_embed_whitespace_returns_zero_vector(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI"):
                svc = EmbeddingService()
                result = svc.embed("   \n\t  ")
                assert result is not None
                vec = struct.unpack(f"{EMBEDDING_DIM}f", result)
                assert all(v == 0.0 for v in vec)

    def test_embed_not_available_returns_none(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", ""):
            svc = EmbeddingService()
            result = svc.embed("hello")
            assert result is None

    def test_embed_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIM)]
        mock_client.embeddings.create.return_value = mock_response

        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                svc = EmbeddingService()
                result = svc.embed("hello world")
                assert result is not None
                vec = struct.unpack(f"{EMBEDDING_DIM}f", result)
                assert abs(vec[0] - 0.1) < 1e-6
                mock_client.embeddings.create.assert_called_once()

    def test_embed_api_failure_returns_none(self):
        mock_client = MagicMock()
        mock_client.embeddings.create.side_effect = RuntimeError("API down")

        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                svc = EmbeddingService()
                result = svc.embed("hello")
                assert result is None

    def test_embed_dimension_mismatch_returns_none(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 100)]  # wrong dim
        mock_client.embeddings.create.return_value = mock_response

        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                svc = EmbeddingService()
                result = svc.embed("hello")
                assert result is None


class TestEmbedBatch:
    def test_batch_all_empty_texts(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI"):
                svc = EmbeddingService()
                results = svc.embed_batch(["", "  ", "\t"])
                assert len(results) == 3
                for r in results:
                    vec = struct.unpack(f"{EMBEDDING_DIM}f", r)
                    assert all(v == 0.0 for v in vec)

    def test_batch_mixed_empty_and_non_empty(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * EMBEDDING_DIM),
            MagicMock(embedding=[0.2] * EMBEDDING_DIM),
        ]
        mock_client.embeddings.create.return_value = mock_response

        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                svc = EmbeddingService()
                results = svc.embed_batch(["hello", "", "world", "  "])
                assert len(results) == 4
                # Non-empty texts at index 0 and 2
                vec0 = struct.unpack(f"{EMBEDDING_DIM}f", results[0])
                assert abs(vec0[0] - 0.1) < 1e-6
                vec2 = struct.unpack(f"{EMBEDDING_DIM}f", results[2])
                assert abs(vec2[0] - 0.2) < 1e-6
                # Empty texts are zero vectors
                vec1 = struct.unpack(f"{EMBEDDING_DIM}f", results[1])
                assert all(v == 0.0 for v in vec1)
                vec3 = struct.unpack(f"{EMBEDDING_DIM}f", results[3])
                assert all(v == 0.0 for v in vec3)

    def test_batch_api_failure_fallback_to_single(self):
        mock_client = MagicMock()
        mock_client.embeddings.create.side_effect = [
            RuntimeError("batch failed"),  # first call (batch) fails
            MagicMock(data=[MagicMock(embedding=[0.1] * EMBEDDING_DIM)]),  # single fallback succeeds
        ]

        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", "test-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                svc = EmbeddingService()
                results = svc.embed_batch(["hello"])
                assert len(results) == 1
                assert results[0] is not None
                # Should have been called twice: batch failed, then single fallback
                assert mock_client.embeddings.create.call_count == 2

    def test_batch_not_available_returns_all_none(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", ""):
            svc = EmbeddingService()
            results = svc.embed_batch(["a", "b"])
            assert results == [None, None]


class TestSingleton:
    def test_get_embedding_service_returns_same_instance(self):
        with patch("app.services.embedding_service.DASHSCOPE_API_KEY", ""):
            # Reset singleton
            import app.services.embedding_service as _emb_mod
            _emb_mod._embedding_service = None
            s1 = get_embedding_service()
            s2 = get_embedding_service()
            assert s1 is s2


class TestModuleLevelFunctions:
    def test_neural_embedding_delegates_to_service(self):
        mock_svc = MagicMock()
        mock_svc.embed.return_value = b"packed"

        with patch("app.services.embedding_service.get_embedding_service", return_value=mock_svc):
            result = neural_embedding("hello")
            assert result == b"packed"
            mock_svc.embed.assert_called_once_with("hello")

    def test_neural_embedding_batch_delegates_to_service(self):
        mock_svc = MagicMock()
        mock_svc.embed_batch.return_value = [b"a", b"b"]

        with patch("app.services.embedding_service.get_embedding_service", return_value=mock_svc):
            result = neural_embedding_batch(["x", "y"])
            assert result == [b"a", b"b"]
            mock_svc.embed_batch.assert_called_once_with(["x", "y"])
