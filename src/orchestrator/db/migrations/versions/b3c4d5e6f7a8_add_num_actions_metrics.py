"""Add num_actions to attempts and total_num_actions to runs

Revision ID: b3c4d5e6f7a8
Revises: 2dd5b4c8bf46
Create Date: 2026-02-08 18:00:00.000000

Adds action/tool call counting for per-stage metrics.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "2dd5b4c8bf46"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add num_actions columns."""
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("num_actions", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("total_num_actions", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    """Remove num_actions columns."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("total_num_actions")

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("num_actions")
