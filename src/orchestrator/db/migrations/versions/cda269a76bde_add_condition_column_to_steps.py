"""add_condition_column_to_steps

Revision ID: cda269a76bde
Revises: 09d74b4804d2
Create Date: 2026-03-15 17:15:25.126547

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cda269a76bde"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "09d74b4804d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("condition", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.drop_column("condition")
