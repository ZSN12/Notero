"""Tests for Alembic migrations."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine


@pytest.mark.integration
def test_notes_table_has_annotations_column():
    """The repair migration should have added notes.annotations."""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("notes")}
    assert "annotations" in columns


@pytest.mark.integration
def test_repair_migration_is_idempotent():
    """Running upgrade head again should not fail even if annotations already exists.

    The test harness creates tables directly from the models, leaving the
    alembic_version table empty. Stamp the current head first so that Alembic
    sees the schema as up-to-date; the repair migration must then skip cleanly.
    """
    alembic_cfg = Config("alembic.ini")
    command.stamp(alembic_cfg, "head")
    command.upgrade(alembic_cfg, "head")

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("notes")}
    assert "annotations" in columns
