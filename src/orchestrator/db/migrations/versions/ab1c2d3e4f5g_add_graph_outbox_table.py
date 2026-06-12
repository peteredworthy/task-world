"""Add graph outbox table.

Revision ID: ab1c2d3e4f5g
Revises: aa1b2c3d4e5f
Create Date: 2026-06-12 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ab1c2d3e4f5g"
down_revision: Union[str, Sequence[str], None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_outbox",
        sa.Column("outbox_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_graph_outbox_event_id"),
    )
    op.create_index("idx_graph_outbox_status_id", "graph_outbox", ["status", "outbox_id"])
    op.create_index("idx_graph_outbox_run", "graph_outbox", ["run_id", "outbox_id"])


def downgrade() -> None:
    op.drop_index("idx_graph_outbox_run", table_name="graph_outbox")
    op.drop_index("idx_graph_outbox_status_id", table_name="graph_outbox")
    op.drop_table("graph_outbox")
