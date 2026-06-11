"""Add cost and interaction log record tables.

Revision ID: aa1b2c3d4e5f
Revises: z1a2b3c4d5e6
Create Date: 2026-06-11 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cost_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=True),
        sa.Column("attempt_num", sa.Integer(), nullable=False),
        sa.Column("agent_runner_type", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("mode_tag", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("wall_time_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("token_usage_by_model", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "task_id",
            "attempt_num",
            "agent_runner_type",
            "phase",
            name="uq_cost_records_execution",
        ),
    )
    op.create_index("idx_cost_records_mode", "cost_records", ["agent_runner_type", "mode_tag"])
    op.create_index("idx_cost_records_run", "cost_records", ["run_id"])

    op.create_table(
        "interaction_log_artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("cost_record_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=True),
        sa.Column("attempt_num", sa.Integer(), nullable=False),
        sa.Column("agent_runner_type", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("action_log_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cost_record_id"], ["cost_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "task_id",
            "attempt_num",
            "agent_runner_type",
            "phase",
            name="uq_interaction_log_artifacts_execution",
        ),
    )
    op.create_index("idx_interaction_log_artifacts_run", "interaction_log_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_index("idx_interaction_log_artifacts_run", table_name="interaction_log_artifacts")
    op.drop_table("interaction_log_artifacts")
    op.drop_index("idx_cost_records_run", table_name="cost_records")
    op.drop_index("idx_cost_records_mode", table_name="cost_records")
    op.drop_table("cost_records")
