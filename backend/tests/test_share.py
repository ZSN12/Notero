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


def _create_other_user(email: str, username: str, password: str = "other123") -> None:
    """Directly create a user in DB to bypass rate-limited registration API."""
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == email).first():
            user = User(username=username, email=email, password_hash=hash_password(password))
            db.add(user)
            db.commit()
    finally:
        db.close()

def _create_notebook_and_session(client: TestClient, headers: dict):
    """Helper: create a notebook and session, return (notebook_id, session_id)."""
    nb_resp = client.post("/api/notebooks", json={"title": "Test Notebook"}, headers=headers)
    assert nb_resp.status_code == 201, nb_resp.text
    notebook_id = nb_resp.json()["id"]

    sess_resp = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "Test Session", "summary": "A test summary", "keywords": ["test", "share"]},
        headers=headers,
    )
    assert sess_resp.status_code == 201, sess_resp.text
    session_id = sess_resp.json()["id"]

    return notebook_id, session_id


# -- Share enable / disable / status --

def test_share_enable_generates_token():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        # Enable share
        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["share_enabled"] is True
        assert len(data["share_token"]) > 0
        assert f"token={data['share_token']}" in data["share_url"]

        # Check status
        resp = client.get(f"/api/sessions/{session_id}/share/status", headers=headers)
        assert resp.status_code == 200
        status = resp.json()
        assert status["share_enabled"] is True
        assert status["share_token"] == data["share_token"]


def test_share_disable_invalidates_token():
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        # Enable
        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # Disable
        resp = client.post(f"/api/sessions/{session_id}/share/disable", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["share_enabled"] is False

        # Check status
        resp = client.get(f"/api/sessions/{session_id}/share/status", headers=headers)
        assert resp.status_code == 200
        status = resp.json()
        assert status["share_enabled"] is False
        assert status["share_token"] is None
        assert status["share_url"] is None

        # Old token should be rejected
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 403


def test_share_enable_idempotent():
    """Enabling twice should regenerate token."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp1 = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp1.status_code == 200
        token1 = resp1.json()["share_token"]

        resp2 = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp2.status_code == 200
        token2 = resp2.json()["share_token"]

        # Token should be regenerated (different each time)
        assert token1 != token2

        # Old token should be invalid
        resp = client.get(f"/api/public/share/{session_id}?token={token1}")
        assert resp.status_code == 403

        # New token should work
        resp = client.get(f"/api/public/share/{session_id}?token={token2}")
        assert resp.status_code == 200


# -- Public share endpoint --

def test_public_share_no_token():
    """Access without token returns 403 (FastAPI requires query param)."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        # Enable share first
        client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)

        # No token at all
        resp = client.get(f"/api/public/share/{session_id}")
        assert resp.status_code in (403, 422)  # 422 = missing required query param


def test_public_share_not_enabled():
    """Access share endpoint when share is not enabled -> 403."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.get(f"/api/public/share/{session_id}?token=fake-token")
        assert resp.status_code == 403


def test_public_share_wrong_token():
    """Wrong token returns 403."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)

        resp = client.get(f"/api/public/share/{session_id}?token=wrong-token-value")
        assert resp.status_code == 403


def test_public_share_valid_token_returns_data():
    """Valid token returns full shared data without auth."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # Access WITHOUT auth headers
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["session"]["title"] == "Test Session"
        assert data["session"]["summary"] == "A test summary"
        assert data["session"]["keywords"] == ["test", "share"]
        assert data["notebook"]["title"] == "Test Notebook"
        assert "note" in data  # Key exists even if None


def test_public_share_disabled_after_enable():
    """After disabling, old valid token becomes invalid."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # Verify it works
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 200

        # Disable
        client.post(f"/api/sessions/{session_id}/share/disable", headers=headers)

        # Now it should fail
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 403


def test_public_share_nonexistent_session():
    """Non-existent session returns 404."""
    with TestClient(app) as client:
        resp = client.get("/api/public/share/nonexistent-id?token=fake")
        assert resp.status_code == 404


# -- Public media endpoint --

def test_public_media_wrong_token():
    """Public media with wrong token returns 403."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)

        resp = client.get(f"/api/public/media/slides/{session_id}/fake.png?token=wrong-token")
        assert resp.status_code == 403


def test_public_media_valid_token_but_missing_file():
    """Valid token but file doesn't exist returns 404."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        resp = client.get(f"/api/public/media/slides/{session_id}/nonexistent.png?token={token}")
        assert resp.status_code == 404


