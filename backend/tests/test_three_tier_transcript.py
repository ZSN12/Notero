"""Tests for the three-tier transcript fallback (raw -> local clean -> DeepSeek)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-three-tier"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Note, User, SessionProcessingState
from app.services.term_corrector import corrector, RestructureResult
from app.services.state_service import get_state
from app.agents.transcript_agent import ParagraphRange


def auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": "http://localhost:5173",
    }


def _create_notebook_session_note(client: TestClient, headers: dict, content: str = ""):
    nb = client.post("/api/notebooks", json={"title": "Three Tier Test NB"}, headers=headers)
    assert nb.status_code == 201
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "Three Tier Test Session", "keywords": ["test"]},
        headers=headers,
    )
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    client.put(
        f"/api/notes/session/{session_id}",
        json={"content": content},
        headers=headers,
    )
    return notebook_id, session_id


def _mock_openai_response(data: dict):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(data)
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


# -- Unit: _finalize_display_text_for_stream --

def test_finalize_returns_three_tiers_on_success():
    with patch.object(corrector, "_client", MagicMock()):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content.strip.return_value = "今天我们学习了单例模式。"
        corrector._client.chat.completions.create.return_value = mock_response

        import asyncio
        from app.api.process.audio import _finalize_display_text_for_stream

        result = asyncio.run(_finalize_display_text_for_stream(
            raw_text="今天 我们 学习了 单例 模式 啊 呃",
            display_source="今天 我们 学习了 单例 模式 啊 呃",
            course_title="测试",
            keywords=["test"],
        ))

        assert "display_text" in result
        assert result["corrected_text"] is not None
        assert result["is_ai_corrected"] is True
        assert result["correction_error"] is None


def test_finalize_returns_local_on_deepseek_failure():
    with patch.object(corrector, "_client", MagicMock()):
        corrector._client.chat.completions.create.side_effect = RuntimeError("API down")

        import asyncio
        from app.api.process.audio import _finalize_display_text_for_stream

        result = asyncio.run(_finalize_display_text_for_stream(
            raw_text="今天 我们 学习了 单例 模式",
            display_source="今天 我们 学习了 单例 模式",
            course_title="测试",
            keywords=["test"],
        ))

        assert "display_text" in result
        assert result["corrected_text"] is None
        assert result["is_ai_corrected"] is False
        assert result["correction_error"] == "AI 整理失败"


# -- Integration: restructure endpoint --

def test_restructure_endpoint_creates_corrected_text():
    from app.api.process import transcript as transcript_module
    with patch.object(
        transcript_module.corrector,
        "restructure_transcript_chunked",
        return_value=RestructureResult(
            text="今天我们学习了单例模式。",
            local_text="raw text",
            is_ai_corrected=True,
            chunks_total=1,
            chunks_succeeded=1,
            chunks_failed=0,
        ),
    ):
        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers, content="raw text")

            # Seed a transcript with raw_text
            db = SessionLocal()
            try:
                note = db.query(Note).filter(Note.session_id == session_id).first()
                note.transcript = [{
                    "chunk_index": 0,
                    "text": "raw text",
                    "raw_text": "raw text from ASR",
                    "display_text": "raw text",
                    "correction_stage": "final",
                    "is_ai_corrected": False,
                }]
                db.commit()
            finally:
                db.close()

            resp = client.post(
                f"/api/process/session/{session_id}/restructure",
                json={"force": True},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            note_data = body["note"]
            assert note_data["transcript"][0]["raw_text"] == "raw text from ASR"
            assert note_data["transcript"][0]["corrected_text"] is not None
            assert note_data["transcript"][0]["is_ai_corrected"] is True


def test_restructure_endpoint_fallback_on_failure():
    from app.api.process import transcript as transcript_module
    with patch.object(
        transcript_module.corrector,
        "restructure_transcript_chunked",
        return_value=RestructureResult(
            text="raw text",
            local_text="raw text",
            is_ai_corrected=False,
            error_code="timeout",
            error="AI 整理超时",
            retryable=True,
            chunks_total=1,
            chunks_succeeded=0,
            chunks_failed=1,
        ),
    ):
        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers, content="raw text")

            db = SessionLocal()
            try:
                note = db.query(Note).filter(Note.session_id == session_id).first()
                note.transcript = [{
                    "chunk_index": 0,
                    "text": "raw text",
                    "raw_text": "raw text from ASR",
                    "display_text": "raw text",
                    "correction_stage": "final",
                    "is_ai_corrected": False,
                }]
                db.commit()
            finally:
                db.close()

            resp = client.post(
                f"/api/process/session/{session_id}/restructure",
                json={"force": True},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            note_data = body["note"]
            assert note_data["transcript"][0]["raw_text"] == "raw text from ASR"
            assert note_data["transcript"][0]["corrected_text"] is None
            assert note_data["transcript"][0]["is_ai_corrected"] is False
            assert note_data["transcript"][0]["correction_error_code"] == "timeout"


# -- Integration: streaming ASR finalize saves three tiers --

def test_streaming_asr_finalize_saves_local_only():
    """finalize() no longer calls DeepSeek; it returns a local-only entry."""
    from app.services.streaming_asr import StreamingRecognizer

    rec = StreamingRecognizer(session_id="s1", course_title="测试")
    rec.final_segments = [MagicMock(text="今天 我们 学习了 单例 模式 啊", start_ms=0, end_ms=5000)]
    rec.all_timestamps = [{"text": "今天", "start": 0, "end": 500}]
    rec.audio_buffer = bytearray()

    payload = rec.finalize()
    entry = payload["transcript"][0]

    assert entry["raw_text"] == "今天 我们 学习了 单例 模式 啊"
    assert entry["display_text"] is not None
    assert entry["corrected_text"] is None
    assert entry["is_ai_corrected"] is False
    assert entry["correction_error"] is None
    assert entry["correction_stage"] == "local"


def test_streaming_asr_finalize_local_no_failure():
    """Without DeepSeek, finalize never reports an AI failure."""
    from app.services.streaming_asr import StreamingRecognizer

    rec = StreamingRecognizer(session_id="s1", course_title="测试")
    rec.final_segments = [MagicMock(text="今天 我们 学习了 单例 模式 啊", start_ms=0, end_ms=5000)]
    rec.all_timestamps = [{"text": "今天", "start": 0, "end": 500}]
    rec.audio_buffer = bytearray()

    payload = rec.finalize()
    entry = payload["transcript"][0]

    assert entry["raw_text"] == "今天 我们 学习了 单例 模式 啊"
    assert entry["display_text"] is not None
    assert entry["corrected_text"] is None
    assert entry["is_ai_corrected"] is False
    assert entry["correction_error"] is None
    assert entry["correction_stage"] == "local"


# -- Integration: processing-state tracking --

def test_restructure_sets_ready_state_on_ai_success():
    """When AI correction succeeds, transcript_finalize state should be 'ready'."""
    from app.api.process import transcript as transcript_module
    with patch.object(
        transcript_module.corrector,
        "restructure_transcript_chunked",
        return_value=RestructureResult(
            text="AI corrected text.",
            local_text="raw text",
            is_ai_corrected=True,
            chunks_total=1,
            chunks_succeeded=1,
            chunks_failed=0,
        ),
    ):
        with patch.object(transcript_module.corrector, "preserves_source_content", return_value=True):
            with TestClient(app) as client:
                headers = auth_headers(client)
                _, session_id = _create_notebook_session_note(client, headers)

                db = SessionLocal()
                try:
                    note = db.query(Note).filter(Note.session_id == session_id).first()
                    note.transcript = [{
                        "chunk_index": 0,
                        "text": "raw text",
                        "raw_text": "raw text",
                        "display_text": "raw text",
                        "correction_stage": "final",
                    }]
                    db.commit()
                finally:
                    db.close()

                resp = client.post(
                    f"/api/process/session/{session_id}/restructure",
                    json={"force": True},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text

                db = SessionLocal()
                try:
                    state = get_state(db, session_id, "transcript_finalize")
                    assert state is not None
                    assert state.status == "ready"
                finally:
                    db.close()


def test_restructure_sets_fallback_state_on_ai_failure():
    """When AI correction fails, transcript_finalize state should be 'fallback'."""
    from app.api.process import transcript as transcript_module
    with patch.object(
        transcript_module.corrector,
        "restructure_transcript_chunked",
        return_value=RestructureResult(
            text="raw text",
            local_text="raw text",
            is_ai_corrected=False,
            error_code="timeout",
            error="AI 整理超时",
            retryable=True,
            chunks_total=1,
            chunks_succeeded=0,
            chunks_failed=1,
        ),
    ):
        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            db = SessionLocal()
            try:
                note = db.query(Note).filter(Note.session_id == session_id).first()
                note.transcript = [{
                    "chunk_index": 0,
                    "text": "raw text",
                    "raw_text": "raw text",
                    "display_text": "raw text",
                    "correction_stage": "final",
                }]
                db.commit()
            finally:
                db.close()

            resp = client.post(
                f"/api/process/session/{session_id}/restructure",
                json={"force": True},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text

            db = SessionLocal()
            try:
                state = get_state(db, session_id, "transcript_finalize")
                assert state is not None
                assert state.status == "fallback"
                assert state.error_message is not None
            finally:
                db.close()


def test_restructure_auto_triggers_vector_index_state():
    """After successful finalize, vector_index state should transition to 'ready'."""
    from app.api.process import transcript as transcript_module
    with patch.object(
        transcript_module.corrector,
        "restructure_transcript_chunked",
        return_value=RestructureResult(
            text="AI corrected text.",
            local_text="raw text",
            is_ai_corrected=True,
            chunks_total=1,
            chunks_succeeded=1,
            chunks_failed=0,
        ),
    ):
        with patch.object(transcript_module.corrector, "preserves_source_content", return_value=True):
            with patch("app.api.process.transcript.build_session_index", return_value=3):
                with TestClient(app) as client:
                    headers = auth_headers(client)
                    _, session_id = _create_notebook_session_note(client, headers)

                    db = SessionLocal()
                    try:
                        note = db.query(Note).filter(Note.session_id == session_id).first()
                        note.transcript = [{
                            "chunk_index": 0,
                            "text": "raw text",
                            "raw_text": "raw text",
                            "display_text": "raw text",
                            "correction_stage": "final",
                        }]
                        db.commit()
                    finally:
                        db.close()

                    resp = client.post(
                        f"/api/process/session/{session_id}/restructure",
                        json={"force": True},
                        headers=headers,
                    )
                    assert resp.status_code == 200, resp.text

                    db = SessionLocal()
                    try:
                        vector_state = get_state(db, session_id, "vector_index")
                        assert vector_state is not None
                        assert vector_state.status == "ready"
                    finally:
                        db.close()
