"""add phase pipeline columns to tasks

Revision ID: 09d74b4804d2
Revises: ca739d2b9086
Create Date: 2026-03-13 19:44:32.023834

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "09d74b4804d2"
down_revision: Union[str, Sequence[str], None] = "ca739d2b9086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tasks", sa.Column("current_phase_index", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("tasks", sa.Column("phase_outputs", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "current_phase_index")
    op.drop_column("tasks", "phase_outputs")
