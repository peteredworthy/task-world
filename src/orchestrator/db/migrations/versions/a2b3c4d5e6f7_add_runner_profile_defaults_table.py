"""add runner_profile_defaults table

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-06 00:00:01.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create runner_profile_defaults table."""
    op.create_table(
        "runner_profile_defaults",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("runner_type", sa.String(), nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runner_type", "profile", name="uq_runner_profile"),
    )


def downgrade() -> None:
    """Drop runner_profile_defaults table."""
    op.drop_table("runner_profile_defaults")
