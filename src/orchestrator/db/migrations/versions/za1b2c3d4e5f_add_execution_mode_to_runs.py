"""Add execution_mode to runs.

Revision ID: za1b2c3d4e5f
Revises: ab1c2d3e4f5g
Create Date: 2026-06-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "za1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "ab1c2d3e4f5g"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column("execution_mode", sa.String(), nullable=False, server_default="legacy")
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("execution_mode")
