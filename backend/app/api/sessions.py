from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from sqlalchemy import func as sql_func
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.api.schemas import SessionCreate, SessionUpdate, SessionResponse
from app.models import Session as DBSession, Notebook, User, VectorChunk
from app.services.file_service import delete_session_files
from app.services.session_service import get_user_session
from app.services.state_service import get_session_processing_status
import secrets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/", response_model=list[SessionResponse])
def list_sessions(
    notebook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == current_user.id,
    ).first()
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")

    return db.query(DBSession).filter(
        DBSession.notebook_id == notebook_id
    ).order_by(DBSession.created_at.desc()).all()


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    data: SessionCreate,
    notebook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == current_user.id,
    ).first()
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    session = DBSession(notebook_id=notebook_id, **data.model_dump())
    db.add(session)
    db.commit()
    # Atomically increment session_count to avoid race conditions
    db.query(Notebook).filter(Notebook.id == notebook_id).update(
        {"session_count": Notebook.session_count + 1}
    )
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.put("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: str,
    data: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(session, key, value)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Remove vector_chunks for this session to avoid FK constraint violations.
        db.query(VectorChunk).filter(VectorChunk.session_id == session_id).delete(
            synchronize_session=False
        )

        # Atomically decrement session_count
        db.query(Notebook).filter(Notebook.id == session.notebook_id).update(
            {"session_count": sql_func.greatest(Notebook.session_count - 1, 0)}
        )
        db.delete(session)
        db.commit()
    except Exception:
        logger.exception(
            "delete_session_failed session_id=%s user_id=%s",
            session_id,
            current_user.id,
        )
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="删除课次失败，请稍后重试",
        )

    # File cleanup runs after the DB transaction is committed so that
    # filesystem errors never leave the database in an inconsistent state.
    background_tasks.add_task(_cleanup_session_files, session_id)
    return None


def _cleanup_session_files(session_id: str) -> None:
    try:
        # Deleting the whole session must also remove its recording files.
        delete_session_files(session_id, delete_audio=True)
    except Exception as exc:
        logger.warning(
            "delete_session_files_failed session_id=%s error=%s",
            session_id,
            exc,
            exc_info=True,
        )


# ── Share endpoints ──

@router.post("/{session_id}/share/enable")
def enable_share(
    session_id: str,
    expires_in_hours: int = None,
    max_views: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable sharing for a session, generating a share token."""
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    token = secrets.token_urlsafe(24)
    session.share_enabled = True
    session.share_token = token
    session.share_view_count = 0
    if expires_in_hours is not None:
        if expires_in_hours > 0:
            session.share_expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        else:
            # Non-positive duration means already expired (used for testing/invalidating shares).
            session.share_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    else:
        session.share_expires_at = None
    if max_views is not None and max_views > 0:
        session.share_max_views = max_views
    else:
        session.share_max_views = None
    db.commit()

    return {"share_enabled": True, "share_token": token,
            "share_url": f"/share/{session_id}?token={token}",
            "share_expires_at": session.share_expires_at,
            "share_max_views": session.share_max_views}


@router.post("/{session_id}/share/disable")
def disable_share(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable sharing for a session."""
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.share_enabled = False
    session.share_token = None
    session.share_expires_at = None
    session.share_max_views = None
    session.share_view_count = 0
    db.commit()

    return {"share_enabled": False}


@router.get("/{session_id}/share/status")
def get_share_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current share status for a session."""
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "share_enabled": bool(session.share_enabled),
        "share_token": session.share_token if session.share_enabled else None,
        "share_url": f"/share/{session_id}?token={session.share_token}" if session.share_enabled and session.share_token else None,
        "share_expires_at": session.share_expires_at,
        "share_max_views": session.share_max_views,
        "share_view_count": session.share_view_count,
    }


@router.get("/{session_id}/processing-status")
def get_processing_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return unified processing status for all stages of a session."""
    session = get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return get_session_processing_status(db, session_id)
