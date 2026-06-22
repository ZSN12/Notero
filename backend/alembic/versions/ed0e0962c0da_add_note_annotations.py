"""add note annotations

Revision ID: ed0e0962c0da
Revises: b095f3411709
Create Date: 2026-06-17 10:34:03.182787

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed0e0962c0da'
down_revision: Union[str, Sequence[str], None] = 'b095f3411709'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add annotations JSON column to notes."""
    op.add_column(
        "notes",
        sa.Column("annotations", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Drop annotations column from notes."""
    op.drop_column("notes", "annotations")
