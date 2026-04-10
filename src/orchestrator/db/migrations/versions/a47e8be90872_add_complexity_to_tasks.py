"""add_complexity_to_tasks

Revision ID: a47e8be90872
Revises: e8f9a0b1c2d3
Create Date: 2026-03-05 23:21:56.504815

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a47e8be90872"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tasks", sa.Column("complexity", sa.String(), nullable=False, server_default="standard")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "complexity")
