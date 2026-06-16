"""High-level test helpers built on top of the harness fixtures."""

from __future__ import annotations

from fastapi.testclient import TestClient


def auth_headers(
    client: TestClient,
    email: str = "admin",
    password: str = "admin123",
    *,
    origin: str = "http://localhost:5173",
) -> dict[str, str]:
    """Login through the API and return Authorization headers."""
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": origin,
    }


def create_other_user(db_session, email: str, username: str, password: str = "other1234") -> None:
    """Directly create a user in the given DB session to bypass rate-limited registration."""
    from app.models import User
    from app.core.auth import hash_password

    existing = db_session.query(User).filter(User.email == email).first()
    if not existing:
        db_session.add(
            User(
                username=username,
                email=email,
                password_hash=hash_password(password),
            )
        )
        db_session.commit()


def create_notebook_and_session(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str = "Test Notebook",
    session_title: str = "Test Session",
    keywords: list[str] | None = None,
) -> tuple[str, str]:
    """Create a notebook + session through the API and return (notebook_id, session_id)."""
    nb = client.post("/api/notebooks", json={"title": title}, headers=headers)
    assert nb.status_code == 201, nb.text
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": session_title, "keywords": keywords or ["test"]},
        headers=headers,
    )
    assert sess.status_code == 201, sess.text
    return notebook_id, sess.json()["id"]


def create_notebook_session_note(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str = "Test Notebook",
    session_title: str = "Test Session",
    keywords: list[str] | None = None,
    content: str = "",
    layout_blocks: list[dict] | None = None,
) -> tuple[str, str]:
    """Create a notebook + session + note through the API and return (notebook_id, session_id)."""
    notebook_id, session_id = create_notebook_and_session(
        client,
        headers,
        title=title,
        session_title=session_title,
        keywords=keywords,
    )

    payload: dict = {"content": content}
    if layout_blocks is not None:
        payload["layout_blocks"] = layout_blocks
    elif content:
        payload["layout_blocks"] = [
            {"id": "t1", "type": "transcript", "content": content}
        ]

    note = client.put(
        f"/api/notes/session/{session_id}",
        json=payload,
        headers=headers,
    )
    assert note.status_code in (200, 201), note.text
    return notebook_id, session_id
