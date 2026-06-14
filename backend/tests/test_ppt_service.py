"""Tests for PPT service text extraction and analysis (no Pillow rendering)."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.services.ppt_service import (
    extract_text_from_slide,
    extract_keywords_from_ppt,
    _is_likely_chapter_header,
)


def _make_mock_slide(texts, notes_text=None):
    """Build a minimal mock slide with text frames and optional notes."""
    slide = MagicMock()
    paragraphs = []
    for t in texts:
        para = MagicMock()
        para.text = t
        paragraphs.append(para)

    text_frame = MagicMock()
    text_frame.paragraphs = paragraphs

    shape = MagicMock()
    shape.has_text_frame = True
    shape.text_frame = text_frame
    shape.table = None

    slide.shapes = [shape]
    slide.has_notes_slide = notes_text is not None
    if notes_text:
        notes_slide = MagicMock()
        notes_text_frame = MagicMock()
        notes_text_frame.text = notes_text
        notes_slide.notes_text_frame = notes_text_frame
        slide.notes_slide = notes_slide

    return slide


def _make_mock_slide_with_table(cell_texts):
    """Build a mock slide with a table."""
    slide = MagicMock()
    table_shape = MagicMock()
    table_shape.has_text_frame = False
    table_shape.table = True

    rows = []
    for row_texts in cell_texts:
        row = MagicMock()
        cells = []
        for t in row_texts:
            cell = MagicMock()
            cell.text = t
            cells.append(cell)
        row.cells = cells
        rows.append(row)

    table_shape.table.rows = rows
    slide.shapes = [table_shape]
    slide.has_notes_slide = False
    return slide


class TestExtractTextFromSlide:
    def test_extracts_text_from_paragraphs(self):
        slide = _make_mock_slide(["Hello world", "Second paragraph"])
        result = extract_text_from_slide(slide)
        assert "Hello world" in result
        assert "Second paragraph" in result

    def test_skips_empty_paragraphs(self):
        slide = _make_mock_slide(["Real text", "   ", "", "More text"])
        result = extract_text_from_slide(slide)
        assert "Real text" in result
        assert "More text" in result
        assert "   " not in result.split("\n")

    def test_extracts_table_cells(self):
        slide = _make_mock_slide_with_table([["Cell A", "Cell B"], ["Cell C", "Cell D"]])
        result = extract_text_from_slide(slide)
        assert "Cell A" in result
        assert "Cell B" in result
        assert "Cell C" in result
        assert "Cell D" in result

    def test_includes_notes(self):
        slide = _make_mock_slide(["Title"], notes_text="Speaker notes here")
        result = extract_text_from_slide(slide)
        assert "Title" in result
        assert "备注: Speaker notes here" in result

    def test_combines_text_and_table(self):
        slide = _make_mock_slide(["Slide title"])
        table_shape = MagicMock()
        table_shape.has_text_frame = False
        table_shape.table = True
        row = MagicMock()
        cell = MagicMock()
        cell.text = "Table cell"
        row.cells = [cell]
        table_shape.table.rows = [row]
        slide.shapes.append(table_shape)
        result = extract_text_from_slide(slide)
        assert "Slide title" in result
        assert "Table cell" in result


class TestExtractKeywordsFromPpt:
    @patch("app.services.ppt_service.Presentation")
    def test_extracts_repeated_chinese_terms(self, mock_pres_cls):
        slide = _make_mock_slide(["单例模式很重要，工厂模式也很重要"])
        mock_pres = MagicMock()
        mock_pres.slides = [slide]
        mock_pres_cls.return_value = mock_pres

        keywords = extract_keywords_from_ppt("fake.pptx", "设计模式")
        assert "单例模式" in keywords or "工厂模式" in keywords

    @patch("app.services.ppt_service.Presentation")
    def test_filters_common_words(self, mock_pres_cls):
        slide = _make_mock_slide(["我们我们我们 他们他们 单例模式"])
        mock_pres = MagicMock()
        mock_pres.slides = [slide]
        mock_pres_cls.return_value = mock_pres

        keywords = extract_keywords_from_ppt("fake.pptx", "课程")
        # "我们" and "他们" are in common_words list
        assert "我们" not in keywords
        assert "他们" not in keywords

    @patch("app.services.ppt_service.Presentation")
    def test_returns_max_15_keywords(self, mock_pres_cls):
        # Create many unique repeated terms
        texts = ["术语" + str(i) for i in range(30)] * 2
        slide = _make_mock_slide(texts)
        mock_pres = MagicMock()
        mock_pres.slides = [slide]
        mock_pres_cls.return_value = mock_pres

        keywords = extract_keywords_from_ppt("fake.pptx", "课程")
        assert len(keywords) <= 15

    @patch("app.services.ppt_service.Presentation")
    def test_requires_minimum_count_2(self, mock_pres_cls):
        slide = _make_mock_slide(["只出现一次的词"])
        mock_pres = MagicMock()
        mock_pres.slides = [slide]
        mock_pres_cls.return_value = mock_pres

        keywords = extract_keywords_from_ppt("fake.pptx", "课程")
        # "只出现一次的词" appears only once, so it shouldn't be included
        assert "只出现一次的词" not in keywords


class TestIsLikelyChapterHeader:
    def test_empty_title_returns_false(self):
        assert _is_likely_chapter_header({"title": "", "text": ""}) is False

    def test_short_remainder_is_chapter(self):
        slide = {"title": "第一章", "text": "第一章"}
        assert _is_likely_chapter_header(slide) is True

    def test_contents_page_is_chapter(self):
        slide = {"title": "目录", "text": "目录\nCONTENTS"}
        assert _is_likely_chapter_header(slide) is True

    def test_summary_page_is_chapter(self):
        slide = {"title": "Summary", "text": "Summary\nSUMMARY"}
        assert _is_likely_chapter_header(slide) is True

    def test_number_only_is_chapter(self):
        slide = {"title": "01", "text": "01\n01"}
        assert _is_likely_chapter_header(slide) is True

    def test_content_rich_slide_is_not_chapter(self):
        slide = {"title": "单例模式", "text": "单例模式\n\n确保一个类只有一个实例，并提供一个全局访问点。"}
        assert _is_likely_chapter_header(slide) is False

    def test_mixed_number_and_text_is_not_chapter(self):
        slide = {"title": "第3章", "text": "第3章\n\n这一章我们介绍设计模式的分类和应用场景。"}
        assert _is_likely_chapter_header(slide) is False

    def test_thankyou_slide_is_chapter(self):
        slide = {"title": "Thank You", "text": "Thank You\nTHANKYOU"}
        assert _is_likely_chapter_header(slide) is True

    def test_chinese_contents_is_chapter(self):
        slide = {"title": "内容", "text": "内容\n目录"}
        assert _is_likely_chapter_header(slide) is True
