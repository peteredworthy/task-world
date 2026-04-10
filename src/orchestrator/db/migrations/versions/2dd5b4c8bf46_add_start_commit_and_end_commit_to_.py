"""Add start_commit and end_commit to attempts

Revision ID: 2dd5b4c8bf46
Revises: a1b2c3d4e5f6
Create Date: 2026-02-07 13:21:18.414515

Also fixes index names on runs table from the previous migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2dd5b4c8bf46"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add git tracking columns to attempts
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("start_commit", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("end_commit", sa.String(), nullable=True))

    # Fix index names on runs (previous migration used _new_ suffix)
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index("ix_runs_new_repo_name")
        batch_op.drop_index("ix_runs_new_status")
        batch_op.create_index(batch_op.f("ix_runs_repo_name"), ["repo_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_status"), ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_status"))
        batch_op.drop_index(batch_op.f("ix_runs_repo_name"))
        batch_op.create_index("ix_runs_new_status", ["status"], unique=False)
        batch_op.create_index("ix_runs_new_repo_name", ["repo_name"], unique=False)

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("end_commit")
        batch_op.drop_column("start_commit")
