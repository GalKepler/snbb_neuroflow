"""Add workflow_runs table and enhance existing models.

Revision ID: 001_add_workflow_runs
Revises:
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_add_workflow_runs'
down_revision = None  # Or previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create workflow_runs table
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('trigger_type', sa.String(32), nullable=False),
        sa.Column('trigger_details', sa.JSON()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('stages_completed', sa.JSON(), server_default='[]'),
        sa.Column('current_stage', sa.String(64)),
        sa.Column('sessions_discovered', sa.Integer(), server_default='0'),
        sa.Column('sessions_converted', sa.Integer(), server_default='0'),
        sa.Column('subjects_preprocessed', sa.Integer(), server_default='0'),
        sa.Column('sessions_reconstructed', sa.Integer(), server_default='0'),
        sa.Column('sessions_parcellated', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_stage', sa.String(64)),
        sa.Column('error_details', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_workflow_runs_status', 'workflow_runs', ['status'])
    op.create_index('idx_workflow_runs_started_at', 'workflow_runs', ['started_at'])

    # Add workflow_run_id to pipeline_runs
    op.add_column(
        'pipeline_runs',
        sa.Column('workflow_run_id', sa.Integer(), sa.ForeignKey('workflow_runs.id'))
    )
    op.create_index('idx_pipeline_runs_workflow', 'pipeline_runs', ['workflow_run_id'])

    # Add new columns to sessions
    op.add_column('sessions', sa.Column('needs_rerun', sa.Boolean(), server_default='false'))
    op.add_column('sessions', sa.Column('last_failure_reason', sa.Text()))
    op.add_column('sessions', sa.Column('last_bids_conversion_at', sa.DateTime(timezone=True)))
    op.add_column('sessions', sa.Column('last_qsirecon_at', sa.DateTime(timezone=True)))
    op.add_column('sessions', sa.Column('last_qsiparc_at', sa.DateTime(timezone=True)))

    # Add new columns to subjects
    op.add_column('subjects', sa.Column('needs_qsiprep', sa.Boolean(), server_default='false'))
    op.add_column('subjects', sa.Column('qsiprep_last_run_at', sa.DateTime(timezone=True)))
    op.add_column('subjects', sa.Column('sessions_at_last_qsiprep', sa.Integer(), server_default='0'))


def downgrade() -> None:
    """Downgrade database schema."""
    # Remove columns from subjects
    op.drop_column('subjects', 'sessions_at_last_qsiprep')
    op.drop_column('subjects', 'qsiprep_last_run_at')
    op.drop_column('subjects', 'needs_qsiprep')

    # Remove columns from sessions
    op.drop_column('sessions', 'last_qsiparc_at')
    op.drop_column('sessions', 'last_qsirecon_at')
    op.drop_column('sessions', 'last_bids_conversion_at')
    op.drop_column('sessions', 'last_failure_reason')
    op.drop_column('sessions', 'needs_rerun')

    # Remove workflow_run_id from pipeline_runs
    op.drop_index('idx_pipeline_runs_workflow', table_name='pipeline_runs')
    op.drop_column('pipeline_runs', 'workflow_run_id')

    # Drop workflow_runs table
    op.drop_index('idx_workflow_runs_started_at', table_name='workflow_runs')
    op.drop_index('idx_workflow_runs_status', table_name='workflow_runs')
    op.drop_table('workflow_runs')
