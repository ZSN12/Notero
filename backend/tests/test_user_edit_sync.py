"""Unit tests for transcript/content sync when user edits the transcript."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["AGENTS_SYNC"] = "1"

from app.api.notes import (
    _extract_transcript_from_content,
    _sync_transcript_from_content,
)
from app.services.note_utils import get_canonical_transcript_text


class MockNote:
    def __init__(self, content=None, transcript=None):
        self.content = content
        self.transcript = transcript


def test_extract_transcript_from_content():
    assert _extract_transcript_from_content("") == ""
    assert _extract_transcript_from_content("## 语音转文字\n\nhello world") == "hello world"
    assert _extract_transcript_from_content("## 语音转文字\n\nhello\n\n---\n\nnote") == "hello"
    assert _extract_transcript_from_content("plain text") == ""


def test_sync_transcript_no_change():
    note = MockNote(
        content="## 语音转文字\n\nhello world",
        transcript=[{
            "chunk_index": 0,
            "text": "hello world",
            "display_text": "hello world",
            "correction_stage": "final",
        }],
    )
    _sync_transcript_from_content(note)
    # Exact match: keep existing final entry as authoritative; no superseded churn.
    assert len(note.transcript) == 1
    assert note.transcript[0]["correction_stage"] == "final"


def test_sync_transcript_partial_delete():
    note = MockNote(
        content="## 语音转文字\n\nhello",
        transcript=[{
            "chunk_index": 0,
            "text": "hello world",
            "display_text": "hello world",
            "raw_text": "hello world raw",
            "correction_stage": "final",
        }],
    )
    _sync_transcript_from_content(note)
    assert len(note.transcript) == 2
    assert note.transcript[0]["correction_stage"] == "superseded"
    entry = note.transcript[1]
    assert entry["correction_stage"] == "user_edited"
    assert entry["display_text"] == "hello"
    assert entry["text"] == "hello"
    assert entry["raw_text"] == "hello world raw"
    assert entry["timestamps"] == []


def test_sync_transcript_full_clear():
    note = MockNote(
        content="## 语音转文字\n\n---\n\nmy note",
        transcript=[{
            "chunk_index": 0,
            "text": "hello world",
            "display_text": "hello world",
            "raw_text": "hello world raw",
            "correction_stage": "final",
        }],
    )
    _sync_transcript_from_content(note)
    assert len(note.transcript) == 2
    assert note.transcript[0]["correction_stage"] == "superseded"
    entry = note.transcript[1]
    assert entry["correction_stage"] == "user_edited"
    assert entry["display_text"] == ""
    assert entry["text"] == ""


def test_sync_transcript_when_transcript_empty():
    # During real-time streaming the transcript array may be empty while content
    # already holds partial text. We should still create a user_edited entry so
    # that deletions made while streaming are preserved.
    note = MockNote(
        content="## 语音转文字\n\npartial text",
        transcript=[],
    )
    _sync_transcript_from_content(note)
    assert len(note.transcript) == 1
    assert note.transcript[0]["correction_stage"] == "user_edited"
    assert note.transcript[0]["display_text"] == "partial text"


def test_sync_transcript_ignores_non_marker_content():
    note = MockNote(
        content="plain text content",
        transcript=[{
            "chunk_index": 0,
            "text": "hello world",
            "display_text": "hello world",
            "correction_stage": "final",
        }],
    )
    _sync_transcript_from_content(note)
    assert len(note.transcript) == 1
    assert note.transcript[0]["correction_stage"] == "final"


def test_sync_creates_user_edited_and_preserves_raw_text():
    """User edits the transcript; we must keep their corrections and preserve raw ASR."""
    note = MockNote(
        content="## 语音转文字\n\nalpha beta",
        transcript=[{
            "chunk_index": 0,
            "text": "old alpha beta",
            "display_text": "old alpha beta",
            "raw_text": "old alpha beta raw",
            "correction_stage": "local",
        }],
    )
    _sync_transcript_from_content(note)
    assert len(note.transcript) == 2
    assert note.transcript[0]["correction_stage"] == "superseded"
    entry = note.transcript[1]
    assert entry["correction_stage"] == "user_edited"
    assert entry["display_text"] == "alpha beta"
    assert entry["text"] == "alpha beta"
    assert entry["raw_text"] == "old alpha beta raw"


def test_dedupe_append_variants():
    """_dedupe_append should append new text without repeating existing words."""
    from app.services.note_utils import _dedupe_append

    # New text contains the existing text as a prefix (streaming ASR cumulative result).
    assert _dedupe_append("alpha beta", "alpha beta gamma delta") == "alpha beta\n\ngamma delta"
    # Brand new text.
    assert _dedupe_append("alpha beta", "gamma delta") == "alpha beta\n\ngamma delta"
    # Overlap at boundary.
    assert _dedupe_append("alpha beta", "beta gamma") == "alpha beta\n\ngamma"
    # Empty new text.
    assert _dedupe_append("alpha beta", "") == "alpha beta"
    # Cumulative old+A+B where user already edited A to A' (share a common tail).
    assert _dedupe_append("alpha beta", "old alpha beta gamma delta") == "alpha beta\n\ngamma delta"


def test_dedupe_append_chinese():
    """_dedupe_append must work for Chinese text without spaces."""
    from app.services.note_utils import _dedupe_append

    # User edits A -> A', ASR returns cumulative A+B.
    assert _dedupe_append("你好世界", "旧的你好世界新增内容") == "你好世界\n\n新增内容"
    # ASR returns just B.
    assert _dedupe_append("你好世界", "新增内容") == "你好世界\n\n新增内容"
    # A' and A share a shorter tail (3+ chars).
    assert _dedupe_append("快速学习", "可以快速地学习内容") == "快速学习\n\n内容"
    # No overlap.
    assert _dedupe_append("你好世界", "今天天气") == "你好世界\n\n今天天气"


def test_finalize_merges_user_edited_with_post_asr():
    """Pause-edit-resume: finalization input must be A' + B, not old A + B."""
    from app.services.note_utils import _dedupe_append

    note = MockNote(
        content="## 语音转文字\n\nalpha beta\n\ngamma delta",
        transcript=[
            {
                "chunk_index": 0,
                "text": "old alpha beta",
                "display_text": "old alpha beta",
                "raw_text": "old alpha beta raw",
                "correction_stage": "local",
            },
            {
                "chunk_index": 0,
                "text": "alpha beta",
                "display_text": "alpha beta",
                "raw_text": "old alpha beta raw",
                "correction_stage": "user_edited",
            },
            {
                "chunk_index": 1,
                "text": "old alpha beta gamma delta",
                "display_text": "old alpha beta gamma delta",
                "raw_text": "old alpha beta gamma delta raw",
                "correction_stage": "local",
            },
        ],
    )

    sorted_entries = sorted(
        note.transcript,
        key=lambda e: e.get("chunk_index", 0) if isinstance(e, dict) else 0,
    )
    latest_user_edited_idx = -1
    for i, e in enumerate(sorted_entries):
        if isinstance(e, dict) and e.get("correction_stage") == "user_edited":
            latest_user_edited_idx = i

    assert latest_user_edited_idx == 1
    baseline = sorted_entries[latest_user_edited_idx]
    baseline_text = (baseline.get("display_text") or baseline.get("text") or "").strip()

    post_texts = [
        (e.get("display_text") or e.get("text") or "").strip()
        for e in sorted_entries[latest_user_edited_idx + 1:]
        if isinstance(e, dict)
    ]

    full_local_text = baseline_text
    for text in post_texts:
        full_local_text = _dedupe_append(full_local_text, text)

    # The deleted prefix "old" must not be restored.
    assert "old alpha beta" not in full_local_text
    assert "old" not in full_local_text
    assert full_local_text == "alpha beta\n\ngamma delta"


