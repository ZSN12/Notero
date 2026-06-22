"""add missing indexes

Revision ID: e4f5g6h7i8j9
Revises: d3e4f5g6h7i8
Create Date: 2026-06-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5g6h7i8j9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5g6h7i8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes for frequently queried foreign keys and filters."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    # Foreign keys and commonly filtered columns
    op.create_index('ix_notebooks_user_id', 'notebooks', ['user_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_sessions_notebook_id', 'sessions', ['notebook_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_sessions_share_token', 'sessions', ['share_token'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_sessions_share_enabled', 'sessions', ['share_enabled'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_notes_session_id', 'notes', ['session_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_files_session_id', 'files', ['session_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_tasks_session_id', 'tasks', ['session_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_tasks_session_type_status', 'tasks', ['session_id', 'task_type', 'status'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_vocabulary_notebook_id', 'vocabulary', ['notebook_id'], if_not_exists=(dialect == 'postgresql'))
    op.create_index('ix_vector_chunks_source_type', 'vector_chunks', ['source_type'], if_not_exists=(dialect == 'postgresql'))


def downgrade() -> None:
    """Drop the added indexes."""
    op.drop_index('ix_vector_chunks_source_type', table_name='vector_chunks')
    op.drop_index('ix_vocabulary_notebook_id', table_name='vocabulary')
    op.drop_index('ix_tasks_session_type_status', table_name='tasks')
    op.drop_index('ix_tasks_session_id', table_name='tasks')
    op.drop_index('ix_files_session_id', table_name='files')
    op.drop_index('ix_notes_session_id', table_name='notes')
    op.drop_index('ix_sessions_share_enabled', table_name='sessions')
    op.drop_index('ix_sessions_share_token', table_name='sessions')
    op.drop_index('ix_sessions_notebook_id', table_name='sessions')
    op.drop_index('ix_notebooks_user_id', table_name='notebooks')
