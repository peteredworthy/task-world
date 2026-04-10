"""Add skipped and skip_reason to steps table

Revision ID: g2a3b4c5d6e7
Revises: 622868ff30c7
Create Date: 2026-03-10 12:00:00.000000

Adds skipped (bool, default False) and skip_reason (nullable string) columns
to the steps table to support conditional step execution.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g2a3b4c5d6e7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "622868ff30c7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add skipped and skip_reason columns to steps table with safe defaults."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("skip_reason", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove skipped and skip_reason columns from steps table."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.drop_column("skip_reason")
        batch_op.drop_column("skipped")
