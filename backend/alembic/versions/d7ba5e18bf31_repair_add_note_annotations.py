"""repair add note annotations

Revision ID: d7ba5e18bf31
Revises: 023de9a7f922
Create Date: 2026-06-22 20:22:09.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = 'd7ba5e18bf31'
down_revision: Union[str, Sequence[str], None] = '023de9a7f922'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add annotations JSON column to notes if it does not already exist.

    This is a repair migration: the Note model already references this column,
    but some deployments may not have it in the actual database.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("notes")}

    if "annotations" in columns:
        logger.info("notes.annotations already exists, skipping repair migration")
        return

    op.add_column(
        "notes",
        sa.Column("annotations", sa.JSON(), nullable=True),
    )
    logger.info("notes.annotations added by repair migration")


def downgrade() -> None:
    """No-op downgrade.

    We cannot reliably determine whether this repair migration created the
    annotations column, so dropping it could destroy user data on databases
    that already had the column before this migration ran.
    """
    pass
