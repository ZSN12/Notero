import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-mindmap"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import User
from app.core.auth import hash_password


def auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": "http://localhost:5173",
    }


def _create_other_user(email: str, username: str, password: str = "other12345") -> None:
    """Directly create a user in DB to bypass rate-limited registration API."""
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == email).first():
            user = User(username=username, email=email, password_hash=hash_password(password))
            db.add(user)
            db.commit()
    finally:
        db.close()

def _create_notebook_session_note(client: TestClient, headers: dict):
    """Create notebook + session + note with content."""
    nb = client.post("/api/notebooks", json={"title": "MindMap Test NB"}, headers=headers)
    assert nb.status_code == 201
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "MindMap Test Session", "summary": "Testing mind map", "keywords": ["design", "patterns"]},
        headers=headers,
    )
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    client.put(
        f"/api/notes/session/{session_id}",
        json={
            "content": "## 语音转文字\n\n设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。",
            "layout_blocks": [
                {"id": "t1", "type": "transcript", "content": "设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。"}
            ]
        },
        headers=headers,
    )

    return notebook_id, session_id


def _wait_for_mindmap_status(client: TestClient, session_id: str, headers: dict, expected: set[str], timeout: float = 5.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in expected:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {expected}, last={last}")


MOCK_MINDMAP_RESPONSE = {
    "title": "设计模式",
    "summary": "本节课介绍了软件设计模式的基本概念",
    "nodes": [
        {
            "id": "node-1",
            "title": "设计模式概述",
            "description": "设计模式是软件工程中常用的解决方案",
            "type": "concept",
            "importance": "high",
            "sources": [{"source_type": "transcript", "snippet": "设计模式是软件工程中常用的解决方案", "page": None, "block_id": "t1"}],
            "children": []
        }
    ],
    "relations": []
}


def test_get_mindmap_empty():
    """Session without note content returns 'empty'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        nb = client.post("/api/notebooks", json={"title": "Empty NB"}, headers=headers)
        sess = client.post(
            f"/api/sessions?notebook_id={nb.json()['id']}",
            json={"title": "Empty Session"},
            headers=headers,
        )
        session_id = sess.json()["id"]

        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "empty"


def test_get_mindmap_not_generated():
    """Session with content but no mind map returns 'not_generated'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_generated"


@patch("app.core.llm.OpenAI")
def test_generate_mind_map_success(mock_openai_cls):
    """Generate mind map with mocked DeepSeek returns 'ready'."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    import json
    mock_response.choices[0].message.content = json.dumps(MOCK_MINDMAP_RESPONSE)
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Generate
        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        assert resp.json()["status"] == "generating"
        assert resp.json()["task_id"]

        # GET should now return ready
        data = _wait_for_mindmap_status(client, session_id, headers, {"ready"})
        assert data["status"] == "ready"
        assert data["mind_map"]["title"] == "设计模式"


@patch("app.core.llm.OpenAI")
def test_generate_mind_map_reuses_running_task(mock_openai_cls):
    """Repeated generate requests while running should reuse the active task."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(MOCK_MINDMAP_RESPONSE)

    def slow_response(*args, **kwargs):
        time.sleep(0.25)
        return mock_response

    mock_client.chat.completions.create.side_effect = slow_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        first = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        second = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["task_id"] == second.json()["task_id"]

        _wait_for_mindmap_status(client, session_id, headers, {"ready"})
        assert mock_client.chat.completions.create.call_count == 1


@patch("app.core.llm.OpenAI")
def test_mind_map_stale_after_content_change(mock_openai_cls):
    """After modifying note content, status should be 'stale'."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(MOCK_MINDMAP_RESPONSE)
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Generate
        client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        _wait_for_mindmap_status(client, session_id, headers, {"ready"})

        # Modify content
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "content": "## 语音转文字\n\n全新的内容，和之前完全不同。",
                "layout_blocks": [
                    {"id": "t1", "type": "transcript", "content": "全新的内容，和之前完全不同。"}
                ]
            },
            headers=headers,
        )

        # Should be stale
        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.json()["status"] == "stale"


@patch("app.core.llm.OpenAI")
def test_mind_map_ready_after_regenerate(mock_openai_cls):
    """Regenerating after stale returns 'ready'."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(MOCK_MINDMAP_RESPONSE)
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Generate
        client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        _wait_for_mindmap_status(client, session_id, headers, {"ready"})

        # Modify content
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "content": "## 语音转文字\n\n修改后的内容。",
                "layout_blocks": [
                    {"id": "t1", "type": "transcript", "content": "修改后的内容。"}
                ]
            },
            headers=headers,
        )

        # Regenerate
        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        data = _wait_for_mindmap_status(client, session_id, headers, {"ready"})
        assert data["status"] == "ready"


