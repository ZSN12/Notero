"""Slide aligner — matches transcript text to PPT slides using keyword overlap.

Strategy (lightweight, no large model needed):
1. Pre-process each slide's text into a set of jieba keywords
2. For each match call, extract keywords from the input text
3. Score each slide by keyword overlap + substring matching
4. Apply positional smoothing (nearby slides get a small bonus)
5. Return best match if score exceeds threshold

Works for Chinese lecture content.
"""

import re
from typing import List, Dict, Optional

import jieba


class SlideAligner:
    """Match transcript segments to the most relevant PPT slide."""

    def __init__(self):
        self.slides: List[Dict] = []
        self.slide_keywords: List[set] = []   # jieba keyword sets per slide
        self.slide_raw: List[str] = []        # raw text per slide (for substring matching)
        self.current_page: Optional[int] = None
        self._cache: Dict[str, set] = {}      # keyword extraction cache

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def set_slides(self, slides: List[Dict]):
        """Load slides and pre-compute keyword sets for fast matching."""
        self.slides = slides
        self.current_page = None
        self.slide_keywords = []
        self.slide_raw = []
        self._cache = {}

        for slide in slides:
            text = slide.get("text", "") or ""
            title = slide.get("title", "") or ""
            # Title appears twice for extra weight.
            # Cover slide (page 1) gets extra title weight so the title
            # dominates over broad body text and still matches topic mentions.
            if slide.get("page") == 1:
                combined = f"{title} {title} {title} {text}"
            else:
                combined = f"{title} {title} {text}"
            kw_set = self._extract_keywords(combined)
            self.slide_keywords.append(kw_set)
            self.slide_raw.append(combined)

    def match(self, text: str, threshold: float = 0.15) -> Optional[int]:
        """Return the index of the best-matching slide, or None.

        Args:
            text: Transcript segment (a sentence or short paragraph).
            threshold: Minimum score (0–1) required to return a match.

        Returns:
            0-based slide index, or None if no slide scores above threshold.
        """
        if not self.slides or not text or not text.strip():
            return None

        input_kw = self._extract_keywords(text)
        if not input_kw:
            return None

        text_lower = text.lower()

        scores = []
        for i, slide_kw in enumerate(self.slide_keywords):
            score = self.score_slide(input_kw, slide_kw, self.slide_raw[i], text_lower, i)
            scores.append(score)

        # Find best and second-best scores
        sorted_scores = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        best_idx, best_score = sorted_scores[0]
        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

        # Accept if:
        # 1. Absolute score above threshold, OR
        # 2. Clear winner with meaningful signal — best beats second-best
        #    by a clear margin AND has at least some signal
        margin = best_score - second_score
        if best_score >= threshold:
            self.current_page = best_idx
            return best_idx
        # For the very first match, require a stronger signal to avoid
        # generic opening sentences latching onto a random content slide.
        if self.current_page is not None:
            if margin >= 0.06 and best_score >= 0.05:
                self.current_page = best_idx
                return best_idx

        return None

    # ----------------------------------------------------------------
    # Scoring
    # ----------------------------------------------------------------

    def get_slide_score(self, text: str, slide_idx: int) -> float:
        """Return the alignment score of *text* against a specific slide index."""
        if not self.slides or not text or not text.strip():
            return 0.0
        if slide_idx < 0 or slide_idx >= len(self.slides):
            return 0.0
        input_kw = self._extract_keywords(text)
        if not input_kw:
            return 0.0
        return self.score_slide(
            input_kw,
            self.slide_keywords[slide_idx],
            self.slide_raw[slide_idx],
            text.lower(),
            slide_idx,
        )

    def score_slide(self, input_kw: set, slide_kw: set,
                    slide_raw: str, input_raw: str, slide_idx: int) -> float:
        """Score a single slide against input keywords.

        Combines:
        1. Keyword overlap — primary signal (70%)
        2. Substring match — catches partial token overlap (20%)
        3. Positional bonus — nearby pages preferred (up to 10%)
        """
        if not slide_kw:
            return 0.0

        # 1) Keyword overlap
        overlap = len(input_kw & slide_kw)

        # Jaccard: penalises slides that are too broad
        union = len(input_kw | slide_kw)
        jaccard = overlap / union if union > 0 else 0.0

        # Coverage: what fraction of input keywords appear in the slide
        coverage = overlap / len(input_kw) if input_kw else 0.0

        keyword_score = coverage * 0.6 + jaccard * 0.4

        # 2) Substring matching — handles partial matches like "卷积" in "卷积层"
        substr_score = 0.0
        if slide_raw:
            # Count how many input keywords appear as substrings in the slide text
            matched = 0
            for kw in input_kw:
                if len(kw) >= 2 and kw in slide_raw:
                    matched += 1
            substr_score = matched / len(input_kw) if input_kw else 0.0

        # Also check if slide title/terms appear in the input text
        slide_in_input = 0
        slide_terms = [t for t in slide_kw if len(t) >= 3]
        if slide_terms and input_raw:
            slide_in_input = sum(1 for t in slide_terms if t in input_raw) / len(slide_terms)

        substr_score = max(substr_score, slide_in_input * 0.5)

        base_score = keyword_score * 0.5 + substr_score * 0.5

        # 3) Positional bonus — only boosts slides that already have signal
        if self.current_page is None:
            distance = slide_idx
        else:
            distance = abs(slide_idx - self.current_page)
        positional = 0.0
        if base_score > 0:
            if distance == 0:
                positional = 0.06
            elif distance == 1:
                positional = 0.04
            elif distance <= 3:
                positional = 0.02

        return min(base_score + positional, 1.0)

    # ----------------------------------------------------------------
    # Keyword extraction
    # ----------------------------------------------------------------

    def _extract_keywords(self, text: str) -> set:
        """Extract meaningful tokens from Chinese text using jieba."""
        text = text.strip()
        if text in self._cache:
            return self._cache[text]

        text = re.sub(r'\s+', ' ', text)

        tokens = jieba.lcut(text)

        keywords = set()
        for t in tokens:
            t = t.strip().lower()
            if not t or len(t) < 2:
                continue
            # Skip pure punctuation / whitespace / numbers
            if re.match(r'^[\s\d\W_]+$', t):
                continue
            keywords.add(t)

        # Add bigrams for compound terms
        cleaned = [t.strip().lower() for t in tokens
                   if len(t.strip()) >= 2 and not re.match(r'^[\s\d\W_]+$', t.strip())]
        for i in range(len(cleaned) - 1):
            bigram = f"{cleaned[i]}{cleaned[i+1]}"
            keywords.add(bigram)

        self._cache[text] = keywords
        return keywords


# Module-level singleton for the /ppt-align endpoint (real-time)
aligner = SlideAligner()
