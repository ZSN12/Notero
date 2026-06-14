from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User
from app.services import mindmap_service

router = APIRouter(prefix="/api/mindmap", tags=["mindmap"])


class PositionsUpdate(BaseModel):
    positions: dict


@router.get("/session/{session_id}")
def get_session_mind_map(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get mind map status and data for a session."""
    try:
        return mindmap_service.get_mind_map_status(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/session/{session_id}/generate")
def generate_session_mind_map(
    session_id: str,
    force: bool = False,
    response: Response = Response(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start or reuse mind map generation for a session.

    Pass force=True to regenerate even if a ready mind map already exists.
    """
    try:
        result = mindmap_service.start_mind_map_generation(session_id, current_user, db, force=force)
        if result.get("status") == "generating":
            response.status_code = status.HTTP_202_ACCEPTED
        return result
    except ValueError as e:
        error_msg = str(e)
        if "DEEPSEEK_API_KEY" in error_msg:
            raise HTTPException(status_code=503, detail=error_msg)
        if "JSON" in error_msg or "结构" in error_msg or "对象" in error_msg or "节点" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg)
        if "失败" in error_msg or "超时" in error_msg or "timeout" in error_msg.lower():
            raise HTTPException(status_code=502, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)


@router.delete("/session/{session_id}")
def delete_session_mind_map(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete mind map for a session."""
    try:
        return mindmap_service.delete_mind_map(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/session/{session_id}/positions")
def update_session_mind_map_positions(
    session_id: str,
    update: PositionsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save node positions for a session's mind map."""
    try:
        return mindmap_service.save_mind_map_positions(
            session_id, update.positions, current_user, db
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
