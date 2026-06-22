"""Streaming ASR service using FunASR online model with per-connection state.

Each WebSocket connection gets a StreamingRecognizer that uses
``paraformer-zh-streaming`` with an incremental ``cache``.  The model
only emits *new* text for every chunk; already-output text is never
duplicated.

The frontend protocol remains the same:
  - ``partial``: temporary text (may change)
  - ``final``:   confirmed text (committed after silence)
  - ``done``:    end-of-stream with full note
"""

import asyncio
import logging
import os
import threading
import wave
from typing import List, Optional

from app.config import AUDIO_DIR
from app.services.term_corrector import corrector
from app.services.transcriber import transcriber, ASRSegment

logger = logging.getLogger(__name__)

# Audio parameters
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # int16
MS_PER_BYTE = 1000 / (SAMPLE_RATE * BYTES_PER_SAMPLE)

# Promote accumulated partial → final after this much silence.
FINAL_SILENCE_MS = 800


class StreamingRecognizer:
    """Per-connection streaming recognizer using FunASR online model.

    Internally holds a ``StreamingASRSession`` (``paraformer-zh-streaming``)
    that feeds audio in ~600 ms strides and returns only incremental new text.
    """

    def __init__(
        self,
        session_id: str,
        course_title: str = "",
        keywords: Optional[list] = None,
    ):
        self.session_id = session_id
        self.course_title = course_title or ""
        self.keywords = keywords or []

        # Full recording for WAV export
        self.audio_buffer = bytearray()

        # State
        self.is_paused = False
        self.is_ended = False

        # Results
        self.final_segments: list[ASRSegment] = []
        self.partial_text = ""
        self.all_timestamps: list[dict] = []
        self._session_start_ms = 0.0
        self._last_final_at_ms = 0.0
        self._total_ms = 0.0

        # FunASR streaming session (lazy init)
        self._asr_session = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed_pcm(self, pcm_bytes: bytes) -> list[dict]:
        """Feed one frame of PCM int16 audio.  Returns events to emit.

        Events are dicts with keys: type (partial|final), text,
        start_ms, end_ms.
        """
        if self.is_paused or self.is_ended:
            return []

        self.audio_buffer.extend(pcm_bytes)
        frame_ms = len(pcm_bytes) * MS_PER_BYTE
        self._total_ms += frame_ms

        # Lazy-init the streaming model session
        if self._asr_session is None:
            try:
                self._asr_session = transcriber.create_streaming_session()
            except Exception as exc:
                logger.error("streaming_session_init_failed session_id=%s error=%s", self.session_id, exc)
                return []

        events: list[dict] = []

        # Feed to the streaming model
        new_text, is_final_seg = self._asr_session.feed_pcm(pcm_bytes)

        if new_text:
            self.partial_text += new_text
            events.append({
                "type": "partial",
                "text": self.partial_text,
                "start_ms": int(self._session_start_ms),
                "end_ms": int(self._total_ms),
            })

        if is_final_seg and self.partial_text:
            seg = ASRSegment(
                text=self.partial_text,
                start_ms=int(self._session_start_ms),
                end_ms=int(self._last_final_at_ms or self._total_ms),
            )
            self.final_segments.append(seg)
            self.all_timestamps.append(seg.to_dict())
            events.append({
                "type": "final",
                "text": self.partial_text,
                "start_ms": int(self._session_start_ms),
                "end_ms": int(self._total_ms),
            })
            self.partial_text = ""
            self._session_start_ms = self._total_ms
            self._last_final_at_ms = self._total_ms

        return events

    def pause(self) -> None:
        self.is_paused = True

    def resume(self) -> None:
        self.is_paused = False

    def flush_partial(self) -> list[dict]:
        """Promote the current pending partial text to final events.

        Used when the user manually pauses recording: the streaming model
        may not have detected enough silence to emit a final segment, so we
        force-commit whatever is buffered so the UI doesn't lose the last
        spoken words.  We also flush the underlying ASR session accumulator
        so that the next utterance after resume doesn't duplicate this text.
        """
        events: list[dict] = []

        # Prefer the ASR session's accumulated text; it is the authoritative
        # pending partial.  Fall back to our own partial_text if session is None.
        flushed_segments: list[ASRSegment] = []
        if self._asr_session:
            flushed_segments = self._asr_session.flush()

        if not flushed_segments and self.partial_text:
            flushed_segments.append(
                ASRSegment(
                    text=self.partial_text,
                    start_ms=int(self._session_start_ms),
                    end_ms=int(self._total_ms),
                )
            )

        for seg in flushed_segments:
            self.final_segments.append(seg)
            self.all_timestamps.append(seg.to_dict())
            events.append({
                "type": "final",
                "text": seg.text,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
            })

        self.partial_text = ""
        self._session_start_ms = self._total_ms
        self._last_final_at_ms = self._total_ms
        return events

    def finalize(self) -> dict:
        """End of stream: flush remaining audio, do local cleanup, and return payload.

        DeepSeek finalization is deferred to the audio-finish endpoint so that
        the unified restructure runs on the complete session transcript.
        """
        self.is_ended = True

        # Flush any remaining buffered text from the streaming session
        if self._asr_session:
            flush_segments = self._asr_session.finalize()
            for seg in flush_segments:
                if self.partial_text:
                    seg.text = self.partial_text + seg.text
                    self.partial_text = ""
                self.final_segments.append(seg)
                self.all_timestamps.append(seg.to_dict())

        # Also commit dangling partial text
        if self.partial_text:
            self.final_segments.append(
                ASRSegment(
                    text=self.partial_text,
                    start_ms=int(self._session_start_ms),
                    end_ms=int(self._total_ms),
                )
            )
            self.partial_text = ""

        # Deduplicate overlapping finals
        deduped = corrector.dedupe_stream_finals(self.final_segments)
        self.final_segments = deduped

        raw_text = "\n\n".join(seg.text for seg in self.final_segments)

        # Tier 2: local deterministic cleanup — ALWAYS runs
        local_display = corrector.clean_transcript_for_display(raw_text).strip() or raw_text

        # Tier 3 is deferred to audio-finish / restructure endpoint
        display_text = local_display
        corrected_text = None
        is_ai_corrected = False
        correction_error = None

        # Save full audio WAV
        self._save_audio_wav()

        # Build return payload (caller saves to DB)
        transcript_entry = {
            "chunk_index": 0,
            "text": display_text,
            "raw_text": raw_text,
            "display_text": display_text,
            "corrected_text": corrected_text,
            "timestamps": self.all_timestamps,
            "is_corrected": display_text != raw_text,
            "is_ai_corrected": is_ai_corrected,
            "correction_error": correction_error,
            "is_restructured": False,
            "correction_stage": "local",
        }

        note_payload = {
            "transcript": [transcript_entry],
            "audio_saved": bool(self.audio_buffer),
            "session_id": self.session_id,
        }

        logger.info(
            "streaming_finalize session_id=%s final_segments=%s display_chars=%s",
            self.session_id,
            len(self.final_segments),
            len(display_text),
        )
        return note_payload

    def cleanup(self) -> None:
        """Release resources."""
        self.is_ended = True
        if self._asr_session:
            try:
                self._asr_session.finalize()
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
            self._asr_session = None
        self.audio_buffer = bytearray()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save_audio_wav(self) -> None:
        if not self.audio_buffer:
            return
        try:
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            output_path = AUDIO_DIR / f"{self.session_id}.wav"

            # Read existing audio data if present and concatenate
            existing_frames = bytearray()
            if output_path.exists():
                try:
                    with wave.open(str(output_path), "rb") as wf:
                        existing_frames = bytearray(wf.readframes(wf.getnframes()))
                except Exception:
                    logger.warning("suppressed_exception", exc_info=True)

            combined = existing_frames + self.audio_buffer

            with wave.open(str(output_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(BYTES_PER_SAMPLE)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(combined)
            logger.info(
                "streaming_audio_saved session_id=%s path=%s existing_bytes=%s new_bytes=%s total_bytes=%s",
                self.session_id, output_path, len(existing_frames), len(self.audio_buffer), len(combined),
            )
        except Exception as exc:
            logger.warning("streaming_audio_save_failed session_id=%s error=%s", self.session_id, exc)


class StreamingASRManager:
    """Global singleton managing active StreamingRecognizers."""

    _instance: Optional["StreamingASRManager"] = None
    _recognizers: dict[str, StreamingRecognizer]
    _lock = threading.Lock()

    def __new__(cls) -> "StreamingASRManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._recognizers = {}
        return cls._instance

    def create_recognizer(
        self,
        session_id: str,
        course_title: str = "",
        keywords: Optional[list] = None,
    ) -> StreamingRecognizer:
        rec = StreamingRecognizer(
            session_id=session_id,
            course_title=course_title,
            keywords=keywords,
        )
        with self._lock:
            self._recognizers[session_id] = rec
        logger.info("streaming_recognizer_created session_id=%s", session_id)
        return rec

    def get_recognizer(self, session_id: str) -> Optional[StreamingRecognizer]:
        with self._lock:
            return self._recognizers.get(session_id)

    def remove_recognizer(self, session_id: str) -> None:
        with self._lock:
            rec = self._recognizers.pop(session_id, None)
        if rec:
            rec.cleanup()
            logger.info("streaming_recognizer_removed session_id=%s", session_id)
