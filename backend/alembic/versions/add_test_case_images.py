"""Add controlled images for test cases and structured steps.

Revision ID: add_test_case_images
Revises: add_ai_automation_followup
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import table_exists


revision = "add_test_case_images"
down_revision = "add_ai_automation_followup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if table_exists(op.get_bind(), "test_case_images"):
        return
    op.create_table(
        "test_case_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("test_step_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("alt_text", sa.String(length=500), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_step_id"], ["test_case_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_test_case_images_test_case_id", "test_case_images", ["test_case_id"])
    op.create_index("ix_test_case_images_test_step_id", "test_case_images", ["test_step_id"])


def downgrade() -> None:
    if table_exists(op.get_bind(), "test_case_images"):
        op.drop_table("test_case_images")
