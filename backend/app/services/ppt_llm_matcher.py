"""LLM-based slide placement matcher.

Given a full transcript and a list of PPT slides, ask a large model to decide
which sentence each slide should be inserted after. The result is a list of
placement anchors that the caller can turn into content blocks.

This module is designed to fail safely: any parsing or API error returns
``None`` so the caller can fall back to the existing SlideAligner.
"""

import json
import logging
import re
from typing import Optional

from app.config import DEEPSEEK_MODEL
from app.core.llm import ChatMessage, get_default_chat_provider
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_PROMPT = load_prompt("agents/ppt_placement")

# Rough input budget. deepseek-v4-flash has a large context window; this cap
# keeps us well within the token limit for a typical lecture while still
# sending enough text for a global decision.
_MAX_INPUT_CHARS = 48000
_MAX_TOKENS = 4000
_TEMPERATURE = 0.2
_TIMEOUT_SECONDS = 60.0


def _split_sentences(transcript: str) -> list[str]:
    """Split transcript into sentences the same way the PPT endpoint does."""
    raw = re.split(r"(?<=[。！？\n])", transcript)
    return [s.strip() for s in raw if s.strip()]


def _escape_template_value(value: str) -> str:
    """Escape '$' so string.Template does not treat user text as substitutions."""
    return value.replace("$", "$$")


def _strip_code_fences(raw: str) -> str:
    """Remove markdown JSON fences if the model emits them."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    return raw


def compute_placements(transcript: str, slides: list[dict]) -> Optional[list[dict]]:
    """Return a list of {page, after_sentence_index, reason} placements.

    Returns ``None`` if the input is empty or the LLM call fails, so the caller
    can fall back to keyword-based alignment.
    """
    provider = get_default_chat_provider()
    if not provider.available:
        logger.debug("ppt_llm_matcher skipped: no chat provider available")
        return None

    transcript = transcript.strip()
    if not transcript or not slides:
        return None

    sentences = _split_sentences(transcript)
    if not sentences:
        return None

    # Build a compact representation of slides for the prompt.
    slide_items = []
    for slide in slides:
        page = slide.get("page")
        if not isinstance(page, int):
            continue
        title = (slide.get("title") or "")[:200]
        text = (slide.get("text") or "")[:800]
        slide_items.append({"page": page, "title": title, "text": text})

    if not slide_items:
        return None

    numbered_sentences = "\n".join(
        f"{i}: {sent}" for i, sent in enumerate(sentences)
    )
    slides_json = json.dumps(slide_items, ensure_ascii=False, indent=2)

    # Cap individual inputs to avoid blowing the context window.
    numbered_sentences = numbered_sentences[:_MAX_INPUT_CHARS]
    slides_json = slides_json[:_MAX_INPUT_CHARS]

    user_content = _PROMPT.render(
        transcript_text=_escape_template_value(numbered_sentences),
        slides_json=_escape_template_value(slides_json),
    )

    # DeepSeek V4 defaults to thinking mode; structured placement generation
    # does not benefit from reasoning chains and is faster without them.
    kwargs = {"timeout": _TIMEOUT_SECONDS, "response_format": {"type": "json_object"}}
    if DEEPSEEK_MODEL and "deepseek-v4" in DEEPSEEK_MODEL:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        response = provider.chat(
            model=DEEPSEEK_MODEL,
            messages=[
                ChatMessage(role="system", content=_PROMPT.system),
                ChatMessage(role="user", content=user_content),
            ],
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            **kwargs,
        )
    except Exception as exc:
        logger.warning("ppt_llm_matcher api_failed error=%s", exc)
        return None

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        return None

    try:
        data = json.loads(_strip_code_fences(raw))
    except Exception as exc:
        logger.warning(
            "ppt_llm_matcher json_parse_failed error=%s raw=%s",
            exc,
            raw[:200],
        )
        return None

    placements = data.get("placements") if isinstance(data, dict) else None
    if not isinstance(placements, list):
        logger.warning("ppt_llm_matcher missing placements list")
        return None

    valid_pages = {s.get("page") for s in slide_items}
    accepted: list[dict] = []
    last_page = -1
    last_idx = -1

    for item in placements:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        idx = item.get("after_sentence_index")
        if not isinstance(page, int) or not isinstance(idx, int):
            continue
        if page not in valid_pages:
            continue
        if page <= last_page:
            continue
        # Clamp to the valid sentence range. -1 means "before the first sentence".
        idx = max(-1, min(idx, len(sentences) - 1))
        if idx < last_idx:
            continue
        accepted.append(
            {
                "page": page,
                "after_sentence_index": idx,
                "reason": (item.get("reason") or "")[:200],
            }
        )
        last_page = page
        last_idx = idx

    if not accepted:
        logger.warning("ppt_llm_matcher no_valid_placements")
        return None

    logger.info(
        "ppt_llm_matcher success placements=%s slides=%s sentences=%s",
        len(accepted),
        len(slide_items),
        len(sentences),
    )
    return accepted
