"""WebSocket endpoint for real-time streaming ASR.

Frontend sends:
  - binary: PCM int16 frames @ 16kHz mono
  - JSON control: { "type": "start" | "pause" | "resume" | "end" }

Backend sends:
  - { "type": "partial", "text": "...", "start_ms": 0, "end_ms": 3000 }
  - { "type": "final",   "text": "...", "start_ms": 0, "end_ms": 5000 }
  - { "type": "status",  "message": "..." }
  - { "type": "error",   "detail": "..." }
  - { "type": "done",    "note": {...} }
"""

import asyncio
import json
import logging
import re

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from sqlalchemy.orm import Session

from app.config import SECRET_KEY, ALGORITHM
from app.core.database import SessionLocal
from app.models import User, Session as DBSession, Notebook, Note
from app.services.streaming_asr import StreamingASRManager
from app.services.note_utils import _dedupe_append

logger = logging.getLogger(__name__)
router = APIRouter()


def _decode_ws_token(token: str) -> User | None:
    """Decode JWT and return user instance (or None)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
    except jwt.ExpiredSignatureError:
        return None
    except jwt.PyJWTError:
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        return user
    finally:
        db.close()


def _save_note_from_payload(session_id: str, payload: dict) -> None:
    """Best-effort save transcript data to note (used on 'end' and on disconnect)."""
    db = SessionLocal()
    try:
        note = db.query(Note).filter(Note.session_id == session_id).first()
        transcript_data = payload.get("transcript", [])

        def _extract_notes_content(content: str | None) -> str:
            existing = (content or "").strip()
            if not existing:
                return ""
            marker = "\n\n---\n\n"
            if existing.startswith("## 语音转文字"):
                return existing.split(marker, 1)[1].strip() if marker in existing else ""
            return ""

        def _extract_transcript_text(content: str | None) -> str:
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

        if note:
            notes_content = _extract_notes_content(note.content)
            existing_transcript_text = _extract_transcript_text(note.content)

            new_display_text = ""
            if transcript_data:
                new_display_text = (
                    transcript_data[0].get("display_text")
                    or transcript_data[0].get("text")
                    or ""
                ).strip()

            # If the user has already edited the transcript (indicated by a
            # user_edited entry), keep the user-edited baseline and append the
            # new ASR text after it, deduping any repeated prefix/overlap. The
            # new ASR entries are still appended to note.transcript for audit.
            has_user_edited = any(
                isinstance(e, dict) and e.get("correction_stage") == "user_edited"
                for e in (note.transcript or [])
            )
            if has_user_edited:
                combined_transcript_text = _dedupe_append(existing_transcript_text, new_display_text)
            elif existing_transcript_text and new_display_text:
                combined_transcript_text = f"{existing_transcript_text}\n\n{new_display_text}".strip()
            elif new_display_text:
                combined_transcript_text = new_display_text
            else:
                combined_transcript_text = existing_transcript_text

            if notes_content and combined_transcript_text:
                note.content = f"## 语音转文字\n\n{combined_transcript_text}\n\n---\n\n{notes_content}".strip()
            elif combined_transcript_text:
                note.content = f"## 语音转文字\n\n{combined_transcript_text}".strip()
            else:
                note.content = notes_content

            existing_transcript = list(note.transcript or [])
            base_index = len(existing_transcript)
            for i, entry in enumerate(transcript_data):
                entry["chunk_index"] = base_index + i
            existing_transcript.extend(transcript_data)
            note.transcript = existing_transcript

            existing_layout = list(note.layout_blocks or [])
            note_blocks = [
                block for block in existing_layout
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
            note.layout_blocks = all_transcript_blocks + note_blocks

            db.commit()
            db.refresh(note)
        else:
            display_text = ""
            if transcript_data:
                display_text = (
                    transcript_data[0].get("display_text")
                    or transcript_data[0].get("text")
                    or ""
                ).strip()
            note = Note(
                session_id=session_id,
                transcript=transcript_data,
                content=f"## 语音转文字\n\n{display_text}".strip() if display_text else "",
                ppt_images=[],
                vocabulary=[],
            )
            if display_text:
                note.layout_blocks = [
                    {
                        "id": f"transcript-{i + 1}",
                        "type": "transcript",
                        "content": part.strip(),
                    }
                    for i, part in enumerate(display_text.split("\n\n"))
                    if part.strip()
                ]
            db.add(note)
            db.commit()
            db.refresh(note)
            logger.info(
                "asr_ws_note_saved session_id=%s note_id=%s transcript_entries=%s",
                session_id, note.id, len(transcript_data) if transcript_data else 0,
            )
    except Exception:
        logger.exception("asr_ws_save_note_failed session_id=%s", session_id)
    finally:
        db.close()


def _get_user_session(session_id: str, user: User) -> DBSession | None:
    """Verify session exists and belongs to user.  Returns session or None."""
    db = SessionLocal()
    try:
        session = (
            db.query(DBSession)
            .filter(DBSession.id == session_id)
            .join(Notebook)
            .filter(Notebook.user_id == user.id)
            .first()
        )
        return session
    finally:
        db.close()


async def _send_note_payload(websocket: WebSocket, payload: dict) -> None:
    """Serialize a StreamingRecognizer finalize payload into a note-like
