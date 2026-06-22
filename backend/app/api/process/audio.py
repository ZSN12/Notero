import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import wave

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Note, Session as DBSession, Notebook, User
from app.services.transcriber import transcriber, _FUNASR_AVAILABLE
from app.services.term_corrector import corrector
from app.services.state_service import set_running, set_ready, set_error, set_fallback
from app.services.vector_service import build_session_index, _compute_session_content_hash
from app.middleware.metrics import observe_asr_processing
from app.config import AUDIO_DIR, DASHSCOPE_API_KEY

MAX_AUDIO_CHUNK_SIZE = 50 * 1024 * 1024  # 50MB
MAX_FULL_AUDIO_SIZE = 500 * 1024 * 1024  # 500MB
MAX_CHUNK_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB per chunk for resumable upload

ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/flac",
    "audio/x-flac",
    "application/octet-stream",
}
logger = logging.getLogger(__name__)

from app.api.process.transcript import finalize_session_transcript
import re

# Validate session_id is a UUID before using it in filesystem paths
_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

def _validate_session_id(sid: str) -> str:
    if not _UUID_RE.match(sid):
        raise HTTPException(status_code=400, detail='Invalid session_id format')
    return sid



def _check_asr_available() -> bool:
    """Check if any ASR service is available."""
    return _FUNASR_AVAILABLE or bool(DASHSCOPE_API_KEY)

router = APIRouter()


class FinalizeTranscriptRequest(BaseModel):
    auto_generate: bool = True
    force: bool = False
    retry_failed_only: bool = False


async def _correct_window_for_stream(
    raw_text: str,
    course_title: str,
    keywords: list,
    ppt_slides: list | None = None,
    timeout_seconds: float = 25.0,
) -> dict:
    """Prepare one ASR window for SSE display.

    Always returns display text. DeepSeek is best-effort; local deterministic
    cleanup is the fallback when the API is unavailable, slow, or rejects.
    """
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return {
            "text": "",
            "raw_text": raw_text or "",
            "is_ai_corrected": False,
            "correction_error": None,
        }

    try:
        local_text = corrector.clean_transcript_for_display(cleaned).strip() or cleaned
    except Exception as exc:
        logger.warning(
            "audio_batch_local_cleanup_failed error_type=%s error=%s",
            type(exc).__name__, exc,
            exc_info=True,
        )
        local_text = cleaned

    if not getattr(corrector, "has_llm", False):
        return {
            "text": local_text,
            "raw_text": cleaned,
            "is_ai_corrected": False,
            "correction_error": "未配置 DeepSeek API，已使用本地整理",
        }

    try:
        logger.info(
            "correct_window_llm_start text_len=%s course=%s keywords=%s",
            len(local_text), course_title, len(keywords),
        )
        ai_text = await asyncio.wait_for(
            asyncio.to_thread(
                corrector.restructure_transcript,
                local_text,
                course_title,
                keywords,
                ppt_slides,
            ),
            timeout=timeout_seconds,
        )
        ai_text = (ai_text or "").strip()
        logger.info(
            "correct_window_llm_done text_len=%s ai_len=%s",
            len(local_text), len(ai_text),
        )
        if not ai_text:
            raise ValueError("DeepSeek returned empty text")

        ai_display = corrector.clean_transcript_for_display(ai_text).strip() or ai_text
        return {
            "text": ai_display,
            "raw_text": cleaned,
            "is_ai_corrected": ai_display != local_text,
            "correction_error": None,
        }
    except asyncio.TimeoutError:
        return {
            "text": local_text,
            "raw_text": cleaned,
            "is_ai_corrected": False,
            "correction_error": "DeepSeek 纠正超时，已使用本地整理",
        }
    except Exception as exc:
        logger.warning(
            "audio_batch_ai_correction_failed error_type=%s error=%s",
            type(exc).__name__, exc,
            exc_info=True,
        )
        return {
            "text": local_text,
            "raw_text": cleaned,
            "is_ai_corrected": False,
            "correction_error": "AI 整理失败，已使用本地整理",
        }


