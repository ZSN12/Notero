import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from tests.harness.helpers import (
    auth_headers,
    create_notebook_and_session,
    create_other_user,
)


def test_rag_session_scope_validates_owner_without_session_user_id(client: TestClient):
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

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


def test_rag_rejects_other_users_session(client: TestClient, db):
    admin_headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, admin_headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

    create_other_user(db, "rag-other@example.com", "rag-other")
    other_headers = auth_headers(client, "rag-other@example.com", "other1234")

    resp = client.post(
        "/api/rag/ask",
        json={"query": "这节课讲了什么？", "session_id": session_id},
        headers=other_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Session not found"


def test_rag_rejects_other_users_notebook(client: TestClient, db):
    admin_headers = auth_headers(client)
    notebook_id, _ = create_notebook_and_session(
        client, admin_headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

    create_other_user(db, "rag-reader@example.com", "rag-reader")
    other_headers = auth_headers(client, "rag-reader@example.com", "other1234")

    resp = client.post(
        "/api/rag/ask",
        json={"query": "这门课有哪些重点？", "notebook_id": notebook_id},
        headers=other_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Notebook not found"


# -- Source attribution & streaming structure --

def test_rag_returns_source_cards_in_sse(client: TestClient):
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

    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

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


def test_rag_top_k_boundary(client: TestClient):
    """top_k must be rejected when outside [1, 50]."""
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

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


def test_rag_empty_query_rejected(client: TestClient):
    """Empty query must return 400."""
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

    resp = client.post(
        "/api/rag/ask",
        json={"query": "   ", "session_id": session_id},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_rag_streaming_llm_chunks(client: TestClient):
    """LLM chunks should be streamed as individual SSE events."""
    mock_results = []
    mock_chunks = [
        json.dumps({"type": "chunk", "text": "单例模式"}, ensure_ascii=False),
        json.dumps({"type": "chunk", "text": "是一种设计模式"}, ensure_ascii=False),
    ]

    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="RAG Test Notebook", session_title="RAG Test Session", keywords=["rag"]
    )

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
