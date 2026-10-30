"""Add token ledger, cached tokens, and failure suggestions.

Revision ID: add_ai_automation_followup
Revises: add_ai_automation_platform
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import add_column_if_missing, drop_column_if_exists, table_exists


revision = "add_ai_automation_followup"
down_revision = "add_ai_automation_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        op,
        "ai_automation_tasks",
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    connection = op.get_bind()
    if not table_exists(connection, "ai_automation_token_ledger"):
        op.create_table(
            "ai_automation_token_ledger",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("entry_type", sa.String(length=30), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost_micros", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["ai_automation_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "entry_type", name="uq_ai_automation_token_ledger_entry"),
        )
        op.create_index("ix_ai_automation_token_ledger_task_id", "ai_automation_token_ledger", ["task_id"])
        op.create_index("ix_ai_automation_token_ledger_project_id", "ai_automation_token_ledger", ["project_id"])
    if not table_exists(connection, "ai_automation_failure_suggestions"):
        op.create_table(
            "ai_automation_failure_suggestions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("signals", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("confirmed_by", sa.Integer(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["ai_automation_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", name="uq_ai_automation_failure_suggestion_task"),
        )
        op.create_index("ix_ai_automation_failure_suggestions_task_id", "ai_automation_failure_suggestions", ["task_id"])
        op.create_index("ix_ai_automation_failure_suggestions_project_id", "ai_automation_failure_suggestions", ["project_id"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "ai_automation_failure_suggestions"):
        op.drop_table("ai_automation_failure_suggestions")
    if table_exists(connection, "ai_automation_token_ledger"):
        op.drop_table("ai_automation_token_ledger")
    drop_column_if_exists(op, "ai_automation_tasks", "cached_tokens")
