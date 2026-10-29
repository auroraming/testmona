"""Add unified AI automation task records.

Revision ID: add_ai_automation_tasks
Revises: add_mindmap_test_case_links
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import table_exists


revision = "add_ai_automation_tasks"
down_revision = "add_mindmap_test_case_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "ai_automation_tasks"):
        return
    op.create_table(
        "ai_automation_runners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("runner_type", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=12), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="offline"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_ai_automation_runner_project_name"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_ai_automation_runners_project_id", "ai_automation_runners", ["project_id"])
    op.create_index("ix_ai_automation_runners_token_hash", "ai_automation_runners", ["token_hash"])
    op.create_index("ix_ai_automation_runners_project_type", "ai_automation_runners", ["project_id", "runner_type"])

    op.create_table(
        "ai_automation_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=True),
        sa.Column("test_run_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("runner_type", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False, server_default="ai"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("token_budget", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runner_id", sa.Integer(), nullable=True),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["execution_environments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["runner_id"], ["ai_automation_runners.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_automation_tasks_project_id", "ai_automation_tasks", ["project_id"])
    op.create_index("ix_ai_automation_tasks_test_case_id", "ai_automation_tasks", ["test_case_id"])
    op.create_index("ix_ai_automation_tasks_test_run_id", "ai_automation_tasks", ["test_run_id"])
    op.create_index("ix_ai_automation_tasks_requested_by", "ai_automation_tasks", ["requested_by"])
    op.create_index("ix_ai_automation_tasks_status", "ai_automation_tasks", ["status"])
    op.create_index("ix_ai_automation_tasks_runner_id", "ai_automation_tasks", ["runner_id"])
    op.create_index("ix_ai_automation_tasks_lease_expires_at", "ai_automation_tasks", ["lease_expires_at"])
    op.create_index("ix_ai_automation_tasks_project_status", "ai_automation_tasks", ["project_id", "status"])
    op.create_index("ix_ai_automation_tasks_project_created", "ai_automation_tasks", ["project_id", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "ai_automation_tasks"):
        op.drop_table("ai_automation_tasks")
    if table_exists(connection, "ai_automation_runners"):
        op.drop_table("ai_automation_runners")
