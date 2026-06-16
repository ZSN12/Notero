"""Tests for the TranscriptOrganizerAgent and downstream consumption."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
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


@patch("app.agents.base.OpenAI")
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


@patch("app.agents.base.OpenAI")
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
