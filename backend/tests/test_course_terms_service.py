"""Tests for notebook-level shared course terms."""

import pytest

from app.models import CourseTerm, Notebook, Session
from app.services.course_terms_service import (
    build_shared_course_terms_for_session,
    upsert_notebook_course_terms,
)


@pytest.mark.integration
def test_course_terms_survive_session_delete(db, admin_user):
    notebook = Notebook(title="操作系统", user_id=admin_user.id, session_count=1)
    db.add(notebook)
    db.commit()
    db.refresh(notebook)

    session = Session(notebook_id=notebook.id, title="进程通信")
    db.add(session)
    db.commit()
    db.refresh(session)

    upsert_notebook_course_terms(
        db,
        notebook.id,
        ["父进程", "子进程", "fork", "无名管道"],
        source="ppt",
        session_id=session.id,
        commit=True,
    )

    db.delete(session)
    db.commit()

    terms = [row.term for row in db.query(CourseTerm).filter(CourseTerm.notebook_id == notebook.id).all()]
    assert "子进程" in terms
    assert "fork" in terms


@pytest.mark.integration
def test_shared_terms_are_used_for_later_session_without_ppt(db, admin_user):
    notebook = Notebook(title="操作系统", user_id=admin_user.id, session_count=2)
    db.add(notebook)
    db.commit()
    db.refresh(notebook)

    first = Session(notebook_id=notebook.id, title="第一讲")
    second = Session(notebook_id=notebook.id, title="第二讲")
    db.add_all([first, second])
    db.commit()
    db.refresh(first)
    db.refresh(second)

    upsert_notebook_course_terms(
        db,
        notebook.id,
        ["父进程", "子进程", "fork"],
        source="ppt",
        session_id=first.id,
        commit=True,
    )

    terms = build_shared_course_terms_for_session(
        db,
        second,
        course_title=notebook.title,
        current_keywords=[],
        ppt_slides=None,
    )

    assert "父进程" in terms
    assert "子进程" in terms
    assert "fork" in terms