async def _finalize_display_text_for_stream(
    raw_text: str,
    display_source: str,
    course_title: str,
    keywords: list,
    ppt_slides: list | None = None,
    timeout_seconds: float = 45.0,
) -> dict:
    """Produce the final display transcript from the whole recording.

    Three-tier fallback:
      1. raw_text       — ASR original (preserved as-is)
      2. display_text   — deterministic local cleanup (always runs)
      3. corrected_text — DeepSeek enhancement (best-effort, never blocks)

    On any DeepSeek failure, timeout, or content-rejection, returns
    display_text = local_clean, corrected_text = None, and a uniform
    correction_error so callers never fall back to raw ASR.
    """
    raw = (raw_text or "").strip()
    source = (display_source or raw).strip()
    if not source:
        return {
            "display_text": "",
            "corrected_text": None,
            "is_ai_corrected": False,
            "correction_error": None,
        }

    # Tier 2 — local deterministic cleanup (always runs)
    try:
        local_display = corrector.clean_transcript_for_display(source).strip() or source
    except Exception as exc:
        logger.warning(
            "audio_batch_final_local_cleanup_failed error_type=%s error=%s",
            type(exc).__name__, exc,
            exc_info=True,
        )
        local_display = source

    display_text = local_display
    corrected_text = None
    is_ai_corrected = False
    correction_error = None

    # Tier 3 — DeepSeek enhancement (best-effort)
    if not getattr(corrector, "has_llm", False):
        correction_error = "AI 整理失败"
    else:
        try:
            ai_text = await asyncio.wait_for(
                asyncio.to_thread(
                    corrector.restructure_transcript,
                    local_display,
                    course_title,
                    keywords,
                    ppt_slides,
                ),
                timeout=timeout_seconds,
            )
            ai_text = (ai_text or "").strip()
            if not ai_text:
                raise ValueError("DeepSeek returned empty final text")

            ai_display = corrector.clean_transcript_for_display(ai_text).strip() or ai_text
            display_text = ai_display
            corrected_text = ai_display
            is_ai_corrected = True
        except asyncio.TimeoutError:
            correction_error = "AI 整理失败"
        except Exception as exc:
            logger.warning(
                "audio_batch_final_ai_cleanup_failed error_type=%s error=%s",
                type(exc).__name__, exc,
                exc_info=True,
            )
            correction_error = "AI 整理失败"

    return {
        "display_text": display_text,
        "corrected_text": corrected_text,
        "is_ai_corrected": is_ai_corrected,
        "correction_error": correction_error,
    }


def _merge_segments_to_chunks(segments, max_speech_ms=8000):
    chunks = []
    current = []
    current_ms = 0
    for seg in segments:
        if not current:
            current.append(seg)
            current_ms = seg.end_ms - seg.start_ms
            continue
        gap = seg.start_ms - current[-1].end_ms
        add_ms = seg.end_ms - seg.start_ms
        if gap > 500 or current_ms + add_ms > max_speech_ms:
            chunks.append(current)
            current = [seg]
            current_ms = add_ms
        else:
            current.append(seg)
            current_ms += add_ms
    if current:
        chunks.append(current)
    return chunks


def _cleanup_temp_files(temp_path: str, wav_path: str | None) -> None:
    if os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)
    if wav_path and os.path.exists(wav_path):
        try:
            os.unlink(wav_path)
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)


