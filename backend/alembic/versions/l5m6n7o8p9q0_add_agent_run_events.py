"""Add agent run events table.

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l5m6n7o8p9q0"
down_revision: Union[str, None] = "k4l5m6n7o8p9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=True),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(50), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_workflows.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_agent_run_events_session_created",
        "agent_run_events",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_agent_run_events_workflow_created",
        "agent_run_events",
        ["workflow_id", "created_at"],
    )
    op.create_index(
        "ix_agent_run_events_task_created",
        "agent_run_events",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_task_created", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_workflow_created", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_session_created", table_name="agent_run_events")
    op.drop_table("agent_run_events")
