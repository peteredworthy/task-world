"""add replay_checkpoints table

Revision ID: e5fe8c18b483
Revises: 622868ff30c7
Create Date: 2026-03-09 21:24:58.281959

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5fe8c18b483"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "g2a3b4c5d6e7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "replay_checkpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("journal_path", sa.String(), nullable=False),
        sa.Column("last_applied_sequence", sa.Integer(), nullable=False),
        sa.Column("last_applied_timestamp", sa.DateTime(), nullable=False),
        sa.Column("backup_snapshot_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journal_path"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("replay_checkpoints")
