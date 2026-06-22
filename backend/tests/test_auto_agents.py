"""Tests for auto-triggering agents after transcription completes."""

from unittest.mock import patch

import pytest

from app.api.agents import _should_auto_trigger_agents, auto_run_agents
from app.models import Note, Task, User
from app.services.state_service import set_fallback, set_ready
from tests.harness.helpers import create_notebook_session_note
from tests.harness.mocks import mock_chat_completion


def _set_stage_status(db, session_id: str, vector_status: str, transcript_status: str):
    """Helper to seed processing-state rows for _should_auto_trigger_agents."""
    if vector_status == "ready":
        set_ready(db, session_id, "vector_index", content_hash="hash")
    else:
        set_fallback(db, session_id, "vector_index", message="not ready")
    if transcript_status == "ready":
        set_ready(db, session_id, "transcript_finalize", content_hash="hash")
    else:
        set_fallback(db, session_id, "transcript_finalize", message="not ready")


# ── _should_auto_trigger_agents unit tests ──

@pytest.mark.unit
def test_should_auto_trigger_when_both_stages_ready(db, session_factory):
    session = session_factory()
    _set_stage_status(db, str(session.id), vector_status="ready", transcript_status="ready")
    db.commit()
    assert _should_auto_trigger_agents(db, str(session.id)) is True


@pytest.mark.unit
def test_should_not_auto_trigger_without_vector_ready(db, session_factory):
    session = session_factory()
    _set_stage_status(db, str(session.id), vector_status="fallback", transcript_status="ready")
    db.commit()
    assert _should_auto_trigger_agents(db, str(session.id)) is False


@pytest.mark.unit
def test_should_not_auto_trigger_with_transcript_fallback(db, session_factory):
    session = session_factory()
    _set_stage_status(db, str(session.id), vector_status="ready", transcript_status="fallback")
    db.commit()
    assert _should_auto_trigger_agents(db, str(session.id)) is False


@pytest.mark.unit
def test_should_not_auto_trigger_with_both_stages_idle(db, session_factory):
    session = session_factory()
    _set_stage_status(db, str(session.id), vector_status="idle", transcript_status="idle")
    db.commit()
    assert _should_auto_trigger_agents(db, str(session.id)) is False


