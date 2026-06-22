"""add composite indexes

Revision ID: g7h8i9j0k1l2
Revises: e4f5g6h7i8j9, f8b6d2c4a91e
Create Date: 2026-06-11 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, Sequence[str], None] = ('e4f5g6h7i8j9', 'f8b6d2c4a91e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes for frequently queried column combinations.

    Existing single-column indexes (added in e4f5g6h7i8j9) are kept for
    backward compatibility; these composite indexes optimize multi-column
    lookups and sorting.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    # Notebook list queries filter by user_id and sort by created_at
    op.create_index('ix_notebooks_user_id_created', 'notebooks', ['user_id', 'created_at'], if_not_exists=(dialect == 'postgresql'))

    # Session list queries filter by notebook_id and sort by created_at
    op.create_index('ix_sessions_notebook_id_created', 'sessions', ['notebook_id', 'created_at'], if_not_exists=(dialect == 'postgresql'))

    # Task status polling filters by session_id and status
    op.create_index('ix_tasks_session_id_status', 'tasks', ['session_id', 'status'], if_not_exists=(dialect == 'postgresql'))

    # Processing state lookups by session and by active status
    op.create_index('ix_sps_session_id', 'session_processing_states', ['session_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_sps_status_updated', 'session_processing_states', ['status', 'updated_at'], if_not_exists=(dialect == 'postgresql'))


def downgrade() -> None:
    """Drop composite indexes."""
    op.drop_index('ix_sps_status_updated', table_name='session_processing_states')
    op.drop_index('ix_sps_session_id', table_name='session_processing_states')
    op.drop_index('ix_tasks_session_id_status', table_name='tasks')
    op.drop_index('ix_sessions_notebook_id_created', table_name='sessions')
    op.drop_index('ix_notebooks_user_id_created', table_name='notebooks')
