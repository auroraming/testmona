"""Add project review policy and case re-review marker.

Revision ID: add_test_case_review_policy
Revises: add_test_case_review_tasks
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import column_exists


revision = "add_test_case_review_policy"
down_revision = "add_test_case_review_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not column_exists(bind, "projects", "test_case_review_on_content_change"):
        op.add_column("projects", sa.Column(
            "test_case_review_on_content_change", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
    if not column_exists(bind, "test_cases", "review_required"):
        op.add_column("test_cases", sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    if not column_exists(bind, "test_cases", "review_required_at"):
        op.add_column("test_cases", sa.Column("review_required_at", sa.DateTime(timezone=True)))
    if not column_exists(bind, "test_cases", "review_required_reason"):
        op.add_column("test_cases", sa.Column("review_required_reason", sa.String(100)))


def downgrade() -> None:
    bind = op.get_bind()
    for column in ("review_required_reason", "review_required_at", "review_required"):
        if column_exists(bind, "test_cases", column):
            op.drop_column("test_cases", column)
    if column_exists(bind, "projects", "test_case_review_on_content_change"):
        op.drop_column("projects", "test_case_review_on_content_change")
