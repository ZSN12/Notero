"""Tests for DELETE /api/sessions/{session_id}."""

import uuid
from unittest.mock import patch

import pytest

from app.models import (
    File,
    Note,
    Notebook,
    RAGMessage,
    Session,
    SessionProcessingState,
    Task,
    User,
    VectorChunk,
)
from app.services import file_service


@pytest.mark.integration
def test_delete_empty_session_decrements_count(client, auth_headers, db, admin_user):
    """Deleting a session with no content should return 204 and update session_count."""
    nb = Notebook(title="Empty Notebook", user_id=admin_user.id, session_count=1)
    db.add(nb)
    db.commit()
    db.refresh(nb)
    session = Session(notebook_id=nb.id, title="Empty Session")
    db.add(session)
    db.commit()

    res = client.delete(f"/api/sessions/{session.id}", headers=auth_headers)
    assert res.status_code == 204

    db.expire_all()
    nb = db.query(Notebook).filter(Notebook.id == nb.id).first()
    assert nb.session_count == 0
    assert db.query(Session).filter(Session.id == session.id).first() is None


@pytest.mark.integration
def test_delete_session_with_all_associated_data(
    client, auth_headers, db, admin_user
):
    """Deleting a session should cascade to notes/files/tasks/etc. and clean files."""
    nb = Notebook(title="Full Notebook", user_id=admin_user.id, session_count=1)
    db.add(nb)
    db.commit()
    db.refresh(nb)
    session = Session(notebook_id=nb.id, title="Full Session")
    db.add(session)
    db.commit()
    db.refresh(session)

    # Note with Pad annotations
    note = Note(
        session_id=session.id,
        content="note content",
        annotations={"slides": {"1": [{"type": "stroke", "color": "#000", "width": 2, "points": []}]}},
    )
    db.add(note)

    # File record
    file_record = File(
        session_id=session.id,
        file_type="ppt",
        file_name="slides.pptx",
        file_path="/dummy/path",
        file_size=100,
    )
    db.add(file_record)

    # Task
    task = Task(session_id=session.id, task_type="mindmap", status="pending")
    db.add(task)

    # VectorChunk
    chunk = VectorChunk(
        user_id=admin_user.id,
        notebook_id=nb.id,
        session_id=session.id,
        source_type="transcript",
        text="chunk text",
    )
    db.add(chunk)

    # Processing state
    state = SessionProcessingState(session_id=session.id, stage="mindmap", status="ready")
    db.add(state)

    # RAG message
    rag = RAGMessage(
        session_id=session.id,
        notebook_id=nb.id,
        role="user",
        content="question",
    )
    db.add(rag)
    db.commit()

    # Create on-disk PPT and audio files so we can verify full cleanup.
    # Include both the audio pipeline format ({session_id}.wav) and the legacy
    # upload format ({session_id}_{uuid}_{name}) to ensure neither leaks.
    file_service.save_file("ppt", str(session.id), "slides.pptx", b"ppt data")
    file_service.save_file("audio", str(session.id), "lecture.wav", b"audio data")
    audio_pipeline_path = file_service.AUDIO_DIR / f"{session.id}.wav"
    audio_pipeline_path.write_bytes(b"pipeline audio data")

    res = client.delete(f"/api/sessions/{session.id}", headers=auth_headers)
    assert res.status_code == 204

    db.expire_all()
    nb = db.query(Notebook).filter(Notebook.id == nb.id).first()
    assert nb.session_count == 0
    assert db.query(Session).filter(Session.id == session.id).first() is None
    assert db.query(Note).filter(Note.session_id == session.id).first() is None
    assert db.query(File).filter(File.session_id == session.id).first() is None
    assert db.query(Task).filter(Task.session_id == session.id).first() is None
    assert db.query(VectorChunk).filter(VectorChunk.session_id == session.id).first() is None
    assert (
        db.query(SessionProcessingState)
        .filter(SessionProcessingState.session_id == session.id)
        .first()
        is None
    )
    assert db.query(RAGMessage).filter(RAGMessage.session_id == session.id).first() is None

    # Background file cleanup should have run in TestClient.
    ppt_prefix = f"{session.id}_"
    for f in file_service.PPT_DIR.iterdir():
        assert not f.name.startswith(ppt_prefix)
    for f in file_service.AUDIO_DIR.iterdir():
        assert not (
            f.name.startswith(ppt_prefix) or f.name == f"{session.id}.wav"
        )


