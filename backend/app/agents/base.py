"""Base agent framework for the notero multi-agent pipeline.

Provides a unified interface for LLM-powered agents that operate on a
Session/Note and persist their outputs into Note.vocabulary via Task tracking.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openai import OpenAI
from sqlalchemy.orm import Session as DBSession

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.models import Notebook, Note, Session as DBSessionModel, Task, User
from app.services.prompt_loader import load_prompt

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
    ) -> str:
        """Call DeepSeek with the agent's prompt and return raw text."""
        if not DEEPSEEK_API_KEY:
            raise ValueError("未配置 DEEPSEEK_API_KEY，无法运行 Agent")

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=120.0,
        )
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": prompt_template.system},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            )
        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise ValueError(f"Agent '{self.role}' 请求 DeepSeek 超时，请稍后重试")
            raise ValueError(f"Agent '{self.role}' 调用 DeepSeek 失败: {error_msg}")

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError(
                f"Agent '{self.role}' 返回被截断 (finish_reason=length)，"
                f"请减少输入长度或增加 max_tokens"
            )

        return choice.message.content.strip()

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

        **Thread-safety:** takes a per-note lock and re-reads Note.vocabulary from
        DB inside a fresh query so parallel agents do not overwrite each other's
        entries (read-modify-write race on the JSON column).
        """
        note_id = ctx.note.id
        lock = _get_vocabulary_lock(note_id)
        with lock:
            # Expire any cached Note object in this session so the next query
            # hits the DB and sees concurrent commits from other threads.
            ctx.db.expire_all()

            # Re-read the note row to get the latest vocabulary state.
            note = ctx.db.query(Note).filter(Note.id == note_id).first()
            if not note:
                raise ValueError(f"Note {note_id} not found during save_to_vocabulary")

            existing = note.vocabulary if isinstance(note.vocabulary, list) else []
            next_items = [
                item for item in existing
                if not (isinstance(item, dict) and item.get("kind") == self.output_kind)
            ]
            entry: dict[str, Any] = {
                "kind": self.output_kind,
                "data": data,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            if extra:
                entry.update(extra)
            next_items.append(entry)
            note.vocabulary = next_items
            ctx.db.commit()

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
        """Best-effort JSON repair: close strings and balance brackets."""
        repaired = text.rstrip()
        while repaired and repaired[-1] == "\\":
            repaired = repaired[:-1]

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
            elif ch in "}]":
                if stack:
                    stack.pop()

        pairs = {"{": "}", "[": "]"}
        while stack:
            repaired += pairs[stack.pop()]

        repaired = repaired.rstrip()
        if repaired.endswith(","):
            repaired = repaired[:-1]
            # Re-close after removing trailing comma
            stack = []
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
                elif ch in "}]":
                    if stack:
                        stack.pop()
            while stack:
                repaired += pairs[stack.pop()]

        return repaired
