"""Memory agent for multi-turn RAG conversations.

Responsible for compressing a single Q&A turn into a short summary that can
be used as condensed context in future turns.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.llm import get_default_chat_provider, ChatMessage
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


class RAGMemoryAgent:
    """Generate a concise summary of a Q&A turn for long-term conversation memory."""

    role: str = "rag_memory"
    task_type: str = "rag_memory"

    def __init__(self) -> None:
        self._prompt_template = load_prompt("agents/rag_memory")

    def summarize_turn(
        self,
        prior_summary: str,
        user_query: str,
        assistant_answer: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Return a one-sentence summary of the turn, or empty string if irrelevant."""
        if not user_query.strip() or not assistant_answer.strip():
            return ""

        user_prompt = self._prompt_template.render(
            prior_summary=prior_summary or "（无）",
            user_query=user_query.strip(),
            assistant_answer=assistant_answer.strip(),
        )

        try:
            provider = get_default_chat_provider()
            response = provider.chat(
                messages=[
                    ChatMessage(role="system", content=self._prompt_template.system),
                    ChatMessage(role="user", content=user_prompt),
                ],
                temperature=0.2,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
            summary = (parsed.get("turn_summary") or "").strip()
            return summary
        except Exception:
            logger.exception("rag_memory_agent_failed")
            return ""

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.split("\n") if not line.startswith("```")
            ).strip()
        return json.loads(text)
