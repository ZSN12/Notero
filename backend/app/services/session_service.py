"""Small helpers for session ownership lookups."""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.models import Notebook, Session as SessionModel


def get_user_session(
    db: DBSession,
    session_id: str,
    user_id: str,
) -> SessionModel | None:
    """Return the session if it belongs to ``user_id``, else None."""
    return (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .join(Notebook)
        .filter(Notebook.user_id == user_id)
        .first()
    )
