import logging
import re
from difflib import SequenceMatcher
from typing import List, Optional
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


_REPEATED_COMMA = re.compile(r'(，\s*){2,}')
_MULTI_SPACE = re.compile(r'\s{2,}')


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
        """LLM correction + reorder. Falls back to deterministic cleanup on error.

        The LLM call is delegated to TranscriptOrganizerAgent so that the agent
        owns the canonical restructuring logic while legacy callers can still use
        this thin wrapper.
        """
        from app.agents.transcript_agent import TranscriptOrganizerAgent

        if not self._client or not text or not text.strip():
            return text

        result = TranscriptOrganizerAgent.restructure_text(
            raw_text=text,
            course_title=course_title,
            keywords=keywords,
            ppt_slides=ppt_slides,
        )
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
    def keyword_retention_ratio(cls, source: str, candidate: str) -> float:
        """Ratio of source keywords retained in candidate."""
        source_kw = cls.extract_keywords(source)
        if not source_kw:
            return 1.0
        candidate_text = candidate or ""
        retained = sum(1 for kw in source_kw if kw in candidate_text)
        return retained / len(source_kw)

    @classmethod
    def preserves_source_content(
        cls,
        raw_source: str,
        candidate: str,
        min_ratio: float = 0.55,
        keyword_min_ratio: float = 0.65,
        keyword_hard_min_ratio: float = 0.50,
    ) -> bool:
        """Check that candidate didn't delete real content vs raw_source.

        Currently always accepts AI output; threshold validation is disabled
        per user preference.  Summary detection is still active.
        """
        if cls.looks_like_summary(candidate, raw_source):
            return False
        return True

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

# Singleton
corrector = TermCorrector()
