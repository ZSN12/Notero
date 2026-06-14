"""Tests for the multi-agent API endpoints."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-agents"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Note, User
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


def _create_notebook_session_note(client: TestClient, headers: dict):
    """Create notebook + session + note with content."""
    nb = client.post("/api/notebooks", json={"title": "Agent Test NB"}, headers=headers)
    assert nb.status_code == 201
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "Agent Test Session", "keywords": ["test"]},
        headers=headers,
    )
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    client.put(
        f"/api/notes/session/{session_id}",
        json={
            "content": "今天我们学习了单例模式和工厂模式。单例模式确保一个类只有一个实例。",
        },
        headers=headers,
    )

    return notebook_id, session_id


def _mock_openai_response(data: dict):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(data)
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client
