"""Add routine_meta table for archive status and other routine metadata.

Revision ID: l1a2b3c4d5e6
Revises: k1a2b3c4d5e6
Create Date: 2026-03-25 10:00:00.000000

Creates a routine_meta table to store user-managed metadata (e.g. is_archived)
for routines that are otherwise discovered from YAML files on disk.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "l1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "k1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create routine_meta table."""
    op.create_table(
        "routine_meta",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("routine_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("is_archived", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("routine_id", "source", name="uq_routine_meta_id_source"),
    )
    op.create_index("ix_routine_meta_routine_id", "routine_meta", ["routine_id"])


def downgrade() -> None:
    """Drop routine_meta table."""
    op.drop_index("ix_routine_meta_routine_id", table_name="routine_meta")
    op.drop_table("routine_meta")
