"""Add disposable graph node-detail read model tables

Revision ID: zd1e2f3g4h5i
Revises: zc1d2e3f4g5h
Create Date: 2026-06-20 00:00:00.000000

Node-detail summary reads are derived from events_v2 and are safe to
delete/rebuild. The checkpoint records the run-local graph event position that
has been fully applied to compact per-node rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "zd1e2f3g4h5i"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "zc1d2e3f4g5h"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_node_detail_summaries",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("task_region_id", sa.String(), nullable=True),
        sa.Column("input_ports", sa.JSON(), nullable=False),
        sa.Column("output_records", sa.JSON(), nullable=False),
        sa.Column("file_state_records", sa.JSON(), nullable=False),
        sa.Column("leases", sa.JSON(), nullable=False),
        sa.Column("active_lease", sa.JSON(), nullable=True),
        sa.Column("callback_history", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("prompt_summary", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "node_id"),
    )
    op.create_index(
        "idx_graph_node_detail_summaries_run",
        "graph_node_detail_summaries",
        ["run_id"],
    )
    op.create_index(
        "idx_graph_node_detail_summaries_run_position",
        "graph_node_detail_summaries",
        ["run_id", "position"],
    )

    op.create_table(
        "graph_node_detail_summary_checkpoints",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("graph_node_detail_summary_checkpoints")
    op.drop_index(
        "idx_graph_node_detail_summaries_run_position",
        table_name="graph_node_detail_summaries",
    )
    op.drop_index(
        "idx_graph_node_detail_summaries_run",
        table_name="graph_node_detail_summaries",
    )
    op.drop_table("graph_node_detail_summaries")
