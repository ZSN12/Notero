"""add course terms

Revision ID: e25f6a7b8c9d
Revises: d7ba5e18bf31
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e25f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "d7ba5e18bf31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_terms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notebook_id", sa.String(length=36), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("first_seen_session_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notebook_id", "term", name="uix_course_terms_notebook_term"),
    )
    op.create_index(
        "ix_course_terms_notebook_weight",
        "course_terms",
        ["notebook_id", "weight"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_course_terms_notebook_weight", table_name="course_terms")
    op.drop_table("course_terms")
