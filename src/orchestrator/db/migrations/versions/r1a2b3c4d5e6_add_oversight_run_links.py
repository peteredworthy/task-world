"""Add oversight parent/child run links.

Revision ID: r1a2b3c4d5e6
Revises: q1a2b3c4d5e6
Create Date: 2026-05-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "q1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("parent_run_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("parent_slice_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("oversight_state", sa.JSON(), nullable=True))
        batch_op.create_foreign_key("fk_runs_parent_run_id", "runs", ["parent_run_id"], ["id"])
        batch_op.create_index("ix_runs_parent_run_id", ["parent_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_parent_run_id")
        batch_op.drop_constraint("fk_runs_parent_run_id", type_="foreignkey")
        batch_op.drop_column("oversight_state")
        batch_op.drop_column("parent_slice_id")
        batch_op.drop_column("parent_run_id")
