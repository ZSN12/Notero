"""Tests for the agent workflow orchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.orchestrator import (
    AgentWorkflowOrchestrator,
    AGENT_DEPENDENCIES,
    _expand_roles,
    on_agent_heartbeat,
)
from app.models import AgentWorkflow, Task
from app.tasks.workflow_tasks import _mark_stale_roles


def test_expand_roles_includes_transitive_dependencies():
    """Upstream dependencies should be added to the workflow role list."""
    roles = ["mindmap", "quiz"]
    expanded = _expand_roles(roles, AGENT_DEPENDENCIES)
    assert set(expanded) == {"mindmap", "quiz", "transcript"}
    # Requested roles come first, in order.
    assert expanded[:2] == ["mindmap", "quiz"]


def test_expand_roles_no_duplicates():
    """A dependency shared by multiple downstream roles is only added once."""
    roles = ["mindmap", "quiz", "review"]
    expanded = _expand_roles(roles, AGENT_DEPENDENCIES)
    assert expanded.count("transcript") == 1


def _set_final_transcript(note):
    """Seed a finalized transcript so TranscriptOrganizerAgent skips the LLM."""
    note.transcript = [{
        "chunk_index": 0,
        "text": "整理后的课堂内容。",
        "display_text": "整理后的课堂内容。",
        "correction_stage": "final",
        "is_ai_corrected": True,
    }]


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_workflow_dispatches_dependencies_first(mock_openai_cls, db, note_factory):
    """When mindmap is requested, transcript runs first and then mindmap."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"title": "T", "summary": "S", "nodes": [{"id": "n1", "title": "根节点", "type": "topic", "importance": "high", "description": "这是一个测试节点的描述，长度超过50字以确保通过验证。", "sources": [{"source_type": "transcript", "snippet": "测试片段"}], "children": []}], "relations": []}'
    )
    mock_response.choices[0].finish_reason = "stop"
    mock_client.chat.completions.create.return_value = mock_response

    note = note_factory(content="课堂内容")
    _set_final_transcript(note)
    db.commit()
    session = note.session
    orchestrator = AgentWorkflowOrchestrator.create(
        str(session.id),
        str(session.notebook.user_id),
        ["mindmap"],
        dependencies=AGENT_DEPENDENCIES,
        db=db,
    )
    workflow = orchestrator.start(db=db)
    assert workflow is not None
    assert workflow.status == "success"

    # Both transcript and mindmap tasks were created.
    tasks = (
        db.query(Task)
        .filter(Task.session_id == str(session.id))
        .filter(Task.task_type.in_(["agent_transcript", "agent_mindmap"]))
        .all()
    )
    task_types = {t.task_type for t in tasks}
    assert task_types == {"agent_transcript", "agent_mindmap"}
    assert all(t.status == "success" for t in tasks)


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_workflow_reuses_active_task(mock_openai_cls, db, note_factory):
    """An already-running dependency task should be reused, not duplicated."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"title": "T", "summary": "S", "nodes": [{"id": "n1", "title": "根节点", "type": "topic", "importance": "high", "description": "这是一个测试节点的描述，长度超过50字以确保通过验证。", "sources": [{"source_type": "transcript", "snippet": "测试片段"}], "children": []}], "relations": []}'
    )
    mock_response.choices[0].finish_reason = "stop"
    mock_client.chat.completions.create.return_value = mock_response

    note = note_factory(content="课堂内容")
    _set_final_transcript(note)
    db.commit()
    session = note.session
    active = Task(
        session_id=str(session.id),
        task_type="agent_transcript",
        status="running",
        progress=0.5,
    )
    db.add(active)
    db.commit()

    orchestrator = AgentWorkflowOrchestrator.create(
        str(session.id),
        str(session.notebook.user_id),
        ["mindmap"],
        dependencies=AGENT_DEPENDENCIES,
        role_states={"transcript": {"status": "running", "task_id": active.id}},
        db=db,
    )
    workflow = orchestrator.start(db=db)
    assert workflow is not None

    # Only one transcript task exists.
    transcript_tasks = (
        db.query(Task)
        .filter(Task.session_id == str(session.id), Task.task_type == "agent_transcript")
        .all()
    )
    assert len(transcript_tasks) == 1
    assert transcript_tasks[0].id == active.id


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_workflow_marks_error_when_agent_fails(mock_openai_cls, db, note_factory):
    """A failing downstream role should leave the workflow in error status."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    # First call for transcript succeeds; second call for quiz fails.
    call_count = [0]

    def fake_create(*args, **kwargs):
        call_count[0] += 1
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        if call_count[0] == 1:
            mock_response.choices[0].message.content = "整理后的课堂内容。"
        else:
            mock_response.choices[0].message.content = "not valid json"
        return mock_response

    mock_client.chat.completions.create.side_effect = fake_create

    note = note_factory(content="课堂内容")
    _set_final_transcript(note)
    db.commit()
    session = note.session
    orchestrator = AgentWorkflowOrchestrator.create(
        str(session.id),
        str(session.notebook.user_id),
        ["quiz"],
        dependencies=AGENT_DEPENDENCIES,
        db=db,
    )
    workflow = orchestrator.start(db=db)
    assert workflow is not None
    assert workflow.status == "error"
    assert workflow.role_states["transcript"]["status"] == "success"
    assert workflow.role_states["quiz"]["status"] == "error"


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_workflow_heartbeat_updates_and_sweep_detects_stale(
    mock_openai_cls, db, note_factory
):
    """A role without a recent heartbeat should be marked as error by sweep."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"title": "T", "summary": "S", "nodes": [{"id": "n1", "title": "根节点", "type": "topic", "importance": "high", "description": "这是一个测试节点的描述，长度超过50字以确保通过验证。", "sources": [{"source_type": "transcript", "snippet": "测试片段"}], "children": []}], "relations": []}'
    )
    mock_response.choices[0].finish_reason = "stop"
    mock_client.chat.completions.create.return_value = mock_response

    note = note_factory(content="课堂内容")
    _set_final_transcript(note)
    db.commit()
    session = note.session

    # Create a workflow manually and mark transcript as running with an old heartbeat.
    from datetime import datetime, timezone, timedelta

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=1200)
    orchestrator = AgentWorkflowOrchestrator.create(
        str(session.id),
        str(session.notebook.user_id),
        ["mindmap"],
        dependencies=AGENT_DEPENDENCIES,
        role_states={
            "transcript": {
                "status": "running",
                "task_id": "task-1",
                "started_at": stale_time.isoformat(),
                "heartbeat_at": stale_time.isoformat(),
            },
            "mindmap": {"status": "pending"},
        },
        db=db,
    )
    from app.models import AgentWorkflow
    workflow = db.query(AgentWorkflow).filter(AgentWorkflow.id == orchestrator.workflow_id).first()
    workflow.status = "running"
    workflow.last_heartbeat_at = stale_time
    db.commit()

    changed = _mark_stale_roles(workflow, datetime.now(timezone.utc) - timedelta(seconds=600))
    assert changed is True
    assert workflow.role_states["transcript"]["status"] == "error"
    assert workflow.status == "error"


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_workflow_heartbeat_refresh_via_helper(mock_openai_cls, db, note_factory):
    """on_agent_heartbeat updates role heartbeat and workflow heartbeat."""
    note = note_factory(content="课堂内容")
    _set_final_transcript(note)
    db.commit()
    session = note.session

    orchestrator = AgentWorkflowOrchestrator.create(
        str(session.id),
        str(session.notebook.user_id),
        ["mindmap"],
        dependencies=AGENT_DEPENDENCIES,
        role_states={"transcript": {"status": "running"}, "mindmap": {"status": "pending"}},
        db=db,
    )
    db.commit()

    workflow = db.query(AgentWorkflow).filter(AgentWorkflow.id == orchestrator.workflow_id).first()
    workflow.status = "running"
    db.commit()

    on_agent_heartbeat(str(session.id), str(session.notebook.user_id), "transcript", db=db)
    db.refresh(workflow)
    assert workflow.last_heartbeat_at is not None
    assert "heartbeat_at" in workflow.role_states["transcript"]
