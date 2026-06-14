"""Unit of work pattern for background tasks and long-running operations.

Provides a context manager that handles session creation, commit, rollback,
and cleanup consistently across agent threads, Celery tasks, and async workers.
"""

from contextlib import contextmanager
from typing import Generator, Optional
import logging

from sqlalchemy.orm import Session

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Create a database session with automatic commit/rollback/close.

    Usage:
        with db_session() as db:
            user = db.query(User).filter(...).first()
            # commit happens automatically on success
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
        logger.debug("db_session committed")
    except Exception:
        db.rollback()
        logger.warning("db_session rolled back")
        raise
    finally:
        db.close()
        logger.debug("db_session closed")


@contextmanager
def db_session_nested(
    parent: Optional[Session] = None,
) -> Generator[Session, None, None]:
    """Use an existing session if provided, otherwise create a new one.

    Useful when a function may be called from both HTTP handlers (which
    already have a session) and background threads (which need a new one).
    """
    if parent is not None:
        yield parent
        return

    with db_session() as db:
        yield db
