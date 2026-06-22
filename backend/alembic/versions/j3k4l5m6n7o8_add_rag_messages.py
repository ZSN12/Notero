"""Add rag_messages table for multi-turn RAG conversations.

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7, ed0e0962c0da
Create Date: 2026-06-17 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j3k4l5m6n7o8"
down_revision: Union[str, Sequence[str], None] = ("i2j3k4l5m6n7", "ed0e0962c0da")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rag_messages_session_id_created", "rag_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_rag_messages_session_id_created", table_name="rag_messages")
    op.drop_table("rag_messages")
