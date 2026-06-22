"""add pgvector hnsw index

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure embedding_vector is vector(1536) and create HNSW index."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        logger.info("Skipping pgvector index: not running on PostgreSQL")
        return

    try:
        with bind.begin_nested():
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as e:
        logger.warning("Could not create pgvector extension: %s", e)
        return

    # If the column was previously created as TEXT (older migration bug),
    # attempt to cast it to vector(1536). This may fail if non-numeric
    # data is present; in that case manual cleanup is required.
    try:
        op.execute(
            "ALTER TABLE vector_chunks "
            "ALTER COLUMN embedding_vector TYPE vector(1536) "
            "USING embedding_vector::vector(1536)"
        )
        logger.info("Converted embedding_vector to vector(1536)")
    except Exception as e:
        logger.warning(
            "Could not convert embedding_vector to vector(1536) "
            "(may already be correct type): %s",
            e,
        )

    # Create HNSW index for fast approximate vector search.
    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_chunks_embedding_hnsw "
            "ON vector_chunks USING hnsw (embedding_vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
        logger.info("Created HNSW index on vector_chunks.embedding_vector")
    except Exception as e:
        logger.warning("Could not create HNSW index: %s", e)

    # Also add a plain B-tree index on session_id for metadata filtering.
    try:
        op.create_index(
            "idx_vector_chunks_session_id",
            "vector_chunks",
            ["session_id"],
            if_not_exists=True,
        )
        logger.info("Created B-tree index on vector_chunks.session_id")
    except Exception as e:
        logger.warning("Could not create session_id index: %s", e)


def downgrade() -> None:
    """Drop pgvector indexes."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    try:
        op.drop_index("idx_vector_chunks_embedding_hnsw", table_name="vector_chunks", if_exists=True)
    except Exception as e:
        logger.warning("Could not drop HNSW index: %s", e)

    try:
        op.drop_index("idx_vector_chunks_session_id", table_name="vector_chunks", if_exists=True)
    except Exception as e:
        logger.warning("Could not drop session_id index: %s", e)
