"""Add automation credentials, batches, devices, drafts, and budget alerts.

Revision ID: add_ai_automation_platform
Revises: add_ai_automation_evidence
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import add_column_if_missing, drop_column_if_exists, table_exists


revision = "add_ai_automation_platform"
down_revision = "add_ai_automation_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, "ai_automation_batches"):
        op.create_table(
            "ai_automation_batches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=120), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("runner_type", sa.String(length=20), nullable=False),
            sa.Column("execution_mode", sa.String(length=20), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("requested_by", sa.Integer(), nullable=False),
            sa.Column("allowlist", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["execution_environments.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "idempotency_key", name="uq_ai_automation_batch_idempotency"),
        )
        op.create_index("ix_ai_automation_batches_project_id", "ai_automation_batches", ["project_id"])

    if not table_exists(connection, "ai_automation_credentials"):
        op.create_table(
            "ai_automation_credentials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "name", name="uq_ai_automation_credential_project_name"),
        )
        op.create_index("ix_ai_automation_credentials_project_id", "ai_automation_credentials", ["project_id"])

    if not table_exists(connection, "ai_automation_devices"):
        op.create_table(
            "ai_automation_devices",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("runner_id", sa.Integer(), nullable=True),
            sa.Column("external_id", sa.String(length=120), nullable=False),
            sa.Column("platform", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lock_task_id", sa.Integer(), nullable=True),
            sa.Column("lock_runner_id", sa.Integer(), nullable=True),
            sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["runner_id"], ["ai_automation_runners.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["lock_task_id"], ["ai_automation_tasks.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["lock_runner_id"], ["ai_automation_runners.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "external_id", name="uq_ai_automation_device_project_external"),
        )
        op.create_index("ix_ai_automation_devices_project_id", "ai_automation_devices", ["project_id"])
        op.create_index("ix_ai_automation_devices_project_status", "ai_automation_devices", ["project_id", "status"])

    if not table_exists(connection, "ai_automation_script_drafts"):
        op.create_table(
            "ai_automation_script_drafts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_task_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("script", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_task_id"], ["ai_automation_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["execution_environments.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_task_id", "revision", name="uq_ai_automation_script_draft_revision"),
        )
        op.create_index("ix_ai_automation_script_drafts_project_id", "ai_automation_script_drafts", ["project_id"])
        op.create_index("ix_ai_automation_script_drafts_source_task_id", "ai_automation_script_drafts", ["source_task_id"])

    if not table_exists(connection, "ai_automation_budget_alerts"):
        op.create_table(
            "ai_automation_budget_alerts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("level", sa.String(length=20), nullable=False),
            sa.Column("threshold_ratio", sa.String(length=8), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False),
            sa.Column("output_tokens", sa.Integer(), nullable=False),
            sa.Column("token_budget", sa.Integer(), nullable=False),
            sa.Column("estimated_cost_micros", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["ai_automation_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "level", name="uq_ai_automation_budget_alert_level"),
        )
        op.create_index("ix_ai_automation_budget_alerts_task_id", "ai_automation_budget_alerts", ["task_id"])
        op.create_index("ix_ai_automation_budget_alerts_project_id", "ai_automation_budget_alerts", ["project_id"])

    add_column_if_missing(op, "ai_automation_tasks", sa.Column("batch_id", sa.Integer(), nullable=True))
    add_column_if_missing(op, "ai_automation_tasks", sa.Column("retry_of_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    drop_column_if_exists(op, "ai_automation_tasks", "retry_of_id")
    drop_column_if_exists(op, "ai_automation_tasks", "batch_id")
    connection = op.get_bind()
    for table_name in (
        "ai_automation_budget_alerts",
        "ai_automation_script_drafts",
        "ai_automation_devices",
        "ai_automation_credentials",
        "ai_automation_batches",
    ):
        if table_exists(connection, table_name):
            op.drop_table(table_name)
