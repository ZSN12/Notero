"""Transcript organizer agent.

This agent owns the LLM-powered restructuring of classroom transcripts. It is
the upstream dependency for mindmap and quiz agents: after it runs, downstream
agents consume the organized transcript instead of raw ASR output.

The core restructuring logic is exposed as a class method so that legacy callers
(rolling correction, batch audio cleanup) can reuse it without constructing a
full AgentContext.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.services.prompt_loader import load_prompt
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


# Regexes imported from term_corrector for consistent fence stripping.
_FENCE_START_RE = re.compile(r"^```(?:\w+)?\n", flags=re.MULTILINE)
_FENCE_END_RE = re.compile(r"\n?```\s*$", flags=re.MULTILINE)


class TranscriptOrganizerAgent(BaseAgent):
    """Organizes raw ASR transcript into a clean, readable classroom transcript.

    The agent writes:
      - note.transcript final entry (display_text / corrected_text)
      - note.content "## 语音转文字" section
      - note.layout_blocks transcript blocks
      - note.vocabulary entry kind="organized_transcript"
    """

    role = "transcript"
    task_type = "agent_transcript"
    output_kind = "organized_transcript"
    prompt_name = "transcript"

    temperature = 0.2
    max_tokens = 8000

    # ── Public orchestration ──

    def run(self, ctx: AgentContext) -> AgentResult:
        """Run the transcript organization pipeline for the session."""
        started = time.monotonic()
        try:
            # If the transcript has already been finalized (e.g. by
            # finalize_session_transcript), just package the finalized output
            # instead of running another LLM call.
            finalized_text = self._get_finalized_transcript_text(ctx)
            if finalized_text:
                self._save_organized_transcript(ctx, finalized_text)
                logger.info(
                    "transcript_agent_packaged session_id=%s user_id=%s elapsed_ms=%s",
                    ctx.session_id,
                    ctx.user.id,
                    int((time.monotonic() - started) * 1000),
                )
                return AgentResult(success=True, data={"plain_text": finalized_text})

            from app.services.note_utils import get_canonical_transcript_text

            raw_text = get_canonical_transcript_text(ctx.note)
            if not raw_text.strip():
                return AgentResult(success=False, error_message="没有可用的转写内容")

            course_title = ctx.notebook.title if ctx.notebook else ""
            keywords = ctx.session.keywords or []
            ppt_slides = self._extract_ppt_slides(ctx.note)

            display_text = self._organize_transcript(
                raw_text=raw_text,
                course_title=course_title,
                keywords=keywords,
                ppt_slides=ppt_slides,
            )

            self._persist_transcript(ctx, raw_text, display_text)
            self._save_organized_transcript(ctx, display_text)

            logger.info(
                "transcript_agent_success session_id=%s user_id=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data={"plain_text": display_text})
        except Exception as e:
            logger.exception("transcript_agent_failed session_id=%s", ctx.session_id)
            ctx.db.rollback()
            return AgentResult(success=False, error_message=str(e))

    # ── Reusable LLM core ──

    @classmethod
    def restructure_text(
        cls,
        raw_text: str,
        course_title: str,
        keywords: Optional[list[str]] = None,
        ppt_slides: Optional[list[dict]] = None,
    ) -> str:
        """LLM-powered transcript restructuring (text-in, text-out).

        This is the canonical LLM call previously living in TermCorrector.
        It is kept as a classmethod so rolling correction and batch audio
        cleanup can reuse it without a DB session / AgentContext.
        """
        from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI

        if not DEEPSEEK_API_KEY or not raw_text or not raw_text.strip():
            return raw_text or ""

        keyword_str = "、".join(keywords) if keywords else "无"
        ppt_context = ""

        if ppt_slides:
            ppt_lines = ["## PPT 页面信息（按课堂顺序）"]
            for s in ppt_slides:
                page = s.get("page", "?")
                title = s.get("title", "")
                stext = s.get("text", "")[:200]
                ppt_lines.append(f"第{page}页：{title} — {stext}")
            ppt_context = "\n".join(ppt_lines)
            prompt_template = load_prompt("asr_reorder")
        else:
            prompt_template = load_prompt("asr_correction")

        prompt = prompt_template.render(
            course_title=course_title,
            keywords=keyword_str,
            text=raw_text,
            ppt_context=ppt_context,
        )

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=120.0,
        )
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": prompt_template.system},
                {"role": "user", "content": prompt},
            ],
            temperature=cls.temperature,
            max_tokens=cls.max_tokens,
        )

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError("转写整理返回被截断，请减少输入长度或增加 max_tokens")

        content = choice.message.content.strip()
        content = _FENCE_START_RE.sub("", content)
        content = _FENCE_END_RE.sub("", content)
        return content.strip()

    # ── Internal helpers ──

    def _organize_transcript(
        self,
        raw_text: str,
        course_title: str,
        keywords: list[str],
        ppt_slides: Optional[list[dict]],
    ) -> str:
        """Run LLM + deterministic cleanup to produce display text."""
        from app.services.term_corrector import corrector

        # Tier 2 — deterministic cleanup (always runs)
        local_display = corrector.clean_transcript_for_display(raw_text).strip() or raw_text

        # Tier 3 — LLM enhancement (best-effort)
        try:
            ai_text = self.restructure_text(
                raw_text=local_display,
                course_title=course_title,
                keywords=keywords,
                ppt_slides=ppt_slides,
            )
            ai_text = (ai_text or "").strip()
            if not ai_text:
                raise ValueError("DeepSeek returned empty text")

            display_text = corrector.clean_transcript_for_display(ai_text).strip() or ai_text
        except Exception:
            logger.warning(
                "transcript_agent_llm_fallback session_id=%s",
                getattr(self, "_last_session_id", "unknown"),
                exc_info=True,
            )
            display_text = local_display

        return display_text

    def _get_finalized_transcript_text(self, ctx: AgentContext) -> str:
        """Return already-finalized transcript text if available and fresh."""
        from app.services.note_utils import _extract_transcript_from_content

        # Prefer the finalized entry in note.transcript.
        transcript = getattr(ctx.note, "transcript", None)
        if isinstance(transcript, list):
            for entry in transcript:
                if not isinstance(entry, dict):
                    continue
                if entry.get("correction_stage") == "final":
                    display_text = (
                        entry.get("display_text")
                        or entry.get("corrected_text")
                        or entry.get("text")
                        or ""
                    ).strip()
                    if display_text:
                        return display_text

        # Fallback to the transcript section in note.content.
        content = getattr(ctx.note, "content", None)
        display_text = _extract_transcript_from_content(content).strip()
        return display_text

    def _extract_ppt_slides(self, note) -> Optional[list[dict]]:
        """Return PPT slides from the note if available."""
        ppt_images = getattr(note, "ppt_images", None)
        if not isinstance(ppt_images, list) or not ppt_images:
            return None
        last_ppt = ppt_images[-1]
        if not isinstance(last_ppt, dict):
            return None
        slides = last_ppt.get("slides", [])
        return slides if isinstance(slides, list) else None

    def _persist_transcript(self, ctx: AgentContext, raw_text: str, display_text: str) -> None:
        """Update note.transcript, note.content and note.layout_blocks."""
        note = ctx.note

        # Build unified transcript entry
        updated_entry = {
            "chunk_index": 0,
            "text": display_text,
            "raw_text": raw_text,
            "display_text": display_text,
            "corrected_text": display_text,
            "timestamps": [],
            "is_corrected": display_text != raw_text,
            "is_ai_corrected": True,
            "correction_error": None,
            "is_restructured": False,
            "correction_stage": "final",
        }
        note.transcript = [updated_entry]

        # Update content, preserving student notes below the divider
        existing_content = (note.content or "").strip()
        notes_content = ""
        marker = "\n\n---\n\n"
        if existing_content.startswith("## 语音转文字") and marker in existing_content:
            notes_content = existing_content.split(marker, 1)[1].strip()

        if notes_content:
            note.content = f"## 语音转文字\n\n{display_text}\n\n---\n\n{notes_content}".strip()
        else:
            note.content = f"## 语音转文字\n\n{display_text}".strip()

        # Update layout_blocks, preserving non-transcript blocks
        existing_blocks = list(note.layout_blocks or [])
        transcript_blocks = [
            {
                "id": f"transcript-{i + 1}",
                "type": "transcript",
                "content": part.strip(),
            }
            for i, part in enumerate(display_text.split("\n\n"))
            if part.strip()
        ]
        new_blocks: list[dict] = []
        replaced_transcript = False
        for block in existing_blocks:
            if isinstance(block, dict) and block.get("type") == "transcript":
                if not replaced_transcript:
                    new_blocks.extend(transcript_blocks)
                    replaced_transcript = True
                continue
            new_blocks.append(block)
        if not replaced_transcript:
            new_blocks = transcript_blocks + new_blocks
        note.layout_blocks = new_blocks

        ctx.db.commit()
        ctx.db.refresh(note)

    def _save_organized_transcript(self, ctx: AgentContext, display_text: str) -> None:
        """Save the organized transcript into note.vocabulary."""
        sections = [
            {"title": f"段落 {i + 1}", "text": part.strip()}
            for i, part in enumerate(display_text.split("\n\n"))
            if part.strip()
        ]
        data: dict[str, Any] = {
            "plain_text": display_text,
            "sections": sections,
            "source": "transcript_agent",
        }
        content_hash = _compute_session_content_hash(ctx.note)
        self.save_to_vocabulary(ctx, data, extra={"content_hash": content_hash})
        ctx.db.commit()
