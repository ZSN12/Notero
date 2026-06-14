"""Reusable FastAPI dependencies for common authorization patterns."""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User, Notebook, Session as DBSession, Note
from app.core.exceptions import ResourceNotFoundError, AuthorizationError


def require_notebook_owner(
    notebook_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notebook:
    """Verify the current user owns the given notebook."""
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.user_id == current_user.id)
        .first()
    )
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return notebook


def require_session_owner(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DBSession:
    """Verify the current user owns the session (via notebook)."""
    session = (
        db.query(DBSession)
        .filter(DBSession.id == session_id)
        .join(Notebook)
        .filter(Notebook.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def require_note_owner(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Note:
    """Verify the current user owns the note for the given session."""
    note = (
        db.query(Note)
        .filter(Note.session_id == session_id)
        .join(DBSession)
        .join(Notebook)
        .filter(Notebook.user_id == current_user.id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


# -- Service-layer helpers (not FastAPI dependencies) --

def get_notebook_for_user(
    notebook_id: str,
    user: User,
    db: Session,
) -> Notebook:
    """Service-layer helper: fetch notebook if owned by user."""
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == notebook_id, Notebook.user_id == user.id)
        .first()
    )
    if not notebook:
        raise ResourceNotFoundError("Notebook", notebook_id)
    return notebook


def get_session_for_user(
    session_id: str,
    user: User,
    db: Session,
) -> DBSession:
    """Service-layer helper: fetch session if owned by user."""
    session = (
        db.query(DBSession)
        .filter(DBSession.id == session_id)
        .join(Notebook)
        .filter(Notebook.user_id == user.id)
        .first()
    )
    if not session:
        raise ResourceNotFoundError("Session", session_id)
    return session


def get_note_for_session(
    session_id: str,
    user: User,
    db: Session,
) -> Note:
    """Service-layer helper: fetch note for session if owned by user."""
    note = (
        db.query(Note)
        .filter(Note.session_id == session_id)
        .join(DBSession)
        .join(Notebook)
        .filter(Notebook.user_id == user.id)
        .first()
    )
    if not note:
        raise ResourceNotFoundError("Note", session_id)
    return note
