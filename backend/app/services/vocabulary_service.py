"""Centralized, concurrency-safe read/write helpers for ``Note.vocabulary``.

All operations that read-modify-write the JSON column go through this module
and use ``SELECT ... FOR UPDATE`` so parallel agents (including Celery workers
in separate processes) do not overwrite each other's entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models import Note


def _lock_note(db: Session, note_id: str) -> Note:
    """Return the Note row locked with ``SELECT ... FOR UPDATE``."""
    note = (
        db.query(Note)
        .populate_existing()
        .filter(Note.id == note_id)
        .with_for_update()
        .first()
    )
    if note is None:
        raise ValueError(f"Note {note_id} not found")
    return note


def get_vocabulary_entries(note: Note, kind: Optional[str] = None) -> list[dict]:
    """Return vocabulary entries, optionally filtered by kind."""
    if not isinstance(note.vocabulary, list):
        return []
    if kind is None:
        return [item for item in note.vocabulary if isinstance(item, dict)]
    return [
        item for item in note.vocabulary
        if isinstance(item, dict) and item.get("kind") == kind
    ]


def get_vocabulary_entry(note: Note, kind: str) -> Optional[dict]:
    """Return the first vocabulary entry of ``kind``, or None."""
    for item in get_vocabulary_entries(note, kind):
        return item
    return None


def save_vocabulary_entry(
    db: Session,
    note_id: str,
    entry: dict,
    replace_predicate: Optional[Callable[[dict], bool]] = None,
) -> None:
    """Replace matching entries and append ``entry`` under row lock.

    By default any existing entry with the same ``kind`` is replaced.  Pass a
    custom ``replace_predicate`` for finer control (e.g. replace by kind AND
    quiz_id).
    """
    note = _lock_note(db, note_id)
    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    if replace_predicate is None:
        kind = entry.get("kind")
        replace_predicate = lambda item: item.get("kind") == kind  # noqa: E731
    next_items = [item for item in existing if not replace_predicate(item)]
    next_items.append(entry)
    note.vocabulary = next_items
    db.commit()


def append_vocabulary_entry(db: Session, note_id: str, entry: dict) -> None:
    """Append ``entry`` without replacing any existing entries."""
    note = _lock_note(db, note_id)
    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    note.vocabulary = list(existing) + [entry]
    db.commit()


def delete_vocabulary_entries(
    db: Session,
    note_id: str,
    predicate: Callable[[dict], bool],
) -> None:
    """Delete entries matching ``predicate`` under row lock."""
    note = _lock_note(db, note_id)
    existing = note.vocabulary if isinstance(note.vocabulary, list) else []
    note.vocabulary = [item for item in existing if not predicate(item)]
    db.commit()


def build_entry(
    kind: str,
    data: dict,
    extra: Optional[dict] = None,
) -> dict:
    """Build a standard vocabulary entry dict."""
    entry: dict = {
        "kind": kind,
        "data": data,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        entry.update(extra)
    return entry