async def _generate_audio_sse(
    session_id: str,
    process_path: str,
    temp_path: str,
    wav_path: str | None,
    course_title: str,
    keywords: list,
    ppt_slides: list | None,
):
    """Async generator that transcribes audio and yields SSE events."""
    from app.core.database import SessionLocal

    def _state_running(progress=0.0, message=None):
        db = SessionLocal()
        try:
            set_running(db, session_id, "upload_transcribe", progress=progress, message=message)
        finally:
            db.close()

    def _state_ready():
        db = SessionLocal()
        try:
            set_ready(db, session_id, "upload_transcribe")
        finally:
            db.close()

    def _state_error(error_message):
        db = SessionLocal()
        try:
            set_error(db, session_id, "upload_transcribe", error_message)
        finally:
            db.close()

    _state_running(0.0, "开始识别语音")

    # Save persistent audio (concatenate with existing if present)
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_output = AUDIO_DIR / f"{session_id}.wav"
        def _copy_or_concat_audio():
            src_path = process_path if process_path == wav_path else temp_path
            if audio_output.exists():
                temp_concat = str(audio_output) + ".concat.wav"
                try:
                    concatenate_wav_files([str(audio_output), src_path], temp_concat)
                    os.replace(temp_concat, str(audio_output))
                except Exception as concat_err:
                    logger.warning("audio_concat_failed session_id=%s error=%s, falling back to overwrite", session_id, concat_err)
                    with open(src_path, "rb") as src, open(audio_output, "wb") as dst:
                        dst.write(src.read())
            else:
                with open(src_path, "rb") as src, open(audio_output, "wb") as dst:
                    dst.write(src.read())
        await asyncio.to_thread(_copy_or_concat_audio)
        logger.info("audio_batch_saved_audio session_id=%s path=%s", session_id, audio_output)
    except Exception as save_err:
        logger.warning("audio_batch_save_audio_failed session_id=%s error=%s", session_id, save_err, exc_info=True)

    yield f"data: {json.dumps({'type': 'status', 'message': '开始识别语音', 'segment': 0, 'total': 1}, ensure_ascii=False)}\n\n"

    import time
    asr_start = time.perf_counter()
    try:
        all_segments = await asyncio.to_thread(transcriber.transcribe, process_path)
        observe_asr_processing("funasr" if _FUNASR_AVAILABLE else "dashscope", time.perf_counter() - asr_start)
    except Exception as e:
        observe_asr_processing("funasr" if _FUNASR_AVAILABLE else "dashscope", time.perf_counter() - asr_start)
        logger.warning("audio_batch_transcribe_failed session_id=%s error=%s", session_id, e)
        all_segments = []

    if not all_segments:
        logger.warning("audio_batch_no_text session_id=%s", session_id)
        _state_error("未识别到语音内容，请检查音频格式、音量或 ASR 配置")
        yield f"data: {json.dumps({'type': 'error', 'detail': '未识别到语音内容，请检查音频格式、音量或 ASR 配置'}, ensure_ascii=False)}\n\n"
        _cleanup_temp_files(temp_path, wav_path)
        return

    logger.info(
        "audio_batch_whole_transcribe session_id=%s segments=%s",
        session_id, len(all_segments),
    )

    chunks = _merge_segments_to_chunks(all_segments, max_speech_ms=8000)
    total_chunks = len(chunks)

    raw_parts = []
    display_parts = []
    all_timestamps = []

    for i, chunk in enumerate(chunks):
        chunk_text = " ".join(seg.text for seg in chunk).strip()
        if not chunk_text:
            continue

        raw_parts.append(chunk_text)
        all_timestamps.extend(seg.to_dict() for seg in chunk)

        cleaned = corrector.clean_transcript_for_display(chunk_text).strip()
        if not cleaned:
            continue

        history = "\n\n".join(display_parts)
        display_text = corrector.prepare_stream_chunk(cleaned, history).strip()
        if not display_text:
            logger.info("audio_batch_chunk_deduped session_id=%s chunk=%s", session_id, i + 1)
            continue

        display_parts.append(display_text)

        _state_running(progress=min(0.9, (i + 1) / max(total_chunks, 1)), message="转写中...")

        yield f"data: {json.dumps({'type': 'chunk', 'text': display_text, 'segment': i + 1, 'segment_total': total_chunks, 'is_ai_corrected': False, 'is_final': False}, ensure_ascii=False)}\n\n"

    # Local cleanup only; unified DeepSeek restructure happens after all files
    yield f"data: {json.dumps({'type': 'status', 'message': '已保存本地转写', 'segment': total_chunks, 'total': total_chunks}, ensure_ascii=False)}\n\n"

    raw_text = "\n\n".join(raw_parts)
    display_source = "\n\n".join(display_parts)
    if not display_source:
        display_source = corrector.clean_transcript_for_display(raw_text).strip() or raw_text

    display_text = display_source  # local cleanup only, no per-file DeepSeek

    transcript_data = [{
        "chunk_index": 0,
        "text": display_text,
        "raw_text": raw_text,
        "display_text": display_text,
        "corrected_text": None,
        "timestamps": all_timestamps,
        "is_corrected": display_text != raw_text,
        "is_ai_corrected": False,
        "correction_error": None,
        "is_restructured": False,
        "correction_stage": "local",
    }]
    transcript_blocks = [
        {
            "id": f"transcript-{i + 1}",
            "type": "transcript",
            "content": part.strip(),
        }
        for i, part in enumerate(display_text.split("\n\n"))
        if part.strip()
    ]

    def _notes_content_from_existing(content):
        existing = (content or "").strip()
        if not existing:
            return ""
        marker = "\n\n---\n\n"
        if existing.startswith("## 语音转文字"):
            return existing.split(marker, 1)[1].strip() if marker in existing else ""
        return existing

    def _transcript_content_from_existing(content):
        existing = (content or "").strip()
        if not existing:
            return ""
        if existing.startswith("## 语音转文字"):
            marker = "\n\n---\n\n"
            if marker in existing:
                transcript_part = existing.split(marker, 1)[0].strip()
            else:
                transcript_part = existing.strip()
            if transcript_part.startswith("## 语音转文字"):
                transcript_part = transcript_part[len("## 语音转文字"):].strip()
            return transcript_part
        return ""

    def _serialize_note(note):
        return {
            "id": note.id,
            "session_id": note.session_id,
            "content": note.content or "",
            "transcript": note.transcript,
            "ppt_images": note.ppt_images or [],
            "vocabulary": note.vocabulary or [],
            "layout_blocks": note.layout_blocks or [],
            "created_at": note.created_at.isoformat() if note.created_at else None,
        }

    def _save():
        from app.core.database import SessionLocal
        sav_db = SessionLocal()
        try:
            existing_note = sav_db.query(Note).filter(Note.session_id == session_id).first()
            if existing_note:
                notes_content = _notes_content_from_existing(existing_note.content)
                existing_transcript_text = _transcript_content_from_existing(existing_note.content)

                # Combine transcript text (append new to existing)
                if existing_transcript_text:
                    combined_transcript_text = f"{existing_transcript_text}\n\n{display_text}".strip()
                else:
                    combined_transcript_text = display_text

                # Build content
                if notes_content:
                    existing_note.content = f"## 语音转文字\n\n{combined_transcript_text}\n\n---\n\n{notes_content}".strip()
                else:
                    existing_note.content = f"## 语音转文字\n\n{combined_transcript_text}".strip()

                # Append transcript entries with correct chunk_index
                # Use list() copy so SQLAlchemy detects the mutation
                existing_transcript = list(existing_note.transcript or [])
                base_index = len(existing_transcript)
                for i, entry in enumerate(transcript_data):
                    entry["chunk_index"] = base_index + i
                existing_transcript.extend(transcript_data)
                existing_note.transcript = existing_transcript

                # Rebuild layout blocks from combined transcript to keep consistency
                existing_note_blocks = list(existing_note.layout_blocks or [])
                note_blocks = [
                    block for block in existing_note_blocks
                    if isinstance(block, dict) and block.get("type") == "note"
                ]
                all_transcript_blocks = [
                    {
                        "id": f"transcript-{i + 1}",
                        "type": "transcript",
                        "content": part.strip(),
                    }
                    for i, part in enumerate(combined_transcript_text.split("\n\n"))
                    if part.strip()
                ]
                existing_note.layout_blocks = all_transcript_blocks + note_blocks
                sav_db.commit()
                sav_db.refresh(existing_note)
                return _serialize_note(existing_note)
            else:
                note = Note(
                    session_id=session_id,
                    content=f"## 语音转文字\n\n{display_text}".strip(),
                    transcript=transcript_data,
                    ppt_images=[],
                    vocabulary=[],
                )
                note.layout_blocks = transcript_blocks
                sav_db.add(note)
                sav_db.commit()
                sav_db.refresh(note)
                return _serialize_note(note)
        finally:
            sav_db.close()

    try:
        saved_note = await asyncio.to_thread(_save)
        logger.info(
            "audio_batch_saved session_id=%s raw_chars=%s display_chars=%s chunks=%s",
            session_id, len(raw_text), len(display_text), total_chunks,
        )
        _state_ready()
        yield f"data: {json.dumps({'type': 'done', 'note': saved_note}, ensure_ascii=False)}\n\n"
    except Exception as db_err:
        logger.exception("audio_batch_db_save_failed session_id=%s", session_id)
        _state_error(f"保存转写结果失败: {db_err}")
        yield f"data: {json.dumps({'type': 'error', 'detail': f'Failed to save: {db_err}'})}\n\n"

    _cleanup_temp_files(temp_path, wav_path)


