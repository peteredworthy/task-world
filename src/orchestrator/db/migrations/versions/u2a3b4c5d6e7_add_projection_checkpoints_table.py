"""Add projection_checkpoints table

Revision ID: u2a3b4c5d6e7
Revises: u1a2b3c4d5e6
Create Date: 2026-05-26 00:00:00.000000

Creates the projection_checkpoints table to track per-projector progress
through the event log. Each row records the last event position successfully
processed by a given projector, enabling incremental and rebuild workflows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u2a3b4c5d6e7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "u1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create projection_checkpoints table."""
    op.create_table(
        "projection_checkpoints",
        sa.Column("projector_name", sa.String(), primary_key=True),
        sa.Column("last_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.String(), nullable=False),
    )


def downgrade() -> None:
    """Drop projection_checkpoints table."""
    op.drop_table("projection_checkpoints")
