"""Context agent for multi-turn RAG conversations.

Responsible for turning a contextualized follow-up question into a
standalone retrieval query and a short conversation summary.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.llm import get_default_chat_provider, ChatMessage
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


class RAGContextAgent:
    """Rewrite a follow-up query using conversation history."""

    role: str = "rag_context"
    task_type: str = "rag_context"

    def __init__(self) -> None:
        self._prompt_template = load_prompt("agents/rag_context")

    def contextualize(
        self,
        history: list[dict[str, Any]],
        latest_query: str,
    ) -> dict[str, str]:
        """Return {'standalone_query': str, 'context_summary': str}.

        If history is empty, returns the original query verbatim.
        """
        if not history:
            return {"standalone_query": latest_query, "context_summary": ""}

        history_text = self._format_history(history)
        user_prompt = self._prompt_template.render(
            history=history_text,
            latest_query=latest_query,
        )

        try:
            provider = get_default_chat_provider()
            response = provider.chat(
                messages=[
                    ChatMessage(role="system", content=self._prompt_template.system),
                    ChatMessage(role="user", content=user_prompt),
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
            standalone = (parsed.get("standalone_query") or latest_query).strip()
            summary = (parsed.get("context_summary") or "").strip()
            if not standalone:
                standalone = latest_query
            return {"standalone_query": standalone, "context_summary": summary}
        except Exception:
            logger.exception("rag_context_agent_failed")
            # Fail open: still answer using the original query.
            return {"standalone_query": latest_query, "context_summary": ""}

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for msg in history:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if msg.get("is_summary") or role == "summary":
                lines.append(f"摘要：{content}")
            elif role == "user":
                lines.append(f"学生：{content}")
            else:
                lines.append(f"助教：{content}")
        return "\n".join(lines) if lines else "（无历史对话）"

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.split("\n") if not line.startswith("```")
            ).strip()
        return json.loads(text)
