"""Tests for transcript correction logic."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.api.process.correction import (
    _extract_ppt_slides,
    _display_text_from_entry,
    correct_uncorrected_transcripts_from_data,
    schedule_correction,
    _correction_tasks,
    _last_correction_time,
    _pending_force_correction,
)


def _clear_correction_state():
    _correction_tasks.clear()
    _last_correction_time.clear()
    _pending_force_correction.clear()


class TestExtractPptSlides:
    def test_no_ppt(self):
        note = MagicMock()
        note.ppt_images = None
        assert _extract_ppt_slides(note) is None

    def test_empty_ppt(self):
        note = MagicMock()
        note.ppt_images = []
        assert _extract_ppt_slides(note) is None

    def test_extracts_slides(self):
        note = MagicMock()
        note.ppt_images = [{"slides": [{"page": 1, "text": "Slide 1"}]}]
        result = _extract_ppt_slides(note)
        assert result == [{"page": 1, "text": "Slide 1"}]

    def test_last_ppt_no_slides_key(self):
        note = MagicMock()
        note.ppt_images = [{"other": "data"}]
        assert _extract_ppt_slides(note) is None


class TestDisplayTextFromEntry:
    def test_display_text_priority(self):
        entry = {"display_text": "display", "text": "text", "raw_text": "raw"}
        assert _display_text_from_entry(entry) == "display"

    def test_text_fallback(self):
        entry = {"text": "text", "raw_text": "raw"}
        assert _display_text_from_entry(entry) == "text"

    def test_raw_fallback(self):
        entry = {"raw_text": "raw"}
        assert _display_text_from_entry(entry) == "raw"

    def test_empty(self):
        assert _display_text_from_entry({}) == ""


class TestCorrectUncorrectedTranscriptsFromData:
    def test_note_not_found(self):
        db = MagicMock()
        db.query().filter().first.return_value = None
        with patch("app.api.process.correction.logger"):
            correct_uncorrected_transcripts_from_data("sid", "course", [], [], db)
        db.commit.assert_not_called()

    def test_empty_transcript(self):
        db = MagicMock()
        note = MagicMock()
        note.transcript = None
        db.query().filter().first.return_value = note
        with patch("app.api.process.correction.logger"):
            correct_uncorrected_transcripts_from_data("sid", "course", [], [], db)
        db.commit.assert_not_called()

    def test_no_text_to_correct(self):
        db = MagicMock()
        note = MagicMock()
        note.transcript = [{"chunk_index": 0, "text": ""}]
        note.ppt_images = None
        db.query().filter().first.return_value = note
        with patch("app.api.process.correction.logger"):
            correct_uncorrected_transcripts_from_data("sid", "course", [], [], db)
        db.commit.assert_not_called()

    def test_successful_correction(self):
        db = MagicMock()
        note = MagicMock()
        note.transcript = [
            {"chunk_index": 0, "text": "hello world", "timestamps": [{"start": 0, "end": 1000}]},
        ]
        note.ppt_images = None
        db.query().filter().first.return_value = note

        with patch("app.api.process.correction.corrector") as mock_corrector:
            mock_corrector.dedupe_repeated_texts.return_value = ["hello world"]
            mock_corrector.restructure_transcript.return_value = "corrected text"
            mock_corrector.preserves_source_content.return_value = True
            mock_corrector.clean_transcript_for_display.return_value = "cleaned"

            correct_uncorrected_transcripts_from_data(
                "sid", "course", ["kw"], note.transcript, db, snapshot_max_chunk=0
            )

            assert note.transcript is not None
            db.commit.assert_called()

    def test_correction_rejected(self):
        db = MagicMock()
        note = MagicMock()
        note.transcript = [
            {"chunk_index": 0, "text": "hello", "timestamps": []},
        ]
        note.ppt_images = None
        db.query().filter().first.return_value = note

        with patch("app.api.process.correction.corrector") as mock_corrector:
            mock_corrector.dedupe_repeated_texts.return_value = ["hello"]
            mock_corrector.restructure_transcript.return_value = "bad"
            mock_corrector.preserves_source_content.return_value = False
            mock_corrector.clean_transcript_for_display.return_value = "hello"

            correct_uncorrected_transcripts_from_data(
                "sid", "course", [], note.transcript, db, snapshot_max_chunk=0
            )
            db.commit.assert_called()

    def test_exception_handled(self):
        db = MagicMock()
        db.query().filter().first.side_effect = Exception("db error")
        with patch("app.api.process.correction.logger"):
            correct_uncorrected_transcripts_from_data("sid", "course", [], [], db)
        db.commit.assert_not_called()


class TestScheduleCorrection:
    def setup_method(self):
        _clear_correction_state()

    def test_throttled(self):
        # First call sets last time
        db = MagicMock()
        with patch("app.api.process.correction.threading.Thread") as mock_thread:
            schedule_correction("sid", "course", ["kw"], db, force=False)
            # Second immediate call should be throttled
            schedule_correction("sid", "course", ["kw"], db, force=False)
            # Thread should only be started once
            assert mock_thread.call_count == 1

    def test_force_while_running(self):
        db = MagicMock()
        with patch("app.api.process.correction.threading.Thread") as mock_thread:
            schedule_correction("sid", "course", ["kw"], db, force=False)
            # Force while running should set pending force
            schedule_correction("sid", "course", ["kw"], db, force=True)
            # Still only one thread started
            assert mock_thread.call_count == 1

    def test_force_not_throttled(self):
        db = MagicMock()
        with patch("app.api.process.correction.threading.Thread") as mock_thread:
            schedule_correction("sid", "course", ["kw"], db, force=True)
            assert mock_thread.call_count == 1

    def _wait_for_task_clear(self, timeout: float = 2.0) -> None:
        import time
        deadline = time.monotonic() + timeout
        while "sid" in _correction_tasks and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_thread_runs_correction(self):
        import time
        mock_db = MagicMock()
        note = MagicMock()
        note.transcript = [
            {"chunk_index": 0, "text": "hello world", "timestamps": [{"start": 0, "end": 1000}]}
        ]
        mock_db.query().filter().first.return_value = note

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            with patch("app.api.process.correction.correct_uncorrected_transcripts_from_data") as mock_correct:
                schedule_correction("sid", "course", ["kw"], None, force=True, delay_seconds=0.05)
                deadline = time.monotonic() + 2.0
                while not mock_correct.called and time.monotonic() < deadline:
                    time.sleep(0.05)
                mock_correct.assert_called_once()
                # Task should be cleared after completion
                self._wait_for_task_clear()
                assert "sid" not in _correction_tasks

    def test_thread_skips_empty_note(self):
        mock_db = MagicMock()
        mock_db.query().filter().first.return_value = None

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            schedule_correction("sid", "course", ["kw"], None, force=True, delay_seconds=0.05)
            self._wait_for_task_clear()
            assert "sid" not in _correction_tasks

    def test_thread_skips_no_text(self):
        mock_db = MagicMock()
        note = MagicMock()
        note.transcript = [{"chunk_index": 0, "text": ""}]
        mock_db.query().filter().first.return_value = note

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            schedule_correction("sid", "course", ["kw"], None, force=True, delay_seconds=0.05)
            self._wait_for_task_clear()
            assert "sid" not in _correction_tasks
