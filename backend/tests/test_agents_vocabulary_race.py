"""Direct test for save_to_vocabulary thread-safety.

Two agents saving concurrently should each preserve their entry.
"""

import os
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.core.database import SessionLocal, engine
from app.models import Base, Notebook, Note, Session as DBSession, User
from app.core.auth import hash_password
from app.agents.base import AgentContext, BaseAgent, AgentResult
from app.services.mindmap_service import _set_mind_map_in_vocabulary
from app.services.quiz_service import _set_quiz_bank_in_vocabulary
from sqlalchemy.orm import Session as ORMSession


class AlphaAgent(BaseAgent):
    role = "alpha"
    task_type = "agent_alpha"
    output_kind = "alpha_output"
    prompt_name = "mindmap"

    def run(self, ctx: AgentContext) -> AgentResult:
        self.save_to_vocabulary(ctx, {"value": "alpha"})
        ctx.db.commit()
        return AgentResult(success=True)


class BetaAgent(BaseAgent):
    role = "beta"
    task_type = "agent_beta"
    output_kind = "beta_output"
    prompt_name = "mindmap"

    def run(self, ctx: AgentContext) -> AgentResult:
        self.save_to_vocabulary(ctx, {"value": "beta"})
        ctx.db.commit()
        return AgentResult(success=True)


def _setup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            username="race_test",
            email=f"race_{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("race12345"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        notebook = Notebook(title="Race NB", user_id=user.id)
        db.add(notebook)
        db.commit()
        db.refresh(notebook)

        session = DBSession(title="Race Session", notebook_id=notebook.id, keywords=[])
        db.add(session)
        db.commit()
        db.refresh(session)

        note = Note(session_id=session.id, content="race content", vocabulary=[])
        db.add(note)
        db.commit()
        db.refresh(note)

        return user.id, notebook.id, session.id, note.id
    finally:
        db.close()


def _agent_worker(session_id: str, user_id: str, agent_cls, note_id: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        session = db.query(DBSession).filter(DBSession.id == session_id).first()
        notebook = db.query(Notebook).filter(Notebook.id == session.notebook_id).first()
        note = db.query(Note).filter(Note.id == note_id).first()
        ctx = AgentContext(
            session_id=session_id,
            user=user,
            db=db,
            note=note,
            session=session,
            notebook=notebook,
        )
        agent = agent_cls()
        agent.run(ctx)
    finally:
        db.close()


def test_save_to_vocabulary_is_thread_safe():
    user_id, _, session_id, note_id = _setup()

    import threading

    t1 = threading.Thread(target=_agent_worker, args=(session_id, user_id, AlphaAgent, note_id))
    t2 = threading.Thread(target=_agent_worker, args=(session_id, user_id, BetaAgent, note_id))

    # Add a small stagger to maximize the race window.
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    db = SessionLocal()
    try:
        note = db.query(Note).filter(Note.id == note_id).first()
        vocab = note.vocabulary if isinstance(note.vocabulary, list) else []
        kinds = {item.get("kind") for item in vocab if isinstance(item, dict)}
        assert "alpha_output" in kinds, f"Missing alpha_output in {kinds}"
        assert "beta_output" in kinds, f"Missing beta_output in {kinds}"
    finally:
        db.close()


def test_concurrent_mind_map_and_quiz_bank_preserve_both():
    """Two independent DB sessions saving mind_map and quiz_bank concurrently.

    Each write must preserve the other kind; the final row must contain both
    entries.  This exercises the ``SELECT ... FOR UPDATE`` row lock across
    separate sessions.
    """
    user_id, _, session_id, note_id = _setup()
    import threading

    def save_mind_map():
        db = SessionLocal()
        try:
            note = db.query(Note).filter(Note.id == note_id).first()
            _set_mind_map_in_vocabulary(
                db, note, {"nodes": [{"id": "n1"}]}, "mindmap_hash"
            )
        finally:
            db.close()

    def save_quiz_bank():
        db = SessionLocal()
        try:
            note = db.query(Note).filter(Note.id == note_id).first()
            _set_quiz_bank_in_vocabulary(
                db, note, {"questions": [{"id": "q1"}]}, "quiz_hash"
            )
        finally:
            db.close()

    t1 = threading.Thread(target=save_mind_map)
    t2 = threading.Thread(target=save_quiz_bank)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    db = SessionLocal()
    try:
        note = db.query(Note).filter(Note.id == note_id).first()
        vocab = note.vocabulary if isinstance(note.vocabulary, list) else []
        kinds = {item.get("kind") for item in vocab if isinstance(item, dict)}
        assert "mind_map" in kinds, f"Missing mind_map in {kinds}"
        assert "quiz_bank" in kinds, f"Missing quiz_bank in {kinds}"
    finally:
        db.close()
