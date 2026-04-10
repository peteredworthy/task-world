"""Add source_branch_sha to runs.

Records the SHA of the source branch at the time the worktree was created.
Used as the fixed base for all diff operations in the review tab, so that
diffs always show "work done on this branch" rather than shifting as main
advances.

Revision ID: q1a2b3c4d5e6
Revises: p1a2b3c4d5e6
Create Date: 2026-04-10 00:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "q1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "p1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("source_branch_sha", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "source_branch_sha")
