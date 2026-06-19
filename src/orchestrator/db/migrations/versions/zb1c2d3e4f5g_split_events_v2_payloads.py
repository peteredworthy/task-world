"""Split events_v2 payloads into a side table

Revision ID: zb1c2d3e4f5g
Revises: za1b2c3d4e5f
Create Date: 2026-06-19 00:00:00.000000

The events_v2 table is scanned frequently for cursors, positions, event types,
and aggregate ordering. Keeping large JSON envelopes inline makes those scans
pay unnecessary I/O cost. This migration moves the raw envelope into a
one-to-one payload table keyed by events_v2.position.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "zb1c2d3e4f5g"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "za1b2c3d4e5f"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Move raw event payload JSON out of events_v2."""
    op.create_table(
        "events_v2_payloads",
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["position"], ["events_v2.position"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("position"),
    )
    op.execute(
        "INSERT INTO events_v2_payloads (position, payload) SELECT position, payload FROM events_v2"
    )
    with op.batch_alter_table("events_v2") as batch_op:
        batch_op.drop_column("payload")


def downgrade() -> None:
    """Move raw event payload JSON back onto events_v2."""
    with op.batch_alter_table("events_v2") as batch_op:
        batch_op.add_column(sa.Column("payload", sa.Text(), nullable=True))

    op.execute(
        "UPDATE events_v2 "
        "SET payload = ("
        "SELECT events_v2_payloads.payload "
        "FROM events_v2_payloads "
        "WHERE events_v2_payloads.position = events_v2.position"
        ")"
    )
    op.execute("UPDATE events_v2 SET payload = '{}' WHERE payload IS NULL")
    with op.batch_alter_table("events_v2") as batch_op:
        batch_op.alter_column("payload", nullable=False)
    op.drop_table("events_v2_payloads")