def _find_ffmpeg() -> str | None:
    """Find ffmpeg executable, trying multiple known locations.

    The ffmpeg bundled by imageio_ffmpeg lives deep in site-packages and is
    typically not on the system PATH when running from a server subprocess.
    """
    candidates = [
        "ffmpeg",  # hope PATH works
        "ffmpeg.exe",
    ]
    # Add imageio_ffmpeg bundled binary if available
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p:
            candidates.append(p)
    except Exception:
        logger.warning("suppressed_exception", exc_info=True)

    for c in candidates:
        if shutil.which(c):
            return c
        if os.path.isfile(c):
            return c
    return None


def concatenate_wav_files(wav_paths: list[str], output_path: str) -> None:
    """Concatenate multiple WAV files into a single WAV file.

    Streams data in chunks instead of loading all WAV data into memory.
    """
    if not wav_paths:
        return

    # Read header from first file
    try:
        with wave.open(wav_paths[0], 'rb') as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            total_frames = 0
            for path in wav_paths:
                try:
                    with wave.open(path, 'rb') as pf:
                        total_frames += pf.getnframes()
                except Exception:
                    logger.warning("suppressed_exception", exc_info=True)
    except Exception:
        logger.exception("audio_concat_read_header_failed")
        return

    if total_frames == 0:
        return

    # Write output, streaming each file's data frame-by-frame
    CHUNK_FRAMES = 4096
    with wave.open(output_path, 'wb') as out_wf:
        out_wf.setnchannels(num_channels)
        out_wf.setsampwidth(sample_width)
        out_wf.setframerate(sample_rate)
        for path in wav_paths:
            try:
                with wave.open(path, 'rb') as in_wf:
                    while True:
                        data = in_wf.readframes(CHUNK_FRAMES)
                        if not data:
                            break
                        out_wf.writeframes(data)
            except Exception:
                logger.warning("audio_concat_read_file_failed path=%s", path, exc_info=True)


