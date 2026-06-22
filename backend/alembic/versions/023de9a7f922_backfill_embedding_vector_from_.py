"""backfill embedding_vector from embedding_v2

Revision ID: 023de9a7f922
Revises: a7a62ca55395
Create Date: 2026-06-22 03:17:17.386492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging
import struct

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = '023de9a7f922'
down_revision: Union[str, Sequence[str], None] = 'a7a62ca55395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VEC_DIM = 1536
BATCH_SIZE = 500


def _unpack_neural_bytes(emb_bytes: bytes) -> list[float] | None:
    """Convert packed float32 bytes to a list of floats suitable for pgvector."""
    if not emb_bytes:
        return None
    expected = VEC_DIM * 4
    if len(emb_bytes) != expected:
        logger.warning("unexpected embedding_v2 length: %s (expected %s)", len(emb_bytes), expected)
        return None
    try:
        return list(struct.unpack(f"{VEC_DIM}f", emb_bytes))
    except Exception:
        logger.warning("failed to unpack embedding_v2 bytes", exc_info=True)
        return None


def upgrade() -> None:
    """Backfill embedding_vector from existing embedding_v2 bytes."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        logger.info("Skipping embedding_vector backfill: not running on PostgreSQL")
        return

    # Ensure pgvector extension is available.
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as e:
        logger.warning("Could not create pgvector extension: %s", e)
        logger.warning("Skipping embedding_vector backfill.")
        return

    select_sql = sa.text(
        "SELECT id, embedding_v2 FROM vector_chunks "
        "WHERE embedding_v2 IS NOT NULL AND embedding_vector IS NULL "
        f"LIMIT {BATCH_SIZE}"
    )
    update_sql = sa.text(
        "UPDATE vector_chunks SET embedding_vector = :vec WHERE id = :id"
    )

    total_updated = 0
    total_skipped = 0

    while True:
        rows = bind.execute(select_sql).fetchall()
        if not rows:
            break

        for row_id, emb_bytes in rows:
            vec = _unpack_neural_bytes(emb_bytes)
            if vec is None:
                total_skipped += 1
                continue
            bind.execute(update_sql, {"id": row_id, "vec": vec})
            total_updated += 1

        logger.info("backfilled %s vector_chunks rows so far", total_updated)

    logger.info(
        "embedding_vector backfill complete: updated=%s skipped=%s",
        total_updated, total_skipped,
    )


def downgrade() -> None:
    """No-op: downgrading the data backfill is not meaningful."""
    pass
