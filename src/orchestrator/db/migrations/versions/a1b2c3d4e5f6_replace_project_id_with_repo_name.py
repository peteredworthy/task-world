"""Replace project_id with repo_name

Revision ID: a1b2c3d4e5f6
Revises: 0cef0a513109
Create Date: 2026-02-07 10:00:00.000000

This migration:
1. Deletes all existing runs (clean slate approach)
2. Drops project_id column
3. Adds repo_name column (required)
4. Adds routine_path column (nullable)
5. Adds routine_commit column (nullable)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0cef0a513109"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - replace project_id with repo_name."""
    # Delete all existing data (clean slate)
    op.execute("DELETE FROM events")
    op.execute("DELETE FROM clarification_responses")
    op.execute("DELETE FROM clarification_requests")
    op.execute("DELETE FROM attempts")
    op.execute("DELETE FROM tasks")
    op.execute("DELETE FROM steps")
    op.execute("DELETE FROM runs")

    # For SQLite, we need to recreate the table since ALTER TABLE
    # doesn't support DROP COLUMN in older versions

    # Create new runs table with updated schema
    op.create_table(
        "runs_new",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("repo_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("routine_id", sa.String(), nullable=True),
        sa.Column("routine_sha", sa.String(), nullable=True),
        sa.Column("routine_source", sa.String(), nullable=True),
        sa.Column("routine_embedded", sa.JSON(), nullable=True),
        sa.Column("routine_path", sa.String(), nullable=True),
        sa.Column("routine_commit", sa.String(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=True),
        sa.Column("agent_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("worktree_enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("worktree_path", sa.String(), nullable=True),
        sa.Column(
            "delete_worktree_on_completion", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("source_branch", sa.String(), nullable=True),
        sa.Column("merge_strategy", sa.String(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("env_file_specs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("env_source_dir", sa.String(), nullable=True),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("agent_started_at", sa.DateTime(), nullable=True),
        sa.Column("total_tokens_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_write", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_cache", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_new_repo_name", "runs_new", ["repo_name"])
    op.create_index("ix_runs_new_status", "runs_new", ["status"])

    # Drop old table and rename new one
    op.drop_table("runs")
    op.rename_table("runs_new", "runs")


def downgrade() -> None:
    """Downgrade schema - restore project_id."""
    # This is a destructive migration, downgrade just creates original schema
    # (data will be lost)

    op.create_table(
        "runs_old",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("routine_id", sa.String(), nullable=True),
        sa.Column("routine_sha", sa.String(), nullable=True),
        sa.Column("routine_source", sa.String(), nullable=True),
        sa.Column("routine_embedded", sa.JSON(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=True),
        sa.Column("agent_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("worktree_enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("worktree_path", sa.String(), nullable=True),
        sa.Column(
            "delete_worktree_on_completion", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("source_branch", sa.String(), nullable=True),
        sa.Column("merge_strategy", sa.String(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("env_file_specs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("env_source_dir", sa.String(), nullable=True),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("agent_started_at", sa.DateTime(), nullable=True),
        sa.Column("total_tokens_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_write", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_cache", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_old_project_id", "runs_old", ["project_id"])
    op.create_index("ix_runs_old_status", "runs_old", ["status"])

    op.drop_table("runs")
    op.rename_table("runs_old", "runs")