@router.post("/audio-stream")
async def stream_audio_process(
    file: UploadFile = File(...),
    session_id: str = "",
    chunk_index: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Process an audio chunk: transcribe + save + schedule async correction.

    Args:
        file: Audio chunk (webm format from browser).
        session_id: The session ID to save the result to.
        chunk_index: Which chunk this is (for ordering).
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    logger.info("audio_stream_received session_id=%s user_id=%s chunk_index=%s", session_id, current_user.id, chunk_index)

    # Verify session exists and belongs to user
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        logger.warning("audio_stream_session_denied session_id=%s user_id=%s", session_id, current_user.id)
        raise HTTPException(status_code=404, detail="Session not found")

    # Get course context
    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    course_title = notebook.title if notebook else ""
    keywords = session.keywords or []
    logger.info("audio_stream_context session_id=%s course_title=%s keyword_count=%s", session_id, course_title, len(keywords))

    # Validate MIME type before reading full content
    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format: {file.content_type}. Allowed: audio/webm, audio/wav, audio/mpeg, etc."
        )

    # Save audio chunk temporarily for transcription
    # Pre-check: read size without reading full content
    audio_bytes = await file.read()
    file_size = len(audio_bytes)
    if file_size > MAX_AUDIO_CHUNK_SIZE:
        raise HTTPException(status_code=413, detail=f"Chunk too large: {file_size} bytes (max {MAX_AUDIO_CHUNK_SIZE} bytes)")

    logger.info("audio_chunk_size session_id=%s chunk_index=%s bytes=%s", session_id, chunk_index, file_size)

    # Save chunk to session audio dir for later concatenation
    chunk_dir = AUDIO_DIR / session_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunk_dir / f"chunk_{chunk_index:04d}.wav"
    with open(chunk_path, 'wb') as f:
        f.write(audio_bytes)

    # Save wav to temp file for transcription
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        audio_path = f.name
        logger.debug("audio_chunk_temp_saved session_id=%s chunk_index=%s path=%s", session_id, chunk_index, audio_path)

    try:
        # Step 1: Transcribe with FunASR
        logger.info("audio_chunk_transcribe_start session_id=%s chunk_index=%s", session_id, chunk_index)
        import time
        asr_start = time.perf_counter()
        try:
            segments = transcriber.transcribe(audio_path)
            observe_asr_processing("funasr" if _FUNASR_AVAILABLE else "dashscope", time.perf_counter() - asr_start)
        except Exception as transcribe_error:
            observe_asr_processing("funasr" if _FUNASR_AVAILABLE else "dashscope", time.perf_counter() - asr_start)
            logger.exception("audio_chunk_transcribe_failed session_id=%s chunk_index=%s", session_id, chunk_index)
            segments = []

        if not segments:
            logger.warning("audio_chunk_empty_transcript session_id=%s chunk_index=%s", session_id, chunk_index)
            result = {
                "chunk_index": chunk_index,
                "original": "",
                "corrected": "",
                "timestamps": [],
                "course_title": course_title,
            }
        else:
            segments = corrector.dedupe_asr_segments(segments)
            logger.info("audio_chunk_transcribe_success session_id=%s chunk_index=%s segment_count=%s", session_id, chunk_index, len(segments))

            # Step 2: Local cleanup for immediate display; final AI correction happens at stop
            raw_text = " ".join(seg.text for seg in segments)
            try:
                display_text = corrector.clean_transcript_for_display(raw_text).strip() or raw_text
            except Exception:
                display_text = raw_text

            result = {
                "chunk_index": chunk_index,
                "original": raw_text,
                "corrected": display_text,
                "timestamps": [seg.to_dict() for seg in segments],
                "course_title": course_title,
            }

        # Return JSON response (no per-chunk DB save — finalization happens on audio-finish)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("audio_stream_unexpected_error session_id=%s chunk_index=%s", session_id, chunk_index)
        # Return empty result instead of 500 to keep streaming alive
        result = {
            "chunk_index": chunk_index,
            "original": "",
            "corrected": "",
            "timestamps": [],
            "course_title": course_title,
            "error": str(e),
        }
        return result
    finally:
        try:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)


