"""Add token_usage_by_model JSON columns to attempts and runs.

Stores per-model token counts with embedded cost rates for accurate
cost accounting across different models (parent + sub-agents).

Revision ID: p1a2b3c4d5e6
Revises: o1a2b3c4d5e6
Create Date: 2026-04-05 00:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "p1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "o1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_usage_by_model", sa.JSON(), nullable=True))

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_usage_by_model", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("token_usage_by_model")

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("token_usage_by_model")
