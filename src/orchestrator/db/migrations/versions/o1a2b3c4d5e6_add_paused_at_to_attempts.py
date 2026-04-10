"""Add paused_at column to attempts for mid-phase pause tracking.

Revision ID: o1a2b3c4d5e6
Revises: n1a2b3c4d5e6
Create Date: 2026-03-30 00:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "o1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "n1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("paused_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("paused_at")
