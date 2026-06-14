"""Shared pytest fixtures for backend tests.

Joins all tracked agent daemon threads after each test case so that slow LLM
mocks do not leak into the next test and pollute OpenAI mock call counts or
Task state.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import create_engine, text

# Ensure backend is on path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
os.environ.setdefault("ADMIN_DEFAULT_EMAIL", "admin")
os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "admin123")
os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["AGENTS_SYNC"] = "1"
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/notero_test",
)


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

from app.core.task_runner import wait_for_agent_threads  # noqa: E402
from app.main import app  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.core.auth import hash_password  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Ensure tables exist for the shared PostgreSQL test database
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


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
def client():
    """Yield a TestClient with app lifespan managed."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    """Yield a fresh SQLAlchemy session and roll it back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Login as admin and return Authorization headers."""
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": "http://localhost:5173",
    }


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
