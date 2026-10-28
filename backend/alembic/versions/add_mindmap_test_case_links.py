"""Add normalized mindmap node to test-case links.

Revision ID: add_mindmap_test_case_links
Revises: add_user_profile_fields
"""

from alembic import op
import sqlalchemy as sa

from app.services.migration_helpers import table_exists


revision = "add_mindmap_test_case_links"
down_revision = "add_user_profile_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, "test_mindmap_test_case_links"):
        return
    op.create_table(
        "test_mindmap_test_case_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mindmap_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mindmap_id"], ["test_mindmaps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mindmap_id", "node_id", "test_case_id", name="uq_mindmap_node_test_case"),
    )
    op.create_index(
        "ix_mindmap_links_mindmap_node",
        "test_mindmap_test_case_links",
        ["mindmap_id", "node_id"],
    )
    op.create_index(
        "ix_mindmap_links_test_case",
        "test_mindmap_test_case_links",
        ["test_case_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, "test_mindmap_test_case_links"):
        return
    op.drop_index("ix_mindmap_links_test_case", table_name="test_mindmap_test_case_links")
    op.drop_index("ix_mindmap_links_mindmap_node", table_name="test_mindmap_test_case_links")
    op.drop_table("test_mindmap_test_case_links")
