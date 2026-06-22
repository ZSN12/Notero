import os
import tempfile
import logging
from pathlib import Path
from typing import List, Optional
import numpy as np
from app.config import DASHSCOPE_API_KEY, FUNASR_MODEL_DIR, FUNASR_MODEL_NAME, FUNASR_VAD_MODEL, FUNASR_PUNC_MODEL

logger = logging.getLogger(__name__)

try:
    from funasr import AutoModel
    _FUNASR_AVAILABLE = True
except ImportError:
    _FUNASR_AVAILABLE = False
    logger.warning("FunASR not available, will use cloud ASR fallback")

try:
    from dashscope.audio import asr
    _DASHSCOPE_ASR_AVAILABLE = True
except ImportError:
    _DASHSCOPE_ASR_AVAILABLE = False
    logger.warning("DashScope ASR not available")


class ASRSegment:
    """Single transcribed segment with timestamps."""
    def __init__(self, text: str, start_ms: int, end_ms: int):
        self.text = text
        self.start_ms = start_ms
        self.end_ms = end_ms

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }


def _resolve_funasr_model(name: str) -> str:
    """Return a local/cache path for a FunASR model id when available.

    Priority:
      1. <FUNASR_MODEL_DIR>/<name>
      2. Standard ModelScope cache folder (~/.cache/modelscope/hub/models/iic/...)
      3. The original model id (lets FunASR download if needed)
    """
    explicit = os.path.join(FUNASR_MODEL_DIR, name)
    if os.path.exists(explicit):
        return explicit

    cache_root = Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic"
    if not cache_root.exists():
        return name

    # Known FunASR default ids -> ModelScope cached folder names
    mapping = {
        "paraformer-zh": "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "fsmn-vad": "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "ct-punc": "punc_ct-transformer_cn-en-common-vocab471067-large",
        "paraformer-zh-streaming": "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    }
    cached_name = mapping.get(name)
    if cached_name:
        cached_path = cache_root / cached_name
        if cached_path.exists():
            return str(cached_path)

    # Best-effort fallback: any cache folder whose name contains the tokenized id
    token = name.replace("-", "_")
    for candidate in cache_root.iterdir():
        if candidate.is_dir() and token in candidate.name:
            return str(candidate)

    return name


class Transcriber:
    """Speech-to-text service with FunASR fallback to DashScope cloud API."""

    def __init__(self):
        self._model = None
        self._model_loaded = False
        self._streaming_model = None
        self._streaming_model_loaded = False

    def _load_model(self):
        if self._model_loaded:
            return
        if _FUNASR_AVAILABLE:
            try:
                model_name = _resolve_funasr_model(FUNASR_MODEL_NAME)
                vad_model_name = _resolve_funasr_model(FUNASR_VAD_MODEL)
                punc_model_name = _resolve_funasr_model(FUNASR_PUNC_MODEL)

                self._model = AutoModel(
                    model=model_name,
                    vad_model=vad_model_name,
                    punc_model=punc_model_name,
                    disable_update=True,
                )
                logger.info(f"FunASR model loaded successfully from: {model_name}")
                self._model_loaded = True
            except Exception as e:
                logger.error(f"FunASR model load failed: {e}", exc_info=True)
                self._model = None

    def _load_streaming_model(self):
        """Lazy-load the streaming (online) model for real-time ASR."""
        if self._streaming_model_loaded:
            return
        if _FUNASR_AVAILABLE:
            try:
                model_name = _resolve_funasr_model("paraformer-zh-streaming")

                self._streaming_model = AutoModel(
                    model=model_name,
                    disable_update=True,
                )
                logger.info(f"FunASR streaming model loaded successfully from: {model_name}")
                self._streaming_model_loaded = True
            except Exception as e:
                logger.error(f"FunASR streaming model load failed: {e}", exc_info=True)
                self._streaming_model = None

    def _transcribe_with_funasr(self, audio_path: str) -> List[ASRSegment]:
        """Use local FunASR model for transcription."""
        if not _FUNASR_AVAILABLE or not os.path.exists(audio_path):
            return []

        self._load_model()
        if not self._model:
            return []

        result = self._model.generate(
            input=audio_path,
            language="zh",
            use_itn=True,
            batch_size_s=120,
        )

        # Debug: log raw FunASR result structure
        if isinstance(result, list) and result:
            sample = result[0]
            ts = sample.get("timestamp", [])
            logger.info("FunASR raw result: text=%r, timestamp_len=%d, first_ts=%r",
                        sample.get("text", "")[:50], len(ts), ts[:3] if ts else None)
        elif isinstance(result, dict):
            ts = result.get("timestamp", [])
            logger.info("FunASR raw result: text=%r, timestamp_len=%d, first_ts=%r",
                        result.get("text", "")[:50], len(ts), ts[:3] if ts else None)

        segments = []
        if isinstance(result, list):
            for item in result:
                segments.extend(self._parse_funasr_result(item))
        elif isinstance(result, dict):
            segments = self._parse_funasr_result(result)

        return segments

    def _transcribe_with_dashscope(self, audio_path: str) -> List[ASRSegment]:
        """Use DashScope cloud ASR API for transcription."""
        if not DASHSCOPE_API_KEY:
            logger.warning("DASHSCOPE_API_KEY not configured, skipping cloud ASR fallback")
            return []

        try:
            from dashscope.audio.asr import Recognition
            recognizer = Recognition(
                model='paraformer-realtime-v2',
                format='webm',
                sample_rate=16000,
                callback=None,
            )
            result = recognizer.call(audio_path)

            if result and hasattr(result, 'output') and result.output:
                segments = []
                for sentence in result.output.get('sentences', []):
                    text = sentence.get('text', '')
                    start_ms = int(sentence.get('begin_time', 0))
                    end_ms = int(sentence.get('end_time', 0))
                    if text.strip():
                        segments.append(ASRSegment(text=text, start_ms=start_ms, end_ms=end_ms))
                return segments
        except Exception as e:
            logger.error(f"DashScope ASR failed: {e}", exc_info=True)
        return []

    def _transcribe_with_whisper_api(self, audio_path: str) -> List[ASRSegment]:
        """Use OpenAI-compatible Whisper API as fallback."""
        if not DASHSCOPE_API_KEY:
            return []

        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

            with open(audio_path, 'rb') as f:
                response = client.audio.transcriptions.create(
                    model="paraformer-v2",
                    file=f,
                    language="zh",
                    response_format="verbose_json",
                )

            segments = []
            if hasattr(response, 'segments'):
                for seg in response.segments:
                    text = seg.get('text', '') if isinstance(seg, dict) else getattr(seg, 'text', '')
                    start = seg.get('start', 0) if isinstance(seg, dict) else getattr(seg, 'start', 0)
                    end = seg.get('end', 0) if isinstance(seg, dict) else getattr(seg, 'end', 0)
                    if text.strip():
                        segments.append(ASRSegment(text=text, start_ms=int(start * 1000), end_ms=int(end * 1000)))
            elif hasattr(response, 'text') and response.text:
                segments.append(ASRSegment(text=response.text.strip(), start_ms=0, end_ms=0))

            return segments
        except Exception as e:
            logger.error(f"Whisper API transcription failed: {e}", exc_info=True)
        return []

    def transcribe(self, audio_path: str) -> List[ASRSegment]:
        """Transcribe audio file to segments with timestamps.

        Tries FunASR first, then DashScope cloud API, then Whisper API.

        Args:
            audio_path: Path to audio file (supports wav, mp3, webm, m4a, flac, ogg).

        Returns:
            List of ASRSegment with text and time info.
        """
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return []

        # Try FunASR first
        if _FUNASR_AVAILABLE:
            logger.debug("Trying FunASR local model...")
            segments = self._transcribe_with_funasr(audio_path)
            if segments:
                return segments
            logger.debug("FunASR returned no results")

        # Try DashScope cloud API
        if DASHSCOPE_API_KEY:
            logger.debug("Trying DashScope cloud ASR...")
            segments = self._transcribe_with_dashscope(audio_path)
            if segments:
                return segments
            logger.debug("DashScope ASR returned no results")

            logger.debug("Trying DashScope Whisper-compatible API...")
            segments = self._transcribe_with_whisper_api(audio_path)
            if segments:
                return segments

        logger.error("All transcription methods failed")
        return []

    def _parse_funasr_result(self, item: dict) -> List[ASRSegment]:
        """Parse FunASR result dict into ASRSegment list.

        FunASR returns timestamps in two shapes:
        - [[start, end, text], ...] → each entry has its own text; emit per-entry.
        - [[start, end], ...]       → only time info; emit a single segment for
          the whole utterance to avoid duplicating ``item["text"]`` N times.
        """
        segments = []
        text = item.get("text", "")
        timestamp = item.get("timestamp", [])

        if not timestamp:
            segments.append(ASRSegment(text=text, start_ms=0, end_ms=0))
            return segments

        # Detect whether each timestamp entry carries its own text token.
        has_per_entry_text = all(len(ts) > 2 for ts in timestamp)

        if has_per_entry_text:
            for ts in timestamp:
                seg_text = ts[2] if len(ts) > 2 else ""
                segments.append(ASRSegment(
                    text=seg_text,
                    start_ms=int(ts[0]),
                    end_ms=int(ts[1]),
                ))
        else:
            # Binary timestamps: single segment covering the full text.
            start_ms = int(timestamp[0][0])
            end_ms = int(timestamp[-1][1])
            segments.append(ASRSegment(text=text, start_ms=start_ms, end_ms=end_ms))

        return segments

    def create_streaming_session(self) -> "StreamingASRSession":
        """Create a new real-time streaming ASR session.

        Uses ``paraformer-zh-streaming`` with incremental decode and a
        persistent ``cache`` so the model never re-emits already-output text.
        """
        self._load_streaming_model()
        if not self._streaming_model:
            raise RuntimeError("Streaming model not available")
        return StreamingASRSession(self._streaming_model)


class StreamingASRSession:
    """Per-connection streaming ASR using FunASR online model.

    Buffers incoming PCM frames (int16 @ 16kHz) until a full chunk stride
    (600 ms) is reached, then feeds it to the streaming model.  The model
    ``cache`` is kept alive for the lifetime of the session so text is never
    duplicated across chunks.
    """

    # 600 ms @ 16 kHz, int16 = 2 bytes / sample
    CHUNK_STRIDE_SAMPLES = 9600
    BYTES_PER_CHUNK = CHUNK_STRIDE_SAMPLES * 2
    # If no new text arrives for this long, treat accumulated text as a final segment.
    SILENCE_FINALIZE_MS = 800

    def __init__(self, model):
        self._model = model
        self._cache = {}
        self._buffer = bytearray()
        self._accumulated_text = ""
        self._last_text_at_ms = 0.0
        self._session_start_ms = 0.0
        self._total_ms = 0.0
        self._final_segments: list[ASRSegment] = []

    # ── public API ──

    def feed_pcm(self, pcm_bytes: bytes) -> tuple[str, bool]:
        """Feed one or more PCM frames.  Returns (new_text, is_final_segment).

        ``new_text`` is the incremental text recognized since the last call.
        ``is_final_segment`` is True when accumulated text was promoted to a
        final segment because of detected silence.
        """
        self._buffer.extend(pcm_bytes)
        frame_ms = len(pcm_bytes) / 2 / 16  # int16 samples / 16000 Hz
        self._total_ms += frame_ms

        new_parts: list[str] = []
        is_final = False

        while len(self._buffer) >= self.BYTES_PER_CHUNK:
            chunk_bytes = self._buffer[: self.BYTES_PER_CHUNK]
            self._buffer = self._buffer[self.BYTES_PER_CHUNK :]
            chunk = np.frombuffer(chunk_bytes, dtype=np.int16)
            text = self._recognize_chunk(chunk, is_final=False)
            if text:
                new_parts.append(text)
                self._last_text_at_ms = self._total_ms

        # Promote accumulated text to a final segment if speaker has been
        # silent for longer than SILENCE_FINALIZE_MS.
        if (
            self._accumulated_text
            and self._total_ms - self._last_text_at_ms > self.SILENCE_FINALIZE_MS
        ):
            is_final = True
            self._final_segments.append(
                ASRSegment(
                    text=self._accumulated_text,
                    start_ms=int(self._session_start_ms),
                    end_ms=int(self._last_text_at_ms),
                )
            )
            self._accumulated_text = ""
            self._session_start_ms = self._total_ms

        new_text = "".join(new_parts)
        if new_text:
            self._accumulated_text += new_text

        return new_text, is_final

    def flush(self) -> list[ASRSegment]:
        """Force-commit accumulated partial text as final segments without ending the session.

        Used when the user manually pauses recording: the streaming model may not
        have detected enough silence to emit a final segment, so we promote the
        buffered text and reset the accumulator so the next utterance starts fresh.
        """
        flushed: list[ASRSegment] = []
        if self._accumulated_text:
            flushed.append(
                ASRSegment(
                    text=self._accumulated_text,
                    start_ms=int(self._session_start_ms),
                    end_ms=int(self._total_ms),
                )
            )
            self._accumulated_text = ""
            self._session_start_ms = self._total_ms
        return flushed

    def finalize(self) -> list[ASRSegment]:
        """End of stream: flush remaining buffer and return all final segments."""
        if self._buffer:
            chunk = np.frombuffer(self._buffer, dtype=np.int16)
            text = self._recognize_chunk(chunk, is_final=True)
            if text:
                self._accumulated_text += text
            self._buffer = bytearray()

        if self._accumulated_text:
            self._final_segments.append(
                ASRSegment(
                    text=self._accumulated_text,
                    start_ms=int(self._session_start_ms),
                    end_ms=int(self._total_ms),
                )
            )
            self._accumulated_text = ""

        # Clear model cache so the next session starts fresh.
        self._cache = {}
        return list(self._final_segments)

    # ── internal ──

    def _recognize_chunk(self, chunk: object, is_final: bool) -> str:
        try:
            res = self._model.generate(
                input=chunk,
                cache=self._cache,
                is_final=is_final,
                chunk_size=[0, 10, 5],
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
            )
            if res and isinstance(res, list):
                return res[0].get("text", "")
        except Exception as exc:
            logger.warning("streaming_recognize_chunk_failed error=%s", exc)
        return ""


# Singleton instance
transcriber = Transcriber()
