"""Add events_v2 table for unified event store

Revision ID: u1a2b3c4d5e6
Revises: t1a2b3c4d5e6
Create Date: 2026-05-26 00:00:00.000000

Creates the events_v2 table as the foundation for the unified SQLite event store.
Includes a UNIQUE(aggregate_id, version) constraint for optimistic concurrency
control and two composite indexes for efficient stream and type queries.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "t1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create events_v2 table with unique constraint and indexes."""
    op.create_table(
        "events_v2",
        sa.Column("position", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("aggregate_id", "version", name="uq_events_v2_aggregate_version"),
    )
    op.create_index("idx_events_v2_aggregate", "events_v2", ["aggregate_id", "position"])
    op.create_index("idx_events_v2_type", "events_v2", ["event_type", "position"])


def downgrade() -> None:
    """Drop events_v2 table and its indexes."""
    op.drop_index("idx_events_v2_type", table_name="events_v2")
    op.drop_index("idx_events_v2_aggregate", table_name="events_v2")
    op.drop_table("events_v2")