@pytest.mark.integration
def test_delete_session_does_not_touch_other_sessions_audio(
    client, auth_headers, db, admin_user
):
    """Deleting one session must not remove audio files belonging to other sessions."""
    nb = Notebook(title="Multi Session Notebook", user_id=admin_user.id, session_count=2)
    db.add(nb)
    db.commit()
    db.refresh(nb)

    session_to_delete = Session(notebook_id=nb.id, title="Delete Me")
    other_session = Session(notebook_id=nb.id, title="Keep Me")
    db.add_all([session_to_delete, other_session])
    db.commit()
    db.refresh(session_to_delete)
    db.refresh(other_session)

    # Create audio files for both sessions.
    delete_audio_path = file_service.AUDIO_DIR / f"{session_to_delete.id}.wav"
    other_audio_path = file_service.AUDIO_DIR / f"{other_session.id}.wav"
    delete_audio_path.write_bytes(b"delete me")
    other_audio_path.write_bytes(b"keep me")

    res = client.delete(f"/api/sessions/{session_to_delete.id}", headers=auth_headers)
    assert res.status_code == 204

    # The other session's audio must still exist.
    assert other_audio_path.exists()
    # The deleted session's audio must be gone.
    assert not delete_audio_path.exists()


@pytest.mark.integration
def test_delete_session_succeeds_when_file_cleanup_fails(
    client, auth_headers, db, admin_user, caplog
):
    """Filesystem errors must not roll back the database deletion and are logged."""
    nb = Notebook(title="Cleanup Failure Notebook", user_id=admin_user.id, session_count=1)
    db.add(nb)
    db.commit()
    db.refresh(nb)
    session = Session(notebook_id=nb.id, title="Cleanup Failure Session")
    db.add(session)
    db.commit()
    db.refresh(session)

    note = Note(session_id=session.id, content="content")
    db.add(note)
    db.commit()

    with patch("app.api.sessions.delete_session_files", side_effect=OSError("disk busy")):
        res = client.delete(f"/api/sessions/{session.id}", headers=auth_headers)

    assert res.status_code == 204
    db.expire_all()
    assert db.query(Session).filter(Session.id == session.id).first() is None
    assert db.query(Note).filter(Note.session_id == session.id).first() is None

    # The wrapper should log a warning containing the session id and the error.
    assert "delete_session_files_failed" in caplog.text
    assert str(session.id) in caplog.text


@pytest.mark.integration
def test_delete_nonexistent_session_returns_404(client, auth_headers):
    fake_id = str(uuid.uuid4())
    res = client.delete(f"/api/sessions/{fake_id}", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.integration
def test_delete_session_cleans_up_recording_chunk_dir(
    client, auth_headers, db, admin_user
):
    """Deleting a session must remove any leftover real-time recording chunks."""
    nb = Notebook(title="Chunk Notebook", user_id=admin_user.id, session_count=1)
    db.add(nb)
    db.commit()
    db.refresh(nb)
    session = Session(notebook_id=nb.id, title="Chunk Session")
    db.add(session)
    db.commit()
    db.refresh(session)

    note = Note(session_id=session.id, content="content")
    db.add(note)
    db.commit()

    chunk_dir = file_service.AUDIO_DIR / str(session.id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    (chunk_dir / "chunk_0001.wav").write_bytes(b"chunk data")

    res = client.delete(f"/api/sessions/{session.id}", headers=auth_headers)
    assert res.status_code == 204

    assert not chunk_dir.exists()
