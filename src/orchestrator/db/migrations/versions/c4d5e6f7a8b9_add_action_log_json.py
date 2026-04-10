"""Add action_log_json to attempts

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-02-11 12:00:00.000000

Adds a JSON column for storing structured agent action logs
(tool calls, text, metrics, etc.) captured during execution.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add action_log_json column to attempts table."""
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("action_log_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove action_log_json column from attempts table."""
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("action_log_json")
