"""Add durable paginated graph archival view read models.

Revision ID: zi1j2k3l4m5n
Revises: zh1i2j3k4l5m
Create Date: 2026-08-04 00:00:00.000000

Topology, final-invariant blockers, and task regions are independently
pageable read owners.  They cannot share the bounded projection snapshot JSON
because a large view would otherwise make an unrelated decision owner stale.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "zi1j2k3l4m5n"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "zh1i2j3k4l5m"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_archival_view_checkpoints",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "graph_topology_view_entries",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("entry_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_index(
        "idx_graph_topology_view_entries_run_sequence",
        "graph_topology_view_entries",
        ["run_id", "sequence"],
    )
    op.create_table(
        "graph_final_blocker_view_entries",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_index(
        "idx_graph_final_blocker_view_entries_run_sequence",
        "graph_final_blocker_view_entries",
        ["run_id", "sequence"],
    )
    op.create_table(
        "graph_region_view_entries",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("task_region_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_index(
        "idx_graph_region_view_entries_run_sequence",
        "graph_region_view_entries",
        ["run_id", "sequence"],
    )
    op.create_index(
        "idx_graph_region_view_entries_run_region",
        "graph_region_view_entries",
        ["run_id", "task_region_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_graph_region_view_entries_run_region", table_name="graph_region_view_entries"
    )
    op.drop_index(
        "idx_graph_region_view_entries_run_sequence", table_name="graph_region_view_entries"
    )
    op.drop_table("graph_region_view_entries")
    op.drop_index(
        "idx_graph_final_blocker_view_entries_run_sequence",
        table_name="graph_final_blocker_view_entries",
    )
    op.drop_table("graph_final_blocker_view_entries")
    op.drop_index(
        "idx_graph_topology_view_entries_run_sequence",
        table_name="graph_topology_view_entries",
    )
    op.drop_table("graph_topology_view_entries")
    op.drop_table("graph_archival_view_checkpoints")
