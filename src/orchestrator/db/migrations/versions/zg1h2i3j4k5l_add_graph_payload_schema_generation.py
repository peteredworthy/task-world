"""Add graph payload schema generation to events_v2.

Revision ID: zg1h2i3j4k5l
Revises: zf1g2h3i4j5k
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zg1h2i3j4k5l"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "zf1g2h3i4j5k"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events_v2", sa.Column("payload_schema_generation", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("events_v2", "payload_schema_generation")
