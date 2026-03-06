"""rename agent columns to runner on runs

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-03-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a47e8be90872"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename agent_type, agent_config, agent_started_at to runner_* equivalents."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column("agent_type", new_column_name="runner_type")
        batch_op.alter_column("agent_config", new_column_name="runner_config")
        batch_op.alter_column("agent_started_at", new_column_name="runner_started_at")

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.alter_column("agent_type", new_column_name="runner_type")


def downgrade() -> None:
    """Reverse rename: runner_* back to agent_* columns."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column("runner_type", new_column_name="agent_type")
        batch_op.alter_column("runner_config", new_column_name="agent_config")
        batch_op.alter_column("runner_started_at", new_column_name="agent_started_at")

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.alter_column("runner_type", new_column_name="agent_type")
