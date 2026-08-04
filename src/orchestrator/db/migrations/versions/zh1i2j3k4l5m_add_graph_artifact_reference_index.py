"""Add durable indexed graph artifact authorization references.

Revision ID: zh1i2j3k4l5m
Revises: r04a1b2c3d4e
Create Date: 2026-08-04 00:00:00.000000

Artifact range requests must not scan graph event JSON.  This migration creates
the durable exact-reference index and backfills valid historical check-result
stdout/stderr references from canonical graph events.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "zh1i2j3k4l5m"
down_revision: Union[str, Sequence[str], None] = "r04a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_artifact_references",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("encoding", sa.String(), nullable=True),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "content_hash"),
    )
    op.create_index(
        "idx_graph_artifact_references_run_hash",
        "graph_artifact_references",
        ["run_id", "content_hash"],
    )
    for reference_field in ("stdout_ref", "stderr_ref"):
        field_path = f"$.payload.value.{reference_field}"
        hash_path = f"{field_path}.content_hash"
        op.execute(
            sa.text(
                "INSERT OR IGNORE INTO graph_artifact_references "
                "(run_id, content_hash, artifact_id, size_bytes, media_type, encoding, storage_uri, position) "
                "SELECT substr(aggregate_id, 7), "
                f"json_extract(payload, '{hash_path}'), "
                f"json_extract(payload, '{field_path}.artifact_id'), "
                f"json_extract(payload, '{field_path}.size_bytes'), "
                f"json_extract(payload, '{field_path}.media_type'), "
                f"json_extract(payload, '{field_path}.encoding'), "
                f"json_extract(payload, '{field_path}.storage_uri'), version "
                "FROM events_v2 "
                "WHERE aggregate_id LIKE 'graph:%' "
                "AND event_type = 'output_record_accepted' "
                "AND json_valid(payload) = 1 "
                "AND json_extract(payload, '$.payload.record_type') = 'check_result' "
                f"AND json_type(payload, '{hash_path}') = 'text' "
                f"AND length(json_extract(payload, '{hash_path}')) = 71 "
                f"AND json_extract(payload, '{hash_path}') LIKE 'sha256:%' "
                f"AND json_extract(payload, '{field_path}.artifact_id') = json_extract(payload, '{hash_path}') "
                f"AND json_type(payload, '{field_path}.size_bytes') IN ('integer', 'real') "
                f"AND json_type(payload, '{field_path}.media_type') = 'text' "
                f"AND json_type(payload, '{field_path}.storage_uri') = 'text'"
            )
        )


def downgrade() -> None:
    op.drop_index("idx_graph_artifact_references_run_hash", table_name="graph_artifact_references")
    op.drop_table("graph_artifact_references")
