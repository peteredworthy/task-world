"""Deprecate pending_signals table (signals now stored in events_v2)

Revision ID: v1a2b3c4d5e6
Revises: u2a3b4c5d6e7
Create Date: 2026-05-27 00:00:00.000000

Adds a _deprecated column to pending_signals to signal that this table is
no longer written to by the application. Signals are now stored as
SignalEnqueued / SignalProcessed events in the events_v2 table via
EventSignalTransport.

The table is kept (not dropped) to preserve historical data and allow
rollback. The _deprecated column documents the migration date.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "v1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "u2a3b4c5d6e7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add _deprecated column to pending_signals table."""
    with op.batch_alter_table("pending_signals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "_deprecated",
                sa.String(),
                nullable=True,
                comment="Set when this table is superseded; signals now use events_v2",
            )
        )


def downgrade() -> None:
    """Remove _deprecated column from pending_signals table."""
    with op.batch_alter_table("pending_signals") as batch_op:
        batch_op.drop_column("_deprecated")
