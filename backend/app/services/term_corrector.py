import json
import re
import time
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable, Any
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.services.prompt_loader import load_prompt

# openai is imported lazily inside methods; import the module for error types.
try:
    import openai
except Exception:  # pragma: no cover
    openai = None  # type: ignore

logger = logging.getLogger(__name__)


_REPEATED_COMMA = re.compile(r'(，\s*){2,}')
_MULTI_SPACE = re.compile(r'\s{2,}')


CORRECTION_ERROR_CODES = {
    "timeout": "AI 整理超时",
    "rate_limit": "AI 服务限流，请稍后重试",
    "authentication": "AI 服务认证失败，请检查 API Key",
    "network": "网络连接失败",
    "empty_response": "AI 返回内容为空",
    "truncated_response": "AI 返回内容不完整",
    "invalid_response": "AI 返回格式异常",
    "content_validation_failed": "AI 整理结果丢失关键内容，已回退本地稿",
    "server_error": "AI 服务内部错误，请稍后重试",
    "content_filter": "AI 服务拒绝处理该内容，请检查文本是否合规",
    "unknown": "AI 整理发生内部异常，请查看后端日志或重新尝试",
}


def _classify_by_status_code(status_code) -> Optional[tuple[str, str, bool]]:
    """Classify an OpenAI-compatible HTTP status code.

    Returns None if the status code is not an integer or not recognized.
    """
    if not isinstance(status_code, int):
        return None
    if status_code == 400:
        return "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], False
    if status_code in (401, 403):
        return "authentication", CORRECTION_ERROR_CODES["authentication"], False
    if status_code == 429:
        return "rate_limit", CORRECTION_ERROR_CODES["rate_limit"], True
    if 500 <= status_code < 600:
        return "server_error", CORRECTION_ERROR_CODES["server_error"], True
    return None


def classify_correction_exception(exc: Exception) -> tuple[str, str, bool]:
    """Map an arbitrary LLM/worker exception to a stable error code and user message.

    Order of precedence:
    1. CorrectionError wrapper.
    2. HTTP status_code on OpenAI-compatible exceptions.
    3. Specific exception classes (Authentication, RateLimit, BadRequest, ContentPolicy).
    4. Generic APIStatusError / APIError as server-side errors.
    5. Message heuristics.
    """
    if isinstance(exc, CorrectionError):
        return exc.code, exc.message, exc.retryable
    msg = str(exc).lower()
    openai_module = openai
    if openai_module:
        # Safely resolve error classes that may not exist in older openai versions.
        _get_exc = lambda name: getattr(openai_module, name, None)
        AuthenticationError = _get_exc("AuthenticationError")
        RateLimitError = _get_exc("RateLimitError")
        APITimeoutError = _get_exc("APITimeoutError")
        APIConnectionError = _get_exc("APIConnectionError")
        BadRequestError = _get_exc("BadRequestError")
        InternalServerError = _get_exc("InternalServerError")
        APIError = _get_exc("APIError")
        APIStatusError = _get_exc("APIStatusError")
        ContentPolicyViolationError = _get_exc("ContentPolicyViolationError")

        # Prefer HTTP status_code when available; fall back to isinstance checks.
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            classified = _classify_by_status_code(status_code)
            if classified:
                return classified

        # Specific exception classes.  BadRequestError is a subclass of
        # APIStatusError, so it must be checked before the generic parent.
        if AuthenticationError and isinstance(exc, AuthenticationError):
            return "authentication", CORRECTION_ERROR_CODES["authentication"], False
        if RateLimitError and isinstance(exc, RateLimitError):
            return "rate_limit", CORRECTION_ERROR_CODES["rate_limit"], True
        if BadRequestError and isinstance(exc, BadRequestError):
            return "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], False
        if ContentPolicyViolationError and isinstance(exc, ContentPolicyViolationError):
            return "content_filter", CORRECTION_ERROR_CODES["content_filter"], False
        if APITimeoutError and isinstance(exc, APITimeoutError):
            return "timeout", CORRECTION_ERROR_CODES["timeout"], True
        if APIConnectionError and isinstance(exc, APIConnectionError):
            return "network", CORRECTION_ERROR_CODES["network"], True
        # DeepSeek / OpenAI-compatible server-side errors (5xx, overloaded, etc.)
        if (
            (InternalServerError and isinstance(exc, InternalServerError))
            or (APIError and isinstance(exc, APIError))
            or (APIStatusError and isinstance(exc, APIStatusError))
        ):
            return "server_error", CORRECTION_ERROR_CODES["server_error"], True
    if isinstance(exc, TimeoutError) or "timeout" in msg:
        return "timeout", CORRECTION_ERROR_CODES["timeout"], True
    if "connection" in msg or "network" in msg:
        return "network", CORRECTION_ERROR_CODES["network"], True
    if "rate limit" in msg or "too many requests" in msg:
        return "rate_limit", CORRECTION_ERROR_CODES["rate_limit"], True
    if "authentication" in msg or "api key" in msg:
        return "authentication", CORRECTION_ERROR_CODES["authentication"], False
    if "bad request" in msg or "model" in msg or "not found" in msg or "does not exist" in msg:
        return "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], False
    if "content_policy" in msg or "content filter" in msg or "safety" in msg or "moderation" in msg or "inappropriate" in msg:
        return "content_filter", CORRECTION_ERROR_CODES["content_filter"], False
    if "server" in msg or "internal" in msg or "overloaded" in msg or "temporarily unavailable" in msg:
        return "server_error", CORRECTION_ERROR_CODES["server_error"], True
    if "empty" in msg:
        return "empty_response", CORRECTION_ERROR_CODES["empty_response"], True
    if "truncated" in msg:
        return "truncated_response", CORRECTION_ERROR_CODES["truncated_response"], True
    # Preserve the original exception message for truly unexpected errors.
    return "unknown", msg or CORRECTION_ERROR_CODES["unknown"], False


class CorrectionError(Exception):
    """Structured error from a single correction chunk or whole correction."""

    def __init__(self, code: str, message: str, retryable: bool = False, finish_reason: Optional[str] = None):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.finish_reason = finish_reason
        super().__init__(message)


@dataclass
class RestructureChunkResult:
    index: int
    input: str
    output: str
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    elapsed: float = 0.0
    finish_reason: Optional[str] = None
    input_length: int = 0
    review_performed: bool = False
    review_repaired: bool = False
    missing_facts: List[str] = field(default_factory=list)
    review_error_code: Optional[str] = None
    review_error_message: Optional[str] = None


@dataclass
class RestructureResult:
    text: str
    local_text: str
    is_ai_corrected: bool
    error_code: Optional[str] = None
    error: Optional[str] = None
    retryable: bool = False
    chunks_total: int = 0
    chunks_succeeded: int = 0
    chunks_failed: int = 0
    chunk_results: List[RestructureChunkResult] = field(default_factory=list)


