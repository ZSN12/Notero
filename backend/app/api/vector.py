from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User
from app.services import vector_service
from app.services.state_service import set_running, set_ready, set_error
from app.services.vector_service import _compute_session_content_hash
from app.middleware.metrics import observe_vector_rebuild
from app.models import Note

router = APIRouter(prefix="/api/vector", tags=["vector"])


class SearchRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    notebook_id: Optional[str] = None
    limit: int = 20


@router.post("/session/{session_id}/rebuild")
def rebuild_session_index(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild vector index for a single session."""
    set_running(db, session_id, "vector_index", commit=False)
    try:
        chunk_count = vector_service.build_session_index(session_id, current_user, db)
        note = db.query(Note).filter(Note.session_id == session_id).first()
        current_hash = _compute_session_content_hash(note) if note else ""
        set_ready(db, session_id, "vector_index", content_hash=current_hash, commit=False)
        db.commit()
        observe_vector_rebuild("session", success=True)
        return {"session_id": session_id, "chunk_count": chunk_count, "status": "indexed"}
    except ValueError as e:
        set_error(db, session_id, "vector_index", error_message=str(e), commit=False)
        db.commit()
        observe_vector_rebuild("session", success=False)
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/notebook/{notebook_id}/rebuild")
def rebuild_notebook_index(
    notebook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild vector index for all sessions in a notebook."""
    try:
        chunk_count = vector_service.build_notebook_index(notebook_id, current_user, db)
        observe_vector_rebuild("notebook", success=True)
        return {"notebook_id": notebook_id, "chunk_count": chunk_count, "status": "indexed"}
    except ValueError as e:
        observe_vector_rebuild("notebook", success=False)
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/session/{session_id}/rebuild-v2")
def rebuild_session_index_v2(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild vector index with neural embedding for a single session."""
    set_running(db, session_id, "vector_index", commit=False)
    try:
        chunk_count = vector_service.build_session_index(session_id, current_user, db, use_neural=True)
        note = db.query(Note).filter(Note.session_id == session_id).first()
        current_hash = _compute_session_content_hash(note) if note else ""
        set_ready(db, session_id, "vector_index", content_hash=current_hash, commit=False)
        db.commit()
        observe_vector_rebuild("session", success=True)
        return {"session_id": session_id, "chunk_count": chunk_count, "status": "indexed", "embedding_type": "neural"}
    except ValueError as e:
        set_error(db, session_id, "vector_index", error_message=str(e), commit=False)
        db.commit()
        observe_vector_rebuild("session", success=False)
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/notebook/{notebook_id}/rebuild-v2")
def rebuild_notebook_index_v2(
    notebook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild vector index with neural embedding for all sessions in a notebook."""
    try:
        chunk_count = vector_service.build_notebook_index(notebook_id, current_user, db, use_neural=True)
        return {"notebook_id": notebook_id, "chunk_count": chunk_count, "status": "indexed", "embedding_type": "neural"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/session/{session_id}/status")
def get_session_vector_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get vector index status for a session."""
    try:
        return vector_service.get_session_index_status(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/search")
def search_vectors(
    req: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search vector chunks by query."""
    results = vector_service.search_vectors(
        user=current_user,
        query=req.query,
        session_id=req.session_id,
        notebook_id=req.notebook_id,
        limit=req.limit,
        db=db,
    )
    return {"results": results, "total": len(results)}
