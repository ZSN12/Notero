"""Tests for the TranscriptOrganizerAgent and downstream consumption."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.agents.transcript_agent import ParagraphRange, TranscriptOrganizerAgent
from tests.harness.helpers import auth_headers, create_notebook_session_note


def _get_note(client, session_id, headers):
    resp = client.get(f"/api/notes/session/{session_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_agent(client, session_id, role, headers):
    resp = client.post(
        f"/api/agents/session/{session_id}/run/{role}",
        headers=headers,
    )
    return resp


def _set_raw_transcript(client, session_id, text, headers):
    """Set note.transcript via the process/transcript endpoint."""
    import json

    payload = json.dumps(
        [{"chunk_index": 0, "text": text, "raw_text": text}],
        ensure_ascii=False,
    )
    resp = client.put(
        "/api/process/transcript",
        params={"session_id": session_id, "content": payload},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_transcript_agent_packages_finalized_content():
    """If the transcript is already finalized, the agent just packages it."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = create_notebook_session_note(
            client,
            headers,
            content="## 语音转文字\n\n这是整理后的课堂内容。\n\n第二段内容。",
        )

        # Ensure note.transcript has a finalized entry
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "transcript": [
                    {
                        "chunk_index": 0,
                        "text": "这是整理后的课堂内容。第二段内容。",
                        "display_text": "这是整理后的课堂内容。\n\n第二段内容。",
                        "correction_stage": "final",
                    }
                ]
            },
            headers=headers,
        )

        resp = _run_agent(client, session_id, "transcript", headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ready"
        assert data["role"] == "transcript"

        note = _get_note(client, session_id, headers)
        vocab = note.get("vocabulary", [])
        organized = [v for v in vocab if isinstance(v, dict) and v.get("kind") == "organized_transcript"]
        assert len(organized) == 1
        assert "这是整理后的课堂内容" in organized[0]["data"]["plain_text"]


@patch("app.core.llm.OpenAI")
def test_transcript_agent_restructures_raw_transcript(mock_openai_cls):
    """The agent can restructure a raw transcript when no finalized entry exists."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "整理后的课堂内容。\n\n第二段。"
    mock_response.choices[0].finish_reason = "stop"
    mock_client.chat.completions.create.return_value = mock_response

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = create_notebook_session_note(
            client,
            headers,
            content="",
        )

        # Set a raw transcript without a finalized entry
        _set_raw_transcript(client, session_id, "啊 那个 整理后的课堂内容 第二段", headers)

        resp = _run_agent(client, session_id, "transcript", headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ready"

        note = _get_note(client, session_id, headers)
        vocab = note.get("vocabulary", [])
        organized = [v for v in vocab if isinstance(v, dict) and v.get("kind") == "organized_transcript"]
        assert len(organized) == 1
        assert "整理后的课堂内容" in organized[0]["data"]["plain_text"]


@patch("app.core.llm.OpenAI")
def test_downstream_agent_uses_organized_transcript(mock_openai_cls):
    """Mindmap agent should consume the organized transcript when available."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    def respond_based_on_prompt(*args, **kwargs):
        messages = kwargs.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        if "整理后的" in user_content:
            # Mindmap prompt used organized transcript
            mock_response.choices[0].message.content = (
                '{"title": "T", "summary": "S", "nodes": [{"id": "n1", "title": "整理后的", "description": "D", "type": "concept", "importance": "high", "sources": [{"source_type": "transcript", "snippet": "整理后的课堂内容", "page": null}], "children": []}], "relations": []}'
            )
        else:
            # Transcript restructure prompt
            mock_response.choices[0].message.content = "整理后的课堂内容。"
        mock_response.choices[0].finish_reason = "stop"
        return mock_response

    mock_client.chat.completions.create.side_effect = respond_based_on_prompt

    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = create_notebook_session_note(
            client,
            headers,
            content="## 语音转文字\n\n整理后的课堂内容。",
        )
        client.put(
            f"/api/notes/session/{session_id}",
            json={
                "transcript": [
                    {
                        "chunk_index": 0,
                        "text": "整理后的课堂内容。",
                        "display_text": "整理后的课堂内容。",
                        "correction_stage": "final",
                    }
                ]
            },
            headers=headers,
        )

        # Run transcript agent first
        resp = _run_agent(client, session_id, "transcript", headers)
        assert resp.status_code == 200, resp.text

        # Run mindmap agent
        resp = _run_agent(client, session_id, "mindmap", headers)
        assert resp.status_code == 200, resp.text

        # Verify the mindmap prompt contained the organized text
        calls = mock_client.chat.completions.create.call_args_list
        mindmap_calls = [
            c for c in calls
            if len(c.kwargs.get("messages", [])) > 1 and "请根据以下课堂笔记内容" in c.kwargs["messages"][1]["content"]
        ]
        assert len(mindmap_calls) == 1
        assert "整理后的课堂内容" in mindmap_calls[0].kwargs["messages"][1]["content"]


def test_parse_marked_paragraphs_extracts_time_ranges():
    raw = "[1200-5600] 这是第一段。\n\n[5600-8900] 这是第二段。"
    ranges = TranscriptOrganizerAgent._parse_marked_paragraphs(raw)
    assert len(ranges) == 2
    assert ranges[0].text == "这是第一段。"
    assert ranges[0].start_ms == 1200
    assert ranges[0].end_ms == 5600
    assert ranges[1].text == "这是第二段。"
    assert ranges[1].start_ms == 5600
    assert ranges[1].end_ms == 8900


def test_parse_marked_paragraphs_handles_missing_markers():
    raw = "没有标记的段落。\n\n[1000-2000] 有标记的段落。"
    ranges = TranscriptOrganizerAgent._parse_marked_paragraphs(raw)
    assert len(ranges) == 2
    assert ranges[0].text == "没有标记的段落。"
    assert ranges[0].start_ms == 0
    assert ranges[0].end_ms == 0
    assert ranges[1].text == "有标记的段落。"


def test_build_timestamped_text_skips_empty_segments():
    segments = [
        {"text": "", "start_ms": 0, "end_ms": 100},
        {"text": "有效文本", "start_ms": 100, "end_ms": 500},
    ]
    text = TranscriptOrganizerAgent._build_timestamped_text(segments)
    assert "[100-500] 有效文本" in text
    assert "[0-100]" not in text


def test_restructure_text_joins_paragraph_texts():
    with patch.object(TranscriptOrganizerAgent, "restructure_with_time", return_value=[
        ParagraphRange(text="第一段。", start_ms=0, end_ms=1000),
        ParagraphRange(text="第二段。", start_ms=1000, end_ms=2000),
    ]):
        result = TranscriptOrganizerAgent.restructure_text(
            raw_text="raw",
            course_title="",
        )
    assert result == "第一段。\n\n第二段。"
