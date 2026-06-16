"""add task updated_at

Revision ID: b095f3411709
Revises: i2j3k4l5m6n7
Create Date: 2026-06-16 15:28:02.952307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b095f3411709'
down_revision: Union[str, Sequence[str], None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add updated_at to tasks."""
    op.add_column(
        "tasks",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )


def downgrade() -> None:
    """Drop updated_at from tasks."""
    op.drop_column("tasks", "updated_at")
