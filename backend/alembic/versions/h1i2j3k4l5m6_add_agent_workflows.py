"""Add agent_workflows table.

Revision ID: h1i2j3k4l5m6
Revises: g7h8i9j0k1l2
Create Date: 2026-06-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("agent_workflows"):
        return
    op.create_table(
        "agent_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False, default=list),
        sa.Column("dependencies", sa.JSON(), nullable=False, default=dict),
        sa.Column("role_states", sa.JSON(), nullable=False, default=dict),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_workflows_session_id", "agent_workflows", ["session_id"])
    op.create_index("ix_agent_workflows_status", "agent_workflows", ["status"])


def downgrade() -> None:
    op.drop_table("agent_workflows")
