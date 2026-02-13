"""Add pause_reason to runs

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-02-13 12:00:00.000000

Adds a nullable string column for tracking why a run was paused
(e.g., "agent_died", "manual_pause").
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pause_reason column to runs table."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pause_reason", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove pause_reason column from runs table."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("pause_reason")