dict compatible with the frontend BackendNote type."""
    note_data = payload.get("transcript", [])
    await websocket.send_json({
        "type": "done",
        "note": {
            "id": "",
            "session_id": payload.get("session_id", ""),
            "content": "",
            "transcript": note_data,
            "ppt_images": [],
            "vocabulary": [],
            "layout_blocks": [],
            "created_at": None,
        },
    })


@router.websocket("/ws/asr/{session_id}")
async def asr_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
):
    # --- Auth ---
    user = _decode_ws_token(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db_session = _get_user_session(session_id, user)
    if db_session is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info("asr_ws_accepted session_id=%s user_id=%s", session_id, user.id)

    # --- Init recognizer ---
    notebook = None
    db = SessionLocal()
    try:
        notebook = db.query(Notebook).filter(Notebook.id == db_session.notebook_id).first()
    finally:
        db.close()

    manager = StreamingASRManager()
    recognizer = manager.create_recognizer(
        session_id=session_id,
        course_title=notebook.title if notebook else "",
        keywords=db_session.keywords or [],
    )

    MAX_BINARY_SIZE = 1024 * 1024  # 1 MB per audio frame
    MAX_TEXT_SIZE = 64 * 1024      # 64 KB per control message

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                pcm = message["bytes"]
                if len(pcm) > MAX_BINARY_SIZE:
                    logger.warning("asr_ws_oversized_binary session_id=%s size=%s", session_id, len(pcm))
                    await websocket.send_json({
                        "type": "error",
                        "detail": f"Audio frame too large: {len(pcm)} bytes (max {MAX_BINARY_SIZE})",
                    })
                    continue
                events = recognizer.feed_pcm(pcm)
                for ev in events:
                    await websocket.send_json(ev)

            elif "text" in message:
                text = message["text"]
                if len(text) > MAX_TEXT_SIZE:
                    logger.warning("asr_ws_oversized_text session_id=%s size=%s", session_id, len(text))
                    await websocket.send_json({
                        "type": "error",
                        "detail": f"Control message too large: {len(text)} bytes (max {MAX_TEXT_SIZE})",
                    })
                    continue
                data = json.loads(text)
                msg_type = data.get("type")

                if msg_type == "start":
                    await websocket.send_json({
                        "type": "status",
                        "message": "识别已开始",
                    })

                elif msg_type == "pause":
                    recognizer.pause()
                    # Force-commit any buffered partial text so the user sees the
                    # words spoken right before pausing instead of losing them.
                    for ev in recognizer.flush_partial():
                        await websocket.send_json(ev)
                    await websocket.send_json({
                        "type": "status",
                        "message": "已暂停",
                    })

                elif msg_type == "resume":
                    recognizer.resume()
                    await websocket.send_json({
                        "type": "status",
                        "message": "已恢复",
                    })

                elif msg_type == "end":
                    payload = recognizer.finalize()
                    _save_note_from_payload(session_id, payload)
                    await _send_note_payload(websocket, payload)
                    break

            else:
                # Unknown message type
                pass

    except WebSocketDisconnect:
        logger.info("asr_ws_disconnect session_id=%s", session_id)
        # Best-effort save on abrupt disconnect (user closed tab/navigated away)
        try:
            payload = recognizer.finalize()
            _save_note_from_payload(session_id, payload)
        except Exception:
            pass
    except Exception as exc:
        logger.exception("asr_ws_error session_id=%s", session_id)
        try:
            await websocket.send_json({
                "type": "error",
                "detail": str(exc) or "内部错误",
            })
        except Exception:
            pass
    finally:
        recognizer.cleanup()
        manager.remove_recognizer(session_id)
        try:
            await websocket.close()
        except Exception:
            pass
