import re
import shutil
import uuid
import os
import logging
from pathlib import Path
from app.config import AUDIO_DIR, PPT_DIR, IMAGE_DIR, SLIDE_DIR, MAX_AUDIO_SIZE, MAX_PPT_SIZE

logger = logging.getLogger(__name__)

# Allowed UUID pattern for session_id validation
_RE_SAFE_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _validate_session_id(session_id: str) -> str:
    """Validate session_id is a safe UUID string."""
    sid = str(session_id)
    if not _RE_SAFE_ID.match(sid):
        raise ValueError(f"Invalid session_id format: {sid}")
    return sid


def _safe_upload_name(file_name: str) -> str:
    """Return a filesystem-safe basename for an uploaded file."""
    original = Path(file_name or "upload").name
    safe_name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in original).strip()
    return safe_name or "upload"


def get_upload_path(file_type: str, session_id: str, file_name: str) -> Path:
    """Get the absolute upload path for a file."""
    safe_name = _safe_upload_name(file_name)
    directory = AUDIO_DIR if file_type == "audio" else PPT_DIR if file_type == "ppt" else None
    if directory is None:
        raise ValueError(f"Invalid file type: {file_type}")

    sid = _validate_session_id(session_id)
    target = (directory / f"{sid}_{uuid.uuid4().hex}_{safe_name}").resolve()
    base = directory.resolve()
    if not target.is_relative_to(base):
        raise ValueError("Invalid upload path")
    return target


def get_image_dir(session_id: str) -> Path:
    """Get the image output directory for a session."""
    sid = _validate_session_id(session_id)
    dir_path = IMAGE_DIR / sid
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def save_file(file_type: str, session_id: str, file_name: str, file_content: bytes) -> Path:
    """Save uploaded file and return its path."""
    if file_type == "audio":
        if len(file_content) > MAX_AUDIO_SIZE:
            raise ValueError(f"Audio file exceeds {MAX_AUDIO_SIZE / 1024 / 1024}MB limit")
    elif file_type == "ppt":
        if len(file_content) > MAX_PPT_SIZE:
            raise ValueError(f"PPT file exceeds {MAX_PPT_SIZE / 1024 / 1024}MB limit")

    file_path = get_upload_path(file_type, session_id, file_name)
    with open(file_path, "wb") as f:
        f.write(file_content)
    return file_path


def delete_file(file_path: Path) -> None:
    """Delete a file if it exists and is within an allowed directory."""
    if not file_path:
        return
    resolved = file_path.resolve()
    allowed_bases = [AUDIO_DIR.resolve(), PPT_DIR.resolve(), IMAGE_DIR.resolve(), SLIDE_DIR.resolve()]
    if not any(resolved.is_relative_to(base) for base in allowed_bases):
        raise ValueError("Attempted to delete file outside allowed directories")
    if resolved.exists():
        resolved.unlink()


def _is_session_audio_file(file_name: str, sid: str) -> bool:
    """Check whether a file name belongs to a session's audio recording.

    Recordings created by the audio pipeline are stored as ``{session_id}.wav``,
    while legacy uploads via ``save_file`` use ``{session_id}_{uuid}_{name}``.
    """
    return file_name == f"{sid}.wav" or file_name.startswith(f"{sid}_")


def delete_session_files(session_id: str, delete_audio: bool = False) -> None:
    """Delete all files associated with a session.

    Args:
        session_id: UUID of the session whose files should be removed.
        delete_audio: If True, also delete the session's audio recording.
            Audio is kept by default so that other call sites can clean PPT
            and images without removing recordings.
    """
    sid = _validate_session_id(session_id)

    # Delete audio (only if requested - audio is kept by default)
    if delete_audio and AUDIO_DIR.exists():
        for f in AUDIO_DIR.iterdir():
            if f.is_file() and _is_session_audio_file(f.name, sid):
                try:
                    f.unlink()
                    logger.info("deleted_audio_file session_id=%s path=%s", sid, f)
                except Exception as exc:
                    logger.warning(
                        "delete_audio_file_failed session_id=%s path=%s error=%s",
                        sid, f, exc, exc_info=True,
                    )

        # Real-time recording chunks live in a per-session subdirectory. If the
        # session is deleted before audio-finish runs, this directory would leak.
        chunk_dir = AUDIO_DIR / sid
        if chunk_dir.exists():
            try:
                shutil.rmtree(chunk_dir)
                logger.info("deleted_audio_chunk_dir session_id=%s path=%s", sid, chunk_dir)
            except Exception as exc:
                logger.warning(
                    "delete_audio_chunk_dir_failed session_id=%s path=%s error=%s",
                    sid, chunk_dir, exc, exc_info=True,
                )

    # Delete PPT (always deleted)
    ppt_prefix = f"{sid}_"
    if PPT_DIR.exists():
        for f in PPT_DIR.iterdir():
            if f.is_file() and f.name.startswith(ppt_prefix):
                try:
                    f.unlink()
                    logger.info("deleted_ppt_file session_id=%s path=%s", sid, f)
                except Exception as exc:
                    logger.warning(
                        "delete_ppt_file_failed session_id=%s path=%s error=%s",
                        sid, f, exc, exc_info=True,
                    )

    # Delete images
    image_dir = IMAGE_DIR / sid
    if image_dir.exists():
        try:
            shutil.rmtree(image_dir)
            logger.info("deleted_image_dir session_id=%s path=%s", sid, image_dir)
        except Exception as exc:
            logger.warning(
                "delete_image_dir_failed session_id=%s path=%s error=%s",
                sid, image_dir, exc, exc_info=True,
            )

    # Delete rendered PPT slide images
    slide_dir = SLIDE_DIR / sid
    if slide_dir.exists():
        try:
            shutil.rmtree(slide_dir)
            logger.info("deleted_slide_dir session_id=%s path=%s", sid, slide_dir)
        except Exception as exc:
            logger.warning(
                "delete_slide_dir_failed session_id=%s path=%s error=%s",
                sid, slide_dir, exc, exc_info=True,
            )


