"""Notebook-level course terms shared across sessions.

Course terms are used as context hints for ASR correction. They are stored at
the notebook level so deleting one session does not remove the vocabulary that
has been learned for the whole course.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models import CourseTerm, Session as DBSession
from app.services.term_corrector import TermCorrector

logger = logging.getLogger(__name__)

DEFAULT_COURSE_TERM_LIMIT = 120
MAX_STORED_TERMS_PER_NOTEBOOK = 300


def _normalize_term(term: str) -> str:
    return str(term or "").strip()


def _merge_ordered(*term_lists: Iterable[str], limit: int = DEFAULT_COURSE_TERM_LIMIT) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for terms in term_lists:
        for term in terms or []:
            clean = _normalize_term(term)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            merged.append(clean)
            if len(merged) >= limit:
                return merged
    return merged


def get_notebook_course_terms(
    db: Session,
    notebook_id: str,
    limit: int = DEFAULT_COURSE_TERM_LIMIT,
) -> list[str]:
    """Return persisted notebook terms ordered by importance."""
    if not notebook_id:
        return []
    rows = (
        db.query(CourseTerm)
        .filter(CourseTerm.notebook_id == notebook_id)
        .order_by(CourseTerm.weight.desc(), CourseTerm.updated_at.desc(), CourseTerm.created_at.desc())
        .limit(limit)
        .all()
    )
    return [row.term for row in rows if row.term]


def upsert_notebook_course_terms(
    db: Session,
    notebook_id: str,
    terms: Iterable[str],
    *,
    source: str,
    session_id: Optional[str] = None,
    weight: float = 1.0,
    commit: bool = True,
) -> int:
    """Insert/update notebook-level terms.

    Existing terms keep the highest observed weight. The table is intentionally
    tied to notebook_id, not session_id, so session deletion does not remove
    shared course vocabulary.
    """
    cleaned = [
        _normalize_term(term)
        for term in terms
        if TermCorrector._is_high_value_course_term(_normalize_term(term))
    ]
    cleaned = _merge_ordered(cleaned, limit=MAX_STORED_TERMS_PER_NOTEBOOK)
    if not notebook_id or not cleaned:
        return 0

    existing = {
        row.term: row
        for row in db.query(CourseTerm)
        .filter(CourseTerm.notebook_id == notebook_id, CourseTerm.term.in_(cleaned))
        .all()
    }

    changed = 0
    for term in cleaned:
        row = existing.get(term)
        if row:
            row.weight = max(float(row.weight or 0.0), float(weight))
            row.source = row.source or source
            row.first_seen_session_id = row.first_seen_session_id or session_id
            changed += 1
            continue
        db.add(
            CourseTerm(
                notebook_id=notebook_id,
                term=term,
                source=source,
                weight=weight,
                first_seen_session_id=session_id,
            )
        )
        changed += 1

    if commit:
        db.commit()
    return changed


def build_terms_from_ppt(
    course_title: str,
    keywords: Optional[list[str]],
    ppt_slides: Optional[list[dict]],
    limit: int = DEFAULT_COURSE_TERM_LIMIT,
) -> list[str]:
    return TermCorrector.build_course_terms(course_title, keywords, ppt_slides, limit=limit)


def build_shared_course_terms_for_session(
    db: Session,
    session: DBSession,
    *,
    course_title: str = "",
    current_keywords: Optional[list[str]] = None,
    ppt_slides: Optional[list[dict]] = None,
    limit: int = DEFAULT_COURSE_TERM_LIMIT,
) -> list[str]:
    """Merge current-session terms with notebook-level persisted terms."""
    persisted = get_notebook_course_terms(db, session.notebook_id, limit=limit)
    keywords = _merge_ordered(current_keywords or [], persisted, limit=limit)
    current_terms = TermCorrector.build_course_terms(
        course_title=course_title,
        keywords=keywords,
        ppt_slides=ppt_slides,
        limit=limit,
    )
    return _merge_ordered(current_terms, persisted, limit=limit)
