"""Tests for audio processing endpoints and helpers."""

import os
import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.api.process.audio import (
    _merge_segments_to_chunks,
    _cleanup_temp_files,
    _find_ffmpeg,
    concatenate_wav_files,
    _correct_window_for_stream,
    _finalize_display_text_for_stream,
)
from app.services.transcriber import ASRSegment


class TestMergeSegmentsToChunks:
    def test_empty(self):
        assert _merge_segments_to_chunks([]) == []

    def test_single_segment(self):
        segs = [ASRSegment("A", 0, 1000)]
        result = _merge_segments_to_chunks(segs)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_gap_creates_new_chunk(self):
        segs = [
            ASRSegment("A", 0, 1000),
            ASRSegment("B", 2000, 3000),  # gap > 500ms
        ]
        result = _merge_segments_to_chunks(segs)
        assert len(result) == 2

    def test_merge_within_gap(self):
        segs = [
            ASRSegment("A", 0, 1000),
            ASRSegment("B", 1100, 2000),  # gap <= 500ms
        ]
        result = _merge_segments_to_chunks(segs)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_max_speech_ms_split(self):
        segs = [
            ASRSegment("A", 0, 5000),
            ASRSegment("B", 5100, 10000),  # total > 8000ms
        ]
        result = _merge_segments_to_chunks(segs, max_speech_ms=8000)
        assert len(result) == 2


class TestCleanupTempFiles:
    def test_removes_existing_files(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            p1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            p2 = f2.name
        assert os.path.exists(p1)
        assert os.path.exists(p2)
        _cleanup_temp_files(p1, p2)
        assert not os.path.exists(p1)
        assert not os.path.exists(p2)

    def test_missing_files_ok(self):
        # Should not raise
        _cleanup_temp_files("/nonexistent/path/file.txt", "/another/missing.wav")


class TestFindFFmpeg:
    def test_returns_something(self):
        result = _find_ffmpeg()
        # On CI or dev machines it may or may not be present
        assert result is None or isinstance(result, str)


class TestConcatenateWavFiles:
    def test_concatenates_two_files(self):
        # Create two short WAV files
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = os.path.join(tmpdir, "a.wav")
            p2 = os.path.join(tmpdir, "b.wav")
            out = os.path.join(tmpdir, "out.wav")

            for p in (p1, p2):
                with wave.open(p, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b"\x00" * 3200)

            concatenate_wav_files([p1, p2], out)
            assert os.path.exists(out)
            with wave.open(out, "rb") as wf:
                # Each file has 1600 frames (3200 bytes / 2 bytes per sample)
                assert wf.getnframes() == 3200  # 1600 * 2

    def test_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.wav")
            concatenate_wav_files([], out)
            assert not os.path.exists(out)

    def test_bad_file_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = os.path.join(tmpdir, "a.wav")
            out = os.path.join(tmpdir, "out.wav")
            # Write garbage instead of WAV header
            with open(p1, "w") as f:
                f.write("not a wav")
            concatenate_wav_files([p1], out)
            # Should not crash, but may or may not create output


class TestCorrectWindowForStream:
    @pytest.mark.asyncio
    async def test_no_llm_returns_local(self):
        with patch.object(
            type(__import__("app.services.term_corrector", fromlist=["corrector"]).corrector),
            "has_llm",
            new_callable=PropertyMock,
            return_value=False,
        ):
            result = await _correct_window_for_stream("hello world", "course", ["kw"])
            assert result["text"] == "hello world"
            assert result["is_ai_corrected"] is False
            assert "未配置" in result["correction_error"]

    @pytest.mark.asyncio
    async def test_empty_text(self):
        result = await _correct_window_for_stream("", "course", ["kw"])
        assert result["text"] == ""
        assert result["correction_error"] is None


class TestFinalizeDisplayTextForStream:
    @pytest.mark.asyncio
    async def test_empty_source(self):
        result = await _finalize_display_text_for_stream("", "", "course", ["kw"])
        assert result["display_text"] == ""
        assert result["corrected_text"] is None

    @pytest.mark.asyncio
    async def test_no_llm_fallback(self):
        with patch.object(
            type(__import__("app.services.term_corrector", fromlist=["corrector"]).corrector),
            "has_llm",
            new_callable=PropertyMock,
            return_value=False,
        ):
            result = await _finalize_display_text_for_stream("raw", "raw", "course", ["kw"])
            assert result["display_text"] == "raw"
            assert result["correction_error"] == "AI 整理失败"

    @pytest.mark.asyncio
    async def test_local_cleanup_error_fallback(self):
        # Force local cleanup to fail
        with patch(
            "app.api.process.audio.corrector.clean_transcript_for_display",
            side_effect=Exception("cleanup error"),
        ):
            result = await _finalize_display_text_for_stream("raw", "raw", "course", ["kw"])
            assert result["display_text"] == "raw"
