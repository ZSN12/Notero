"""Tests for the LLM-based PPT placement matcher and its integration."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.ppt_llm_matcher import compute_placements
from tests.harness.mocks import mock_ppt_placements, patch_ppt_matcher


class TestComputePlacements:
    def test_returns_valid_placements(self):
        slides = [
            {"page": 1, "title": "Cover", "text": "Intro", "image_path": "slide_01.png"},
            {"page": 2, "title": "Topic", "text": "Content", "image_path": "slide_02.png"},
        ]
        placements = [
            {"page": 1, "after_sentence_index": -1, "reason": "cover"},
            {"page": 2, "after_sentence_index": 0, "reason": "topic"},
        ]

        with patch_ppt_matcher(placements):
            result = compute_placements("Hello world. Today we learn.", slides)

        assert result == placements

    def test_returns_none_when_api_fails(self):
        slides = [{"page": 1, "title": "A", "text": "b"}]

        with patch(
            "app.core.llm.OpenAI"
        ) as MockClient:
            MockClient.return_value.chat.completions.create.side_effect = RuntimeError(
                "API down"
            )
            result = compute_placements("Hello.", slides)

        assert result is None

    def test_returns_none_on_invalid_json(self):
        slides = [{"page": 1, "title": "A", "text": "b"}]

        with patch("app.core.llm.OpenAI") as MockClient:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "not json"
            mock_response.choices[0].finish_reason = "stop"
            MockClient.return_value.chat.completions.create.return_value = mock_response
            result = compute_placements("Hello.", slides)

        assert result is None

    def test_returns_none_when_provider_unavailable(self):
        with patch(
            "app.services.ppt_llm_matcher.get_default_chat_provider"
        ) as mock_get:
            mock_get.return_value = MagicMock(available=False)
            result = compute_placements("Hello.", [{"page": 1, "title": "A", "text": "b"}])
        assert result is None


class TestBuildBlocksFromPlacements:
    def test_builds_text_and_image_blocks(self):
        from app.api.process.ppt import _build_blocks_from_placements

        sentences = ["First sentence.", "Second sentence."]
        slides = [
            {"page": 1, "title": "Cover", "text": "Intro", "image_path": "slide_01.png"},
            {"page": 2, "title": "Topic", "text": "Content", "image_path": "slide_02.png"},
        ]
        placements = [
            {"page": 1, "after_sentence_index": -1},
            {"page": 2, "after_sentence_index": 0},
        ]

        blocks = _build_blocks_from_placements(
            sentences, placements, slides, "sess-123"
        )

        assert blocks[0] == {
            "type": "image",
            "src": "/api/media/slides/sess-123/slide_01.png",
            "page": 1,
            "title": "Cover",
        }
        assert blocks[1] == {"type": "text", "content": "First sentence."}
        assert any(
            b.get("type") == "image" and b.get("page") == 2 for b in blocks
        )
        assert blocks[-1] == {"type": "text", "content": "Second sentence."}


class TestPPTInsertEndpoint:
    def test_uses_llm_placements_and_caches_result(
        self,
        client,
        auth_headers,
        sample_session,
        note_factory,
    ):
        note = note_factory(
            session=sample_session,
            transcript=[{"chunk_index": 0, "text": "First sentence. Second sentence."}],
            ppt_images=[
                {
                    "slides": [
                        {"page": 1, "title": "Cover", "text": "Intro", "image_path": "slide_01.png"},
                        {"page": 2, "title": "Topic", "text": "Content", "image_path": "slide_02.png"},
                    ]
                }
            ],
            vocabulary=[],
        )

        placements = [
            {"page": 1, "after_sentence_index": -1, "reason": "cover"},
            {"page": 2, "after_sentence_index": 0, "reason": "topic"},
        ]

        with patch_ppt_matcher(placements):
            response = client.post(
                f"/api/process/ppt-insert?session_id={sample_session.id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        blocks = data["blocks"]

        assert blocks[0]["type"] == "image"
        assert blocks[0]["page"] == 1
        assert any(b["type"] == "image" and b["page"] == 2 for b in blocks)

        # The endpoint should cache the placements in note.vocabulary.
        cached = next(
            (item for item in note.vocabulary if item.get("kind") == "ppt_placement"),
            None,
        )
        assert cached is not None
        assert cached["data"]["placements"] == placements

    def test_falls_back_to_slide_aligner_when_llm_fails(
        self,
        client,
        auth_headers,
        sample_session,
        note_factory,
    ):
        note_factory(
            session=sample_session,
            transcript=[{"chunk_index": 0, "text": "操作系统进程管理。"}],
            ppt_images=[
                {
                    "slides": [
                        {"page": 1, "title": "操作系统", "text": "进程管理", "image_path": "slide_01.png"},
                    ]
                }
            ],
            vocabulary=[],
        )

        with patch(
            "app.core.llm.OpenAI"
        ) as MockClient:
            MockClient.return_value.chat.completions.create.side_effect = RuntimeError(
                "API down"
            )
            response = client.post(
                f"/api/process/ppt-insert?session_id={sample_session.id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        blocks = data["blocks"]
        # Fallback should still produce an image block from SlideAligner.
        assert any(b["type"] == "image" for b in blocks)
