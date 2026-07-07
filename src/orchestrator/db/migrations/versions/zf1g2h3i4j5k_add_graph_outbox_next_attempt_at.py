"""Add next_attempt_at to graph outbox.

Revision ID: zf1g2h3i4j5k
Revises: ze1f2g3h4i5j
Create Date: 2026-07-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zf1g2h3i4j5k"
down_revision: Union[str, Sequence[str], None] = "ze1f2g3h4i5j"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("graph_outbox", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.create_index(
        "idx_graph_outbox_status_next_attempt_id",
        "graph_outbox",
        ["status", "next_attempt_at", "outbox_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_graph_outbox_status_next_attempt_id", table_name="graph_outbox")
    op.drop_column("graph_outbox", "next_attempt_at")