def test_canonical_prefers_latest_authoritative_entry():
    note = MockNote(
        transcript=[
            {"chunk_index": 0, "text": "old final", "correction_stage": "final"},
            {"chunk_index": 0, "text": "user edited", "display_text": "user edited", "correction_stage": "user_edited"},
            {"chunk_index": 1, "text": "newer local", "correction_stage": "local"},
        ],
    )
    assert get_canonical_transcript_text(note) == "user edited"


def test_canonical_honours_empty_user_edited():
    """A user-edited empty transcript must not fall back to raw_text."""
    note = MockNote(
        transcript=[{
            "chunk_index": 0,
            "text": "",
            "display_text": "",
            "raw_text": "raw asr text",
            "correction_stage": "user_edited",
        }],
    )
    assert get_canonical_transcript_text(note) == ""


if __name__ == "__main__":
    test_extract_transcript_from_content()
    test_sync_transcript_no_change()
    test_sync_transcript_partial_delete()
    test_sync_transcript_full_clear()
    test_sync_transcript_when_transcript_empty()
    test_sync_transcript_ignores_non_marker_content()
    test_sync_creates_user_edited_and_preserves_raw_text()
    test_canonical_prefers_latest_authoritative_entry()
    test_canonical_honours_empty_user_edited()
    test_dedupe_append_variants()
    test_dedupe_append_chinese()
    test_finalize_merges_user_edited_with_post_asr()
    print("ALL TESTS PASSED")
