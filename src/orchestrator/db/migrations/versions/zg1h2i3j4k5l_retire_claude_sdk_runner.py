"""Retire persisted Claude SDK runner values.

Revision ID: zg1h2i3j4k5l
Revises: zf1g2h3i4j5k
Create Date: 2026-07-18 00:00:00.000000

Downgrade is intentionally a no-op: after conversion, a ``retired`` value
does not retain enough information to distinguish historical ``claude_sdk``
records from values that were already retired.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zg1h2i3j4k5l"
down_revision: Union[str, Sequence[str], None] = "zf1g2h3i4j5k"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert mutable historical runner records without touching event payloads."""
    op.execute(
        sa.text(
            "DELETE FROM agent_runner_model_profile_defaults "
            "WHERE runner_type = 'claude_sdk' "
            "AND EXISTS ("
            "SELECT 1 FROM agent_runner_model_profile_defaults AS retired_default "
            "WHERE retired_default.runner_type = 'retired' "
            "AND retired_default.profile = agent_runner_model_profile_defaults.profile"
            ")"
        )
    )
    for table, column in (
        ("runs", "runner_type"),
        ("attempts", "runner_type"),
        ("cost_records", "agent_runner_type"),
        ("interaction_log_artifacts", "agent_runner_type"),
        ("agent_runner_model_profile_defaults", "runner_type"),
    ):
        op.execute(
            sa.text(f"UPDATE {table} SET {column} = 'retired' WHERE {column} = 'claude_sdk'")
        )


def downgrade() -> None:
    """Leave irreversible retirement values unchanged."""
