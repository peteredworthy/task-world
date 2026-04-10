"""Refactor pending_signals: integer PK, rename processed_at to handled_at, add delivered_at.

Revision ID: m1a2b3c4d5e6
Revises: l1a2b3c4d5e6
Create Date: 2026-03-28 10:00:00.000000

Replaces the UUID string primary key with INTEGER PRIMARY KEY AUTOINCREMENT,
renames processed_at to handled_at (repurposing the column, not adding new),
and adds delivered_at TIMESTAMP NULL as a new column.

The created_at column is retained for audit purposes only — it must NOT appear
in any ORDER BY clause; drain queries order by integer PK (id) instead.

Migration assumes a clean server stop with no pending signals; no data backfill
is performed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "m1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "l1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace UUID PK with integer, rename processed_at→handled_at, add delivered_at."""
    # SQLite requires batch_alter_table for structural changes.
    # We rebuild the table with the new schema.
    with op.batch_alter_table("pending_signals", recreate="always") as batch_op:
        # Replace string PK with integer autoincrement PK
        batch_op.alter_column(
            "id",
            existing_type=sa.String(),
            new_column_name="id",
            type_=sa.Integer(),
            existing_nullable=False,
            autoincrement=True,
        )
        # Rename processed_at → handled_at
        batch_op.alter_column(
            "processed_at",
            new_column_name="handled_at",
            existing_type=sa.DateTime(),
            existing_nullable=True,
        )
        # Add new delivered_at column
        batch_op.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Reverse: remove delivered_at, rename handled_at→processed_at, restore string PK."""
    with op.batch_alter_table("pending_signals", recreate="always") as batch_op:
        batch_op.drop_column("delivered_at")
        batch_op.alter_column(
            "handled_at",
            new_column_name="processed_at",
            existing_type=sa.DateTime(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            new_column_name="id",
            type_=sa.String(),
            existing_nullable=False,
            autoincrement=False,
        )
