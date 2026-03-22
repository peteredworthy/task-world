"""Add attempt_id UUID column to attempts table for canonical AttemptRecord

Revision ID: k1a2b3c4d5e6
Revises: j1a2b3c4d5e6
Create Date: 2026-03-22 12:01:00.000000

Adds attempt_id (globally unique UUID string) to the attempts table.
This is the canonical AttemptRecord identifier that maps to a Temporal
Activity ID for future Temporal integration. It differs from the existing
`id` column in that attempt_id is the semantic identity of the attempt
(shared across normal tasks, fan-out children, script tasks, recovery retries)
while `id` is the DB primary key.
The column is nullable for backwards compatibility with existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "k1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "j1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add attempt_id nullable TEXT column to attempts table."""
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attempt_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove attempt_id column from attempts table."""
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("attempt_id")
