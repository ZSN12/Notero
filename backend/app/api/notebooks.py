import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.core.auth import get_current_user
from app.api.schemas import NotebookCreate, NotebookUpdate, NotebookResponse, NotebookPackage, NoteCreate
from app.models import Notebook, User, Session as DBSession, Note, VectorChunk
from app.services.file_service import delete_notebook_files_by_session_ids
from sqlalchemy import func as sql_func

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("/", response_model=list[NotebookResponse])
def list_notebooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Notebook).filter(
        Notebook.user_id == current_user.id
    ).order_by(Notebook.created_at.desc()).all()


@router.post("/", response_model=NotebookResponse, status_code=status.HTTP_201_CREATED)
def create_notebook(
    data: NotebookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notebook = Notebook(user_id=current_user.id, **data.model_dump())
    db.add(notebook)
    db.commit()
    db.refresh(notebook)
    return notebook


@router.get("/{notebook_id}", response_model=NotebookResponse)
def get_notebook(
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
    return notebook


@router.put("/{notebook_id}", response_model=NotebookResponse)
def update_notebook(
    notebook_id: str,
    data: NotebookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == current_user.id,
    ).first()
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(notebook, key, value)
    db.commit()
    db.refresh(notebook)
    return notebook


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notebook(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Collect session ids before deleting the notebook so we can clean up files
    # afterwards (the DB cascade will remove the session rows).
    session_ids = [
        sid for (sid,) in db.query(DBSession.id).filter(DBSession.notebook_id == notebook_id).all()
    ]

    # Use a single bulk DELETE. All foreign keys referencing notebooks/sessions
    # are defined with ON DELETE CASCADE, so the database removes child rows
    # without SQLAlchemy having to load them.
    deleted_count = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == current_user.id,
    ).delete(synchronize_session=False)

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notebook not found")

    db.commit()

    # File cleanup can be slow for notebooks with many sessions; run it in the
    # background so the HTTP response returns immediately and the UI doesn't hang.
    if session_ids:
        background_tasks.add_task(_cleanup_notebook_files, notebook_id, session_ids)
    return None


def _cleanup_notebook_files(notebook_id: str, session_ids: list[str]) -> None:
    """Clean up on-disk files for all sessions of a deleted notebook."""
    try:
        delete_notebook_files_by_session_ids(session_ids)
    except Exception:
        logger.warning(
            "delete_notebook_files_failed notebook_id=%s session_ids=%s",
            notebook_id,
            session_ids,
            exc_info=True,
        )


@router.get("/{notebook_id}/export", response_model=NotebookPackage)
def export_notebook(
    notebook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a complete notebook package including all sessions and notes."""
    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == current_user.id,
    ).first()
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")

    sessions_data = []
    sessions = (
        db.query(DBSession)
        .filter(DBSession.notebook_id == notebook_id)
        .order_by(DBSession.created_at.asc())
        .options(joinedload(DBSession.notes))
        .all()
    )

    for sess in sessions:
        note = sess.notes[0] if sess.notes else None

        bundle = {
            "title": sess.title,
            "summary": sess.summary,
            "keywords": sess.keywords or [],
        }

        if note:
            bundle["content"] = note.content
            bundle["transcript"] = note.transcript
            bundle["ppt_images"] = note.ppt_images
            bundle["layout_blocks"] = note.layout_blocks
        else:
            bundle["content"] = None
            bundle["transcript"] = None
            bundle["ppt_images"] = None
            bundle["layout_blocks"] = None

        sessions_data.append(bundle)

    notebook_create = {
        "title": notebook.title,
        "description": notebook.description,
        "icon": notebook.icon,
        "color": notebook.color,
    }

    return {
        "format_version": 2,
        "notebook": notebook_create,
        "sessions": sessions_data,
    }


@router.post("/import", response_model=NotebookResponse, status_code=status.HTTP_201_CREATED)
def import_notebook(
    data: NotebookPackage,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.format_version not in (1, 2):
        raise HTTPException(status_code=400, detail="Unsupported notebook package version")

    notebook = Notebook(user_id=current_user.id, **data.notebook.model_dump())
    db.add(notebook)
    db.flush()

    for sess_data in data.sessions:
        session = DBSession(notebook_id=notebook.id, title=sess_data.title, summary=sess_data.summary, keywords=sess_data.keywords or [])
        db.add(session)
        db.flush()

        if sess_data.content or sess_data.transcript or sess_data.ppt_images or sess_data.layout_blocks:
            note = Note(session_id=session.id, content=sess_data.content or "", transcript=sess_data.transcript, ppt_images=sess_data.ppt_images)
            if sess_data.layout_blocks is not None:
                note.layout_blocks = sess_data.layout_blocks
            db.add(note)

    db.commit()
    # Recalculate session_count atomically
    notebook.session_count = db.query(sql_func.count(DBSession.id)).filter(
        DBSession.notebook_id == notebook.id
    ).scalar() or 0
    db.commit()
    db.refresh(notebook)
    return notebook
