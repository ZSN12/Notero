"""Verify QuizAgent does not share SQLAlchemy Session across threads."""

import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.agents.quiz_agent import QuizAgent


def test_call_batch_receives_only_plain_strings():
    """_call_batch must not touch ctx.db / ctx.session inside the worker thread."""
    agent = QuizAgent()

    captured = {}

    def fake_try_generate(prompt_template, prompt, min_count):
        # Record which thread ran and what it received.
        captured["thread_id"] = threading.current_thread().ident
        captured["prompt"] = prompt
        return [{"id": "q1", "question": "test"}]

    with patch.object(agent, "_try_generate", side_effect=fake_try_generate):
        result = agent._call_batch(
            prompt_template=MagicMock(render=lambda **kwargs: str(kwargs)),
            session_id="session-1",
            title="Test Session",
            keywords="design, patterns",
            content_text="This is the content text.",
            count=1,
            focus="基础概念",
        )

    assert len(result) == 1
    assert captured["thread_id"] == threading.current_thread().ident
    assert "Test Session" in captured["prompt"]
    assert "design, patterns" in captured["prompt"]
    assert "This is the content text." in captured["prompt"]


def test_run_does_not_pass_orm_objects_to_threads():
    """run() must extract strings before submitting to ThreadPoolExecutor."""
    agent = QuizAgent()

    ctx = MagicMock()
    ctx.session_id = "session-1"
    ctx.session.title = "Test Session"
    ctx.get_keywords_text.return_value = "design, patterns"
    ctx.get_content_text_for_agent.return_value = "Content for quiz."
    ctx.task = None

    submitted = []

    def capture_submit(fn, *args, **kwargs):
        submitted.append(args)
        # Return a completed future so the rest of run() can proceed.
        from concurrent.futures import Future
        fut = Future()
        fut.set_result([])
        return fut

    with patch.object(agent, "load_prompt_template", return_value=MagicMock()):
        with patch("app.agents.quiz_agent.ThreadPoolExecutor") as mock_executor:
            mock_executor.return_value.__enter__.return_value.submit = capture_submit
            # Patch the post-processing / save path so it does not need a real DB.
            with patch.object(agent, "_normalize_question", return_value=""):
                with patch.object(agent, "save_to_vocabulary"):
                    with patch.object(agent, "_update_progress"):
                        agent.run(ctx)

    # submit(fn, *args) -> args[0] is prompt_template, then the extracted strings.
    assert len(submitted) == 2  # easy and advanced batches
    for args in submitted:
        assert args[1] == "session-1"  # session_id
        assert args[2] == "Test Session"  # title
        assert args[3] == "design, patterns"  # keywords
        assert args[4] == "Content for quiz."  # content_text
        for arg in args[1:]:
            assert isinstance(arg, (str, int)), "ORM objects must not be passed to threads"
