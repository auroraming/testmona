"""Add ordered AI automation evidence.

Revision ID: add_ai_automation_evidence
Revises: add_ai_automation_tasks
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import table_exists


revision = "add_ai_automation_evidence"
down_revision = "add_ai_automation_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "ai_automation_evidence"):
        return
    op.create_table(
        "ai_automation_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("artifact_ref", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["ai_automation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_ai_automation_evidence_task_sequence"),
    )
    op.create_index("ix_ai_automation_evidence_task_id", "ai_automation_evidence", ["task_id"])
    op.create_index("ix_ai_automation_evidence_task_created", "ai_automation_evidence", ["task_id", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "ai_automation_evidence"):
        op.drop_table("ai_automation_evidence")
