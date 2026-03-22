"""Add pending_signals table for workflow signal queue

Revision ID: h1a2b3c4d5e6
Revises: cda269a76bde
Create Date: 2026-03-22 10:00:00.000000

Adds a pending_signals table that stores control signals (pause/resume/cancel/
activity_completed/activity_verified) sent to active RunWorkflow instances.
Signals are consumed exactly once via drain() which sets processed_at.

The index on run_id supports efficient drain queries that filter by run.
A partial index (WHERE processed_at IS NULL) would be ideal for PostgreSQL;
SQLite doesn't support partial indexes via Alembic batch mode, so we use a
plain index and let drain() filter in the query.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "cda269a76bde"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pending_signals table with index on run_id."""
    op.create_table(
        "pending_signals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_signals_run_id",
        "pending_signals",
        ["run_id"],
    )


def downgrade() -> None:
    """Drop pending_signals table and its index."""
    op.drop_index("ix_pending_signals_run_id", table_name="pending_signals")
    op.drop_table("pending_signals")