def _delete_files_for_session_ids(session_ids: set[str]) -> None:
    """Delete on-disk files for the given session ids.

    Scans the shared audio/ppt directories once for the whole set instead of
    once per session to avoid O(sessions * total_files) behaviour.
    """
    if not session_ids:
        return

    # Scan audio dir once
    if AUDIO_DIR.exists():
        for f in AUDIO_DIR.iterdir():
            if not f.is_file():
                continue
            sid = next(
                (sid for sid in session_ids if _is_session_audio_file(f.name, sid)),
                None,
            )
            if sid is None:
                continue
            try:
                f.unlink()
                logger.info("deleted_audio_file session_id=%s path=%s", sid, f)
            except Exception as exc:
                logger.warning(
                    "delete_audio_file_failed session_id=%s path=%s error=%s",
                    sid, f, exc, exc_info=True,
                )

    # Scan ppt dir once
    prefixes = {f"{sid}_" for sid in session_ids}
    if PPT_DIR.exists():
        for f in PPT_DIR.iterdir():
            if not f.is_file():
                continue
            sid = next(
                (sid for sid in session_ids if f.name.startswith(f"{sid}_")),
                None,
            )
            if sid is None:
                continue
            try:
                f.unlink()
                logger.info("deleted_ppt_file session_id=%s path=%s", sid, f)
            except Exception as exc:
                logger.warning(
                    "delete_ppt_file_failed session_id=%s path=%s error=%s",
                    sid, f, exc, exc_info=True,
                )

    # Delete audio chunk dirs and image/slide dirs directly by session id
    for sid in session_ids:
        chunk_dir = AUDIO_DIR / sid
        if chunk_dir.exists():
            try:
                shutil.rmtree(chunk_dir)
                logger.info("deleted_audio_chunk_dir session_id=%s path=%s", sid, chunk_dir)
            except Exception as exc:
                logger.warning(
                    "delete_audio_chunk_dir_failed session_id=%s path=%s error=%s",
                    sid, chunk_dir, exc, exc_info=True,
                )

        image_dir = IMAGE_DIR / sid
        if image_dir.exists():
            try:
                shutil.rmtree(image_dir)
                logger.info("deleted_image_dir session_id=%s path=%s", sid, image_dir)
            except Exception as exc:
                logger.warning(
                    "delete_image_dir_failed session_id=%s path=%s error=%s",
                    sid, image_dir, exc, exc_info=True,
                )
        slide_dir = SLIDE_DIR / sid
        if slide_dir.exists():
            try:
                shutil.rmtree(slide_dir)
                logger.info("deleted_slide_dir session_id=%s path=%s", sid, slide_dir)
            except Exception as exc:
                logger.warning(
                    "delete_slide_dir_failed session_id=%s path=%s error=%s",
                    sid, slide_dir, exc, exc_info=True,
                )


def delete_notebook_files(notebook_id: str, db=None) -> None:
    """Delete all files for all sessions in a notebook.

    Note: when called after the notebook has already been deleted from the DB,
    no session ids will be found and files will NOT be cleaned up. Prefer
    collecting session ids before deleting the notebook and passing them to
    ``delete_notebook_files_by_session_ids``.
    """
    from app.models import Session
    from app.core.database import SessionLocal

    if db is None:
        db = SessionLocal()
        own_session = True
    else:
        own_session = False

    try:
        session_ids = {
            sid for (sid,) in db.query(Session.id).filter(Session.notebook_id == notebook_id).all()
        }
    finally:
        if own_session:
            db.close()

    _delete_files_for_session_ids(session_ids)


def delete_notebook_files_by_session_ids(session_ids: list[str]) -> None:
    """Delete all on-disk files for the given session ids."""
    _delete_files_for_session_ids(set(session_ids))
