"""Add versioned test-case review tasks.

Revision ID: add_test_case_review_tasks
Revises: add_test_case_images
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import table_exists


revision = "add_test_case_review_tasks"
down_revision = "add_test_case_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, "test_case_review_tasks"):
        op.create_table(
            "test_case_review_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("test_suite_id", sa.Integer(), sa.ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False, server_default="single"),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_test_case_review_tasks_project_id", "test_case_review_tasks", ["project_id"])
        op.create_index("ix_test_case_review_tasks_test_suite_id", "test_case_review_tasks", ["test_suite_id"])
        op.create_index("ix_test_case_review_tasks_status", "test_case_review_tasks", ["status"])
    if not table_exists(bind, "test_case_review_rounds"):
        op.create_table(
            "test_case_review_rounds",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("test_case_review_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("round_number", sa.Integer(), nullable=False),
            sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("task_id", "test_case_id", "round_number", name="uq_test_case_review_round"),
        )
        op.create_index("ix_test_case_review_rounds_task_id", "test_case_review_rounds", ["task_id"])
        op.create_index("ix_test_case_review_rounds_test_case_id", "test_case_review_rounds", ["test_case_id"])
        op.create_index("ix_test_case_review_rounds_status", "test_case_review_rounds", ["status"])
    if not table_exists(bind, "test_case_review_assignments"):
        op.create_table(
            "test_case_review_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("round_id", sa.Integer(), sa.ForeignKey("test_case_review_rounds.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("decision", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("comment", sa.String(2000)),
            sa.Column("has_suggestion", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("decided_at", sa.DateTime(timezone=True)),
            sa.Column("removed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("round_id", "reviewer_id", name="uq_test_case_review_assignment"),
        )
        op.create_index("ix_test_case_review_assignments_round_id", "test_case_review_assignments", ["round_id"])
        op.create_index("ix_test_case_review_assignments_reviewer_id", "test_case_review_assignments", ["reviewer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("test_case_review_assignments", "test_case_review_rounds", "test_case_review_tasks"):
        if table_exists(bind, table):
            op.drop_table(table)
