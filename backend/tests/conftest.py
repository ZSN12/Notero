"""Shared pytest fixtures for backend tests.

This module acts as the test harness entry point: it sets up the test
database, registers factories, and provides fixtures with strict transaction
isolation so that API calls, direct ORM operations, and background helpers
that open their own SessionLocal() all share the same rolled-back transaction.
"""

import importlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from pytest_factoryboy import register
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Ensure backend is on path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Force a test database before any app module is imported (app.config loads
# the repo .env and would otherwise overwrite this value).
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/notero_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
os.environ.setdefault("ADMIN_DEFAULT_EMAIL", "admin")
os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "admin123")
os.environ.setdefault("SKIP_ASR_PRELOAD", "1")
os.environ.setdefault("AGENTS_SYNC", "1")


def _ensure_test_database(url: str) -> None:
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"}:
        raise RuntimeError("Backend tests require a PostgreSQL TEST_DATABASE_URL.")
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Refusing to reset non-test database '{db_name}'. "
            "Use a database name containing 'test' for TEST_DATABASE_URL."
        )

    maintenance_url = urlunparse(parsed._replace(path="/postgres"))
    admin_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()


_ensure_test_database(os.environ["DATABASE_URL"])

# Import app modules AFTER the test DATABASE_URL has been pinned.
from app.core.task_runner import wait_for_agent_threads  # noqa: E402
from app.main import app  # noqa: E402
from app.core.database import SessionLocal, engine, get_db  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.core.auth import hash_password  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tests.harness.helpers import (  # noqa: E402
    auth_headers as _auth_headers_helper,
    create_notebook_and_session,
)

# Ensure tables exist for the shared PostgreSQL test database
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

# Register factory-boy factories so they can be injected as fixtures.
from tests.harness.factories import (  # noqa: E402
    NotebookFactory,
    NoteFactory,
    SessionFactory,
    TaskFactory,
    UserFactory,
    VocabularyFactory,
)

register(UserFactory)
register(NotebookFactory)
register(SessionFactory)
register(NoteFactory)
register(TaskFactory)
register(VocabularyFactory)

# Modules that import SessionLocal directly.  We patch their module-level
# reference so that every SessionLocal() call inside the app participates in
# the same test transaction.
_SESSION_LOCAL_MODULES = [
    "app.core.database",
    "app.main",
    "app.tasks.agent_tasks",
    "app.api.agents",
    "app.agents.dispatch",
    "app.agents.orchestrator",
    "app.services.file_service",
    "app.services.mindmap_service",
    "app.services.quiz_service",
    "app.core.unit_of_work",
    "app.api.process.asr_ws",
    "app.api.process.audio",
    "app.api.process.correction",
]


def _load_session_local_modules():
    """Return (module, original_SessionLocal) pairs for modules to patch."""
    pairs = []
    for name in _SESSION_LOCAL_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if hasattr(mod, "SessionLocal"):
            pairs.append((mod, mod.SessionLocal))
    return pairs


_MODULE_SESSION_LOCAL_PAIRS = _load_session_local_modules()


@pytest.fixture(autouse=True)
def _join_agent_threads():
    yield
    wait_for_agent_threads(timeout=10.0)


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """Reset login rate-limit state before each test to avoid cross-test locking."""
    from app.core.login_tracker import reset_login_attempts_for_tests
    reset_login_attempts_for_tests()
    yield


@pytest.fixture
def db():
    """Yield a SQLAlchemy session bound to a rolled-back transaction.

    Every SessionLocal() call inside the patched modules is redirected to a
    session that lives on the same connection/transaction, so data created via
    endpoints, direct ORM access, and background helpers is isolated per test.
    """
    connection = engine.connect()
    transaction = connection.begin()

    # Begin a nested transaction (savepoint) so that inner session.commit()
    # calls do not end the outer transaction that we will roll back.
    connection.begin_nested()
    session = SessionLocal(bind=connection)
    session.begin_nested()

    UserFactory._meta.sqlalchemy_session = session
    NotebookFactory._meta.sqlalchemy_session = session
    SessionFactory._meta.sqlalchemy_session = session
    NoteFactory._meta.sqlalchemy_session = session
    TaskFactory._meta.sqlalchemy_session = session
    VocabularyFactory._meta.sqlalchemy_session = session

    # Build a session maker bound to the test connection so that all
    # SessionLocal() calls participate in the same outer transaction.
    test_sessionmaker = sessionmaker(class_=Session, bind=connection)

    def test_session_local() -> Session:
        s = test_sessionmaker()
        s.begin_nested()
        return s

    originals = {}
    for mod, _ in _MODULE_SESSION_LOCAL_PAIRS:
        originals[mod] = mod.SessionLocal
        mod.SessionLocal = test_session_local

    try:
        yield session
    finally:
        for mod, orig in originals.items():
            mod.SessionLocal = orig

        UserFactory._meta.sqlalchemy_session = None
        NotebookFactory._meta.sqlalchemy_session = None
        SessionFactory._meta.sqlalchemy_session = None
        NoteFactory._meta.sqlalchemy_session = None
        TaskFactory._meta.sqlalchemy_session = None
        VocabularyFactory._meta.sqlalchemy_session = None
        session.rollback()
        session.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def client(db):
    """Yield a TestClient with app lifespan and DB dependency override."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Login as admin and return Authorization headers."""
    return _auth_headers_helper(client)


@pytest.fixture
def ensure_admin(db):
    """Ensure the default admin user exists in the current DB session."""
    admin = db.query(User).filter(User.email == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            email="admin",
            password_hash=hash_password("admin123"),
        )
        db.add(admin)
        db.commit()
    return admin


# Convenience harness fixtures -------------------------------------------------

@pytest.fixture
def admin_user(ensure_admin):
    """Return the default admin user for the current test transaction."""
    return ensure_admin


@pytest.fixture
def sample_notebook(notebook_factory, ensure_admin):
    """Create a persisted notebook owned by the default admin."""
    return notebook_factory(user=ensure_admin)


@pytest.fixture
def sample_session(session_factory, sample_notebook):
    """Create a persisted session inside sample_notebook."""
    return session_factory(notebook=sample_notebook)


@pytest.fixture
def sample_note(note_factory, sample_session):
    """Create a persisted note inside sample_session."""
    return note_factory(session=sample_session)


@pytest.fixture
def notebook_session(client: TestClient, auth_headers: dict[str, str]) -> tuple[str, str]:
    """Create a notebook + session via API and return (notebook_id, session_id)."""
    return create_notebook_and_session(client, auth_headers)
