"""Add disposable graph read model tables

Revision ID: zc1d2e3f4g5h
Revises: za1b2c3d4e5f
Create Date: 2026-06-19 00:00:00.000000

Graph API read paths need compact summaries and current-state projections
without replaying full JSON event payloads for every request. These tables are
derived from events_v2 and are safe to delete/rebuild.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "zc1d2e3f4g5h"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "za1b2c3d4e5f"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_event_summaries",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "position"),
    )
    op.create_index(
        "idx_graph_event_summaries_run_position",
        "graph_event_summaries",
        ["run_id", "position"],
    )
    op.create_index(
        "idx_graph_event_summaries_run_type",
        "graph_event_summaries",
        ["run_id", "event_type", "position"],
    )

    op.create_table(
        "graph_projection_snapshots",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("run_state", sa.String(), nullable=True),
        sa.Column("node_states", sa.JSON(), nullable=False),
        sa.Column("task_states", sa.JSON(), nullable=False),
        sa.Column("leases", sa.JSON(), nullable=False),
        sa.Column("ready_nodes", sa.JSON(), nullable=False),
        sa.Column("scheduler", sa.JSON(), nullable=False),
        sa.Column("lease_view", sa.JSON(), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("graph_projection_snapshots")
    op.drop_index("idx_graph_event_summaries_run_type", table_name="graph_event_summaries")
    op.drop_index("idx_graph_event_summaries_run_position", table_name="graph_event_summaries")
    op.drop_table("graph_event_summaries")