def test_public_media_no_token():
    """Public media without token returns validation error."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        client.post(f"/api/sessions/{session_id}/share/enable", headers=headers)

        resp = client.get(f"/api/public/media/slides/{session_id}/fake.png")
        assert resp.status_code in (403, 422)


def test_share_status_not_owner():
    """Non-owner cannot access share status."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        # Create another user directly in DB (bypass rate limit)
        _create_other_user("other@example.com", "Other", "other123")
        other_resp = client.post(
            "/api/auth/login",
            json={"email": "other@example.com", "password": "other123"},
        )
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        # Other user tries to get share status
        resp = client.get(f"/api/sessions/{session_id}/share/status", headers=other_headers)
        assert resp.status_code == 404  # Session belongs to admin, not other user


def test_share_enable_not_owner():
    """Non-owner cannot enable share."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        # Create another user directly in DB (bypass rate limit)
        _create_other_user("other2@example.com", "Other2", "other2123")
        other_resp = client.post(
            "/api/auth/login",
            json={"email": "other2@example.com", "password": "other2123"},
        )
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        resp = client.post(f"/api/sessions/{session_id}/share/enable", headers=other_headers)
        assert resp.status_code == 404


# -- Expiration and max_views guards --

def test_share_expires_after_expiration():
    """Token should be rejected after share_expires_at passes."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(
            f"/api/sessions/{session_id}/share/enable",
            params={"expires_in_hours": -1},  # Already expired
            headers=headers,
        )
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # Access should be rejected due to expiration
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 403
        assert "过期" in resp.json()["detail"]


def test_share_max_views_limits_access():
    """Access should be rejected after share_view_count reaches share_max_views."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(
            f"/api/sessions/{session_id}/share/enable",
            params={"max_views": 2},
            headers=headers,
        )
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # First access - OK
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 200

        # Second access - OK (this is the 2nd view, but we check BEFORE increment in some implementations)
        # Actually the DB update is atomic: WHERE share_view_count < max_views, then increment
        # So the 2nd access should still succeed (count was 0, now 1; next check 1 < 2 => OK)
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 200

        # Third access - should fail (count was 2, now 2 >= 2)
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 403
        assert "最大访问次数" in resp.json()["detail"]


def test_share_max_views_one():
    """max_views=1 should allow exactly one access."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_and_session(client, headers)

        resp = client.post(
            f"/api/sessions/{session_id}/share/enable",
            params={"max_views": 1},
            headers=headers,
        )
        assert resp.status_code == 200
        token = resp.json()["share_token"]

        # First access - OK
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 200

        # Second access - rejected
        resp = client.get(f"/api/public/share/{session_id}?token={token}")
        assert resp.status_code == 403


def test_layout_blocks_survive_export_import_roundtrip():
    """Notebook export/import preserves the exact layout block order."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        notebook_id, session_id = _create_notebook_and_session(client, headers)
        layout_blocks = [
            {"id": "transcript-1", "type": "transcript", "content": "<strong>第一段</strong>"},
            {"id": "ppt-2", "type": "ppt", "page": 1, "title": "Slide 1", "src": "data:image/png;base64,test"},
            {"id": "transcript-3", "type": "transcript", "content": "第二段"},
            {"id": "note-4", "type": "note", "content": "<em>随堂笔记</em>"},
        ]

        resp = client.put(
            f"/api/notes/session/{session_id}",
            headers=headers,
            json={
                "content": "## 语音转文字\n\n第一段\n\n第二段\n\n---\n\n随堂笔记",
                "layout_blocks": layout_blocks,
            },
        )
        assert resp.status_code == 200, resp.text

        resp = client.get(f"/api/notebooks/{notebook_id}/export", headers=headers)
        assert resp.status_code == 200, resp.text
        pkg = resp.json()
        assert pkg["format_version"] == 2
        assert [b["type"] for b in pkg["sessions"][0]["layout_blocks"]] == [
            "transcript",
            "ppt",
            "transcript",
            "note",
        ]

        resp = client.post("/api/notebooks/import", headers=headers, json=pkg)
        assert resp.status_code == 201, resp.text
        imported_notebook_id = resp.json()["id"]

        resp = client.get(f"/api/sessions?notebook_id={imported_notebook_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        imported_session_id = resp.json()[0]["id"]

        resp = client.get(f"/api/notes/session/{imported_session_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        imported_blocks = resp.json()["layout_blocks"]
        assert [b["type"] for b in imported_blocks] == ["transcript", "ppt", "transcript", "note"]
        assert imported_blocks[1]["title"] == "Slide 1"
