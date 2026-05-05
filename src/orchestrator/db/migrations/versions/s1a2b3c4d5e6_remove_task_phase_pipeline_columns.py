"""remove task phase pipeline columns

Revision ID: s1a2b3c4d5e6
Revises: r1a2b3c4d5e6
Create Date: 2026-05-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "s1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "r1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove the retired per-task phase pipeline state."""
    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("tasks")}
    retired_columns = {"phase_outputs", "current_phase_index"} & existing_columns
    if not retired_columns:
        return

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        for column_name in sorted(retired_columns):
            batch_op.drop_column(column_name)


def downgrade() -> None:
    """Restore the retired phase columns for downgrade compatibility."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_phase_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("phase_outputs", sa.JSON(), nullable=True))
