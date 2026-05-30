"""Drop pending_signals table (superseded by events_v2 signal transport)

Revision ID: w1a2b3c4d5e6
Revises: v1a2b3c4d5e6
Create Date: 2026-05-27 00:00:00.000000

Signals are now stored as SignalEnqueued / SignalProcessed events in the
events_v2 table via EventSignalTransport.  The pending_signals table is no
longer written to by the application and can be safely removed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "w1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "v1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop pending_signals table."""
    op.drop_table("pending_signals")


def downgrade() -> None:
    """Recreate pending_signals table."""
    op.create_table(
        "pending_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("deliver_after", sa.DateTime(), nullable=True),
        sa.Column("redelivery_count", sa.Integer(), nullable=True),
        sa.Column("_deprecated", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_signals_run_id", "pending_signals", ["run_id"])
