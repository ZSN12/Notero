from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import update
from datetime import datetime, timezone
from pathlib import Path
from app.core.database import get_db
from app.models import Session as DBSession, Note, Notebook
from app.config import SLIDE_DIR

router = APIRouter(prefix="/api/public", tags=["public"])


def _safe_media_path(base_dir: Path, *parts: str) -> Path:
    base = base_dir.resolve()
    target = (base / Path(*parts)).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=404, detail="Media not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return target


@router.get("/share/{session_id}")
def get_shared_session(
    session_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get shared session data. Requires valid share token. No auth needed."""
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.share_enabled or not session.share_token:
        raise HTTPException(status_code=403, detail="分享已关闭")

    # Check expiration
    if session.share_expires_at and session.share_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="分享链接已过期")

    # Constant-time comparison to prevent timing attacks
    if not _timing_safe_compare(token, session.share_token):
        raise HTTPException(status_code=403, detail="分享链接无效")

    # Atomically increment view count with max_views guard in one UPDATE
    result = db.execute(
        update(DBSession)
        .where(
            DBSession.id == session_id,
            (DBSession.share_max_views.is_(None)) | (DBSession.share_view_count < DBSession.share_max_views),
        )
        .values(share_view_count=DBSession.share_view_count + 1)
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=403, detail="分享链接已达到最大访问次数")

    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    note = db.query(Note).filter(Note.session_id == session_id).first()

    return {
        "session": {
            "id": session.id,
            "notebook_id": session.notebook_id,
            "title": session.title,
            "keywords": session.keywords or [],
            "duration": session.duration,
            "status": session.status,
        },
        "notebook": {
            "id": notebook.id if notebook else "",
            "title": notebook.title if notebook else "未知",
        },
        "note": {
            "content": note.content if note else None,
            "transcript": note.transcript if note else None,
            "ppt_images": note.ppt_images if note else None,
            "layout_blocks": note.layout_blocks if note else None,
        } if note else None,
    }


@router.get("/media/slides/{session_id}/{slide_path:path}")
def get_share_slide_media(
    session_id: str,
    slide_path: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Serve slide images for shared sessions. Validates share token."""
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Media not found")

    _validate_share_token(session, token)

    target = _safe_media_path(SLIDE_DIR, session_id, slide_path)
    return FileResponse(target)


@router.get("/media/slides-pdf/{session_id}")
def get_share_slides_pdf(
    session_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Serve slides PDF for shared sessions."""
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Media not found")

    _validate_share_token(session, token)

    pdf_path = _safe_media_path(SLIDE_DIR, session_id, "slides.pdf")
    return FileResponse(pdf_path)


def _validate_share_token(session: DBSession, token: str) -> None:
    """Validate share token, expiration, and max views. Raises HTTPException on failure."""
    if not session.share_enabled or not session.share_token:
        raise HTTPException(status_code=403, detail="分享已关闭")

    if session.share_expires_at and session.share_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="分享链接已过期")

    if session.share_max_views is not None and session.share_view_count >= session.share_max_views:
        raise HTTPException(status_code=403, detail="分享链接已达到最大访问次数")

    if not _timing_safe_compare(token, session.share_token):
        raise HTTPException(status_code=403, detail="分享链接无效")


def _timing_safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())