"""Tests for streaming ASR recognizer and manager."""

import wave
from unittest.mock import patch

from app.services.streaming_asr import StreamingRecognizer, StreamingASRManager
from app.services.transcriber import ASRSegment
from tests.harness.mocks import MockASRSession


class TestStreamingRecognizer:
    def test_init(self):
        rec = StreamingRecognizer("sess-1", course_title="Test Course", keywords=["kw1"])
        assert rec.session_id == "sess-1"
        assert rec.course_title == "Test Course"
        assert rec.keywords == ["kw1"]
        assert rec.is_paused is False
        assert rec.is_ended is False

    def test_feed_pcm_basic(self):
        rec = StreamingRecognizer("sess-1")
        with patch("app.services.streaming_asr.transcriber.create_streaming_session", return_value=MockASRSession(["hello"], [False])):
            events = rec.feed_pcm(b"\x00" * 3200)
            assert len(events) == 1
            assert events[0]["type"] == "partial"
            assert events[0]["text"] == "hello"

    def test_feed_pcm_final(self):
        rec = StreamingRecognizer("sess-1")
        with patch("app.services.streaming_asr.transcriber.create_streaming_session", return_value=MockASRSession(["hello"], [True])):
            events = rec.feed_pcm(b"\x00" * 3200)
            assert len(events) == 2
            assert events[0]["type"] == "partial"
            assert events[1]["type"] == "final"

    def test_feed_pcm_when_paused(self):
        rec = StreamingRecognizer("sess-1")
        rec.pause()
        events = rec.feed_pcm(b"\x00" * 3200)
        assert events == []

    def test_feed_pcm_when_ended(self):
        rec = StreamingRecognizer("sess-1")
        rec.is_ended = True
        events = rec.feed_pcm(b"\x00" * 3200)
        assert events == []

    def test_pause_resume(self):
        rec = StreamingRecognizer("sess-1")
        rec.pause()
        assert rec.is_paused is True
        rec.resume()
        assert rec.is_paused is False

    def test_finalize_no_session(self):
        rec = StreamingRecognizer("sess-1")
        result = rec.finalize()
        assert result["audio_saved"] is False
        assert result["session_id"] == "sess-1"
        # finalize always returns a transcript entry even if empty
        assert len(result["transcript"]) == 1
        assert result["transcript"][0]["text"] == ""

    def test_finalize_with_segments(self):
        rec = StreamingRecognizer("sess-1")
        with patch("app.services.streaming_asr.transcriber.create_streaming_session", return_value=MockASRSession(["hello world"], [True])):
            rec.feed_pcm(b"\x00" * 3200)
            result = rec.finalize()
            assert len(result["transcript"]) == 1
            entry = result["transcript"][0]
            assert entry["text"] == "hello world"
            assert entry["raw_text"] == "hello world"

    def test_cleanup(self):
        rec = StreamingRecognizer("sess-1")
        with patch("app.services.streaming_asr.transcriber.create_streaming_session", return_value=MockASRSession()):
            rec.feed_pcm(b"\x00" * 3200)
            assert rec._asr_session is not None
            rec.cleanup()
            assert rec._asr_session is None
            assert rec.is_ended is True

    def test_save_audio_wav(self):
        rec = StreamingRecognizer("sess-1")
        rec.audio_buffer = b"\x00" * 16000  # 1 second of silence at 16kHz, 16bit
        rec._save_audio_wav()
        from app.config import AUDIO_DIR
        output_path = AUDIO_DIR / "sess-1.wav"
        assert output_path.exists()
        # Verify WAV header
        with wave.open(str(output_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
        # Clean up
        output_path.unlink()


class TestStreamingASRManager:
    def test_singleton(self):
        m1 = StreamingASRManager()
        m2 = StreamingASRManager()
        assert m1 is m2

    def test_create_and_get_recognizer(self):
        mgr = StreamingASRManager()
        rec = mgr.create_recognizer("sess-2", course_title="Course", keywords=["k"])
        assert rec.session_id == "sess-2"
        found = mgr.get_recognizer("sess-2")
        assert found is rec

    def test_remove_recognizer(self):
        mgr = StreamingASRManager()
        rec = mgr.create_recognizer("sess-3")
        mgr.remove_recognizer("sess-3")
        assert mgr.get_recognizer("sess-3") is None

    def test_remove_nonexistent(self):
        mgr = StreamingASRManager()
        # Should not raise
        mgr.remove_recognizer("nonexistent")
