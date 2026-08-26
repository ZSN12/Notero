"""OCR service: extract text from slide images so picture content is searchable.

Why OCR:
- A classroom slide is often mostly images (screenshots, diagrams, formula
  images, scanned material). Those pixels carry knowledge the text pipeline
  cannot see, so questions, search and AI-generated study materials silently
  miss them.
- OCR turns "words inside pictures" into plain text, so the vector index and
  RAG layer treat image content just like spoken words or typed notes.

Implementation:
- Primary engine: Qwen-VL (DashScope OpenAI-compatible API) — the project
  already ships the ``openai`` client, the DashScope key plumbing and the
  image-compression helper, so OCR reuses that stack instead of adding a heavy
  local deep-learning runtime.
- Degradation: no API key or any error → returns "" and is silently skipped.
  The product degrades to "image has no text" instead of failing the pipeline.
- Cache: recognition is memoized by image hash so re-processing the same
  picture does not burn a second API call.
- Terms: a caller can pass course keywords; they are injected as protected
  words so professional terms (e.g. "勾股定理") are not mis-OCR'd.

This module is intentionally small and side-effect free. It never touches the
database and never raises into the caller; every entry point returns a plain
string (or list of lines).
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import threading
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# DashScope OpenAI-compatible endpoint reused across the codebase.
_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Simple in-process memo: image_file_path / sha256 -> extracted text.
_cache_lock = threading.Lock()
_cache: dict[str, str] = {}


def _load_key() -> str:
    """Return a usable API key or empty string (caller decides to skip)."""
    from app.config import QWEN_VL_API_KEY, DASHSCOPE_API_KEY

    return QWEN_VL_API_KEY or DASHSCOPE_API_KEY


def _ocr_enabled() -> bool:
    from app.config import OCR_ENABLED

    return bool(OCR_ENABLED)


def _image_sha256(path: str) -> Optional[str]:
    """Hash the image bytes so identical images reuse one recognition."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def _compress_to_base64(image_path: str) -> Optional[str]:
    """Resize (if needed) and re-encode the image to a small JPEG base64.

    Returns None on any error so callers can safely skip.
    """
    from app.config import OCR_JPEG_QUALITY, OCR_MAX_WIDTH

    try:
        with Image.open(image_path) as img:
            if img.width > OCR_MAX_WIDTH:
                ratio = OCR_MAX_WIDTH / img.width
                new_height = int(img.height * ratio)
                img = img.resize((OCR_MAX_WIDTH, new_height), Image.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=OCR_JPEG_QUALITY)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("ocr_compress_failed path=%s error=%s", image_path, e)
        return None


def _build_prompt(course_terms: Optional[list[str]]) -> str:
    """Build the OCR instruction. Terms are injected as protected words."""
    prompt = (
        "你是高精度 OCR 识别引擎。请把这张图片里的所有文字原样转录出来，"
        "包括标题、正文、公式文字、图表标注、手写批注。"
        "按从上到下、从左到右的顺序输出，保留换行分隔不同文本块。"
        "不要添加图片里不存在的文字，不要改写，不要翻译。"
    )
    if course_terms:
        terms = "、".join(course_terms)
        prompt += (
            f"\n特别注意：以下课程术语必须准确识别，不要识别成同音或近似错别字：{terms}。"
        )
    return prompt


def extract_text_from_image(
    image_path: str,
    course_terms: Optional[list[str]] = None,
    force: bool = False,
) -> str:
    """OCR a single image and return the recognised text ("" on failure).

    Cache is consulted unless ``force`` is True. Empty image content is also
    cached so repeated runs on the same picture short-circuit cheaply.
    """
    if not image_path or not os.path.exists(image_path):
        return ""

    if not _ocr_enabled():
        logger.info("ocr_skipped_disabled path=%s", image_path)
        return ""

    key = _load_key()
    if not key:
        logger.info("ocr_skipped_no_api_key path=%s", image_path)
        return ""

    cache_key = _image_sha256(image_path)
    if cache_key and not force:
        with _cache_lock:
            if cache_key in _cache:
                return _cache[cache_key]

    image_b64 = _compress_to_base64(image_path)
    if not image_b64:
        return ""

    try:
        from openai import OpenAI

        from app.config import OCR_MODEL

        client = OpenAI(api_key=key, base_url=_DASHSCOPE_BASE_URL)
        response = client.chat.completions.create(
            model=OCR_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_prompt(course_terms)},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=1200,
            timeout=30,
        )
        text = (response.choices[0].message.content or "").strip()
        text = text.strip('"').strip("'").strip()
    except Exception as e:
        logger.warning("ocr_extract_failed path=%s error=%s", image_path, e)
        return ""

    if cache_key:
        with _cache_lock:
            _cache[cache_key] = text

    if text:
        logger.info("ocr_extracted path=%s chars=%d", image_path, len(text))
    return text


def enrich_slides_with_ocr(
    slides: list[dict],
    output_dir: str,
    course_terms: Optional[list[str]] = None,
    skip_if_text_len: Optional[int] = None,
) -> int:
    """Enrich text-poor slides with OCR'd text. Returns how many were updated.

    This complements the existing VL "image description" pass: VL describes
    what a diagram means, OCR transcribes the literal words inside images, so
    the aligned text keeps both the meaning and the exact terminology.
    """
    from app.config import OCR_SKIP_IF_TEXT_LEN

    if skip_if_text_len is None:
        skip_if_text_len = OCR_SKIP_IF_TEXT_LEN

    updated = 0
    for slide in slides:
        text = slide.get("text", "") or ""
        image_path = slide.get("image_path", "")
        if not image_path:
            continue
        # Text-rich slides do not need OCR.
        if len(text) >= skip_if_text_len:
            continue

        img_full = os.path.join(output_dir, image_path)
        if not os.path.exists(img_full):
            continue

        ocr_text = extract_text_from_image(img_full, course_terms=course_terms)
        if not ocr_text:
            continue

        # Merge OCR text into the slide's text, marked so alignment/RAG know
        # where it came from. Deduplicate exact overlap with existing text.
        merged = _merge_text(text, ocr_text)
        if merged == text:
            continue
        slide["text"] = merged
        updated += 1
        logger.info(
            "ocr_enrich page=%s title=%s chars=%d",
            slide.get("page"),
            (slide.get("title") or "")[:20],
            len(ocr_text),
        )
    return updated


def _merge_text(existing: str, ocr: str) -> str:
    """Combine existing slide text and OCR text without exact duplicates."""
    existing_norm = _norm(existing)
    ocr_norm = _norm(ocr)
    if not ocr_norm:
        return existing
    # Empty existing text → OCR alone is the richer content.
    if not existing_norm:
        return f"[图片文字]{ocr}".strip()
    if ocr_norm in existing_norm or existing_norm in ocr_norm:
        return existing
    return f"{existing}\n[图片文字]{ocr}".strip()


def _norm(s: str) -> str:
    return "".join(s.split())
