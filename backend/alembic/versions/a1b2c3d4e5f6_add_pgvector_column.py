"""add pgvector embedding_vector column

Revision ID: a1b2c3d4e5f6
Revises: f8b6d2c4a91e
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8b6d2c4a91e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add embedding_vector column for pgvector-based search."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        logger.info("Skipping pgvector column: not running on PostgreSQL")
        return

    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as e:
        logger.warning("Could not create pgvector extension: %s", e)
        logger.warning("Skipping embedding_vector column. Install pgvector and re-run migration if needed.")
        return

    try:
        # Use raw SQL to add a vector(1536) column so we don't need the
        # pgvector Python package present during migration.
        op.execute(
            "ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS embedding_vector vector(1536)"
        )
        logger.info("Added embedding_vector column to vector_chunks")
    except Exception as e:
        logger.warning("Could not add embedding_vector column: %s", e)


def downgrade() -> None:
    """Drop embedding_vector column."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    try:
        op.drop_column("vector_chunks", "embedding_vector")
    except Exception as e:
        logger.warning("Could not drop embedding_vector column: %s", e)
