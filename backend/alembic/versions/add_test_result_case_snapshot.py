"""Add immutable test-case snapshots to execution results.

Revision ID: add_test_result_case_snapshot
Revises: add_test_case_review_policy
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import column_exists


revision = "add_test_result_case_snapshot"
down_revision = "add_test_case_review_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not column_exists(bind, "test_results", "test_case_snapshot"):
        op.add_column("test_results", sa.Column("test_case_snapshot", sa.JSON(), nullable=True))
    if not column_exists(bind, "test_results", "test_case_revision_number"):
        op.add_column("test_results", sa.Column("test_case_revision_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if column_exists(bind, "test_results", "test_case_revision_number"):
        op.drop_column("test_results", "test_case_revision_number")
    if column_exists(bind, "test_results", "test_case_snapshot"):
        op.drop_column("test_results", "test_case_snapshot")
