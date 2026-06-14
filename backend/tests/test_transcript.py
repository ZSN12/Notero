"""Tests for transcript update and restructure endpoints."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, PropertyMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["DEEPSEEK_API_KEY"] = "test-key"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Notebook, Session as DBSession, Note
from app.services.term_corrector import corrector


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


def _create_session_with_note(db, user_id: str, title="Test Session", transcript=None, content=None):
    notebook = Notebook(title="Test NB", user_id=user_id)
    db.add(notebook)
    db.commit()
    db.refresh(notebook)

    session = DBSession(notebook_id=notebook.id, title=title, keywords=["test"])
    db.add(session)
    db.commit()
    db.refresh(session)

    note = Note(session_id=session.id, content=content, transcript=transcript)
    db.add(note)
    db.commit()

    return session.id


class TestUpdateTranscript:
    def test_update_transcript_success(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                sid = _create_session_with_note(db, user_id, transcript=[{"text": "hello"}])
            finally:
                db.close()

            resp = client.put(
                "/api/process/transcript",
                params={"session_id": sid},
                json={"content": '[{"text": "updated"}]'},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"

    def test_update_transcript_missing_session(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.put("/api/process/transcript", params={"session_id": ""}, json={"content": "[]"}, headers=headers)
            assert resp.status_code == 400

    def test_update_transcript_not_found(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.put(
                "/api/process/transcript",
                params={"session_id": "00000000-0000-0000-0000-000000000000"},
                json={"content": "[]"},
                headers=headers,
            )
            assert resp.status_code == 404


class TestRestructureTranscript:
    def test_restructure_no_transcript(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                sid = _create_session_with_note(db, user_id, transcript=None)
            finally:
                db.close()

            resp = client.post(f"/api/process/session/{sid}/restructure", headers=headers)
            assert resp.status_code == 400

    def test_restructure_success_local_fallback(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                sid = _create_session_with_note(
                    db, user_id, transcript=[{"text": "hello world", "raw_text": "hello world", "display_text": "hello world"}]
                )
            finally:
                db.close()

            with patch.object(type(corrector), "has_llm", new_callable=PropertyMock, return_value=False):
                resp = client.post(f"/api/process/session/{sid}/restructure", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert "note" in data
                assert data["note"]["transcript"][0]["correction_error"] == "AI 整理失败，已使用本地整理稿"

    def test_restructure_empty_text(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                sid = _create_session_with_note(db, user_id, transcript=[{"text": "", "raw_text": ""}])
            finally:
                db.close()

            resp = client.post(f"/api/process/session/{sid}/restructure", headers=headers)
            assert resp.status_code == 400
