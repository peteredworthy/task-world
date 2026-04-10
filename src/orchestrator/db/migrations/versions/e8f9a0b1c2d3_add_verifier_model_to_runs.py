"""add verifier_model to runs

Revision ID: e8f9a0b1c2d3
Revises: 7a7a9c7f5d9c
Create Date: 2026-03-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "7a7a9c7f5d9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("verifier_model", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("verifier_model")
