"""Tests for notebook import/export roundtrip."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Notebook, Session as DBSession, Note


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


class TestNotebookExportImport:
    def test_export_empty_notebook(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                nb = Notebook(title="Export Test", user_id=user_id)
                db.add(nb)
                db.commit()
                db.refresh(nb)
                nb_id = nb.id
            finally:
                db.close()

            resp = client.get(f"/api/notebooks/{nb_id}/export", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["format_version"] == 2
            assert data["notebook"]["title"] == "Export Test"
            assert data["sessions"] == []

    def test_export_with_sessions(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                nb = Notebook(title="Export With Sessions", user_id=user_id)
                db.add(nb)
                db.commit()
                db.refresh(nb)

                s1 = DBSession(notebook_id=nb.id, title="S1", keywords=["k1"])
                db.add(s1)
                db.commit()
                db.refresh(s1)

                note = Note(session_id=s1.id, content="Note content", transcript=[{"text": "hi"}])
                db.add(note)
                db.commit()

                nb_id = nb.id
            finally:
                db.close()

            resp = client.get(f"/api/notebooks/{nb_id}/export", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["title"] == "S1"
            assert data["sessions"][0]["content"] == "Note content"

    def test_import_roundtrip(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            payload = {
                "format_version": 2,
                "notebook": {
                    "title": "Imported NB",
                    "description": "desc",
                    "icon": "BookOpen",
                    "color": "#123456",
                },
                "sessions": [
                    {
                        "title": "Session A",
                        "keywords": ["kw1", "kw2"],
                        "content": "Content A",
                        "transcript": [{"text": "hello"}],
                        "ppt_images": None,
                        "layout_blocks": None,
                    }
                ],
            }
            resp = client.post("/api/notebooks/import", json=payload, headers=headers)
            assert resp.status_code == 201
            data = resp.json()
            assert data["title"] == "Imported NB"
            assert data["session_count"] == 1

    def test_import_unsupported_version(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            payload = {
                "format_version": 99,
                "notebook": {"title": "Bad"},
                "sessions": [],
            }
            resp = client.post("/api/notebooks/import", json=payload, headers=headers)
            assert resp.status_code == 400

    def test_import_v1_accepted(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            payload = {
                "format_version": 1,
                "notebook": {"title": "V1 NB"},
                "sessions": [],
            }
            resp = client.post("/api/notebooks/import", json=payload, headers=headers)
            assert resp.status_code == 201


class TestNotebookCRUD:
    def test_list_notebooks(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.get("/api/notebooks", headers=headers)
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_get_notebook_404(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.get("/api/notebooks/nonexistent-id", headers=headers)
            assert resp.status_code == 404

    def test_update_notebook(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                nb = Notebook(title="Update Me", user_id=user_id)
                db.add(nb)
                db.commit()
                db.refresh(nb)
                nb_id = nb.id
            finally:
                db.close()

            resp = client.put(
                f"/api/notebooks/{nb_id}",
                json={"title": "Updated Title"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["title"] == "Updated Title"

    def test_update_notebook_404(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.put(
                "/api/notebooks/nonexistent-id",
                json={"title": "X"},
                headers=headers,
            )
            assert resp.status_code == 404

    def test_delete_notebook(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                nb = Notebook(title="Delete Me", user_id=user_id)
                db.add(nb)
                db.commit()
                db.refresh(nb)
                nb_id = nb.id
            finally:
                db.close()

            resp = client.delete(f"/api/notebooks/{nb_id}", headers=headers)
            assert resp.status_code == 204

    def test_delete_notebook_404(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.delete("/api/notebooks/nonexistent-id", headers=headers)
            assert resp.status_code == 404

    def test_export_notebook_404(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            resp = client.get("/api/notebooks/nonexistent-id/export", headers=headers)
            assert resp.status_code == 404

    def test_export_notebook_session_without_note(self):
        with TestClient(app) as client:
            headers = auth_headers(client)
            me = client.get("/api/auth/me", headers=headers)
            user_id = me.json()["id"]
            db = SessionLocal()
            try:
                nb = Notebook(title="Export No Note", user_id=user_id)
                db.add(nb)
                db.commit()
                db.refresh(nb)

                s1 = DBSession(notebook_id=nb.id, title="S1", keywords=[])
                db.add(s1)
                db.commit()
                nb_id = nb.id
            finally:
                db.close()

            resp = client.get(f"/api/notebooks/{nb_id}/export", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["content"] is None
            assert data["sessions"][0]["transcript"] is None
