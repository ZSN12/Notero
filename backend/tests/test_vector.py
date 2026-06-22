import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

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


def _create_other_user(email: str, username: str, password: str = "other1234") -> None:
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
    """Create notebook + session + note with content. Returns (notebook_id, session_id)."""
    nb = client.post("/api/notebooks", json={"title": "Vector Test NB"}, headers=headers)
    assert nb.status_code == 201
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "Vector Test Session", "summary": "Testing vector search", "keywords": ["vector", "search"]},
        headers=headers,
    )
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    # Create a note with content via PUT /api/notes/session/{session_id}
    note = client.put(
        f"/api/notes/session/{session_id}",
        json={
            "content": "## 语音转文字\n\n设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。观察者模式用于对象间的一对多依赖关系。\n\n---\n\n随堂笔记：今天学习了设计模式的基本概念。",
            "layout_blocks": [
                {"id": "t1", "type": "transcript", "content": "设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。观察者模式用于对象间的一对多依赖关系。"},
                {"id": "n1", "type": "note", "content": "随堂笔记：今天学习了设计模式的基本概念。"}
            ]
        },
        headers=headers,
    )
    assert note.status_code == 200, note.text

    return notebook_id, session_id


def test_rebuild_session_index():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Status should be not_indexed
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_indexed"

        # Rebuild
        resp = client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunk_count"] > 0
        assert data["status"] == "indexed"

        # Status should now be indexed
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indexed"
        assert resp.json()["chunk_count"] > 0


def test_rebuild_replaces_old_chunks():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # First rebuild
        resp1 = client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)
        assert resp1.status_code == 200
        count1 = resp1.json()["chunk_count"]

        # Second rebuild - should replace, not duplicate
        resp2 = client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)
        assert resp2.status_code == 200
        count2 = resp2.json()["chunk_count"]

        assert count1 == count2  # Same content, same chunk count


def test_search_returns_relevant_results():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Build index
        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Search for "设计模式"
        resp = client.post("/api/vector/search", json={"query": "设计模式"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        # Results should be sorted by score descending
        scores = [r["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)


def test_search_with_session_filter():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Search scoped to session
        resp = client.post("/api/vector/search", json={"query": "设计模式", "session_id": session_id}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

        # Search scoped to non-existent session
        resp = client.post("/api/vector/search", json={"query": "设计模式", "session_id": "nonexistent"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


def test_cannot_index_others_session():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Create another user directly in DB (bypass rate limit)
        _create_other_user("other_vec@example.com", "Other", "other1234")
        other_resp = client.post(
            "/api/auth/login",
            json={"email": "other_vec@example.com", "password": "other1234"},
        )
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        # Other user tries to rebuild index
        resp = client.post(f"/api/vector/session/{session_id}/rebuild", headers=other_headers)
        assert resp.status_code == 404


def test_cannot_search_others_content():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Create another user directly in DB (bypass rate limit)
        _create_other_user("other2_vec@example.com", "Other2", "other21234")
        other_resp = client.post(
            "/api/auth/login",
            json={"email": "other2_vec@example.com", "password": "other21234"},
        )
        assert other_resp.status_code == 200, other_resp.text
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        # Other user searches - should get 0 results (their own chunks are empty)
        resp = client.post("/api/vector/search", json={"query": "设计模式"}, headers=other_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


def test_rebuild_notebook_index():
    with TestClient(app) as client:
        headers = auth_headers(client)
        notebook_id, _ = _create_notebook_session_note(client, headers)

        resp = client.post(f"/api/vector/notebook/{notebook_id}/rebuild", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["chunk_count"] > 0
        assert resp.json()["status"] == "indexed"


def test_empty_query_returns_nothing():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        resp = client.post("/api/vector/search", json={"query": ""}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── Stale detection tests ──

def test_status_indexed_after_rebuild():
    """After rebuild, status should be 'indexed'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indexed"


def test_status_stale_after_content_change():
    """Modifying note content should make status 'stale'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Build index
        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Verify indexed
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "indexed"

        # Modify note content
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "content": "## 语音转文字\n\n全新的内容，和之前完全不同。策略模式定义了一系列算法。",
                "layout_blocks": [
                    {"id": "t1", "type": "transcript", "content": "全新的内容，和之前完全不同。策略模式定义了一系列算法。"}
                ]
            },
            headers=headers,
        )

        # Status should now be stale
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "stale"


def test_status_back_to_indexed_after_rebuild():
    """Rebuilding after stale should bring status back to 'indexed'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Build index
        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

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

        # Should be stale
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "stale"

        # Rebuild
        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Should be indexed again
        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "indexed"


def test_status_stale_after_layout_blocks_change():
    """Changing layout_blocks should make status 'stale'."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        # Build index
        client.post(f"/api/vector/session/{session_id}/rebuild", headers=headers)

        # Change layout_blocks (add a new note block)
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "content": "## 语音转文字\n\n设计模式是软件工程中常用的解决方案。\n\n---\n\n新增的随堂笔记",
                "layout_blocks": [
                    {"id": "t1", "type": "transcript", "content": "设计模式是软件工程中常用的解决方案。"},
                    {"id": "n1", "type": "note", "content": "随堂笔记：今天学习了设计模式的基本概念。"},
                    {"id": "n2", "type": "note", "content": "新增的随堂笔记"}
                ]
            },
            headers=headers,
        )

        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "stale"


def test_empty_note_status():
    """Session without note should be 'empty' or 'not_indexed'."""
    with TestClient(app) as client:
        headers = auth_headers(client)

        # Create notebook + session but NO note
        nb = client.post("/api/notebooks", json={"title": "Empty NB"}, headers=headers)
        notebook_id = nb.json()["id"]
        sess = client.post(
            f"/api/sessions?notebook_id={notebook_id}",
            json={"title": "Empty Session"},
            headers=headers,
        )
        session_id = sess.json()["id"]

        resp = client.get(f"/api/vector/session/{session_id}/status", headers=headers)
        assert resp.json()["status"] == "empty"


# ── Unit tests for vector helper functions ──

def test_neural_bytes_to_list_unpacks_float32():
    """_neural_bytes_to_list should unpack packed float32 bytes."""
    from app.services.vector_service import _neural_bytes_to_list, EMBEDDING_DIM
    import struct

    vec = [float(i) for i in range(EMBEDDING_DIM)]
    packed = struct.pack(f"{EMBEDDING_DIM}f", *vec)
    assert _neural_bytes_to_list(packed) == vec


def test_neural_bytes_to_list_returns_none_for_wrong_length():
    """_neural_bytes_to_list should return None for malformed bytes."""
    from app.services.vector_service import _neural_bytes_to_list

    assert _neural_bytes_to_list(b"\x00\x00") is None
    assert _neural_bytes_to_list(None) is None
    assert _neural_bytes_to_list(b"") is None
