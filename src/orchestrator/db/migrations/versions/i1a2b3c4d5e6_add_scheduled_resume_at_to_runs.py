"""Add scheduled_resume_at column to runs table

Revision ID: i1a2b3c4d5e6
Revises: h1a2b3c4d5e6
Create Date: 2026-03-22 10:01:00.000000

Adds a nullable scheduled_resume_at datetime column to the runs table.
When set, the RunWorkflow poller stub checks this column each iteration
and auto-resumes the run when the scheduled time is reached.

This is required for Temporal-aligned durable timer support (future work).
The column is nullable; NULL means no scheduled resume is pending.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "i1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "h1a2b3c4d5e6"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add scheduled_resume_at nullable datetime column to runs."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scheduled_resume_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove scheduled_resume_at column from runs."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("scheduled_resume_at")
