"""Tests for agent task dispatch mode selection."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.integration
@patch("app.agents.dispatch._RUN_AGENTS_SYNCHRONOUSLY", False)
@patch("app.agents.dispatch._USE_CELERY_FOR_AGENTS", True)
@patch("app.agents.dispatch._celery_workers_available", return_value=False)
@patch("app.agents.dispatch.run_agent_task")
def test_dispatch_falls_back_to_thread_when_no_celery_workers(
    mock_run_agent_task, mock_workers_available, db, note_factory
):
    """If Celery is configured but no worker is online, dispatch must not leave the task pending in the broker."""
    from app.agents.dispatch import dispatch_agent_task

    note = note_factory(content="课堂内容")
    db.commit()
    session = note.session

    dispatch_agent_task(
        str(session.id),
        str(session.notebook.user_id),
        "mindmap",
        "task-123",
    )

    # run_agent.delay() should never be called when no workers are available.
    # The fallback path uses run_agent_task() to execute in a local thread.
    mock_run_agent_task.assert_called_once()
    mock_workers_available.assert_called_once()


@pytest.mark.integration
@patch("app.agents.dispatch._RUN_AGENTS_SYNCHRONOUSLY", False)
@patch("app.agents.dispatch._USE_CELERY_FOR_AGENTS", True)
@patch("app.agents.dispatch._celery_workers_available", return_value=True)
def test_dispatch_uses_celery_when_workers_available(mock_workers_available, db, note_factory):
    """If Celery workers are online, the task should be sent to Celery."""
    from app.agents.dispatch import dispatch_agent_task

    note = note_factory(content="课堂内容")
    db.commit()
    session = note.session

    with patch("app.tasks.agent_tasks.run_agent") as mock_run_agent:
        dispatch_agent_task(
            str(session.id),
            str(session.notebook.user_id),
            "mindmap",
            "task-123",
        )
        mock_run_agent.delay.assert_called_once_with(
            str(session.id), str(session.notebook.user_id), "mindmap", "task-123"
        )
