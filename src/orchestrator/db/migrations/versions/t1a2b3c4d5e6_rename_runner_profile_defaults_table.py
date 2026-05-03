"""rename agent runner model defaults table

Revision ID: t1a2b3c4d5e6
Revises: s1a2b3c4d5e6
Create Date: 2026-05-03 00:00:01.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "s1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename the table to match Agent Runner Model Defaults terminology."""
    op.rename_table("runner_profile_defaults", "agent_runner_model_profile_defaults")


def downgrade() -> None:
    """Restore the previous table name."""
    op.rename_table("agent_runner_model_profile_defaults", "runner_profile_defaults")
