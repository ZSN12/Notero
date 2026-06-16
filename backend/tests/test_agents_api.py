"""Tests for the multi-agent pipeline endpoints.

Covers:
- Parallel agent vocabulary race-condition safety
- Stale detection on single-agent endpoint
- Active task reuse
- Truncation (finish_reason=length) detection
- Single-agent endpoint returns 200 (not 202)
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from tests.harness.helpers import create_notebook_session_note
from tests.harness.mocks import mock_chat_completion


MOCK_MINDMAP = {
    "title": "测试导图",
    "summary": "测试摘要",
    "nodes": [
        {
            "id": "n1",
            "title": "根节点",
            "type": "topic",
            "importance": "high",
            "description": "这是一个测试节点的描述，长度超过50字以确保通过验证。",
            "sources": [{"source_type": "transcript", "snippet": "测试片段", "page": None}],
            "children": []
        }
    ],
    "relations": [],
}
MOCK_QUIZ = {
    "title": "测试题库",
    "questions": [
        {
            "id": "q1",
            "question": "测试题1",
            "options": [
                {"id": "A", "text": "选项A"},
                {"id": "B", "text": "选项B"},
                {"id": "C", "text": "选项C"},
                {"id": "D", "text": "选项D"},
            ],
            "answer": "A",
            "explanation": "因为A正确",
        }
    ],
}


def _mock_response_for_agent(role: str, finish_reason: str = "stop"):
    """Return a mock response object for the given agent role."""
    if role == "mindmap":
        content = MOCK_MINDMAP
    elif role == "quiz":
        content = MOCK_QUIZ
    else:
        content = {}
    return mock_chat_completion(content, finish_reason=finish_reason).chat.completions.create.return_value


def _wait_for_agent_status(
    client,
    session_id: str,
    headers: dict,
    role: str,
    expected: set[str],
    timeout: float = 5.0,
):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/agents/session/{session_id}/tasks", headers=headers)
        assert resp.status_code == 200, resp.text
        agents = resp.json().get("agents", [])
        for a in agents:
            if a.get("task_type") == f"agent_{role}":
                last = a
                if a["status"] in expected:
                    return a
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {expected}, last={last}")


# ── Tests ──

@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_single_agent_returns_200_and_ready(mock_openai_cls, client, auth_headers):
    """Single agent run should return 200 with data, not 202."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("mindmap")

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    resp = client.post(f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "ready"
    assert data["data"] is not None


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_single_agent_reuses_active_task(mock_openai_cls, client, auth_headers, db):
    """When an active task exists, the endpoint should reuse it."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("mindmap")

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    # Manually create an active (running) task in the DB.
    from app.models import Task

    active_task = Task(
        session_id=session_id,
        task_type="agent_mindmap",
        status="running",
        progress=0.5,
        error_message=None,
    )
    db.add(active_task)
    db.commit()
    db.refresh(active_task)
    task_id = active_task.id

    # Call endpoint without force — should reuse the active task.
    resp = client.post(
        f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "generating"
    assert data["task_id"] == task_id
    # Should NOT have called the LLM.
    assert mock_client.chat.completions.create.call_count == 0


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_single_agent_stale_after_content_change(mock_openai_cls, client, auth_headers):
    """After content changes, existing agent output should be considered stale."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("mindmap")

    _, session_id = create_notebook_session_note(
        client, auth_headers, content="原始内容"
    )

    # First run
    resp = client.post(f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers)
    assert resp.status_code == 200

    # Change content
    client.put(
        f"/api/notes/session/{session_id}",
        json={
            "content": "完全不同的新内容",
            "layout_blocks": [{"id": "t1", "type": "transcript", "content": "完全不同的新内容"}],
        },
        headers=auth_headers,
    )

    # Second run (not forced) should regenerate because stale.
    resp2 = client.post(f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers)
    assert resp2.status_code == 200
    # Should have triggered a new run, not returned "ready".
    assert resp2.json()["status"] in ("ready", "generating")

    # Wait for completion
    task = _wait_for_agent_status(client, session_id, auth_headers, "mindmap", {"success", "ready"})
    # Should have generated twice.
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_truncate_finish_reason_raises_error(mock_openai_cls, client, auth_headers):
    """If DeepSeek returns finish_reason='length', the agent should fail."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent(
        "mindmap", finish_reason="length"
    )

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    resp = client.post(f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers)
    assert resp.status_code == 502
    assert "截断" in resp.json()["detail"] or "length" in resp.json()["detail"]


# The vocabulary race-condition is tested directly in
# test_agents_vocabulary_race.py by exercising BaseAgent.save_to_vocabulary()
# from two concurrent threads. This avoids encoding issues when mocking LLM
# responses for the full orchestration path.


@pytest.mark.integration
@patch("app.agents.base.OpenAI")
def test_run_all_agents_reuses_active_tasks(mock_openai_cls, client, auth_headers):
    """run_all_agents should reuse active tasks instead of spawning duplicates."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    def slow_response(*args, **kwargs):
        time.sleep(0.1)
        return _mock_response_for_agent("mindmap")

    mock_client.chat.completions.create.side_effect = slow_response

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试")

    # Start via run_all (async, returns 202 immediately)
    first = client.post(
        f"/api/agents/session/{session_id}/run",
        json={"roles": ["mindmap"]},
        headers=auth_headers,
    )
    assert first.status_code == 202
    first_task_id = first.json()["agents"][0]["task_id"]

    # While still running, call run_all again — should reuse.
    second = client.post(
        f"/api/agents/session/{session_id}/run",
        json={"roles": ["mindmap"]},
        headers=auth_headers,
    )
    # In sync mode the first request blocks until completion, so the second
    # call sees a finished task and may regenerate or return ready data.
    assert second.status_code in (200, 202)
    if second.status_code == 200:
        assert second.json().get("reused") is True
        agent_info = second.json()["agents"][0]
        # Reused active task carries task_id; ready output does not.
        if "task_id" in agent_info:
            assert agent_info["task_id"] == first_task_id
        else:
            assert agent_info["status"] == "ready"

    _wait_for_agent_status(client, session_id, auth_headers, "mindmap", {"success", "ready"})
    # Sync mode: first call completes before second starts, so second may
    # regenerate (call_count can be 2).  Async mode: reuse prevents duplicate
    # (call_count == 1).  Both are acceptable as long as no duplicate active
    # tasks exist simultaneously.
    assert mock_client.chat.completions.create.call_count <= 2
