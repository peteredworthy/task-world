"""Add skipped and skip_reason fields to steps table for conditional step support

Revision ID: 0beef1a2b3c4
Revises: f1a2b3c4d5e6
Create Date: 2026-03-10 12:00:00.000000

Adds skipped (boolean) and skip_reason (string) columns to track why a step was skipped
due to condition evaluation, manual gates, or errors.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0beef1a2b3c4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "622868ff30c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add skipped and skip_reason columns to steps table."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("skip_reason", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove skipped and skip_reason columns from steps table."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.drop_column("skipped")
        batch_op.drop_column("skip_reason")