@patch("app.core.llm.OpenAI")
def test_delete_mind_map(mock_openai_cls):
    """Delete mind map returns to 'not_generated'."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(MOCK_MINDMAP_RESPONSE)
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Generate
        client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        _wait_for_mindmap_status(client, session_id, headers, {"ready"})

        # Delete
        resp = client.delete(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.status_code == 200

        # Should be not_generated
        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "not_generated"


def test_cannot_access_others_mindmap():
    """Non-owner cannot access mind map."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Create another user directly in DB (bypass rate limit)
        _create_other_user("other_mm@example.com", "OtherMM", "other12345")
        other_resp = client.post(
            "/api/auth/login",
            json={"email": "other_mm@example.com", "password": "other12345"},
        )
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        resp = client.get(f"/api/mindmap/session/{session_id}", headers=other_headers)
        assert resp.status_code == 404

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=other_headers)
        assert resp.status_code == 404

        resp = client.delete(f"/api/mindmap/session/{session_id}", headers=other_headers)
        assert resp.status_code == 404


@patch("app.core.llm.OpenAI")
def test_invalid_json_from_ai(mock_openai_cls):
    """AI returning invalid JSON should result in generation failure."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is not valid JSON {{{"
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        data = _wait_for_mindmap_status(client, session_id, headers, {"error"})
        assert "JSON" in data["error"]


def test_no_api_key_returns_error():
    """Without DEEPSEEK_API_KEY, generate should return 503."""
    with patch("app.services.mindmap_service.DEEPSEEK_API_KEY", ""):
        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
            assert resp.status_code == 503


@patch("app.core.llm.OpenAI")
def test_invalid_nodes_type_rejected(mock_openai_cls):
    """AI returning {"nodes": "bad"} should be rejected, not saved."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"title": "test", "nodes": "bad_string"}'
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        _wait_for_mindmap_status(client, session_id, headers, {"error"})

        # Should not be saved, while the failed task remains visible for retry UX.
        resp = client.get(f"/api/mindmap/session/{session_id}", headers=headers)
        assert resp.json()["status"] == "error"
        assert resp.json()["mind_map"] is None


@patch("app.core.llm.OpenAI")
def test_nodes_missing_id_title_dropped(mock_openai_cls):
    """Nodes without id or title should be dropped; all bad nodes = rejection."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "title": "test",
        "nodes": [
            {"description": "no id no title"},
            {"id": "n1"},  # missing title
            {"title": "no id"},  # missing id
        ]
    })
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        _wait_for_mindmap_status(client, session_id, headers, {"error"})


@patch("app.core.llm.OpenAI")
def test_missing_fields_filled_with_defaults(mock_openai_cls):
    """Nodes with missing type/importance should get defaults after normalization."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "title": "Test",
        "summary": "Summary",
        "nodes": [
            {
                "id": "n1",
                "title": "Node 1",
                "description": "Desc",
                "sources": [],
                "children": []
            }
        ]
    })
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        data = _wait_for_mindmap_status(client, session_id, headers, {"ready"})
        node = data["mind_map"]["nodes"][0]
        assert node["type"] == "concept"  # default
        assert node["importance"] == "medium"  # default


@patch("app.core.llm.OpenAI")
def test_deepseek_network_error_returns_502(mock_openai_cls):
    """DeepSeek network/timeout error should result in 502, not 500."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("Request timed out: connection timeout")

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        data = _wait_for_mindmap_status(client, session_id, headers, {"error"})
        assert "超时" in data["error"]


@patch("app.core.llm.OpenAI")
def test_deepseek_generic_error_returns_502(mock_openai_cls):
    """DeepSeek generic API error should result in 502."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API server error")

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/mindmap/session/{session_id}/generate", headers=headers)
        assert resp.status_code == 202
        data = _wait_for_mindmap_status(client, session_id, headers, {"error"})
        assert "失败" in data["error"]
