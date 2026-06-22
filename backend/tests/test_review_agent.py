"""Tests for ReviewPlannerAgent logic without requiring a live LLM."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.agents.review_agent import ReviewPlannerAgent


class TestExtractMistakes:
    def test_empty_vocabulary(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.note.vocabulary = None
        assert agent._extract_mistakes(ctx) == []

    def test_no_quiz_items(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.note.vocabulary = [
            {"kind": "agent_summary", "data": {}},
        ]
        assert agent._extract_mistakes(ctx) == []

    def test_quiz_without_submission(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.note.vocabulary = [
            {"kind": "quiz", "questions_snapshot": []},
        ]
        assert agent._extract_mistakes(ctx) == []

    def test_extracts_wrong_answers(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.note.vocabulary = [
            {
                "kind": "quiz",
                "submission": {
                    "results": [
                        {"question_id": "q1", "correct": False, "selected": "A", "answer": "B"},
                        {"question_id": "q2", "correct": True, "selected": "C", "answer": "C"},
                    ]
                },
                "questions_snapshot": [
                    {"id": "q1", "question": "Q1 text", "explanation": "Because"},
                ],
            }
        ]
        mistakes = agent._extract_mistakes(ctx)
        assert len(mistakes) == 1
        assert mistakes[0]["question"] == "Q1 text"
        assert mistakes[0]["selected"] == "A"
        assert mistakes[0]["answer"] == "B"
        assert mistakes[0]["explanation"] == "Because"


class TestNormalizePlan:
    def test_valid_plan(self):
        agent = ReviewPlannerAgent()
        data = {
            "title": "My Plan",
            "plan": [
                {
                    "day_offset": 1,
                    "focus": "Concepts",
                    "items": [
                        {"type": "concept", "title": "T1", "description": "D1", "source_type": "note"},
                        {"type": "invalid", "title": "T2", "description": "D2", "source_type": "bad"},
                    ],
                }
            ],
        }
        result = agent._normalize_plan(data)
        assert result["title"] == "My Plan"
        assert len(result["plan"]) == 1
        assert len(result["plan"][0]["items"]) == 2
        assert result["plan"][0]["items"][0]["type"] == "concept"
        # Invalid type falls back to "concept"
        assert result["plan"][0]["items"][1]["type"] == "concept"
        # Invalid source_type falls back to "note"
        assert result["plan"][0]["items"][1]["source_type"] == "note"

    def test_not_dict_raises(self):
        agent = ReviewPlannerAgent()
        with pytest.raises(ValueError, match="不是对象"):
            agent._normalize_plan([])

    def test_plan_not_list_raises(self):
        agent = ReviewPlannerAgent()
        with pytest.raises(ValueError, match="plan 不是列表"):
            agent._normalize_plan({"plan": "string"})

    def test_empty_plan_raises(self):
        agent = ReviewPlannerAgent()
        with pytest.raises(ValueError, match="没有有效条目"):
            agent._normalize_plan({"plan": []})


class TestRun:
    def test_run_success(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.get_content_text.return_value = "Some content"
        ctx.session.title = "Test Session"
        ctx.get_keywords_text.return_value = "kw1, kw2"
        ctx.note.vocabulary = []
        ctx.note.id = "note-1"
        ctx.session_id = "sess-1"
        ctx.user.id = "user-1"

        with patch.object(agent, "call_llm", return_value='{"title": "Plan", "plan": [{"day_offset": 1, "focus": "F", "items": []}]}'), \
             patch.object(agent, "save_to_vocabulary"), \
             patch("app.agents.review_agent._compute_session_content_hash", return_value="hash123"):
            result = agent.run(ctx)
            assert result.success is True
            assert result.data["title"] == "Plan"

    def test_run_empty_content(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.get_content_text_for_agent.return_value = ""
        result = agent.run(ctx)
        assert result.success is False
        assert "没有可用的索引内容" in result.error_message

    def test_run_llm_exception(self):
        agent = ReviewPlannerAgent()
        ctx = MagicMock()
        ctx.get_content_text.return_value = "Content"
        ctx.session.title = "Title"
        ctx.get_keywords_text.return_value = "kw"
        ctx.note.vocabulary = []
        ctx.note.id = "note-1"

        with patch.object(agent, "call_llm", side_effect=Exception("boom")):
            result = agent.run(ctx)
            assert result.success is False
            assert "boom" in result.error_message
