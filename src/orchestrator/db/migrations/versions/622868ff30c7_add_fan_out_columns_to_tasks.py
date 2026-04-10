"""Add fan-out columns to tasks

Revision ID: 622868ff30c7
Revises: b1c2d3e4f5a6
Create Date: 2026-03-07 17:12:33.220924

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "622868ff30c7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_task_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("fan_out_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fan_out_input", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("fan_out_output", sa.String(), nullable=True))
        batch_op.create_foreign_key("fk_tasks_parent_task_id", "tasks", ["parent_task_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint("fk_tasks_parent_task_id", type_="foreignkey")
        batch_op.drop_column("fan_out_output")
        batch_op.drop_column("fan_out_input")
        batch_op.drop_column("fan_out_index")
        batch_op.drop_column("parent_task_id")