@router.post("/audio-finish")
async def finish_recording(
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Concatenate recording chunks without running AI finalization.

    Real-time recording remains user-controlled: stopping saves audio and the
    current transcript; the explicit AI organize action calls transcript-finalize.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    chunk_dir = AUDIO_DIR / session_id
    if not chunk_dir.exists():
        return {"status": "no_audio", "audio_path": None}

    chunk_files = sorted(chunk_dir.glob("chunk_*.wav"))
    if not chunk_files:
        return {"status": "no_chunks", "audio_path": None}

    output_path = AUDIO_DIR / f"{session_id}.wav"
    set_running(db, session_id, "recording_finalize", message="正在整理录音...", commit=False)
    try:
        concatenate_wav_files([str(p) for p in chunk_files], str(output_path))
        # Clean up individual chunks
        for chunk_file in chunk_files:
            try:
                chunk_file.unlink()
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
        try:
            chunk_dir.rmdir()
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)

        set_ready(db, session_id, "recording_finalize", commit=False)
        db.commit()
        return {"status": "finished", "audio_path": str(output_path), "note": None}
    except Exception as e:
        logger.exception("audio_finish_failed session_id=%s user_id=%s", session_id, current_user.id)
        set_error(db, session_id, "recording_finalize", error_message=str(e), commit=False)
        db.commit()
        return {"status": "error", "audio_path": None}


@router.delete("/audio")
def delete_audio(
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the recorded audio file for a session."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    deleted = []
    # Full recording
    full_path = AUDIO_DIR / f"{session_id}.wav"
    if full_path.exists():
        full_path.unlink()
        deleted.append(str(full_path))

    # Remaining chunk dir
    chunk_dir = AUDIO_DIR / session_id
    if chunk_dir.exists():
        for f in chunk_dir.glob("chunk_*.wav"):
            try:
                f.unlink()
                deleted.append(str(f))
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
        try:
            chunk_dir.rmdir()
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)

    logger.info("audio_deleted session_id=%s user_id=%s files=%s", session_id, current_user.id, len(deleted))
    return {"status": "deleted", "files": len(deleted)}


