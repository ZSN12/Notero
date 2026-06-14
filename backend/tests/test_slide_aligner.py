"""Tests for the slide aligner (keyword-based PPT-to-transcript matching)."""

import pytest
from app.services.slide_aligner import SlideAligner


class TestSlideAligner:
    def test_match_with_empty_slides_returns_none(self):
        aligner = SlideAligner()
        assert aligner.match("any text") is None

    def test_match_with_empty_text_returns_none(self):
        aligner = SlideAligner()
        aligner.set_slides([{"title": "Intro", "text": "Hello world"}])
        assert aligner.match("") is None
        assert aligner.match("   ") is None
        assert aligner.match(None) is None

    def test_exact_title_match(self):
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Introduction", "text": "Welcome"},
            {"title": "Methods", "text": "We used Python"},
            {"title": "Results", "text": "Accuracy 95%"},
        ])
        # "Methods" should match slide 1 (index 1)
        idx = aligner.match("Methods")
        assert idx == 1

    def test_keyword_overlap_match(self):
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Introduction", "text": "Welcome to the course"},
            {"title": "Deep Learning", "text": "Neural networks and backpropagation"},
            {"title": "Conclusion", "text": "Summary and future work"},
        ])
        # "neural network backpropagation" should match slide 1
        idx = aligner.match("neural network backpropagation")
        assert idx == 1

    def test_no_match_below_threshold(self):
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Quantum Physics", "text": "Entanglement and superposition"},
        ])
        # Completely unrelated topic should not match
        idx = aligner.match("machine learning artificial intelligence deep learning")
        assert idx is None

    def test_positional_bonus_prefers_nearby(self):
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Operating Systems", "text": "Process management and scheduling"},
            {"title": "Memory Management", "text": "Virtual memory and paging"},
            {"title": "File Systems", "text": "Disk scheduling and inode tables"},
        ])
        # First, match slide 0 with its exact content
        idx = aligner.match("operating systems process management")
        assert idx == 0
        assert aligner.current_page == 0

        # "virtual memory paging" clearly belongs to slide 1,
        # and it gets a positional bonus for being next to current_page 0
        idx = aligner.match("virtual memory paging")
        assert idx == 1

    def test_set_slides_resets_state(self):
        aligner = SlideAligner()
        aligner.set_slides([{"title": "A", "text": "aaa"}])
        aligner.match("aaa")
        assert aligner.current_page == 0

        aligner.set_slides([{"title": "B", "text": "bbb"}])
        # State should be reset to "no match yet"
        assert aligner.current_page is None
        assert len(aligner.slides) == 1
        assert aligner.slides[0]["title"] == "B"

    def test_get_slide_score_bounds(self):
        aligner = SlideAligner()
        aligner.set_slides([{"title": "A", "text": "aaa"}])

        assert aligner.get_slide_score("", 0) == 0.0
        assert aligner.get_slide_score("aaa", -1) == 0.0
        assert aligner.get_slide_score("aaa", 999) == 0.0
        assert 0.0 <= aligner.get_slide_score("aaa", 0) <= 1.0

    def test_extract_keywords_filters_noise(self):
        aligner = SlideAligner()
        kw = aligner._extract_keywords("the a is 123 !!! ???")
        # Pure punctuation / numbers / short tokens should be dropped
        assert "123" not in kw
        assert "!!!" not in kw
        assert "a" not in kw  # single char dropped

    def test_extract_keywords_keeps_meaningful_tokens(self):
        aligner = SlideAligner()
        kw = aligner._extract_keywords("卷积神经网络")
        # At least one meaningful token should be present
        assert len(kw) > 0
        assert any("卷积" in t or "神经" in t or "网络" in t for t in kw)

    def test_chinese_content_matching(self):
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "操作系统", "text": "进程管理、内存管理和文件系统"},
            {"title": "计算机网络", "text": "TCP/IP 协议栈、路由和交换"},
        ])
        idx = aligner.match("进程和线程的区别是什么")
        assert idx == 0

    def test_margin_winner_when_below_threshold(self):
        """If no slide exceeds threshold but one clearly wins by margin, accept it.

        Margin fallback is only enabled after the first match has been made,
        otherwise generic early chatter could lock onto an irrelevant slide.
        """
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "A", "text": "xxx yyy zzz"},
            {"title": "B", "text": "aaa bbb ccc"},
        ])
        # Input has a tiny overlap with A but almost none with B
        idx = aligner.match("xxx")
        # "xxx" is a strong enough signal to exceed the threshold
        assert idx == 0

        # After the first match, a weak signal can still win by margin
        aligner.current_page = 0
        idx = aligner.match("zzz")
        assert idx == 0

    def test_first_match_below_threshold_returns_none(self):
        """A weak first match should not lock onto a slide prematurely."""
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Introduction", "text": "welcome to the talk"},
            {"title": "Methods", "text": "we used python"},
        ])
        # Generic filler below threshold should not match anything
        idx = aligner.match("okay um so")
        assert idx is None
        assert aligner.current_page is None

    def test_cover_slide_title_gets_extra_weight(self):
        """The first slide title is boosted so the opening topic maps to it."""
        aligner = SlideAligner()
        aligner.set_slides([
            {"title": "Design Patterns", "text": "Analysis of design patterns in library systems"},
            {"title": "Service Layer", "text": "Business logic and data access separation"},
            {"title": "Factory Pattern", "text": "Object creation details"},
        ])
        idx = aligner.match("design patterns in library systems")
        assert idx == 0
