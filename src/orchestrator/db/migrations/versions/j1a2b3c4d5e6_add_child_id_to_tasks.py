"""Add child_id UUID column to tasks table for stable fan-out child identity

Revision ID: j1a2b3c4d5e6
Revises: i1a2b3c4d5e6
Create Date: 2026-03-22 12:00:00.000000

Fan-out children get a stable UUID (child_id) assigned at creation time.
This ID is durable across restarts and maps to a Temporal child workflow
or activity ID in future Temporal integration.
The column is nullable; NULL means the task is not a fan-out child.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "j1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "i1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add child_id nullable TEXT column to tasks table."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("child_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove child_id column from tasks table."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("child_id")
