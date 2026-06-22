"""Tests for unified agent state sync, heartbeat and stale-task healing."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import AgentWorkflow, SessionProcessingState, Task
from app.services.agent_state_service import (
    INTERRUPTED_MESSAGE,
    heal_stuck_agent_states,
    set_agent_error,
    set_agent_progress,
    set_agent_queued,
    set_agent_ready,
    set_agent_running,
    update_task_heartbeat,
)


pytestmark = pytest.mark.usefixtures("ensure_admin")


def _make_old(dt: datetime, seconds: int = 1200) -> datetime:
    return dt - timedelta(seconds=seconds)


def test_heal_stuck_running_task(db, sample_session):
    task = Task(
        session_id=sample_session.id,
        task_type="agent_mindmap",
        status="running",
        progress=0.5,
    )
    db.add(task)
    db.commit()
    # Simulate old updated_at by flushing past the model default.
    task.updated_at = _make_old(datetime.now(timezone.utc))
    db.commit()

    counts = heal_stuck_agent_states(db, session_id=sample_session.id)
    assert counts["tasks"] == 1

    db.refresh(task)
    assert task.status == "error"
    assert task.progress == 1.0
    assert task.error_message == INTERRUPTED_MESSAGE


def test_heal_stuck_running_state(db, sample_session):
    state = SessionProcessingState(
        session_id=sample_session.id,
        stage="mindmap",
        status="running",
        progress=0.5,
    )
    db.add(state)
    db.commit()
    state.updated_at = _make_old(datetime.now(timezone.utc))
    db.commit()

    counts = heal_stuck_agent_states(db, session_id=sample_session.id)
    assert counts["states"] == 1

    db.refresh(state)
    assert state.status == "error"
    assert state.error_message == INTERRUPTED_MESSAGE


def test_heal_stuck_running_workflow(db, sample_session, admin_user):
    workflow = AgentWorkflow(
        session_id=sample_session.id,
        user_id=admin_user.id,
        roles=["mindmap"],
        dependencies={},
        role_states={
            "mindmap": {
                "status": "running",
                "task_id": "t1",
                "progress": 0.5,
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        status="running",
    )
    db.add(workflow)
    db.commit()
    workflow.last_heartbeat_at = _make_old(datetime.now(timezone.utc))
    workflow.updated_at = _make_old(datetime.now(timezone.utc))
    db.commit()

    counts = heal_stuck_agent_states(db, session_id=sample_session.id)
    assert counts["workflows"] == 1

    db.refresh(workflow)
    assert workflow.status == "error"
    assert workflow.role_states["mindmap"]["status"] == "error"
    assert workflow.role_states["mindmap"]["error_message"] == INTERRUPTED_MESSAGE


def test_set_agent_running_syncs_task_state_workflow(db, sample_session, admin_user):
    workflow = AgentWorkflow(
        session_id=sample_session.id,
        user_id=admin_user.id,
        roles=["mindmap"],
        dependencies={},
        role_states={"mindmap": {"status": "pending"}},
        status="running",
    )
    db.add(workflow)
    task = Task(session_id=sample_session.id, task_type="agent_mindmap", status="pending")
    db.add(task)
    db.commit()

    set_agent_running(db, sample_session.id, "mindmap", task.id, progress=0.1, message="准备中", user_id=admin_user.id)

    db.refresh(task)
    assert task.status == "running"
    assert task.progress == 0.1

    state = db.query(SessionProcessingState).filter(
        SessionProcessingState.session_id == sample_session.id,
        SessionProcessingState.stage == "mindmap",
    ).first()
    assert state is not None
    assert state.status == "running"
    assert state.message == "准备中"

    db.refresh(workflow)
    assert workflow.role_states["mindmap"]["status"] == "running"
    assert workflow.role_states["mindmap"]["progress"] == 0.1


def test_set_agent_queued_keeps_task_pending_for_worker(db, sample_session, admin_user):
    workflow = AgentWorkflow(
        session_id=sample_session.id,
        user_id=admin_user.id,
        roles=["mindmap"],
        dependencies={},
        role_states={"mindmap": {"status": "pending"}},
        status="running",
    )
    db.add(workflow)
    task = Task(session_id=sample_session.id, task_type="agent_mindmap", status="pending")
    db.add(task)
    db.commit()

    set_agent_queued(
        db,
        sample_session.id,
        "mindmap",
        task.id,
        user_id=admin_user.id,
    )

    db.refresh(task)
    assert task.status == "pending"
    state = db.query(SessionProcessingState).filter(
        SessionProcessingState.session_id == sample_session.id,
        SessionProcessingState.stage == "mindmap",
    ).first()
    assert state is not None
    assert state.status == "queued"
    assert state.message == "等待后台任务执行"


def test_set_agent_ready_syncs_task_state_workflow(db, sample_session, admin_user):
    workflow = AgentWorkflow(
        session_id=sample_session.id,
        user_id=admin_user.id,
        roles=["mindmap"],
        dependencies={},
        role_states={"mindmap": {"status": "running", "task_id": "t1"}},
        status="running",
    )
    db.add(workflow)
    task = Task(session_id=sample_session.id, task_type="agent_mindmap", status="running")
    db.add(task)
    db.commit()

    set_agent_ready(db, sample_session.id, "mindmap", task.id, content_hash="hash", message="完成", user_id=admin_user.id)

    db.refresh(task)
    assert task.status == "success"

    state = db.query(SessionProcessingState).filter(
        SessionProcessingState.session_id == sample_session.id,
        SessionProcessingState.stage == "mindmap",
    ).first()
    assert state.status == "ready"
    assert state.content_hash == "hash"
    assert state.message == "完成"

    db.refresh(workflow)
    assert workflow.role_states["mindmap"]["status"] == "success"


def test_set_agent_error_syncs_task_state_workflow(db, sample_session, admin_user):
    workflow = AgentWorkflow(
        session_id=sample_session.id,
        user_id=admin_user.id,
        roles=["mindmap"],
        dependencies={},
        role_states={"mindmap": {"status": "running", "task_id": "t1"}},
        status="running",
    )
    db.add(workflow)
    task = Task(session_id=sample_session.id, task_type="agent_mindmap", status="running")
    db.add(task)
    db.commit()

    set_agent_error(db, sample_session.id, "mindmap", task.id, "boom", user_id=admin_user.id)

    db.refresh(task)
    assert task.status == "error"
    assert task.error_message == "boom"

    state = db.query(SessionProcessingState).filter(
        SessionProcessingState.session_id == sample_session.id,
        SessionProcessingState.stage == "mindmap",
    ).first()
    assert state.status == "error"
    assert state.error_message == "boom"

    db.refresh(workflow)
    assert workflow.role_states["mindmap"]["status"] == "error"


def test_set_agent_progress_updates_task_and_state(db, sample_session):
    task = Task(session_id=sample_session.id, task_type="agent_mindmap", status="running")
    db.add(task)
    state = SessionProcessingState(session_id=sample_session.id, stage="mindmap", status="running")
    db.add(state)
    db.commit()

    set_agent_progress(db, sample_session.id, "mindmap", 0.42, message="调用模型", task_id=task.id)

    db.refresh(task)
    assert task.progress == 0.42
    db.refresh(state)
    assert state.progress == 0.42
    assert state.message == "调用模型"


def test_heartbeat_uses_independent_session():
    """The heartbeat helper must create its own session, never touching caller's db."""
    fake_task = MagicMock()
    fake_task.updated_at = None

    mock_query = MagicMock()
    mock_query.filter.return_value.first.return_value = fake_task
    mock_db = MagicMock()
    mock_db.query.return_value = mock_query

    mock_session_local = MagicMock(return_value=mock_db)

    with patch("app.core.database.SessionLocal", mock_session_local):
        update_task_heartbeat("task-123")

    mock_session_local.assert_called_once()
    mock_db.query.assert_called_once_with(Task)
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()

