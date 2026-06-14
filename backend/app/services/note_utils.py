"""Canonical note text extraction utilities.

Centralises how the backend reads the "final" transcript / note text so that
agents, vector index, mindmap and quiz services all see the same content and do
not accidentally restore raw ASR text that the user has already edited or
deleted.
"""

from __future__ import annotations

import html as html_module
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Note

_TRANSCRIPT_MARKER = "## 语音转文字"
_NOTES_MARKER = "\n\n---\n\n"


def _strip_html(value: str | None) -> str:
    """Remove HTML tags and decode entities."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    return html_module.unescape(text).strip()


def _extract_transcript_from_content(content: str | None) -> str:
    """Extract the transcript section from note.content (below marker, above notes)."""
    content = (content or "").strip()
    if not content.startswith(_TRANSCRIPT_MARKER):
        return ""
    body = content[len(_TRANSCRIPT_MARKER):]
    stripped = body.lstrip()
    # Empty transcript area: content looks like "## 语音转文字\n\n---\n\nnotes"
    if re.match(r"---\s*(?:\n\s*\n|$)", stripped):
        return ""
    if _NOTES_MARKER in body:
        body = body.split(_NOTES_MARKER, 1)[0]
    return body.strip()


def _extract_notes_from_content(content: str | None) -> str:
    """Extract the student-notes section from note.content (below the divider)."""
    content = (content or "").strip()
    if _NOTES_MARKER not in content:
        return ""
    return content.split(_NOTES_MARKER, 1)[1].strip()


def _dedupe_append(existing: str, new: str) -> str:
    """Append new text to existing, removing duplicated prefix/overlap.

    Used when merging a user-edited transcript baseline with later ASR chunks.
    Streaming ASR may return the cumulative transcript (old A + new B) after a
    pause/resume; this function finds the longest suffix of ``existing`` that
    appears inside ``new`` and only appends the genuinely new words/characters
    after it. It works for both space-separated languages and Chinese.
    """
    existing = existing.strip()
    new = new.strip()
    if not new:
        return existing
    if not existing:
        return new
    if new in existing:
        return existing
    if new.startswith(existing):
        suffix = new[len(existing):].strip()
        return f"{existing}\n\n{suffix}".strip() if suffix else existing

    # Word-level overlap detection avoids false matches on single characters.
    existing_words = existing.split()
    new_words = new.split()
    for length in range(len(existing_words), 0, -1):
        suffix = existing_words[-length:]
        for i in range(len(new_words) - length + 1):
            if new_words[i:i + length] == suffix:
                remainder = " ".join(new_words[i + length:]).strip()
                return f"{existing}\n\n{remainder}".strip() if remainder else existing

    # Character-level overlap for Chinese / no-space text. Two-character overlap
    # covers most Chinese words; for Latin text we require a longer overlap to
    # avoid false matches on short letter sequences.
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", existing + new))
    min_overlap = 2 if has_cjk else 5
    max_overlap = min(len(existing), len(new))
    for length in range(max_overlap, min_overlap - 1, -1):
        suffix = existing[-length:]
        pos = new.find(suffix)
        if pos >= 0:
            remainder = new[pos + length:].strip()
            return f"{existing}\n\n{remainder}".strip() if remainder else existing

    return f"{existing}\n\n{new}".strip()


def _transcript_chunk_text(chunk: dict) -> str:
    """Return the best available text from a transcript chunk entry.

    Priority: display_text > corrected_text > text > raw_text
    """
    if not isinstance(chunk, dict):
        return ""
    return (
        chunk.get("display_text")
        or chunk.get("corrected_text")
        or chunk.get("text")
        or chunk.get("raw_text")
        or ""
    ).strip()


def _extract_ppt_text_parts(note: "Note") -> list[str]:
    """Extract supplemental PPT slide text; never used as the primary transcript."""
    parts: list[str] = []
    ppt_images = getattr(note, "ppt_images", None)
    if not ppt_images or not isinstance(ppt_images, list):
        return parts
    for ppt_data in ppt_images:
        if not isinstance(ppt_data, dict):
            continue
        for slide in ppt_data.get("slides", []) or []:
            if not isinstance(slide, dict):
                continue
            slide_text = slide.get("text", "")
            page = slide.get("page", "?")
            if slide_text and str(slide_text).strip():
                parts.append(f"[PPT第{page}页] {str(slide_text).strip()}")
    return parts


def _latest_authoritative_transcript_entry(transcript: list) -> dict | None:
    """Return the latest final or user_edited transcript entry, if any.

    Array order is treated as chronological order. If a user_edited entry exists
    it always wins over an older final entry because it represents the user's
    explicit edit.
    """
    if not isinstance(transcript, list):
        return None
    latest: dict | None = None
    for seg in transcript:
        if not isinstance(seg, dict):
            continue
        stage = seg.get("correction_stage")
        if stage in ("final", "user_edited"):
            latest = seg
    return latest


def get_canonical_transcript_text(note: "Note") -> str:
    """Return the canonical transcript text for a note.

    Reading priority:
      1. The latest note.transcript entry with correction_stage == "final" or
         "user_edited" (display_text > corrected_text > text > raw_text).
      2. Any note.transcript entry with display_text/corrected/text/raw_text
         (only when no authoritative entry exists).
      3. note.content "## 语音转文字" area.
      4. Full note.content.

    Only the latest authoritative entry is used so that a user_edited deletion
    cannot be resurrected by joining it with older final/local entries.
    """
    # 1. Latest authoritative transcript entry (single source of truth).
    transcript = getattr(note, "transcript", None)
    latest = _latest_authoritative_transcript_entry(transcript)
    if latest is not None:
        # Empty string is intentional when the user cleared the transcript, so
        # we check key membership and only fall back to raw_text when no
        # authoritative text field was provided.
        for key in ("display_text", "corrected_text", "text"):
            if key in latest:
                return str(latest[key] or "").strip()
        return str(latest.get("raw_text") or "").strip()

    # 2. Any non-superseded transcript entry (fallback when no authoritative entry exists).
    if transcript and isinstance(transcript, list):
        texts = []
        for seg in sorted(transcript, key=lambda x: x.get("chunk_index", 0) if isinstance(x, dict) else 0):
            if not isinstance(seg, dict):
                continue
            if seg.get("correction_stage") == "superseded":
                continue
            text = _transcript_chunk_text(seg)
            if text:
                texts.append(text)
        if texts:
            return "\n\n".join(texts)

    # 3. Content transcript area.
    content = getattr(note, "content", None)
    from_content = _extract_transcript_from_content(content)
    if from_content:
        return _strip_html(from_content)

    # 4. Full content.
    if content and str(content).strip():
        return _strip_html(content)

    return ""


def get_canonical_note_text(note: "Note", include_ppt: bool = True) -> str:
    """Return canonical note text, optionally appending PPT text as supplemental.

    PPT text is appended; it never overrides transcript/note content.
    """
    main_text = get_canonical_transcript_text(note)
    notes_text = _extract_notes_from_content(getattr(note, "content", None))
    if notes_text:
        if main_text:
            main_text = f"{main_text}\n\n[笔记] {notes_text}"
        else:
            main_text = f"[笔记] {notes_text}"

    if not include_ppt:
        return main_text

    ppt_parts = _extract_ppt_text_parts(note)
    if ppt_parts:
        if main_text:
            return f"{main_text}\n\n" + "\n\n".join(ppt_parts)
        return "\n\n".join(ppt_parts)
    return main_text
