"""Base agent framework for the notero multi-agent pipeline.

Provides a unified interface for LLM-powered agents that operate on a
Session/Note and persist their outputs into Note.vocabulary via Task tracking.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.exceptions import LLMTimeoutError
from app.core.llm import ChatMessage, get_default_chat_provider
from app.models import Notebook, Note, Session as DBSessionModel, Task, User
from app.services.prompt_loader import load_prompt
from app.services.vocabulary_service import build_entry, save_vocabulary_entry

logger = logging.getLogger(__name__)

# Per-note locks to prevent read-modify-write races on Note.vocabulary when
# multiple agents run in parallel threads. Keyed by Note.id.
_VOCABULARY_LOCKS: dict[str, threading.Lock] = {}
_VOCABULARY_LOCKS_LOCK = threading.Lock()


def _get_vocabulary_lock(note_id: str) -> threading.Lock:
    """Return a lock scoped to a single note for vocabulary writes."""
    lock = _VOCABULARY_LOCKS.get(note_id)
    if lock is None:
        with _VOCABULARY_LOCKS_LOCK:
            lock = _VOCABULARY_LOCKS.get(note_id)
            if lock is None:
                lock = threading.Lock()
                _VOCABULARY_LOCKS[note_id] = lock
    return lock


@dataclass
class AgentResult:
    """Result of a single agent execution."""

    success: bool
    data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    skipped: bool = False
    warning_message: Optional[str] = None
    warning_message: Optional[str] = None


@dataclass
class AgentContext:
    """Context passed to every agent run()."""

    session_id: str
    user: User
    db: DBSession
    note: Note
    session: DBSessionModel
    notebook: Notebook
    force: bool = False
    task: Optional[Task] = None  # Optional task for progress updates

    def get_content_text(self, max_length: Optional[int] = None) -> str:
        """Extract all indexable content from the note into a single text.

        Uses the canonical extraction so user edits win over raw ASR and old
        layout_blocks cannot resurrect deleted text.
        """
        from app.services.note_utils import get_canonical_note_text
        text = get_canonical_note_text(self.note, include_ppt=True)
        if max_length and len(text) > max_length:
            text = text[:max_length]
        return text

    def get_keywords_text(self) -> str:
        """Return comma-separated keywords or a default placeholder."""
        return ", ".join(self.session.keywords) if self.session.keywords else "无"

    def get_organized_transcript_text(self, max_length: Optional[int] = None) -> str:
        """Return the organized transcript plain_text if a fresh entry exists."""
        from app.services.vector_service import _compute_session_content_hash

        if not isinstance(self.note.vocabulary, list):
            return ""

        current_hash = _compute_session_content_hash(self.note)
        for item in self.note.vocabulary:
            if not isinstance(item, dict) or item.get("kind") != "organized_transcript":
                continue
            stored_hash = item.get("content_hash")
            if stored_hash != current_hash:
                continue
            data = item.get("data") or {}
            plain_text = (data.get("plain_text") or "").strip()
            if not plain_text:
                continue
            if max_length and len(plain_text) > max_length:
                return plain_text[:max_length]
            return plain_text
        return ""

    def get_content_text_for_agent(self, max_length: Optional[int] = None) -> str:
        """Preferred input text for downstream agents.

        Uses the organized transcript if it is fresh; otherwise falls back to the
        canonical note text (raw transcript + notes + PPT).
        """
        organized = self.get_organized_transcript_text(max_length=max_length)
        if organized:
            return organized
        return self.get_content_text(max_length=max_length)


class BaseAgent(ABC):
    """Abstract base class for all notero agents.

    Subclasses define:
      - role: unique agent identifier
      - task_type: value stored in Task.task_type
      - output_kind: key used in Note.vocabulary
      - prompt_name: prompts/agents/{prompt_name}.md
    """

    role: str = ""
    task_type: str = ""
    output_kind: str = ""
    prompt_name: str = ""

    # Default LLM parameters; subclasses may override.
    temperature: float = 0.3
    max_tokens: int = 4000
    timeout: float = 120.0

    def __init__(self) -> None:
        if not all([self.role, self.task_type, self.output_kind, self.prompt_name]):
            raise ValueError(
                f"Agent subclass {self.__class__.__name__} must define role, task_type, output_kind, and prompt_name"
            )

    # ── Public API ──

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        """Execute the agent against the given context.

        Responsible for reading inputs, calling the LLM, validating output,
        and writing results. Returns AgentResult.
        """
        ...

    # ── Shared helpers ──

    def load_prompt_template(self):
        """Load the agent's prompt template from prompts/agents/."""
        return load_prompt(f"agents/{self.prompt_name}")

    def call_llm(
        self,
        prompt_template,
        user_content: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Call the default chat provider with the agent's prompt and return raw text."""
        provider = get_default_chat_provider()
        if not provider.available:
            raise ValueError(f"未配置可用的 AI Provider，无法运行 Agent '{self.role}'")

        messages = [
            ChatMessage(role="system", content=prompt_template.system),
            ChatMessage(role="user", content=user_content),
        ]

        # DeepSeek V4 defaults to thinking mode, which slows down structured-output
        # agents (mindmap/quiz) and is unnecessary for them. Disable it when the
        # configured model is a V4 variant.
        kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
        if provider.__class__.__name__ == "DeepSeekProvider":
            from app.config import DEEPSEEK_MODEL
            if DEEPSEEK_MODEL and "deepseek-v4" in DEEPSEEK_MODEL:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        started = time.monotonic()
        try:
            response = provider.chat(
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
                timeout=timeout if timeout is not None else self.timeout,
                **kwargs,
            )
        except Exception as e:
            logger.warning(
                "agent_llm_request_failed role=%s elapsed_ms=%s",
                self.role,
                int((time.monotonic() - started) * 1000),
            )
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise ValueError(f"Agent '{self.role}' 请求 LLM 超时，请稍后重试")
            raise ValueError(f"Agent '{self.role}' 调用 LLM 失败: {error_msg}")

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError(
                f"Agent '{self.role}' 返回被截断 (finish_reason=length)，"
                f"请减少输入长度或增加 max_tokens"
            )

        content = choice.message.content.strip()
        logger.info(
            "agent_llm_request_success role=%s elapsed_ms=%s output_chars=%s",
            self.role,
            int((time.monotonic() - started) * 1000),
            len(content),
        )
        return content

    def parse_json(self, raw: str, repair: bool = True) -> dict:
        """Parse LLM JSON output, stripping markdown fences and optionally repairing."""
        text = self._strip_code_fences(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            if repair:
                repaired = self._repair_json(text)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Agent '{self.role}' 返回的 JSON 格式无效: {e}")

    def save_to_vocabulary(
        self,
        ctx: AgentContext,
        data: dict[str, Any],
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Persist agent output into Note.vocabulary as an entry with this agent's kind.

        **Concurrency:** agents may run in parallel Celery workers, so the write
        uses a database-level ``SELECT ... FOR UPDATE`` row lock.  The per-process
        ``threading.Lock`` is kept as an in-process belt-and-suspenders guard.
        """
        note_id = ctx.note.id
        entry = build_entry(self.output_kind, data, extra)
        lock = _get_vocabulary_lock(note_id)
        with lock:
            save_vocabulary_entry(ctx.db, note_id, entry)

    def get_existing_output(self, ctx: AgentContext) -> Optional[dict[str, Any]]:
        """Return any existing vocabulary entry for this agent's kind, or None."""
        if not isinstance(ctx.note.vocabulary, list):
            return None
        for item in ctx.note.vocabulary:
            if isinstance(item, dict) and item.get("kind") == self.output_kind:
                return item
        return None

    # ── Internal helpers ──

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            return "\n".join(lines).strip()
        return raw.strip()

    @staticmethod
    def _repair_json(text: str) -> str:
        """Best-effort JSON repair: close strings and balance brackets.

        With ``response_format={"type": "json_object"}`` this should rarely be
        triggered; it is kept only as a last-resort fallback.
        """
        repaired = text.strip()
        while repaired.endswith("\\"):
            repaired = repaired[:-1]

        # Close an unterminated string.
        in_string = False
        escape = False
        for ch in repaired:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
        if in_string:
            repaired += '"'

        # Balance brackets, ignoring content inside strings.
        stack: list[str] = []
        in_string = False
        escape = False
        for ch in repaired:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]" and stack:
                stack.pop()

        pairs = {"{": "}", "[": "]"}
        while stack:
            repaired += pairs[stack.pop()]

        return repaired
