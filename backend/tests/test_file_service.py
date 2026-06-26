"""Tests for file upload path validation and file system helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import file_service
from app.config import AUDIO_DIR, PPT_DIR, IMAGE_DIR


class TestValidateSessionId:
    def test_valid_uuid_accepted(self):
        valid = "550e8400-e29b-41d4-a716-446655440000"
        assert file_service._validate_session_id(valid) == valid

    def test_invalid_uuid_rejected(self):
        with pytest.raises(ValueError):
            file_service._validate_session_id("not-a-uuid")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            file_service._validate_session_id("../../../etc/passwd")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError):
            file_service._validate_session_id("")


class TestSafeUploadName:
    def test_preserves_normal_filename(self):
        assert file_service._safe_upload_name("lecture.wav") == "lecture.wav"

    def test_strips_path_components(self):
        assert file_service._safe_upload_name("/path/to/file.wav") == "file.wav"

    def test_replaces_dangerous_chars(self):
        assert file_service._safe_upload_name("file<script>.wav") == "file_script_.wav"

    def test_fallback_when_empty(self):
        assert file_service._safe_upload_name("") == "upload"
        assert file_service._safe_upload_name("   ") == "upload"


class TestGetUploadPath:
    def test_audio_path(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        path = file_service.get_upload_path("audio", sid, "test.wav")
        assert path.name.endswith("test.wav")
        assert path.is_relative_to(AUDIO_DIR)

    def test_ppt_path(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        path = file_service.get_upload_path("ppt", sid, "slides.pptx")
        assert path.name.endswith("slides.pptx")
        assert path.is_relative_to(PPT_DIR)

    def test_invalid_file_type_raises(self):
        with pytest.raises(ValueError, match="Invalid file type"):
            file_service.get_upload_path("pdf", "550e8400-e29b-41d4-a716-446655440000", "x.pdf")

    def test_invalid_session_id_raises(self):
        with pytest.raises(ValueError):
            file_service.get_upload_path("audio", "bad-id", "x.wav")


class TestSaveAndDeleteFile:
    def test_save_and_delete_audio(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        content = b"fake audio content"
        path = file_service.save_file("audio", sid, "test.wav", content)
        assert path.exists()
        assert path.read_bytes() == content

        file_service.delete_file(path)
        assert not path.exists()

    def test_save_ppt(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        content = b"fake ppt content"
        path = file_service.save_file("ppt", sid, "slides.pptx", content)
        assert path.exists()
        file_service.delete_file(path)

    def test_save_oversized_audio_raises(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        big = b"x" * (file_service.MAX_AUDIO_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds"):
            file_service.save_file("audio", sid, "big.wav", big)

    def test_delete_outside_allowed_raises(self):
        with pytest.raises(ValueError, match="outside allowed"):
            file_service.delete_file(Path("/etc/passwd"))

    def test_delete_nonexistent_succeeds(self):
        # Should not raise
        file_service.delete_file(None)


class TestDeleteSessionFiles:
    def test_deletes_ppt_and_images(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        # Create a PPT file
        ppt_path = file_service.save_file("ppt", sid, "slides.pptx", b"ppt")
        # Create an image dir
        img_dir = file_service.get_image_dir(sid)
        (img_dir / "slide_1.png").write_bytes(b"png")

        assert ppt_path.exists()
        assert img_dir.exists()

        file_service.delete_session_files(sid, delete_audio=False)

        assert not ppt_path.exists()
        assert not img_dir.exists()

    def test_deletes_audio_when_requested(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        audio_path = file_service.save_file("audio", sid, "rec.wav", b"audio")
        assert audio_path.exists()

        file_service.delete_session_files(sid, delete_audio=True)

        assert not audio_path.exists()

    def test_keeps_audio_by_default(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        audio_path = file_service.save_file("audio", sid, "rec.wav", b"audio")
        file_service.delete_session_files(sid)
        assert audio_path.exists()

    def test_invalid_session_id_raises(self):
        with pytest.raises(ValueError):
            file_service.delete_session_files("bad-id")

    def test_deletes_audio_chunk_dir_when_requested(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        chunk_dir = file_service.AUDIO_DIR / sid
        chunk_dir.mkdir(parents=True, exist_ok=True)
        (chunk_dir / "chunk_0001.wav").write_bytes(b"chunk")

        file_service.delete_session_files(sid, delete_audio=True)

        assert not chunk_dir.exists()

    def test_keeps_audio_chunk_dir_by_default(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        chunk_dir = file_service.AUDIO_DIR / sid
        chunk_dir.mkdir(parents=True, exist_ok=True)
        (chunk_dir / "chunk_0001.wav").write_bytes(b"chunk")

        file_service.delete_session_files(sid)

        assert chunk_dir.exists()


class TestDeleteNotebookFiles:
    def test_deletes_all_sessions(self, db, admin_user):
        from app.models import Notebook, Session

        nb = Notebook(title="Test", user_id=admin_user.id)
        db.add(nb)
        db.commit()
        db.refresh(nb)

        s1 = Session(notebook_id=nb.id, title="S1")
        s2 = Session(notebook_id=nb.id, title="S2")
        db.add_all([s1, s2])
        db.commit()

        # Create files for both sessions
        file_service.save_file("audio", s1.id, "a.wav", b"a")
        file_service.save_file("ppt", s2.id, "b.pptx", b"b")

        file_service.delete_notebook_files(nb.id, db)

        # Files should be gone
        for f in file_service.AUDIO_DIR.iterdir():
            assert not f.name.startswith(str(s1.id))
        for f in file_service.PPT_DIR.iterdir():
            assert not f.name.startswith(str(s2.id))

    def test_deletes_audio_chunk_dirs(self, db, admin_user):
        from app.models import Notebook, Session

        nb = Notebook(title="Test", user_id=admin_user.id)
        db.add(nb)
        db.commit()
        db.refresh(nb)

        s1 = Session(notebook_id=nb.id, title="S1")
        db.add(s1)
        db.commit()

        chunk_dir = file_service.AUDIO_DIR / str(s1.id)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        (chunk_dir / "chunk_0001.wav").write_bytes(b"chunk")

        file_service.delete_notebook_files(nb.id, db)

        assert not chunk_dir.exists()
