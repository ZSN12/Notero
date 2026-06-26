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
from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.llm import ChatMessage, get_default_chat_provider
from app.services.prompt_loader import load_prompt
from app.services.term_corrector import TermCorrector
from app.services.course_terms_service import build_shared_course_terms_for_session
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


# Regexes imported from term_corrector for consistent fence stripping.
_FENCE_START_RE = re.compile(r"^```(?:\w+)?\n", flags=re.MULTILINE)
_FENCE_END_RE = re.compile(r"\n?```\s*$", flags=re.MULTILINE)

# Time marker prefixed to each paragraph by the LLM, e.g. "[1200-5600] 段落文本"
_PARAGRAPH_MARKER_RE = re.compile(r"^\[(\d+)-(\d+)\]\s*", re.MULTILINE)


@dataclass(frozen=True)
class ParagraphRange:
    """A single organized paragraph with its audio time range."""

    text: str
    start_ms: int
    end_ms: int


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
                # Reuse paragraph time ranges computed during finalization if
                # they are still fresh.
                paragraph_ranges = self._load_existing_paragraph_ranges(ctx)
                self._save_organized_transcript(ctx, finalized_text, paragraph_ranges)
                logger.info(
                    "transcript_agent_packaged session_id=%s user_id=%s elapsed_ms=%s",
                    ctx.session_id,
                    ctx.user.id,
                    int((time.monotonic() - started) * 1000),
                )
                return AgentResult(success=True, data={"plain_text": finalized_text})

            from app.services.note_utils import get_canonical_transcript_segments

            raw_text, raw_segments = get_canonical_transcript_segments(ctx.note)
            if not raw_text.strip():
                return AgentResult(success=False, error_message="没有可用的转写内容")

            course_title = ctx.notebook.title if ctx.notebook else ""
            ppt_slides = self._extract_ppt_slides(ctx.note)
            keywords = build_shared_course_terms_for_session(
                ctx.db,
                ctx.session,
                course_title=course_title,
                current_keywords=ctx.session.keywords or [],
                ppt_slides=ppt_slides,
            )

            paragraph_ranges = self._organize_transcript(
                raw_text=raw_text,
                raw_segments=raw_segments,
                course_title=course_title,
                keywords=keywords,
                ppt_slides=ppt_slides,
            )

            display_text = "\n\n".join(r.text for r in paragraph_ranges)
            self._persist_transcript(ctx, raw_text, display_text, paragraph_ranges)
            self._save_organized_transcript(ctx, display_text, paragraph_ranges)

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

        Time ranges are not returned by this thin wrapper; use
        :meth:`restructure_with_time` when audio synchronization is required.
        """
        ranges = cls.restructure_with_time(
            raw_text=raw_text,
            segments=None,
            course_title=course_title,
            keywords=keywords,
            ppt_slides=ppt_slides,
        )
        return "\n\n".join(r.text for r in ranges) if ranges else raw_text

    @classmethod
    def restructure_with_time(
        cls,
        raw_text: str,
        segments: Optional[list[dict]] = None,
        course_title: str = "",
        keywords: Optional[list[str]] = None,
        ppt_slides: Optional[list[dict]] = None,
    ) -> list[ParagraphRange]:
        """LLM-powered restructuring that preserves per-paragraph audio timings.

        When ``segments`` is provided, each raw ASR segment is prefixed with a
        ``[start_ms-end_ms]`` marker in the prompt. The model is instructed to
        keep one marker at the beginning of each output paragraph so callers can
        map paragraphs back to audio positions.

        Returns a list of :class:`ParagraphRange`. If the LLM is unavailable or
        fails, an empty list is returned so callers can fall back to plain text.
        """
        from app.config import DEEPSEEK_API_KEY

        if not DEEPSEEK_API_KEY or not raw_text or not raw_text.strip():
            return []

        keyword_str = "、".join(keywords) if keywords else "无"
        course_terms = TermCorrector.build_course_terms(course_title, keywords, ppt_slides)
        course_terms_str = "、".join(course_terms) if course_terms else "无"
        timestamped_text = cls._build_timestamped_text(segments)
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
            course_terms=course_terms_str,
            text=raw_text,
            timestamped_text=timestamped_text,
            ppt_context=ppt_context,
        )

        provider = get_default_chat_provider()
        response = provider.chat(
            messages=[
                ChatMessage(role="system", content=prompt_template.system),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=cls.temperature,
            max_tokens=cls.max_tokens,
            timeout=120.0,
            response_format={"type": "json_object"},
        )

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError("转写整理返回被截断，请减少输入长度或增加 max_tokens")

        content = choice.message.content.strip()
        content = _FENCE_START_RE.sub("", content)
        content = _FENCE_END_RE.sub("", content)
        return cls._parse_marked_paragraphs(content)

    # ── Internal helpers ──

    def _organize_transcript(
        self,
        raw_text: str,
        raw_segments: list[dict],
        course_title: str,
        keywords: list[str],
        ppt_slides: Optional[list[dict]],
    ) -> list[ParagraphRange]:
        """Run LLM + deterministic cleanup to produce paragraph ranges."""
        from app.services.term_corrector import corrector

        # Tier 2 — deterministic cleanup (always runs)
        local_display = corrector.clean_transcript_for_display(raw_text).strip() or raw_text

        # Tier 3 — LLM enhancement (best-effort)
        try:
            ranges = self.restructure_with_time(
                raw_text=local_display,
                segments=raw_segments,
                course_title=course_title,
                keywords=keywords,
                ppt_slides=ppt_slides,
            )
            if not ranges:
                raise ValueError("DeepSeek returned no paragraph ranges")

            # Clean each paragraph with the deterministic pipeline while
            # preserving the time marker at the start.
            cleaned_ranges: list[ParagraphRange] = []
            for r in ranges:
                cleaned_text = corrector.clean_transcript_for_display(r.text).strip() or r.text
                if not cleaned_text:
                    continue
                cleaned_ranges.append(
                    ParagraphRange(
                        text=cleaned_text,
                        start_ms=r.start_ms,
                        end_ms=max(r.end_ms, r.start_ms),
                    )
                )
            display_ranges = cleaned_ranges
        except Exception:
            logger.warning(
                "transcript_agent_llm_fallback session_id=%s",
                getattr(self, "_last_session_id", "unknown"),
                exc_info=True,
            )
            display_ranges = [ParagraphRange(text=local_display, start_ms=0, end_ms=0)]

        return display_ranges

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

    def _load_existing_paragraph_ranges(self, ctx: AgentContext) -> Optional[list[ParagraphRange]]:
        """Reuse paragraph time ranges from a fresh organized_transcript entry."""
        existing = self.get_existing_output(ctx)
        if not isinstance(existing, dict):
            return None
        data = existing.get("data") or {}
        paragraphs = data.get("paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            return None
        ranges: list[ParagraphRange] = []
        for p in paragraphs:
            if not isinstance(p, dict):
                continue
            text = str(p.get("text") or "").strip()
            if not text:
                continue
            ranges.append(
                ParagraphRange(
                    text=text,
                    start_ms=int(p.get("start_ms") or 0),
                    end_ms=int(p.get("end_ms") or 0),
                )
            )
        return ranges if ranges else None

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

    def _persist_transcript(
        self,
        ctx: AgentContext,
        raw_text: str,
        display_text: str,
        paragraph_ranges: list[ParagraphRange],
    ) -> None:
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
                "content": r.text,
            }
            for i, r in enumerate(paragraph_ranges)
            if r.text
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

    def _save_organized_transcript(
        self,
        ctx: AgentContext,
        display_text: str,
        paragraph_ranges: Optional[list[ParagraphRange]] = None,
    ) -> None:
        """Save the organized transcript into note.vocabulary.

        If ``paragraph_ranges`` is not provided, the method tries to reuse the
        ranges from the existing organized_transcript entry when the content
        hash matches. This keeps audio-text synchronization intact when the
        agent is only repackaging an already-finalized transcript.
        """
        if paragraph_ranges is None:
            paragraph_ranges = self._load_existing_paragraph_ranges(ctx)

        sections = []
        for i, r in enumerate(paragraph_ranges or []):
            sections.append(
                {
                    "title": f"段落 {i + 1}",
                    "text": r.text,
                    "start_ms": r.start_ms,
                    "end_ms": r.end_ms,
                }
            )

        paragraphs: list[dict[str, Any]] = [
            asdict(r) for r in (paragraph_ranges or [])
        ]
        data: dict[str, Any] = {
            "plain_text": display_text,
            "sections": sections,
            "paragraphs": paragraphs,
            "source": "transcript_agent",
        }
        content_hash = _compute_session_content_hash(ctx.note)
        self.save_to_vocabulary(ctx, data, extra={"content_hash": content_hash})
        ctx.db.commit()

    @staticmethod
    def _build_timestamped_text(segments: Optional[list[dict]]) -> str:
        """Build the prompt snippet that carries raw ASR timings."""
        if not segments:
            return "（无）"
        lines: list[str] = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(seg.get("start_ms", 0) or 0)
            end_ms = int(seg.get("end_ms", 0) or 0)
            lines.append(f"[{start_ms}-{end_ms}] {text}")
        return "\n".join(lines) if lines else "（无）"

    @classmethod
    def _parse_marked_paragraphs(cls, text: str) -> list[ParagraphRange]:
        """Split LLM output into paragraphs and extract leading time markers."""
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        ranges: list[ParagraphRange] = []
        for part in parts:
            match = _PARAGRAPH_MARKER_RE.match(part)
            if match:
                start_ms = int(match.group(1))
                end_ms = int(match.group(2))
                para_text = part[match.end() :].strip()
            else:
                start_ms = 0
                end_ms = 0
                para_text = part
            if not para_text:
                continue
            ranges.append(
                ParagraphRange(
                    text=para_text,
                    start_ms=start_ms,
                    end_ms=max(end_ms, start_ms),
                )
            )
        return ranges