# ── auto_run_agents integration tests ──


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_auto_run_agents_skips_when_fallback_local_cleanup(
    mock_cls, client, auth_headers, db
):
    mock_cls.return_value = mock_chat_completion({
        "title": "测试知识导图",
        "summary": "测试摘要",
        "nodes": [
            {
                "id": "n1",
                "title": "单例模式",
                "description": "确保一个类只有一个实例",
                "type": "concept",
                "importance": "high",
                "sources": [{"source_type": "transcript", "snippet": "单例模式"}],
                "children": []
            }
        ],
        "relations": []
    })

    _, session_id = create_notebook_session_note(
        client, auth_headers,
        content="今天我们学习了单例模式和工厂模式。"
    )

    # Inject a transcript that is NOT AI-corrected (local cleanup only)
    note = db.query(Note).filter(Note.session_id == session_id).first()
    assert note is not None
    note.transcript = [{
        "chunk_index": 0,
        "text": "今天我们学习了单例模式和工厂模式。",
        "display_text": "今天我们学习了单例模式和工厂模式。",
        "correction_stage": "final",
        "is_ai_corrected": False,
    }]
    db.commit()

    # Simulate vector ready + transcript fallback (local-only finalization)
    set_ready(db, session_id, "vector_index", content_hash="hash")
    set_fallback(db, session_id, "transcript_finalize", message="local only")

    user = db.query(User).filter(User.email == "admin").first()
    result = auto_run_agents(session_id, user.id, roles=["mindmap", "quiz"])
    assert result is None

    # Local fallback remains usable but does not spend more AI calls.
    tasks = db.query(Task).filter(Task.session_id == session_id).all()
    assert tasks == []


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_auto_run_agents_creates_tasks_when_final_and_ai_corrected(
    mock_cls, client, auth_headers, db
):
    mock_cls.return_value = mock_chat_completion({
        "title": "测试知识导图",
        "summary": "测试摘要",
        "nodes": [
            {
                "id": "n1",
                "title": "单例模式",
                "description": "确保一个类只有一个实例",
                "type": "concept",
                "importance": "high",
                "sources": [{"source_type": "transcript", "snippet": "单例模式"}],
                "children": []
            }
        ],
        "relations": []
    })

    _, session_id = create_notebook_session_note(
        client, auth_headers,
        content="今天我们学习了单例模式和工厂模式。"
    )

    # Inject a final AI-corrected transcript
    note = db.query(Note).filter(Note.session_id == session_id).first()
    note.transcript = [{
        "chunk_index": 0,
        "text": "今天我们学习了单例模式和工厂模式。",
        "display_text": "今天我们学习了单例模式和工厂模式。",
        "correction_stage": "final",
        "is_ai_corrected": True,
    }]
    db.commit()

    # Simulate vector + transcript ready so agents can auto-trigger
    set_ready(db, session_id, "vector_index", content_hash="hash")
    set_ready(db, session_id, "transcript_finalize", content_hash="hash")

    user = db.query(User).filter(User.email == "admin").first()
    result = auto_run_agents(session_id, user.id, roles=["mindmap", "quiz"])
    assert result is not None
    assert result["session_id"] == session_id
    assert len(result["agents"]) > 0

    # Verify tasks were created in DB
    tasks = db.query(Task).filter(Task.session_id == session_id).all()
    assert len(tasks) >= 2  # mindmap, quiz
    roles = {t.task_type.removeprefix("agent_") for t in tasks}
    assert "mindmap" in roles
    assert "quiz" in roles


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_auto_run_agents_does_not_duplicate_active_tasks(
    mock_cls, client, auth_headers, db
):
    mock_cls.return_value = mock_chat_completion({
        "title": "测试知识导图",
        "summary": "测试摘要",
        "nodes": [
            {
                "id": "n1",
                "title": "单例模式",
                "description": "确保一个类只有一个实例",
                "type": "concept",
                "importance": "high",
                "sources": [{"source_type": "transcript", "snippet": "单例模式"}],
                "children": []
            }
        ],
        "relations": []
    })

    _, session_id = create_notebook_session_note(
        client, auth_headers,
        content="测试内容"
    )

    note = db.query(Note).filter(Note.session_id == session_id).first()
    note.transcript = [{
        "chunk_index": 0,
        "text": "测试内容",
        "display_text": "测试内容",
        "correction_stage": "final",
        "is_ai_corrected": True,
    }]
    db.commit()

    # Simulate vector + transcript ready so agents can auto-trigger
    set_ready(db, session_id, "vector_index", content_hash="hash")
    set_ready(db, session_id, "transcript_finalize", content_hash="hash")

    user = db.query(User).filter(User.email == "admin").first()

    # First call
    result1 = auto_run_agents(session_id, user.id, roles=["mindmap"])
    assert result1 is not None
    assert result1.get("reused") is not True

    # Second call immediately — should reuse active tasks
    result2 = auto_run_agents(session_id, user.id, roles=["mindmap"])
    assert result2 is not None
    assert result2.get("reused") is True

    # Only one task should exist for mindmap
    tasks = (
        db.query(Task)
        .filter(Task.session_id == session_id, Task.task_type == "agent_mindmap")
        .all()
    )
    assert len(tasks) == 1


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_auto_run_agents_starts_downstream_without_reprocessing_transcript(
    mock_cls, client, auth_headers, db
):
    """Finalized text feeds mindmap and quiz directly without another LLM pass."""
    mock_cls.return_value = mock_chat_completion({
        "title": "T",
        "summary": "S",
        "nodes": [
            {
                "id": "n1",
                "title": "Node",
                "description": "D",
                "type": "concept",
                "importance": "high",
                "sources": [{"source_type": "transcript", "snippet": "整理后内容"}],
                "children": []
            }
        ],
        "relations": []
    })

    _, session_id = create_notebook_session_note(
        client, auth_headers,
        content="整理后内容"
    )

    note = db.query(Note).filter(Note.session_id == session_id).first()
    note.transcript = [{
        "chunk_index": 0,
        "text": "整理后内容",
        "display_text": "整理后内容",
        "correction_stage": "final",
        "is_ai_corrected": True,
    }]
    db.commit()

    set_ready(db, session_id, "vector_index", content_hash="hash")
    set_ready(db, session_id, "transcript_finalize", content_hash="hash")

    user = db.query(User).filter(User.email == "admin").first()
    result = auto_run_agents(session_id, user.id, roles=["mindmap", "quiz"])
    assert result is not None
    assert "upstream_errors" not in result, result.get("upstream_errors")

    # Both downstream agents start directly and can execute in parallel.
    roles = {a["role"] for a in result["agents"]}
    assert "mindmap" in roles
    assert "quiz" in roles
    assert "transcript" not in roles