class TermCorrector:
    """Clean ASR output without losing source facts."""

    def __init__(self):
        self._client = None
        logger.info("termcorrector_init api_key_present=%s base_url=%s", bool(DEEPSEEK_API_KEY), DEEPSEEK_BASE_URL)
        if DEEPSEEK_API_KEY:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
                logger.info("termcorrector_init openai_client_created")
            except Exception as exc:
                logger.warning("termcorrector_init openai_client_failed error=%s", exc)
        else:
            logger.warning("termcorrector_init no_api_key")

    @property
    def has_llm(self) -> bool:
        return self._client is not None

    # ──────────────────────────────────────────────────────────────────
    # Public API — deterministic cleanup (always runs, no LLM needed)
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def clean_transcript_for_display(cls, raw_text: str) -> str:
        """Full deterministic pipeline: filler removal → dedup → paragraph split.

        Returns a display-ready version of the text.  The original raw_text
        must be stored separately for audit / timestamps.
        """
        if not raw_text or not raw_text.strip():
            return raw_text or ""

        sentences = cls._split_sentences(raw_text)
        sentences = cls._clean_oral_fillers(sentences)
        sentences = cls._dedupe_semantic_sentences(sentences)

        joined = "".join(sentences)
        joined = cls._collapse_repeated_sentence_loops(joined)
        return cls._dedupe_paragraphs(cls.ensure_paragraph_breaks(joined))

    @classmethod
    def prepare_stream_chunk(cls, raw_text: str, history_text: str = "") -> str:
        """Clean one streaming ASR chunk and remove overlap with displayed history."""
        cleaned = cls.clean_transcript_for_display(raw_text).strip()
        if not cleaned:
            return ""
        cleaned = cls.strip_history_overlap(cleaned, history_text).strip()
        if not cleaned:
            return ""
        return cls.clean_transcript_for_display(cleaned).strip()

    @classmethod
    def strip_history_overlap(cls, candidate: str, history_text: str) -> str:
        """Remove text already shown in previous stream chunks.

        Handles cumulative ASR output such as: chunk2 = chunk1 + new words.
        """
        candidate = (candidate or "").strip()
        history_text = (history_text or "").strip()
        if not candidate or not history_text:
            return candidate

        cand_key, cand_positions = cls._norm_key_with_positions(candidate)
        history_key = cls._norm_key(history_text)
        if not cand_key or not history_key:
            return candidate

        if len(cand_key) >= 8 and cand_key in history_key:
            return ""

        overlap = cls._longest_history_prefix_overlap(history_key, cand_key)
        if overlap >= 8 and overlap / max(len(cand_key), 1) >= 0.18:
            cut_pos = cand_positions[min(overlap, len(cand_positions)) - 1] + 1
            candidate = cls._trim_overlap_boundary(candidate[cut_pos:])
            cand_key, cand_positions = cls._norm_key_with_positions(candidate)
            if not cand_key:
                return ""

        # If the chunk starts with a non-tail paragraph that already appeared,
        # remove that prefix too. This catches "previous paragraph + more" loops.
        max_prefix = min(len(cand_key), 260)
        for length in range(max_prefix, 7, -1):
            prefix = cand_key[:length]
            if prefix in history_key and (length >= 18 or length / max(len(cand_key), 1) >= 0.35):
                cut_pos = cand_positions[length - 1] + 1
                candidate = cls._trim_overlap_boundary(candidate[cut_pos:])
                break

        return candidate.strip()

    # ──────────────────────────────────────────────────────────────────
    # LLM-powered (best-effort, failures are caught by deterministic fallback)
    # ──────────────────────────────────────────────────────────────────

    def restructure_transcript(
        self,
        text: str,
        course_title: str,
        keywords: Optional[List[str]] = None,
        ppt_slides: Optional[list] = None,
    ) -> str:
        """LLM correction + reorder. Falls back to deterministic cleanup on error."""
        if not self._client or not text or not text.strip():
            return text

        keyword_str = "、".join(keywords) if keywords else "无"
        course_terms = self.build_course_terms(course_title, keywords, ppt_slides)
        course_terms_str = "、".join(course_terms) if course_terms else "无"
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
            text=text,
            timestamped_text="（无）",
            ppt_context=ppt_context,
        )

        result = self._call_llm(prompt, prompt_template.system, temperature=0.2)
        if not result or not result.strip():
            logger.info("restructure_transcript_llm_empty_return course=%s text_len=%s", course_title, len(text))
            return text
        logger.info(
            "restructure_transcript_done course=%s input_len=%s output_len=%s changed=%s",
            course_title, len(text), len(result), result.strip() != text.strip(),
        )
        return result

    def correct_segments(
        self, text: str, course_title: str, keywords: Optional[List[str]] = None,
    ) -> str:
        """Legacy helper — calls restructure_transcript without PPT context."""
        return self.restructure_transcript(text, course_title, keywords)

    # ──────────────────────────────────────────────────────────────────
    # 1. Sentence splitting
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        raw_parts = re.split(r'(?<=[。！？.!?\n])', text)
        result: List[str] = []
        for p in raw_parts:
            p = p.strip()
            if p:
                result.append(p)
        return result or [text]

    # ──────────────────────────────────────────────────────────────────
    # 2. Oral filler removal
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def _clean_oral_fillers(cls, sentences: List[str]) -> List[str]:
        """Remove oral fillers, keeping knowledge content intact.

        Rules (applied in order):
        1. Sentence-start fillers (optionally followed by ，/,) — delete.
        2. Sentence-end fillers (preceded by ，/,) — delete.
        3. Mid-sentence fillers that are surrounded by punctuation — delete.
        4. Monosyllabic fillers between punctuation — delete.
        5. Isolated punctuation / empty bracket clean-up.
        """

        punctuation = r'\s，。！？,!?；;：:、\n'

        # High-confidence oral fragments. Keep this list conservative: these
        # forms are rarely knowledge-bearing in classroom transcripts.
        _INLINE_FILLERS = [
            "就是这样的啊",
            "就是这样的",
            "就这样的啊",
            "是这样的啊",
            "是这样啊",
            "这样的啊",
            "OK啊",
            "ok啊",
            "好吧",
            "对吧",
            "是吧",
            "对不对",
            "是不是",
            "这个这个",
            "那个那个",
            "那么那么",
            "然后然后",
            "就是就是",
            "复制关系了，那么怎么办",
        ]

        _BOUNDED_PHRASE = re.compile(
            r'(^|[' + punctuation + r'])'
            r'(没有什么区别|什么问题呢)'
            r'(?=[' + punctuation + r']|$)',
            re.IGNORECASE,
        )

        # Single-token – only when followed by ，
        _START_FILLERS = re.compile(
            r'^(OK|ok|Ok|好|就是|然后|那么|这个|那个|哎|诶|呃|嗯|啊|'
            r'所以呢|就说|说起来|对了|记得)[，,]\s*',
            re.IGNORECASE,
        )

        # Single-token – only when preceded by ，
        _END_FILLERS = re.compile(
            r'[，,]\s*(OK|ok|Ok|对吧|是吧|对不对|是这样|这样的啊|就这样啊|是不是)\s*$',
            re.IGNORECASE,
        )

        # Monosyllabic fillers. Python `re` cannot use variable-length
        # lookbehind, so capture and preserve the left boundary instead.
        _MONO_FILLERS_RE = re.compile(
            r'(^|[' + punctuation + r'])[啊呃嗯哦噢诶](?=[' + punctuation + r']|$)',
            re.IGNORECASE,
        )
        _TAIL_TONE_RE = re.compile(r'(?<=[一-鿿])[啊呢吧](?=[，。！？,!?；;：:、\s]|$)')

        _ORPHAN_PUNCT = re.compile(r'[，,]\s*[？？]\s*')
        _ISOLATED_QM = re.compile(r'(^|[\s，,。！;；：:、])？(?=[\s，,。！;；：:、]|$)')
        _ISOLATED_FS = re.compile(r'(^|[\s，,。！？;；：:、])。(?=[\s，,。！？;；：:、]|$)')
        _MULTI_SPACE = re.compile(r'\s{2,}')
        _EMPTY_PARENS = re.compile(r'\(\s*\)')

        cleaned: List[str] = []
        for s in sentences:
            # Phase 1 — sentence-start fillers
            s = _START_FILLERS.sub('', s)

            # Phase 2 — sentence-end fillers
            s = _END_FILLERS.sub('', s)

            # Phase 3 — high-confidence oral fragments.
            for filler in _INLINE_FILLERS:
                s = re.sub(re.escape(filler), '', s, flags=re.IGNORECASE)
            s = _BOUNDED_PHRASE.sub(lambda m: m.group(1), s)

            # Phase 4 — monosyllabic fillers
            s = _MONO_FILLERS_RE.sub(lambda m: m.group(1), s)
            s = _TAIL_TONE_RE.sub('', s)

            # Clean up artifacts
            s = _ORPHAN_PUNCT.sub('', s)
            s = _ISOLATED_QM.sub(lambda m: m.group(1), s)
            s = _ISOLATED_FS.sub(lambda m: m.group(1), s)
            s = _EMPTY_PARENS.sub('', s)
            s = _MULTI_SPACE.sub(' ', s)

            # Compress consecutive punctuation
            s = re.sub(r'[，,]{2,}', '，', s)
            s = re.sub(r'[。]{2,}', '。', s)
            s = re.sub(r'[？?]{2,}', '？', s)
            s = re.sub(r'^[，,。！？?；;：:、\s]+', '', s)
            s = re.sub(r'[，,；;：:、\s]+$', '', s)
            s = re.sub(r'[，,]\s*([。！？?])', r'\1', s)
            s = cls._collapse_repeated_clauses(s)

            s = s.strip()
            compact = re.sub(r'[^\w一-鿿]+', '', s)
            if s and len(compact) >= 3:
                cleaned.append(s)

        return cleaned

    # ──────────────────────────────────────────────────────────────────
    # 3. Semantic sentence dedup
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def _dedupe_semantic_sentences(cls, sentences: List[str]) -> List[str]:
        """Remove adjacent/near-adjacent duplicate sentences.

        Uses a normalised key + tf-like overlap, intentionally conservative:
        only removes sentences that carry NO new knowledge vs a previous one.
        """
        if len(sentences) <= 1:
            return sentences

        result: List[str] = []
        for idx, s in enumerate(sentences):
            if not s or len(s) < 5:
                continue

            dup = False
            lookback = min(idx, 6)
            for prev in result[-lookback:]:
                if cls._sentences_equivalent(prev, s):
                    dup = True
                    break

            if not dup:
                result.append(s)

        return result

    @classmethod
    def _collapse_repeated_clauses(cls, sentence: str) -> str:
        """Collapse adjacent comma-separated ASR phrase loops inside a sentence."""
        if not sentence or not re.search(r'[，,、；;]', sentence):
            return sentence

        clauses = [part.strip() for part in re.split(r'[，,、；;]', sentence) if part.strip()]
        if len(clauses) <= 1:
            return sentence

        result: list[str] = []
        for clause in clauses:
            if not result:
                result.append(clause)
                continue
            prev = result[-1]
            prev_key = cls._norm_key(prev)
            clause_key = cls._norm_key(clause)
            if (
                cls._sentences_equivalent(prev, clause)
                or (len(prev_key) >= 5 and clause_key.startswith(prev_key))
                or (len(clause_key) >= 5 and prev_key.startswith(clause_key))
            ):
                if len(clause_key) > len(prev_key):
                    result[-1] = clause
                continue
            result.append(clause)

        return "，".join(result)

    @classmethod
    def _collapse_repeated_sentence_loops(cls, text: str) -> str:
        """Remove short ASR/LLM loops that repeat the same sentence many times."""
        sentences = cls._split_sentences(text)
        if len(sentences) <= 1:
            return text

        result: list[str] = []
        seen_counts: dict[str, int] = {}
        for sentence in sentences:
            key = cls._norm_key(sentence)
            if not key:
                continue

            # Exact repeated short classroom prompts like "什么问题" are often
            # ASR loops. Keep one occurrence, never a wall of identical prompts.
            if len(key) >= 3 and seen_counts.get(key, 0) >= 1:
                continue

            if any(cls._sentences_equivalent(prev, sentence) for prev in result[-24:]):
                continue

            seen_counts[key] = seen_counts.get(key, 0) + 1
            result.append(sentence)

        return "".join(result)

    @classmethod
    def _dedupe_paragraphs(cls, text: str) -> str:
        """Remove duplicate paragraph cards after sentence cleanup."""
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text or '') if p.strip()]
        if len(paragraphs) <= 1:
            return text

        result: list[str] = []
        seen: set[str] = set()
        for paragraph in paragraphs:
            key = cls._norm_key(paragraph)
            if len(key) >= 20 and key in seen:
                continue
            replaced = False
            skip = False
            for idx, prev in list(enumerate(result))[-8:]:
                prev_key = cls._norm_key(prev)
                if not key or not prev_key:
                    continue
                shorter, longer = (key, prev_key) if len(key) <= len(prev_key) else (prev_key, key)
                if cls.is_repeated_text(paragraph, prev):
                    skip = True
                    break
                if len(shorter) >= 18 and shorter in longer and len(shorter) / max(len(longer), 1) >= 0.55:
                    if len(key) > len(prev_key):
                        result[idx] = paragraph
                        replaced = True
                    skip = True
                    break
            if skip:
                if replaced and len(key) >= 20:
                    seen.add(key)
                continue
            if len(key) >= 20:
                seen.add(key)
            result.append(paragraph)

        return "\n\n".join(result)

    @classmethod
    def _sentences_equivalent(cls, a: str, b: str) -> bool:
        """Return True if b carries no new information beyond a."""
        na = cls._norm_key(a)
        nb = cls._norm_key(b)

        # Exact key match
        if na == nb:
            return True

        if len(na) < 6 or len(nb) < 6:
            return False  # too short to judge unless exact

        shorter, longer = (nb, na) if len(nb) <= len(na) else (na, nb)
        min_len = len(shorter)
        ratio = min_len / max(len(longer), 1)

        # One sentence is contained in the other. Short ASR loops often differ
        # only by "那么/那/啊", so the ratio must be lower than paragraph dedup.
        if shorter in longer:
            if min_len >= 8 and (ratio >= 0.55 or len(longer) - min_len <= 8):
                return True

        similarity = SequenceMatcher(None, na, nb).ratio()
        if min_len <= 20:
            if similarity >= 0.86:
                return True
            if na[:3] == nb[:3] and similarity >= 0.80:
                return True
            if na[-3:] == nb[-3:] and similarity >= 0.80:
                return True
        elif similarity >= 0.84:
            return True

        # Same first 4 chars + same last 4 chars → likely the same sentence spoken twice
        if len(na) >= 8 and len(nb) >= 8:
            if na[:4] == nb[:4] and na[-4:] == nb[-4:]:
                if ratio >= 0.65:
                    return True

        return False

    @staticmethod
    def _norm_key(text: str) -> str:
        """Normalise to a compact key for duplicate detection."""
        clean = re.sub(
            r'(OK|ok|Ok|好的|好吧|对吧|是不是|是吧|对不对|'
            r'是这样啊|是这样|就是这样啊|就是这样的啊|这样的啊|'
            r'那么|然后|这个|那个|啊|呃|嗯|哦|噢|诶|哎)',
            '',
            text,
            flags=re.IGNORECASE,
        )
        return re.sub(r'[^\w一-鿿]+', '', clean).lower()

    @classmethod
    def _norm_key_with_positions(cls, text: str) -> tuple[str, list[int]]:
        key_chars: list[str] = []
        positions: list[int] = []
        for idx, char in enumerate(text or ""):
            if re.match(r'[\w一-鿿]', char, flags=re.IGNORECASE):
                key_chars.append(char.lower())
                positions.append(idx)
        key = cls._norm_key("".join(key_chars))
        if len(key) == len(key_chars):
            return key, positions

        # Filler removal changed the key length; rebuild positions by scanning
        # kept chars in order. This is approximate but good enough for cutting.
        rebuilt_positions: list[int] = []
        search_from = 0
        compact_chars = "".join(key_chars)
        for char in key:
            found = compact_chars.find(char, search_from)
            if found == -1 or found >= len(positions):
                break
            rebuilt_positions.append(positions[found])
            search_from = found + 1
        if len(rebuilt_positions) != len(key):
            return "".join(key_chars), positions
        return key, rebuilt_positions

    @staticmethod
    def _trim_overlap_boundary(text: str) -> str:
        return re.sub(r'^[\s，,。！？!?；;：:、\-—_]+', '', text or "").strip()

    @staticmethod
    def _longest_history_prefix_overlap(history_key: str, cand_key: str) -> int:
        max_len = min(len(history_key), len(cand_key), 320)
        for length in range(max_len, 7, -1):
            if history_key[-length:] == cand_key[:length]:
                return length
        return 0

    # ── chunk-level helpers (kept for backward compat) ──

    @staticmethod
    def _dedupe_key(text: str) -> str:
        return re.sub(r"[\s，。！？,.!?；;：:、\"'“”‘’（）()《》<>【】\[\]\-—_]+", "", (text or "").lower())

    @classmethod
    def is_repeated_text(cls, candidate: str, previous: str) -> bool:
        cand = cls._dedupe_key(candidate)
        prev = cls._dedupe_key(previous)
        if cand == prev:
            return True
        if len(cand) < 6 or len(prev) < 6:
            return False
        shorter, longer = (cand, prev) if len(cand) <= len(prev) else (prev, cand)
        if len(shorter) >= 8 and shorter in longer:
            return len(shorter) / max(len(longer), 1) >= 0.55 or len(longer) - len(shorter) <= 10
        return cls._sentences_equivalent(candidate, previous)

    @classmethod
    def dedupe_repeated_texts(cls, texts: list[str]) -> list[str]:
        result: list[str] = []
        for text in texts:
            cleaned = (text or "").strip()
            if not cleaned:
                continue
            cleaned = cls.strip_history_overlap(cleaned, "\n\n".join(result)).strip()
            if not cleaned:
                continue
            if any(cls.is_repeated_text(cleaned, prev) for prev in result[-8:]):
                continue
            result.append(cleaned)
        return result

    @classmethod
    def dedupe_asr_segments(cls, segments: list) -> list:
        """Drop repeated ASR segments before they become stream windows."""
        result: list = []
        for seg in segments or []:
            text = (getattr(seg, "text", "") or "").strip()
            if not text:
                continue
            if any(cls._sentences_equivalent(getattr(prev, "text", ""), text) for prev in result[-5:]):
                continue
            result.append(seg)
        return result

    @classmethod
    def dedupe_stream_finals(cls, segments: list) -> list:
        """Deduplicate ASR segments that may overlap at stream boundaries.

        When streaming ASR processes overlapping windows or VAD re-triggers,
        the same sentence can appear in consecutive segments. This removes
        near-duplicate segments while preserving order and keeping the longer
        version when duplicates are found.
        """
        if len(segments) <= 1:
            return segments

        result: list = []
        for seg in segments:
            text = getattr(seg, "text", seg) if not isinstance(seg, str) else seg
            is_dup = False
            for prev in result[-3:]:
                prev_text = getattr(prev, "text", prev) if not isinstance(prev, str) else prev
                if cls._sentences_equivalent(prev_text, text):
                    # Keep the longer one
                    if len(text) > len(prev_text):
                        if hasattr(prev, "text"):
                            prev.text = text
                        if hasattr(seg, "end_ms") and hasattr(prev, "end_ms"):
                            prev.end_ms = seg.end_ms
                    is_dup = True
                    break
            if not is_dup:
                result.append(seg)
        return result

    @classmethod
    def dedupe_sentences(cls, text: str) -> str:
        """Legacy sentence dedup — now delegates to _dedupe_semantic_sentences."""
        sentences = cls._split_sentences(text)
        deduped = cls._dedupe_semantic_sentences(sentences)
        return "".join(deduped)

    # ──────────────────────────────────────────────────────────────────
    # 4. Paragraph grouping
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def ensure_paragraph_breaks(cls, text: str) -> str:
        """Insert blank lines between topic shifts."""
        if not text or not text.strip():
            return text or ""

        sentences = cls._split_sentences(text)
        if len(sentences) <= 3:
            return text

        _TOPIC_SHIFT_RE = re.compile(
            r'^(另外|此外|还有|接下来|下面|第二[个节章]|第三[个节章]|第四[个节章]|第五[个节章]|'
            r'那么|所以|但是|不过|然而|因此|总之|最后|'
            r'OK[，,]\s*那|OK[，,]\s*我们|'
            r'好[，,]\s*(我们|现在|那|下面|接下来)|'
            r'那[，,]\s*(我们|现在|我)'
            r')'
        )
        _CONNECTIVE_RE = re.compile(r'^(然后|而且|并且|或者|还是|因为|所以如果|但|可|也)')

        result_parts: list[str] = []
        current_para: list[str] = []
        current_char_count = 0
        MAX_PARA_CHARS = 400

        for s in sentences:
            s_chars = len(re.sub(r'\s', '', s))
            should_break = False

            if _TOPIC_SHIFT_RE.match(s):
                should_break = True
            elif current_char_count + s_chars > MAX_PARA_CHARS and current_char_count > 100:
                should_break = True

            if should_break and _CONNECTIVE_RE.match(s) and current_para:
                should_break = False

            if should_break and current_para:
                result_parts.append("".join(current_para))
                current_para = []
                current_char_count = 0

            current_para.append(s)
            current_char_count += s_chars

        if current_para:
            result_parts.append("".join(current_para))

        return "\n\n".join(result_parts)

    # ──────────────────────────────────────────────────────────────────
    # Content preservation — now uses deduped baseline, not raw
    # ──────────────────────────────────────────────────────────────────

    # ── high-value keywords ──

    _KEYWORD_STOPWORDS = frozenset({
        "然后", "这个", "那个", "我们", "你们", "大家", "是不是", "怎么办",
        "可以", "一样", "对吧", "那么", "就是", "所以", "但是", "不过",
        "因为", "如果", "嗯", "啊", "呃", "哦", "好吧", "对不对", "这样",
        "那样", "这些", "那些", "什么", "怎么", "为什么", "如何", "哪里",
        "谁", "好了", "是吧", "是的", "不是", "好的", "行吧", "来看一下",
        "首先", "其次", "最后", "总之", "简单来说", "换句话说", "也就是说",
        "实际上", "事实上", "基本上", "大致上", "一般来说", "通常情况下",
        "注意", "注意一下", "记住", "记住这个", "记住这点", "不要忘记",
        "重点", "重点来了", "关键点", "核心", "核心点", "核心要点",
        "来看一下", "看一下", "接下来", "那么那么", "然后然后",
    })

    @classmethod
    def extract_keywords(cls, text: str) -> set[str]:
        """Extract high-value keywords from text.

        Includes:
        - Chinese words 2-6 chars (likely nouns / terms)
        - English identifiers / terms / function names
        - Numbers with context (chapter, section, page)

        Excludes oral filler words.
        """
        text = text or ""
        keywords: set[str] = set()

        # Chinese 2-6 char sequences
        for m in re.finditer(r"[\u4e00-\u9fa5]{2,6}", text):
            w = m.group()
            if w not in cls._KEYWORD_STOPWORDS:
                keywords.add(w)

        # English identifiers / code terms (e.g. def_foo, ClassName, module.sub)
        for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_./]*(?:\([^)]*\))?", text):
            w = m.group()
            if len(w) >= 2:
                keywords.add(w)

        # Numbers with chapter/section/page context
        for m in re.finditer(r"(?:第\s*)?\d+(?:[.．]\d+)?(?:\s*[章节页])?", text):
            w = m.group()
            if len(w) >= 1:
                keywords.add(w)

        return keywords

    @classmethod
    def _extract_ordered_terms(cls, text: str) -> list[str]:
        """Extract candidate course terms while preserving first-seen order."""
        seen: set[str] = set()
        terms: list[str] = []
        text = text or ""
        matches: list[tuple[int, str]] = []

        technical_suffixes = (
            "进程|线程|管道|函数|模式|系统|文件|描述符|队列|内存|地址|权限|"
            "信号|指针|中断|寄存器|调度|同步|互斥|死锁|缓冲区|页面|算法|结构"
        )
        for match in re.finditer(r"[\u4e00-\u9fa5]{2,18}", text):
            seq = match.group()
            start = match.start()
            if len(seq) <= 6 and not re.search(r"[与和及或]", seq):
                matches.append((start, seq))
            for part in re.split(r"[与和及或、]", seq):
                if 2 <= len(part) <= 6:
                    offset = seq.find(part)
                    matches.append((start + max(offset, 0), part))
            for term_match in re.finditer(rf"[\u4e00-\u9fa5]{{0,4}}(?:{technical_suffixes})", seq):
                term = term_match.group()
                term = re.sub(r"^[与和及或的在中把被将]+", "", term)
                term = re.sub(r"(区别|特点|流程|步骤|示例|用途|原理|概念|本质)$", "", term)
                if 2 <= len(term) <= 10:
                    matches.append((start + term_match.start(), term))

        for pattern in (
            r"[a-zA-Z_][a-zA-Z0-9_./]*(?:\([^)]*\))?",
            r"(?:第\s*)?\d+(?:[.．]\d+)?(?:\s*[章节页])?",
        ):
            for match in re.finditer(pattern, text):
                matches.append((match.start(), match.group()))

        for _, term in sorted(matches, key=lambda item: item[0]):
            term = str(term).strip()
            term = re.sub(r"^[与和及或的在中把被将]+", "", term)
            term = re.sub(r"(区别|特点|流程|步骤|示例|用途|原理|概念|本质)$", "", term)
            if not cls._is_high_value_course_term(term):
                continue
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    @classmethod
    def _is_high_value_course_term(cls, term: str) -> bool:
        term = (term or "").strip()
        if not term or term in cls._KEYWORD_STOPWORDS:
            return False
        if len(term) > 32:
            return False
        if re.fullmatch(r"\d+", term):
            return False
        if re.search(r"[A-Za-z_./\-]", term):
            return len(term) >= 2
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,10}", term):
            return term not in cls._KEYWORD_STOPWORDS
        return False

    @classmethod
    def build_course_terms(
        cls,
        course_title: str = "",
        keywords: Optional[List[str]] = None,
        ppt_slides: Optional[list] = None,
        limit: int = 80,
    ) -> list[str]:
        """Build an authoritative dynamic term list from title, keywords and PPT.

        We deliberately avoid using raw ASR text here. ASR can contain homophone
        mistakes (e.g. a wrong common word where a technical term should be), and
        protecting those mistakes would make later correction harder.  PPT/title
        terms are much more reliable as a context bias for the LLM.
        """
        scores: dict[str, float] = {}
        order: dict[str, int] = {}

        def add(term: str, weight: float) -> None:
            clean = str(term or "").strip()
            if not cls._is_high_value_course_term(clean):
                return
            if clean not in order:
                order[clean] = len(order)
            scores[clean] = scores.get(clean, 0.0) + weight

        for term in keywords or []:
            add(str(term), 8.0)
            for extracted in cls._extract_ordered_terms(str(term)):
                add(extracted, 4.0)

        for term in cls._extract_ordered_terms(course_title or ""):
            add(term, 6.0)

        if ppt_slides:
            for slide in ppt_slides:
                if not isinstance(slide, dict):
                    continue
                for term in cls._extract_ordered_terms(str(slide.get("title") or "")):
                    add(term, 5.0)
                for term in cls._extract_ordered_terms(str(slide.get("text") or "")):
                    add(term, 2.0)

        ranked = sorted(scores, key=lambda t: (-scores[t], order[t], len(t)))
        return ranked[:limit]

    @classmethod
    def keyword_retention_ratio(cls, source: str, candidate: str) -> float:
        """Ratio of source keywords retained in candidate."""
        source_kw = cls.extract_keywords(source)
        if not source_kw:
            return 1.0
        candidate_text = candidate or ""
        retained = sum(1 for kw in source_kw if kw in candidate_text)
        return retained / len(source_kw)

    @classmethod
    def extract_critical_tokens(cls, text: str) -> set[str]:
        """Extract tokens whose loss would materially change the meaning.

        Covers numbers / decimals / version strings and API/identifier-like
        terms (e.g. ``requests.get``, ``OpenAI``, ``v2``, ``CPU``).
        """
        text = text or ""
        tokens: set[str] = set()
        # Numbers and version strings (e.g. 3.11, v2.0, 2024)
        for m in re.finditer(r"\b(?:v?\d+(?:[.．]\d+)+|\d+[.．]\d+|\d+)\b", text):
            tokens.add(m.group())
        # Identifier-like terms containing dots, underscores, slashes or hyphens
        for m in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_./\-]*[./\-_][a-zA-Z0-9_./\-]*\b", text):
            tokens.add(m.group())
        # CamelCase / PascalCase identifiers (e.g. ClassName, methodName)
        for m in re.finditer(r"\b[a-z]+(?:[A-Z][a-z]+)+\b|\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text):
            tokens.add(m.group())
        # Standalone acronyms / API names in all caps (2-8 chars)
        for m in re.finditer(r"\b[A-Z]{2,8}\b", text):
            tokens.add(m.group())
        return tokens

    @classmethod
    def critical_token_retention_ratio(cls, source: str, candidate: str) -> float:
        """Ratio of source critical tokens retained in candidate."""
        source_tokens = cls.extract_critical_tokens(source)
        if not source_tokens:
            return 1.0
        candidate_text = candidate or ""
        retained = sum(1 for t in source_tokens if t in candidate_text)
        return retained / len(source_tokens)

    @classmethod
    def preserves_source_content(
        cls,
        raw_source: str,
        candidate: str,
        min_ratio: float = 0.55,
        length_min_ratio: float = 0.12,
        length_max_ratio: float = 3.00,
    ) -> bool:
        """Check that candidate didn't delete real content vs raw_source.

        Validates critical tokens (numbers / API names) and extreme length
        changes. Ordinary Chinese wording is intentionally not compared by
        exact keyword retention because semantic correction and paragraph
        restructuring legitimately rewrite those phrases.
        """
        source = (raw_source or "").strip()
        candidate = (candidate or "").strip()
        if not source:
            # No source content means nothing to preserve; accept any candidate.
            return True
        if not candidate:
            return False

        if cls.looks_like_summary(candidate, source):
            return False

        source_len = len(source)
        candidate_len = len(candidate)
        if candidate_len < source_len * length_min_ratio:
            logger.warning(
                "termcorrector_preserve_reject reason=too_short source_len=%s candidate_len=%s",
                source_len, candidate_len,
            )
            return False
        if candidate_len > source_len * length_max_ratio:
            logger.warning(
                "termcorrector_preserve_reject reason=too_long source_len=%s candidate_len=%s",
                source_len, candidate_len,
            )
            return False

        critical_ratio = cls.critical_token_retention_ratio(source, candidate)
        if critical_ratio < min_ratio:
            logger.warning(
                "termcorrector_preserve_reject reason=critical_tokens retained_ratio=%.2f",
                critical_ratio,
            )
            return False

        return True

    @classmethod
    def _content_review_reasons(cls, source: str, candidate: str) -> List[str]:
        """Return semantic-risk signals that justify one AI review pass."""
        source = (source or "").strip()
        candidate = (candidate or "").strip()
        if not source or not candidate:
            return []

        reasons: List[str] = []
        length_ratio = len(candidate) / max(len(source), 1)
        if length_ratio < 0.65:
            reasons.append("substantially_shorter")
        if cls.looks_like_summary(candidate, source):
            reasons.append("summary_style")
        if cls.critical_token_retention_ratio(source, candidate) < 1.0:
            reasons.append("critical_tokens_changed")
        return reasons

    @staticmethod
    def _protected_term_retention_ratio(
        protected_terms: Optional[List[str]], candidate: str,
    ) -> float:
        terms = {
            str(term).strip() for term in (protected_terms or [])
            if str(term).strip()
        }
        if not terms:
            return 1.0
        retained = sum(1 for term in terms if term in (candidate or ""))
        return retained / len(terms)

    @staticmethod
    def _parse_review_json(content: str) -> dict[str, Any]:
        """Parse a review response while tolerating a surrounding explanation."""
        cleaned = (content or "").strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise CorrectionError(
                    "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], True
                )
            try:
                payload = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError as exc:
                raise CorrectionError(
                    "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], True
                ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("has_material_loss"), bool):
            raise CorrectionError(
                "invalid_response", CORRECTION_ERROR_CODES["invalid_response"], True
            )
        return payload

    def review_and_repair_candidate(
        self,
        source: str,
        candidate: str,
        protected_terms: Optional[List[str]] = None,
        timeout_seconds: float = 90.0,
    ) -> dict[str, Any]:
        """Accept a normal draft, or review and repair one that looks suspicious.

        Exact Chinese phrase matching is deliberately avoided. Deterministic
        checks only guard empty/extreme output and critical numbers or code
        tokens; semantic coverage is decided by the review model.
        """
        source = (source or "").strip()
        candidate = (candidate or "").strip()
        if not source or not candidate:
            raise CorrectionError(
                "empty_response", CORRECTION_ERROR_CODES["empty_response"], True
            )

        length_ratio = len(candidate) / max(len(source), 1)
        if length_ratio < 0.12 or length_ratio > 3.0:
            logger.warning(
                "termcorrector_candidate_reject reason=extreme_length source_len=%s candidate_len=%s",
                len(source), len(candidate),
            )
            raise CorrectionError(
                "content_validation_failed",
                CORRECTION_ERROR_CODES["content_validation_failed"],
                True,
            )

        reasons = self._content_review_reasons(source, candidate)
        if self._protected_term_retention_ratio(protected_terms, candidate) < 1.0:
            reasons.append("protected_terms_changed")
        if not reasons:
            return {
                "text": candidate,
                "review_performed": False,
                "review_repaired": False,
                "missing_facts": [],
                "review_error_code": None,
                "review_error_message": None,
            }

        template = load_prompt("asr_content_review")
        prompt = template.render(
            source_text=source,
            candidate_text=candidate,
            risk_reasons="、".join(reasons),
        )
        try:
            review_response = self._call_llm_chunk(prompt, template.system, timeout_seconds)
            payload = self._parse_review_json(review_response["content"])
        except CorrectionError as exc:
            # The first AI draft is already a valid non-empty response. Review
            # is an enhancement and must not turn that draft into a failure.
            logger.warning(
                "termcorrector_candidate_review_failed code=%s message=%s using_first_draft=true",
                exc.code, exc.message,
            )
            return {
                "text": candidate,
                "review_performed": True,
                "review_repaired": False,
                "missing_facts": [],
                "review_error_code": exc.code,
                "review_error_message": exc.message,
            }
        missing_facts = payload.get("missing_facts") or []
        if not isinstance(missing_facts, list):
            missing_facts = []
        missing_facts = [str(item).strip() for item in missing_facts if str(item).strip()]

        has_loss = payload["has_material_loss"]
        repaired_text = str(payload.get("repaired_text") or "").strip()
        selected = repaired_text if has_loss else candidate
        if has_loss and not repaired_text:
            logger.warning(
                "termcorrector_candidate_review_missing_repair using_first_draft=true"
            )
            return {
                "text": candidate,
                "review_performed": True,
                "review_repaired": False,
                "missing_facts": missing_facts,
                "review_error_code": "invalid_response",
                "review_error_message": CORRECTION_ERROR_CODES["invalid_response"],
            }

        selected_ratio = len(selected) / max(len(source), 1)
        if not selected or selected_ratio < 0.12 or selected_ratio > 3.0:
            logger.warning(
                "termcorrector_candidate_review_invalid_repair ratio=%.2f using_first_draft=true",
                selected_ratio,
            )
            return {
                "text": candidate,
                "review_performed": True,
                "review_repaired": False,
                "missing_facts": missing_facts,
                "review_error_code": "invalid_response",
                "review_error_message": CORRECTION_ERROR_CODES["invalid_response"],
            }

        remaining_critical_ratio = self.critical_token_retention_ratio(source, selected)
        remaining_term_ratio = self._protected_term_retention_ratio(protected_terms, selected)
        if remaining_critical_ratio < 1.0 or remaining_term_ratio < 1.0:
            logger.warning(
                "termcorrector_candidate_review_remaining_changes critical_ratio=%.2f protected_ratio=%.2f accepted=true",
                remaining_critical_ratio, remaining_term_ratio,
            )

        logger.info(
            "termcorrector_candidate_reviewed reasons=%s material_loss=%s repaired=%s missing_count=%s",
            reasons, has_loss, bool(has_loss and repaired_text), len(missing_facts),
        )
        return {
            "text": selected,
            "review_performed": True,
            "review_repaired": bool(has_loss and repaired_text),
            "missing_facts": missing_facts,
            "review_error_code": None,
            "review_error_message": None,
        }

    @staticmethod
    def looks_like_summary(candidate: str, source: str = "") -> bool:
        text = (candidate or "").strip()
        if not text:
            return False
        summary_patterns = [
            r"本节课讲了",
            r"本次(?:课程|课|课堂|讲解)",
            r"这(?:节|堂)课",
            r"老师(?:讲了|讲解了|提醒|最后|评价|总结)",
            r"课堂(?:总结|笔记)",
            r"课程(?:总结|摘要)",
            r"总(?:之|结)",
        ]
        if any(re.search(pattern, text) for pattern in summary_patterns):
            return True
        source_first_person = len(re.findall(r"(我们|你们|大家|是不是|对吧|怎么)", source or ""))
        candidate_narration = len(re.findall(r"(老师|同学|本次|课程|课堂|讲解|提醒)", text))
        return candidate_narration >= 3 and candidate_narration > source_first_person

    # ──────────────────────────────────────────────────────────────────
    # LLM call
    # ──────────────────────────────────────────────────────────────────

    def _call_llm(
        self,
        prompt: str,
        system_msg: str,
        temperature: float = 0.2,
        timeout_seconds: float = 60.0,
    ) -> str:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(
            "termcorrector_llm_call model=%s prompt_len=%s system_len=%s timeout=%s",
            DEEPSEEK_MODEL, len(prompt), len(system_msg), timeout_seconds,
        )
        # DeepSeek V4 defaults to thinking mode, which is unnecessary for
        # transcript cleanup and slows down the response. Disable it for V4.
        extra_body = None
        if DEEPSEEK_MODEL and "deepseek-v4" in DEEPSEEK_MODEL:
            extra_body = {"thinking": {"type": "disabled"}}

        t0 = time.time()
        try:
            response = self._client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                timeout=timeout_seconds,
                **({"extra_body": extra_body} if extra_body else {}),
            )
        except Exception as exc:
            elapsed = time.time() - t0
            code, message, _ = classify_correction_exception(exc)
            _logger.warning(
                "termcorrector_llm_exception elapsed=%.2fs code=%s exc_type=%s message=%s",
                elapsed, code, type(exc).__name__, message,
                exc_info=True,
            )
            raise CorrectionError(code, message, False)

        elapsed = time.time() - t0
        if not response.choices:
            _logger.warning("termcorrector_llm_no_choices elapsed=%.2fs", elapsed)
            raise CorrectionError("invalid_response", CORRECTION_ERROR_CODES["invalid_response"], False)
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        content = re.sub(r'^```(?:\w+)?\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)
        _logger.info(
            "termcorrector_llm_response elapsed=%.2fs content_len=%s content_preview=%r",
            elapsed, len(content), content[:120],
        )
        return content.strip()

    # ── chunked restructure ──

    def _classify_exception(self, exc: Exception) -> tuple[str, str, bool]:
        """Map an LLM client exception to a stable error code and user message."""
        return classify_correction_exception(exc)

    def _call_llm_chunk(
        self,
        prompt: str,
        system_msg: str,
        timeout_seconds: float = 90.0,
    ) -> dict[str, Any]:
        """Call the LLM for one chunk and validate the response.

        Returns a dict with content, finish_reason and elapsed.  Raises
        CorrectionError on any failure so the caller can decide whether to
        retry or fall back to the local clean text for this chunk.
        """
        if not self._client:
            raise CorrectionError(
                "authentication", CORRECTION_ERROR_CODES["authentication"], False
            )
        logger.info(
            "termcorrector_chunk_call model=%s prompt_len=%s system_len=%s timeout=%s",
            DEEPSEEK_MODEL, len(prompt), len(system_msg), timeout_seconds,
        )
        # DeepSeek V4 defaults to thinking mode; disable it for cleanup speed.
        extra_body = None
        if DEEPSEEK_MODEL and "deepseek-v4" in DEEPSEEK_MODEL:
            extra_body = {"thinking": {"type": "disabled"}}

        t0 = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=timeout_seconds,
                **({"extra_body": extra_body} if extra_body else {}),
            )
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            code, message, retryable = self._classify_exception(exc)
            logger.warning(
                "termcorrector_chunk_exception elapsed=%.2fs code=%s exc_type=%s message=%s",
                elapsed, code, type(exc).__name__, message,
                exc_info=True,
            )
            raise CorrectionError(code, message, retryable)

        elapsed = time.perf_counter() - t0
        if not response.choices:
            raise CorrectionError(
                "invalid_response", "AI 返回格式异常：无 choices", False, finish_reason=None
            )
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None) or ""
        content = (choice.message.content or "").strip()
        content = re.sub(r'^```(?:\w+)?\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)
        content = content.strip()
        logger.info(
            "termcorrector_chunk_response elapsed=%.2fs finish_reason=%s content_len=%s",
            elapsed, finish_reason, len(content),
        )
        if not content:
            raise CorrectionError(
                "empty_response", CORRECTION_ERROR_CODES["empty_response"], True, finish_reason
            )
        if finish_reason == "length":
            raise CorrectionError(
                "truncated_response", CORRECTION_ERROR_CODES["truncated_response"], True, finish_reason
            )
        return {"content": content, "finish_reason": finish_reason, "elapsed": elapsed}

    def _build_restructure_prompt(
        self,
        text: str,
        course_title: str,
        keywords: Optional[List[str]],
        ppt_slides: Optional[list],
    ) -> tuple[str, str]:
        keyword_str = "、".join(keywords) if keywords else "无"
        course_terms = self.build_course_terms(course_title, keywords, ppt_slides)
        course_terms_str = "、".join(course_terms) if course_terms else "无"
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
            text=text,
            timestamped_text="（无）",
            ppt_context=ppt_context,
        )
        return prompt, prompt_template.system

    @classmethod
    def _split_natural_chunks(
        cls,
        text: str,
        max_chunk: int = 5000,
        min_chunk: int = 3000,
    ) -> List[str]:
        """Split text into chunks at paragraph or sentence boundaries.

        - 6000 chars or less is handled by the caller as a single chunk.
        - Longer texts are split so each chunk is between min_chunk and
          max_chunk characters where possible, never cutting a sentence in half.
        """
        text = text.strip()
        if len(text) <= 6000:
            return [text]

        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
        chunks: List[str] = []
        current = ""

        def flush():
            nonlocal current
            if current:
                chunks.append(current.strip())
                current = ""

        for para in paragraphs:
            # A single paragraph that already exceeds the max must be sentence-split.
            if len(para) > max_chunk:
                flush()
                sentences = cls._split_sentences(para)
                buf = ""
                for s in sentences:
                    if buf and len(buf) + len(s) > max_chunk and len(buf) >= min_chunk:
                        chunks.append(buf.strip())
                        buf = s
                    else:
                        buf += s
                    if len(buf) >= min_chunk:
                        chunks.append(buf.strip())
                        buf = ""
                if buf:
                    if current and len(current) + len(buf) <= max_chunk:
                        current = (current + "\n\n" + buf).strip()
                    else:
                        flush()
                        current = buf
                continue

            candidate = (current + "\n\n" + para).strip() if current else para
            if len(candidate) <= max_chunk:
                current = candidate
            else:
                # If current is already large enough, flush it and start new.
                if len(current) >= min_chunk:
                    chunks.append(current)
                    current = para
                else:
                    # current is small but para pushes us over max; flush current
                    # and put para on its own (it is <= max).
                    flush()
                    current = para
        flush()

        # Merge any trailing tiny chunk back into the previous chunk if size allows.
        if len(chunks) >= 2 and len(chunks[-1]) < min_chunk:
            last = chunks.pop()
            prev = chunks.pop()
            combined = (prev + "\n\n" + last).strip()
            if len(combined) <= max_chunk:
                chunks.append(combined)
            else:
                chunks.append(prev)
                chunks.append(last)

        return chunks or [text]

    def _process_chunk(
        self,
        index: int,
        text: str,
        prompt: str,
        system_msg: str,
        protected_terms: Optional[List[str]] = None,
        timeout_seconds: float = 90.0,
    ) -> RestructureChunkResult:
        """Process a single chunk, retrying once for retryable failures."""
        local_clean = self.clean_transcript_for_display(text).strip() or text
        last_error: Optional[CorrectionError] = None
        elapsed = 0.0
        finish_reason: Optional[str] = None
        for attempt in range(2):
            try:
                # First attempt uses the requested timeout; retry gets up to 120s.
                timeout = timeout_seconds if attempt == 0 else min(120.0, max(timeout_seconds + 30.0, 90.0))
                result = self._call_llm_chunk(prompt, system_msg, timeout)
                review = self.review_and_repair_candidate(
                    local_clean,
                    result["content"],
                    protected_terms=protected_terms,
                    timeout_seconds=timeout,
                )
                return RestructureChunkResult(
                    index=index,
                    input=text,
                    output=review["text"],
                    success=True,
                    elapsed=result["elapsed"],
                    finish_reason=result["finish_reason"],
                    input_length=len(text),
                    review_performed=review["review_performed"],
                    review_repaired=review["review_repaired"],
                    missing_facts=review["missing_facts"],
                    review_error_code=review["review_error_code"],
                    review_error_message=review["review_error_message"],
                )
            except CorrectionError as exc:
                last_error = exc
                finish_reason = exc.finish_reason
                logger.warning(
                    "termcorrector_chunk_failed index=%s attempt=%s code=%s retryable=%s message=%s",
                    index, attempt, exc.code, exc.retryable, exc.message,
                )
                if not exc.retryable or attempt == 1:
                    break
        return RestructureChunkResult(
            index=index,
            input=text,
            output=local_clean,
            success=False,
            error_code=last_error.code if last_error else "unknown",
            error_message=last_error.message if last_error else CORRECTION_ERROR_CODES["unknown"],
            retryable=last_error.retryable if last_error else False,
            elapsed=elapsed,
            finish_reason=finish_reason,
            input_length=len(text),
        )

    def restructure_transcript_chunked(
        self,
        text: str,
        course_title: str,
        keywords: Optional[List[str]] = None,
        ppt_slides: Optional[list] = None,
        previous_results: Optional[List[RestructureChunkResult]] = None,
        retry_failed_only: bool = False,
        on_chunk_complete: Optional[Callable[[int, int], None]] = None,
    ) -> RestructureResult:
        """Restructure transcript in natural chunks with per-chunk fallback.

        Args:
            text: full local-clean transcript to restructure.
            previous_results: optional prior chunk results (used for retry).
            retry_failed_only: when True and previous_results provided, only
                reprocess chunks that failed previously; successful chunks are
                reused so content is never lost.
            on_chunk_complete: optional callback(index, total) invoked each time
                a chunk finishes (success or failure).
        """
        local_text = self.clean_transcript_for_display(text).strip() or text
        if not self._client or not text or not text.strip():
            code = "authentication" if not self._client else None
            message = CORRECTION_ERROR_CODES["authentication"] if not self._client else None
            return RestructureResult(
                text=local_text,
                local_text=local_text,
                is_ai_corrected=False,
                error_code=code,
                error=message,
                retryable=False,
                chunks_total=0,
                chunks_succeeded=0,
                chunks_failed=0,
            )

        chunks = self._split_natural_chunks(text)
        total = len(chunks)
        course_terms = self.build_course_terms(course_title, keywords, ppt_slides)

        # Map previous results by index for reuse.
        prev_by_index: dict[int, RestructureChunkResult] = {}
        if previous_results:
            for r in previous_results:
                if isinstance(r, dict):
                    r = RestructureChunkResult(**r)
                prev_by_index[r.index] = r

        # Build prompt/system once; per-chunk prompts substitute the chunk text.
        _, system_msg = self._build_restructure_prompt(
            "{text}", course_title, keywords, ppt_slides
        )

        def make_prompt(chunk_text: str) -> str:
            prompt, _ = self._build_restructure_prompt(
                chunk_text, course_title, keywords, ppt_slides
            )
            return prompt

        chunk_results: List[RestructureChunkResult] = [None] * total  # type: ignore[list-item]

        def run_chunk(i: int, chunk_text: str) -> RestructureChunkResult:
            if retry_failed_only and i in prev_by_index and prev_by_index[i].success:
                return prev_by_index[i]
            prompt = make_prompt(chunk_text)
            return self._process_chunk(
                i,
                chunk_text,
                prompt,
                system_msg,
                protected_terms=course_terms,
                timeout_seconds=90.0,
            )

        completed_count = 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_index = {
                executor.submit(run_chunk, i, chunk): i for i, chunk in enumerate(chunks)
            }
            for future in as_completed(future_to_index):
                i = future_to_index[future]
                chunk_text = chunks[i]
                local_clean = self.clean_transcript_for_display(chunk_text).strip() or chunk_text
                try:
                    result = future.result()
                except Exception as exc:
                    code, message, retryable = classify_correction_exception(exc)
                    logger.warning(
                        "termcorrector_future_exception index=%s code=%s message=%s",
                        i, code, message,
                        exc_info=True,
                    )
                    result = RestructureChunkResult(
                        index=i,
                        input=chunk_text,
                        output=local_clean,
                        success=False,
                        error_code=code,
                        error_message=message,
                        retryable=retryable,
                        input_length=len(chunk_text),
                    )
                chunk_results[i] = result
                completed_count += 1
                if on_chunk_complete:
                    try:
                        on_chunk_complete(completed_count, total)
                    except Exception:
                        logger.exception("termcorrector_chunk_callback_failed")

        # Defensive: fill any missing slots with local clean text.
        for i, chunk_text in enumerate(chunks):
            if chunk_results[i] is None:
                local_clean = self.clean_transcript_for_display(chunk_text).strip() or chunk_text
                chunk_results[i] = RestructureChunkResult(
                    index=i,
                    input=chunk_text,
                    output=local_clean,
                    success=False,
                    error_code="unknown",
                    error_message=CORRECTION_ERROR_CODES["unknown"],
                    input_length=len(chunk_text),
                )

        combined = "\n\n".join(r.output for r in chunk_results)
        display_text = self.clean_transcript_for_display(combined).strip() or combined

        succeeded = sum(1 for r in chunk_results if r.success)
        failed = total - succeeded

        error_code: Optional[str] = None
        error_message: Optional[str] = None
        retryable = False
        if failed > 0:
            failed_results = [r for r in chunk_results if not r.success]
            retryable = any(r.retryable for r in failed_results)
            if succeeded == 0:
                # All failed: surface the first error.
                first = failed_results[0]
                error_code = first.error_code
                error_message = first.error_message
            else:
                # Partial failure: include counts in the message.
                dominant = max(
                    set(r.error_code for r in failed_results),
                    key=lambda code: sum(1 for r in failed_results if r.error_code == code),
                )
                error_code = dominant
                base = CORRECTION_ERROR_CODES.get(dominant, "AI 整理部分失败")
                error_message = f"{base}：长转写共 {total} 段，成功 {succeeded} 段、失败 {failed} 段"

        return RestructureResult(
            text=display_text,
            local_text=local_text,
            is_ai_corrected=(succeeded == total and total > 0),
            error_code=error_code,
            error=error_message,
            retryable=retryable,
            chunks_total=total,
            chunks_succeeded=succeeded,
            chunks_failed=failed,
            chunk_results=chunk_results,
        )

    def restructure_transcript(
        self,
        text: str,
        course_title: str,
        keywords: Optional[List[str]] = None,
        ppt_slides: Optional[list] = None,
    ) -> str:
        """Backward-compatible wrapper that returns the corrected text or raises.

        When there is no LLM client or the input text is empty, return the
        original text immediately without raising.
        """
        if not self._client or not text or not text.strip():
            return text
        result = self.restructure_transcript_chunked(text, course_title, keywords, ppt_slides)
        if result.is_ai_corrected:
            return result.text
        # Preserve previous behaviour: callers expect an exception when AI fails.
        raise CorrectionError(
            result.error_code or "unknown",
            result.error or CORRECTION_ERROR_CODES["unknown"],
            result.retryable,
        )


# Singleton
corrector = TermCorrector()
