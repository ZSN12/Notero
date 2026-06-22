from fastapi.testclient import TestClient

from tests.harness.helpers import auth_headers


def test_health_and_login(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    # Redis may be unavailable in test environments; accept degraded status.
    assert resp.json()["status"] in ("ok", "degraded")

    resp = client.post(
        "/api/auth/login",
        json={"email": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert "refresh_token" in resp.json()


def test_password_reset_allows_account_only_reset(client: TestClient):
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "Reset User",
            "email": "reset@example.com",
            "password": "oldpass123",
            "security_question": "What is your favorite color?",
            "security_answer": "blue",
        },
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/auth/reset-password",
        json={
            "email": "reset@example.com",
            "security_answer": "blue",
            "new_password": "newpass123",
        },
    )
    assert resp.status_code == 200

    resp = client.post(
        "/api/auth/login",
        json={"email": "reset@example.com", "password": "newpass123"},
    )
    assert resp.status_code == 200


def test_media_routes_require_authentication(client: TestClient):
    resp = client.get("/api/media/audio/example.wav")
    assert resp.status_code in (401, 403)


def test_ppt_align_requires_owned_session(client: TestClient):
    headers = auth_headers(client)
    resp = client.post(
        "/api/process/ppt-align",
        params={"session_id": "missing-session", "text": "hello"},
        headers=headers,
    )
    assert resp.status_code == 404
