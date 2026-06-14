import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.database import SessionLocal
from app.main import app
from app.models import User


def auth_headers(client: TestClient, email: str = "admin", password: str = "admin123") -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": "http://localhost:5173",
    }


def _create_user(email: str, username: str, password: str = "other1234") -> None:
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == email).first():
            db.add(User(username=username, email=email, password_hash=hash_password(password)))
            db.commit()
    finally:
        db.close()


def _create_notebook_session(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    nb = client.post("/api/notebooks", json={"title": "RAG Test Notebook"}, headers=headers)
    assert nb.status_code == 201, nb.text
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "RAG Test Session", "keywords": ["rag"]},
        headers=headers,
    )
    assert sess.status_code == 201, sess.text
    return notebook_id, sess.json()["id"]


def test_rag_session_scope_validates_owner_without_session_user_id():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, headers)

        with patch("app.api.rag.vector_service.search_vectors", return_value=[]), patch(
            "app.api.rag._call_llm_stream",
            return_value=iter(()),
        ):
            resp = client.post(
                "/api/rag/ask",
                json={"query": "这节课讲了什么？", "session_id": session_id},
                headers=headers,
            )

        assert resp.status_code == 200, resp.text


def test_rag_rejects_other_users_session():
    with TestClient(app) as client:
        admin_headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, admin_headers)

        _create_user("rag-other@example.com", "rag-other")
        other_headers = auth_headers(client, "rag-other@example.com", "other1234")

        resp = client.post(
            "/api/rag/ask",
            json={"query": "这节课讲了什么？", "session_id": session_id},
            headers=other_headers,
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"


def test_rag_rejects_other_users_notebook():
    with TestClient(app) as client:
        admin_headers = auth_headers(client)
        notebook_id, _ = _create_notebook_session(client, admin_headers)

        _create_user("rag-reader@example.com", "rag-reader")
        other_headers = auth_headers(client, "rag-reader@example.com", "other1234")

        resp = client.post(
            "/api/rag/ask",
            json={"query": "这门课有哪些重点？", "notebook_id": notebook_id},
            headers=other_headers,
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Notebook not found"


# -- Source attribution & streaming structure --

def test_rag_returns_source_cards_in_sse():
    """RAG SSE stream must include sources event with chunk metadata."""
    mock_results = [
        {
            "chunk_id": "chunk-1",
            "notebook_id": "nb-1",
            "notebook_title": "Test NB",
            "session_id": "sess-1",
            "session_title": "Test Session",
            "source_type": "transcript",
            "snippet": "单例模式确保只有一个实例",
            "score": 0.95,
            "metadata": {"chunk_index": 0},
        },
        {
            "chunk_id": "chunk-2",
            "notebook_id": "nb-1",
            "notebook_title": "Test NB",
            "session_id": "sess-1",
            "session_title": "Test Session",
            "source_type": "ppt",
            "snippet": "PPT: 设计模式概览",
            "score": 0.88,
            "metadata": {"page": 3, "block_type": "ppt"},
        },
    ]

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, headers)

        with patch("app.api.rag.vector_service.search_vectors", return_value=mock_results), patch(
            "app.api.rag._call_llm_stream",
            return_value=iter(()),
        ):
            resp = client.post(
                "/api/rag/ask",
                json={"query": "单例模式是什么？", "session_id": session_id, "top_k": 5},
                headers=headers,
            )

        assert resp.status_code == 200, resp.text
        # Parse SSE events
        lines = [line for line in resp.text.split("\n") if line.startswith("data: ")]
        events = [json.loads(line[6:]) for line in lines]
        event_types = [e["type"] for e in events]

        assert "status" in event_types
        assert "sources" in event_types
        assert "done" in event_types

        sources_event = [e for e in events if e["type"] == "sources"][0]
        sources = sources_event["sources"]
        assert len(sources) == 2
        assert sources[0]["source_type"] == "transcript"
        assert sources[0]["snippet"] == "单例模式确保只有一个实例"
        assert sources[1]["source_type"] == "ppt"
        assert sources[1]["page"] == 3


def test_rag_top_k_boundary():
    """top_k must be rejected when outside [1, 50]."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, headers)

        resp = client.post(
            "/api/rag/ask",
            json={"query": "test", "session_id": session_id, "top_k": 0},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "top_k" in resp.json()["detail"].lower()

        resp = client.post(
            "/api/rag/ask",
            json={"query": "test", "session_id": session_id, "top_k": 51},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "top_k" in resp.json()["detail"].lower()

        resp = client.post(
            "/api/rag/ask",
            json={"query": "test", "session_id": session_id, "top_k": 50},
            headers=headers,
        )
        assert resp.status_code == 200


def test_rag_empty_query_rejected():
    """Empty query must return 400."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, headers)

        resp = client.post(
            "/api/rag/ask",
            json={"query": "   ", "session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()


def test_rag_streaming_llm_chunks():
    """LLM chunks should be streamed as individual SSE events."""
    mock_results = []
    mock_chunks = [
        json.dumps({"type": "chunk", "text": "单例模式"}, ensure_ascii=False),
        json.dumps({"type": "chunk", "text": "是一种设计模式"}, ensure_ascii=False),
    ]

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session(client, headers)

        with patch("app.api.rag.vector_service.search_vectors", return_value=mock_results), patch(
            "app.api.rag._call_llm_stream",
            return_value=(f"data: {c}\n\n" for c in mock_chunks),
        ):
            resp = client.post(
                "/api/rag/ask",
                json={"query": "什么是单例模式？", "session_id": session_id},
                headers=headers,
            )

        assert resp.status_code == 200
        lines = [line for line in resp.text.split("\n") if line.startswith("data: ")]
        events = [json.loads(line[6:]) for line in lines]
        chunk_events = [e for e in events if e["type"] == "chunk"]
        assert len(chunk_events) == 2
        assert chunk_events[0]["text"] == "单例模式"
        assert chunk_events[1]["text"] == "是一种设计模式"
