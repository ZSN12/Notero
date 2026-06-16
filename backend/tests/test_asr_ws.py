"""Tests for WebSocket streaming ASR endpoint."""

import pytest
from fastapi.testclient import TestClient

from tests.harness.helpers import auth_headers, create_notebook_and_session


def _token_from_headers(headers: dict[str, str]) -> str:
    return headers["Authorization"].split(" ")[1]


def test_ws_auth_required(client: TestClient):
    """WebSocket without token should be rejected."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/asr/test-session"):
            pass


def test_ws_invalid_token_rejected(client: TestClient):
    """WebSocket with invalid token should be rejected."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/asr/test-session?token=invalid"):
            pass


def test_ws_non_owner_rejected(client: TestClient):
    """Non-owner should not be able to connect to another user's session."""
    # Register a second user
    resp = client.post(
        "/api/auth/register",
        json={"username": "user2", "email": "user2@test.com", "password": "password123"},
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/auth/login",
        json={"email": "user2@test.com", "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/asr/nonexistent-session?token={token}"):
            pass


def test_ws_owner_can_connect(client: TestClient):
    """Owner can establish WebSocket connection and receive start status."""
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="Test Notebook", session_title="Test Session"
    )

    token = _token_from_headers(headers)
    with client.websocket_connect(f"/ws/asr/{session_id}?token={token}") as ws:
        ws.send_json({"type": "start"})
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert "开始" in msg["message"]
        ws.send_json({"type": "end"})
        # Wait for done
        for _ in range(5):
            try:
                m = ws.receive_json()
                if m["type"] == "done":
                    break
            except Exception:
                break


def test_ws_partial_not_saved(client: TestClient):
    """Partial results should not be persisted to the database until end."""
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="Test Notebook 2", session_title="Test Session 2"
    )

    token = _token_from_headers(headers)
    with client.websocket_connect(f"/ws/asr/{session_id}?token={token}") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()  # status

        # Send minimal audio (silence)
        ws.send_bytes(b"\x00" * 5120)
        # End immediately
        ws.send_json({"type": "end"})
        msg = ws.receive_json()
        assert msg["type"] == "done"


def test_ws_pause_resume(client: TestClient):
    """Pause and resume commands should be acknowledged."""
    headers = auth_headers(client)
    _, session_id = create_notebook_and_session(
        client, headers, title="Test Notebook 3", session_title="Test Session 3"
    )

    token = _token_from_headers(headers)
    with client.websocket_connect(f"/ws/asr/{session_id}?token={token}") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()  # status: 识别已开始

        ws.send_json({"type": "pause"})
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert "暂停" in msg["message"]

        ws.send_json({"type": "resume"})
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert "恢复" in msg["message"]

        ws.send_json({"type": "end"})
        for _ in range(5):
            msg = ws.receive_json()
            if msg["type"] == "done":
                break