@router.post("/audio-batch")
async def process_audio_batch_stream(
    file: UploadFile = File(...),
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload full audio file — split into segments, transcribe each, stream via SSE.

    The audio is split into ~2-minute segments using ffmpeg. Each segment is
    transcribed and corrected independently, and results are pushed to the
    frontend as soon as each segment completes. This avoids long waits with
    no output for large files.

    SSE events:
      data: {"type":"chunk","text":"...","window":N,"total":M}
      data: {"type":"done","note":{...}}
      data: {"type":"error","detail":"..."}
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Verify session exists and belongs to user
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ASR availability before processing
    if not _check_asr_available():
        logger.error("audio_batch_no_asr session_id=%s", session_id)
        raise HTTPException(
            status_code=503,
            detail="语音识别服务不可用。请检查 FunASR 是否正确安装或配置 DASHSCOPE_API_KEY 环境变量。"
        )

    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    course_title = notebook.title if notebook else ""
    keywords = session.keywords or []

    # Validate MIME type
    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format: {file.content_type}. Allowed: audio/webm, audio/wav, audio/mpeg, etc."
        )

    # Read file
    audio_bytes = await file.read()
    file_size = len(audio_bytes)
    if file_size > MAX_FULL_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large: {file_size} bytes (max {MAX_FULL_AUDIO_SIZE} bytes)")
    file_ext = os.path.splitext(file.filename or ".webm")[1] or ".webm"

    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        temp_path = f.name

    # Convert to WAV if needed
    wav_path = None
    process_path = temp_path
    segment_paths: list[str] = []
    segment_start_times: list[float] = []
    try:
        # Only WAV/FLAC/OGG can be directly used by FunASR.
        # All other formats (m4a, mp3, webm, aac, etc.) must be converted.
        supported_exts = {'.wav', '.flac', '.ogg'}
        if file_ext.lower() not in supported_exts:
            wav_path = temp_path + ".wav"
            converted = False

            try:
                ffmpeg = _find_ffmpeg()
                if ffmpeg:
                    result = await asyncio.to_thread(
                        lambda: subprocess.run(
                            [ffmpeg, "-y", "-i", temp_path, "-ar", "16000", "-ac", "1", wav_path],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                        )
                    )
                    if result.returncode == 0 and os.path.exists(wav_path):
                        process_path = wav_path
                        converted = True
                        logger.info("audio_batch_ffmpeg_converted session_id=%s ext=%s", session_id, file_ext)
                    else:
                        logger.warning("audio_batch_ffmpeg_failed session_id=%s returncode=%s stderr=%s", session_id, result.returncode, result.stderr[:300])
                else:
                    logger.warning("audio_batch_ffmpeg_missing session_id=%s", session_id)
            except Exception as e1:
                logger.warning("audio_batch_ffmpeg_exception session_id=%s error=%s", session_id, e1, exc_info=True)

            if not converted:
                # Try direct subprocess ffmpeg (more reliable than pydub which needs ffmpeg on PATH)
                try:
                    ffmpeg_exe = _find_ffmpeg()
                    if not ffmpeg_exe:
                        raise RuntimeError("ffmpeg executable not found")
                    result = await asyncio.to_thread(
                        lambda: subprocess.run(
                            [ffmpeg_exe, "-y", "-i", temp_path, "-ar", "16000", "-ac", "1", wav_path],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                        )
                    )
                    if result.returncode == 0 and os.path.exists(wav_path):
                        process_path = wav_path
                        converted = True
                        logger.info("audio_batch_ffmpeg_converted session_id=%s ext=%s", session_id, file_ext)
                    else:
                        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
                except Exception as e2:
                    logger.warning("audio_batch_convert_failed session_id=%s error=%s", session_id, e2, exc_info=True)

            if not converted:
                logger.warning("audio_batch_convert_fallback_original session_id=%s ext=%s", session_id, file_ext)
                process_path = temp_path

        # ── No more ffmpeg 20s hard-cut ──
        # The entire file is transcribed at once; segments are merged into
        # ~8s chunks based on natural VAD pauses.

        ppt_slides = None
        try:
            note_for_ppt = db.query(Note).filter(Note.session_id == session_id).first()
            if note_for_ppt and isinstance(note_for_ppt.ppt_images, list) and note_for_ppt.ppt_images:
                last_ppt = note_for_ppt.ppt_images[-1]
                if isinstance(last_ppt, dict):
                    ppt_slides = last_ppt.get("slides", [])
        except Exception:
            ppt_slides = None

        return StreamingResponse(
            _generate_audio_sse(session_id, process_path, temp_path, wav_path, course_title, keywords, ppt_slides),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("audio_batch_unexpected_error session_id=%s", session_id)
        # Clean up on error (generator won't run)
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            logger.warning("suppressed_exception", exc_info=True)
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
        for sp in segment_paths:
            if sp != process_path and os.path.exists(sp):
                try:
                    os.unlink(sp)
                except Exception:
                    logger.warning("suppressed_exception", exc_info=True)
        if segment_paths and segment_paths[0] != process_path:
            seg_dir = os.path.dirname(segment_paths[0])
            if seg_dir and os.path.exists(seg_dir) and "notero_segments_" in seg_dir:
                try:
                    os.rmdir(seg_dir)
                except Exception:
                    logger.warning("suppressed_exception", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Audio processing failed: {str(e)}")



@router.post("/audio-chunk")
async def upload_audio_chunk(
    file: UploadFile = File(...),
    session_id: str = "",
    chunk_index: int = 0,
    total_chunks: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Receive a single chunk of a split audio file upload.

    Chunks are stored in a temporary directory and assembled when
    audio-chunk-finish is called.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if chunk_index < 0 or total_chunks < 1:
        raise HTTPException(status_code=400, detail="Invalid chunk_index or total_chunks")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    chunk_bytes = await file.read()
    if len(chunk_bytes) > MAX_CHUNK_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Chunk too large: {len(chunk_bytes)} bytes (max {MAX_CHUNK_UPLOAD_SIZE} bytes)"
        )

    chunk_dir = AUDIO_DIR / f"{session_id}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunk_dir / f"chunk_{chunk_index:04d}"
    with open(chunk_path, "wb") as f:
        f.write(chunk_bytes)

    logger.info(
        "audio_chunk_received session_id=%s chunk=%s/%s size=%s",
        session_id, chunk_index + 1, total_chunks, len(chunk_bytes)
    )

    return {
        "received": True,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
    }


@router.post("/audio-chunk-finish")
async def finish_audio_chunk_upload(
    session_id: str = "",
    file_name: str = "",
    total_chunks: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assemble uploaded chunks and process the complete audio file.

    Returns an SSE stream identical to /audio-batch.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if total_chunks < 1:
        raise HTTPException(status_code=400, detail="total_chunks must be >= 1")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not _check_asr_available():
        raise HTTPException(
            status_code=503,
            detail="语音识别服务不可用。请检查 FunASR 是否正确安装或配置 DASHSCOPE_API_KEY 环境变量。"
        )

    notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
    course_title = notebook.title if notebook else ""
    keywords = session.keywords or []

    chunk_dir = AUDIO_DIR / f"{session_id}_chunks"
    if not chunk_dir.exists():
        raise HTTPException(status_code=400, detail="No chunks found for this session")

    expected_chunks = list(range(total_chunks))
    found_chunks = sorted(
        int(p.name.split("_")[1]) for p in chunk_dir.glob("chunk_*")
        if p.name.split("_")[1].isdigit()
    )
    missing = [i for i in expected_chunks if i not in found_chunks]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing chunks: {missing}"
        )

    file_ext = os.path.splitext(file_name or ".webm")[1] or ".webm"

    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as f:
        temp_path = f.name
        for i in expected_chunks:
            chunk_path = chunk_dir / f"chunk_{i:04d}"
            with open(chunk_path, "rb") as chunk_file:
                f.write(chunk_file.read())

    # Clean up chunk directory after assembly
    try:
        for p in chunk_dir.glob("chunk_*"):
            p.unlink()
        chunk_dir.rmdir()
    except Exception:
        logger.warning("suppressed_exception", exc_info=True)

    # Convert to WAV if needed
    wav_path = None
    process_path = temp_path
    try:
        supported_exts = {'.wav', '.flac', '.ogg'}
        if file_ext.lower() not in supported_exts:
            wav_path = temp_path + ".wav"
            converted = False
            ffmpeg = _find_ffmpeg()
            if ffmpeg:
                try:
                    result = await asyncio.to_thread(
                        lambda: subprocess.run(
                            [ffmpeg, "-y", "-i", temp_path, "-ar", "16000", "-ac", "1", wav_path],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                        )
                    )
                    if result.returncode == 0 and os.path.exists(wav_path):
                        process_path = wav_path
                        converted = True
                except Exception:
                    logger.warning("suppressed_exception", exc_info=True)
            if not converted:
                logger.warning("audio_chunk_finish_convert_failed session_id=%s", session_id)
                process_path = temp_path

        ppt_slides = None
        try:
            note_for_ppt = db.query(Note).filter(Note.session_id == session_id).first()
            if note_for_ppt and isinstance(note_for_ppt.ppt_images, list) and note_for_ppt.ppt_images:
                last_ppt = note_for_ppt.ppt_images[-1]
                if isinstance(last_ppt, dict):
                    ppt_slides = last_ppt.get("slides", [])
        except Exception:
            ppt_slides = None

        return StreamingResponse(
            _generate_audio_sse(session_id, process_path, temp_path, wav_path, course_title, keywords, ppt_slides),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("audio_chunk_finish_unexpected_error session_id=%s", session_id)
        _cleanup_temp_files(temp_path, wav_path)
        raise HTTPException(status_code=500, detail=f"Audio processing failed: {str(e)}")


@router.post("/transcript-finalize")
def finalize_transcript(
    session_id: str = "",
    body: FinalizeTranscriptRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run unified DeepSeek restructure on all accumulated transcripts for a session.

    Delegates to the canonical finalize_session_transcript in transcript.py so
    upload, real-time stop, and manual restructure all share the same logic.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note or not note.transcript:
        raise HTTPException(status_code=404, detail="No transcript found for this session")

    request = body or FinalizeTranscriptRequest()
    result = finalize_session_transcript(
        session_id, db, current_user, retry_failed_only=request.retry_failed_only
    )
    note_payload = result.get("note", result)

    agents = None
    transcript = note_payload.get("transcript", []) if isinstance(note_payload, dict) else []
    final_entry = transcript[-1] if transcript and isinstance(transcript[-1], dict) else {}
    if request.auto_generate and final_entry.get("is_ai_corrected") is True:
        # Import lazily to keep the process router independent from agent router
        # initialization. auto_run_agents owns its DB session and deduplicates
        # active/fresh work by task state and content hash.
        from app.api.agents import auto_run_agents

        agents = auto_run_agents(
            session_id,
            str(current_user.id),
            roles=["mindmap", "quiz"],
            force=request.force,
        )

    return {"note": note_payload, "agents": agents}
