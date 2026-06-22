"""Database safety helpers for the test harness.

These functions are intentionally kept outside ``conftest.py`` so they can be
unit-tested without importing the entire pytest harness.
"""

from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text


def validate_test_database_url(url: str) -> str:
    """Return the database name if ``url`` points to a test database.

    Raises:
        RuntimeError: if the URL is not PostgreSQL or the database name does
        not contain ``test`` (case-insensitive).
    """
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"}:
        raise RuntimeError("Backend tests require a PostgreSQL TEST_DATABASE_URL.")
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Refusing to reset non-test database '{db_name}'. "
            "Use a database name containing 'test' for TEST_DATABASE_URL."
        )
    return db_name


def ensure_test_database(url: str) -> None:
    """Create the test database if it does not already exist.

    The URL is validated first; this function never falls back to the
    development database.
    """
    validate_test_database_url(url)
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
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
