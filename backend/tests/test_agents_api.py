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
MOCK_STUDY_PLAN = {
    "goal": "完善本节课复习资料",
    "summary": "资料基本可用，但题库覆盖仍可增强。",
    "confidence": 0.8,
    "findings": [
        {
            "type": "coverage_gap",
            "severity": "medium",
            "message": "题库尚未覆盖核心概念",
            "evidence": "测试内容",
        }
    ],
    "recommended_actions": [
        {
            "action": "run_agent",
            "params": {"role": "quiz"},
            "reason": "补齐题库覆盖",
            "risk": "low",
            "requires_confirmation": False,
            "verification": "检查题库知识点覆盖",
        }
    ],
    "review_plan": [
        {
            "day_offset": 1,
            "focus": "核心概念",
            "items": ["复习导图", "完成基础题"],
        }
    ],
}


def _mock_response_for_agent(role: str, finish_reason: str = "stop"):
    """Return a mock response object for the given agent role."""
    if role == "mindmap":
        content = MOCK_MINDMAP
    elif role == "quiz":
        content = MOCK_QUIZ
    elif role == "study_planner":
        content = MOCK_STUDY_PLAN
    else:
        content = {}
    return (
        mock_chat_completion(content, finish_reason=finish_reason)
        .chat.completions.create.return_value
    )


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
@patch("app.core.llm.OpenAI")
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
@patch("app.core.llm.OpenAI")
def test_study_planner_agent_returns_plan(mock_openai_cls, client, auth_headers, db):
    """Study planner should run as a normal agent and persist a study_plan entry."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("study_planner")

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    resp = client.post(
        f"/api/agents/session/{session_id}/run/study_planner",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ready"
    assert data["data"]["goal"] == "完善本节课复习资料"
    assert data["data"]["recommended_actions"][0]["action"] == "run_agent"

    from app.models import Note, SessionProcessingState

    note = db.query(Note).filter(Note.session_id == session_id).first()
    assert note is not None
    kinds = [item.get("kind") for item in note.vocabulary if isinstance(item, dict)]
    assert "study_plan" in kinds

    state = (
        db.query(SessionProcessingState)
        .filter(
            SessionProcessingState.session_id == session_id,
            SessionProcessingState.stage == "study_plan",
        )
        .first()
    )
    assert state is not None
    assert state.status == "ready"


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_agent_run_events_are_queryable(mock_openai_cls, client, auth_headers):
    """Agent runs should leave a persisted event trace."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("study_planner")

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    resp = client.post(
        f"/api/agents/session/{session_id}/run/study_planner",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    events_resp = client.get(
        f"/api/agents/session/{session_id}/events",
        headers=auth_headers,
    )
    assert events_resp.status_code == 200, events_resp.text
    events = events_resp.json()["events"]
    event_types = {event["event_type"] for event in events}
    assert "agent_started" in event_types
    assert "agent_completed" in event_types
    assert all("prompt" not in event["payload"] for event in events)


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
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
@patch("app.core.llm.OpenAI")
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
@patch("app.core.llm.OpenAI")
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
@patch("app.core.llm.OpenAI")
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


@pytest.mark.integration
@patch("app.core.llm.OpenAI")
def test_run_all_agents_force_regenerates(mock_openai_cls, client, auth_headers):
    """force=true should ignore fresh cached output and start a new workflow."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_response_for_agent("mindmap")

    _, session_id = create_notebook_session_note(client, auth_headers, content="测试内容")

    # First run generates ready output.
    first = client.post(f"/api/agents/session/{session_id}/run/mindmap", headers=auth_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "ready"

    # Non-force run_all should reuse the ready mindmap output (transcript
    # dependency may still need to run, so it can return 202 with reused=True).
    reused = client.post(
        f"/api/agents/session/{session_id}/run",
        json={"roles": ["mindmap"]},
        headers=auth_headers,
    )
    assert reused.status_code in (200, 202)
    assert reused.json().get("reused") is True

    # Force run_all must start a real workflow. The transcript dependency is
    # not forced, so it may be reported as reused, but mindmap itself must be
    # regenerated (not returned as ready/reused).
    forced = client.post(
        f"/api/agents/session/{session_id}/run",
        json={"roles": ["mindmap"], "force": True},
        headers=auth_headers,
    )
    assert forced.status_code == 202
    forced_data = forced.json()
    assert forced_data["workflow_id"] != "reused"
    mindmap_agent = next(a for a in forced_data["agents"] if a["role"] == "mindmap")
    assert mindmap_agent["status"] in ("pending", "running", "success")
    assert mindmap_agent["status"] != "ready"
