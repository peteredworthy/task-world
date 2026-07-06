"""Add intended_seed_sha to runs.

Records the SHA the run's source branch resolved to at *run-creation* time
(best-effort; null if the repo/branch could not be resolved then). Used at
worktree-seed time to detect the stale-base failure mode: seeding a worktree
from a clone whose branch head is BEHIND what the run creator saw, silently
dropping commits the run was meant to include.

Revision ID: ze1f2g3h4i5j
Revises: zd1e2f3g4h5i
Create Date: 2026-07-06 00:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "ze1f2g3h4i5j"
down_revision: Union[str, Sequence[str], None] = "zd1e2f3g4h5i"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("intended_seed_sha", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "intended_seed_sha")
