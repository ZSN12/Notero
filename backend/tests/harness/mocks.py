"""Shared mock helpers for backend tests."""

import io
import json
import wave
from unittest.mock import MagicMock, patch


def mock_chat_completion(
    content: str | dict | list,
    *,
    model: str = "gpt-4",
    finish_reason: str = "stop",
) -> MagicMock:
    """Build a mocked OpenAI-style chat client that returns the given content.

    If content is a dict or list it is JSON-serialised before being placed in
    the assistant message content.
    """
    if isinstance(content, (dict, list)):
        text = json.dumps(content, ensure_ascii=False)
    else:
        text = content

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock(role="assistant", content=text)
    mock_response.choices[0].finish_reason = finish_reason
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def mock_chat_stream(chunks: list[str | None]) -> MagicMock:
    """Build a mocked OpenAI-style chat client that streams tokens."""
    mock_client = MagicMock()
    stream_chunks = []
    for chunk in chunks:
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock(delta=MagicMock(content=chunk))]
        stream_chunks.append(mock_chunk)
    mock_client.chat.completions.create.return_value = iter(stream_chunks)
    return mock_client


def mock_embedding_response(embeddings: list[list[float]]) -> MagicMock:
    """Build a mocked embedding client that returns the given vectors."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=vec, index=i) for i, vec in enumerate(embeddings)
    ]
    mock_client.embeddings.create.return_value = mock_response
    return mock_client


def patch_chat_provider(content: str | dict | list, *, target: str = "app.core.llm.OpenAI"):
    """Context manager/decorator that patches the default chat provider call."""
    return patch(target, return_value=mock_chat_completion(content))


def patch_chat_stream(chunks: list[str | None], *, target: str = "app.core.llm.OpenAI"):
    """Context manager/decorator that patches the default chat stream call."""
    return patch(target, return_value=mock_chat_stream(chunks))


class MockASRSession:
    """Mock streaming ASR session for testing."""

    def __init__(self, texts=None, finals=None):
        self._texts = texts or []
        self._finals = finals or []
        self._index = 0

    def feed_pcm(self, pcm_bytes):
        if self._index < len(self._texts):
            text = self._texts[self._index]
            is_final = (
                self._finals[self._index]
                if self._index < len(self._finals)
                else False
            )
            self._index += 1
            return text, is_final
        return "", False

    def finalize(self):
        return []


def make_silent_wav(duration_ms: int = 1000, sample_rate: int = 16000) -> bytes:
    """Return PCM16 mono WAV bytes of silence."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    pcm_data = b"\x00\x00" * num_samples
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)
    return buf.getvalue()
