"""Unified LLM provider abstraction.

Provides a thin wrapper around OpenAI-compatible APIs (DeepSeek, DashScope,
Qwen, etc.) so callers don't hard-code provider-specific details.

Migration guide:
  - New code should use get_chat_provider() / get_embedding_provider().
  - Existing code can migrate gradually; the old direct OpenAI client usage
    remains functional.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, List, Optional, Dict, Any

from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatChoice:
    message: ChatMessage
    finish_reason: Optional[str] = None


@dataclass
class ChatResponse:
    choices: List[ChatChoice]


class LLMProvider(ABC):
    """Abstract chat completion provider."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Return True if the provider is configured and ready."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse:
        """Non-streaming chat completion."""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Streaming chat completion; yields text chunks."""
        ...


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    @property
    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def embed(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed a batch of texts. Returns None for failed items."""
        ...


# ---------------------------------------------------------------------------
# DeepSeek provider (OpenAI-compatible)
# ---------------------------------------------------------------------------

class DeepSeekProvider(LLMProvider):
    """DeepSeek via OpenAI-compatible API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.default_model = default_model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self._client = None
        if self.api_key:
            try:
                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                logger.info("deepseek_provider_initialized model=%s", self.default_model)
            except Exception as exc:
                logger.warning("deepseek_provider_init_failed error=%s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def _to_openai_messages(self, messages: List[ChatMessage]) -> List[Dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.available:
            raise RuntimeError("DeepSeek provider is not available (missing API key)")

        params: Dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "stream": stream,
            **kwargs,
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if response_format is not None:
            params["response_format"] = response_format

        resp = self._client.chat.completions.create(**params)
        choices = [
            ChatChoice(
                message=ChatMessage(role=c.message.role, content=c.message.content),
                finish_reason=getattr(c, "finish_reason", None),
            )
            for c in resp.choices
        ]
        return ChatResponse(choices=choices)

    def chat_stream(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        if not self.available:
            raise RuntimeError("DeepSeek provider is not available (missing API key)")

        params = {
            "model": model or self.default_model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "stream": True,
            **kwargs,
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        for chunk in self._client.chat.completions.create(**params):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ---------------------------------------------------------------------------
# DashScope embedding provider (OpenAI-compatible)
# ---------------------------------------------------------------------------

class DashScopeEmbeddingProvider(EmbeddingProvider):
    """DashScope text-embedding via OpenAI-compatible API."""

    EMBEDDING_DIM = 1536
    DEFAULT_MODEL = "text-embedding-v2"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._client = None
        if self.api_key:
            try:
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
                logger.info("dashscope_embedding_provider_initialized")
            except Exception as exc:
                logger.warning("dashscope_embedding_provider_init_failed error=%s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def embed(self, texts: List[str]) -> List[Optional[List[float]]]:
        if not self.available:
            return [None] * len(texts)

        non_empty = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty:
            return [[0.0] * self.EMBEDDING_DIM for _ in texts]

        try:
            response = self._client.embeddings.create(
                model=self.DEFAULT_MODEL,
                input=[t for _, t in non_empty],
                encoding_format="float",
            )
            results: List[Optional[List[float]]] = [None] * len(texts)
            for (orig_idx, _), emb_data in zip(non_empty, response.data):
                vec = emb_data.embedding
                if len(vec) != self.EMBEDDING_DIM:
                    logger.warning(
                        "embedding_dim_mismatch expected=%s got=%s",
                        self.EMBEDDING_DIM, len(vec),
                    )
                    continue
                results[orig_idx] = vec
            for i, t in enumerate(texts):
                if not t or not t.strip():
                    results[i] = [0.0] * self.EMBEDDING_DIM
            return results
        except Exception as exc:
            logger.warning("dashscope_embed_batch_failed count=%s error=%s", len(non_empty), exc)
            return [None] * len(texts)


# ---------------------------------------------------------------------------
# Provider registry & factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: Dict[str, Any] = {}


def register_provider(name: str, provider: Any) -> None:
    """Register a provider instance by name."""
    _PROVIDER_REGISTRY[name] = provider
    logger.info("provider_registered name=%s type=%s", name, type(provider).__name__)


def get_chat_provider(name: Optional[str] = None) -> LLMProvider:
    """Get a chat provider by name, or auto-detect from environment.

    Priority:
      1. Named provider if registered.
      2. DeepSeek if DEEPSEEK_API_KEY is set.
      3. Raise RuntimeError if none available.
    """
    if name and name in _PROVIDER_REGISTRY:
        provider = _PROVIDER_REGISTRY[name]
        if isinstance(provider, LLMProvider):
            return provider
        raise RuntimeError(f"Provider '{name}' is not a chat provider")

    # Auto-detect: DeepSeek
    deepseek = DeepSeekProvider()
    if deepseek.available:
        return deepseek

    raise RuntimeError(
        "No chat provider available. Set DEEPSEEK_API_KEY or register a custom provider."
    )


def get_embedding_provider(name: Optional[str] = None) -> EmbeddingProvider:
    """Get an embedding provider by name, or auto-detect from environment."""
    if name and name in _PROVIDER_REGISTRY:
        provider = _PROVIDER_REGISTRY[name]
        if isinstance(provider, EmbeddingProvider):
            return provider
        raise RuntimeError(f"Provider '{name}' is not an embedding provider")

    dashscope = DashScopeEmbeddingProvider()
    if dashscope.available:
        return dashscope

    raise RuntimeError(
        "No embedding provider available. Set DASHSCOPE_API_KEY or register a custom provider."
    )


# ---------------------------------------------------------------------------
# Lazy-init global singletons (thread-safe enough for typical web workloads)
# ---------------------------------------------------------------------------

_chat_provider: Optional[LLMProvider] = None
_embedding_provider: Optional[EmbeddingProvider] = None


def get_default_chat_provider() -> LLMProvider:
    global _chat_provider
    if _chat_provider is None:
        _chat_provider = get_chat_provider()
    return _chat_provider


def get_default_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = get_embedding_provider()
    return _embedding_provider


def _reset_default_providers() -> None:
    """Reset lazy singletons. Intended for tests only."""
    global _chat_provider, _embedding_provider
    _chat_provider = None
    _embedding_provider = None
