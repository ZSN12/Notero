"""merge session_processing_states and pgvector branches

Revision ID: d3e4f5g6h7i8
Revises: 80e13123932d, b2c3d4e5f6g7
Create Date: 2026-06-11 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5g6h7i8'
down_revision: Union[str, Sequence[str], None] = ('80e13123932d', 'b2c3d4e5f6g7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge branch — both parent revisions have already created their objects."""
    pass


def downgrade() -> None:
    """Downgrade not supported for merge revisions."""
    pass
