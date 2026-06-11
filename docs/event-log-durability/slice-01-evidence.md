# Event-Log Durability Slice 01 Evidence

Date: 2026-06-12

## Schema Evidence

No new Alembic revision was added in this slice. The inspected revision is
`u1a2b3c4d5e6_add_events_v2_table.py` (`revision = "u1a2b3c4d5e6"`).

Inspected/generated `events_v2` SQL shape:

```sql
CREATE TABLE events_v2 (
  position INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  aggregate_id VARCHAR NOT NULL,
  event_type VARCHAR NOT NULL,
  payload TEXT NOT NULL,
  timestamp VARCHAR NOT NULL,
  version INTEGER NOT NULL,
  CONSTRAINT uq_events_v2_aggregate_version UNIQUE (aggregate_id, version)
);
CREATE INDEX idx_events_v2_aggregate ON events_v2 (aggregate_id, position);
CREATE INDEX idx_events_v2_type ON events_v2 (event_type, position);
```

The ORM metadata and migrated SQLite schema are asserted in
`tests/integration/test_event_log_durability.py`:

- `test_events_v2_schema_metadata_exposes_durability_contract`
- `test_events_v2_migration_schema_and_retry_identity`
- `test_events_v2_ordering_uses_position_and_aggregate_version`

## Test Commands

Primary blocking durability command:

```bash
uv run pytest tests/integration/test_event_log_durability.py tests/unit/test_event_store_v2.py tests/integration/test_event_store.py tests/integration/test_projection_recovery.py tests/unit/test_projection_rebuild.py -q
```

Relevant output:

```text
58 passed, 34 warnings in 3.45s
```

The warnings were Python 3.12 `aiosqlite` datetime adapter deprecation warnings
from temporary SQLite tests. They do not skip or replace the real durability
path.

Test files used:

- `tests/integration/test_event_log_durability.py`
- `tests/unit/test_event_store_v2.py`
- `tests/integration/test_event_store.py`
- `tests/integration/test_projection_recovery.py`
- `tests/unit/test_projection_rebuild.py`

Mocking scan for the targeted slice found no `MagicMock`, `patch`,
`monkeypatch`, `skip`, or `xfail` usage in those files.

## Rebuild State Evidence

Canonical projection rebuild assertions live in
`test_canonical_projection_snapshot_matches_after_events_v2_rebuild`,
`test_workflow_service_api_dependency_path_commits_events_v2_then_rebuilds_without_journal`,
and `test_crash_retry_drill_keeps_accepted_events_unique_across_transaction_boundaries`.

Those tests serialize the full before/after canonical snapshots into assertion
messages on mismatch via `_projection_snapshot_json()`. The passing targeted
run proves the serialized before and after snapshots matched for the projected
`runs`, `steps`, `tasks`, and `attempts` tables.

Canonical projection coverage intentionally omits no deterministic read-model
columns:

```json
{
  "runs": {},
  "steps": {},
  "tasks": {},
  "attempts": {}
}
```

## Event Counts And Sequence Ranges

Crash/retry drill (`crash-retry-run`):

```json
{
  "before_pre_commit_crash": {
    "event_count": 3,
    "position_range": [1, 3],
    "aggregate_version_range": [1, 3],
    "event_types": ["run_created", "step_created", "task_created"]
  },
  "after_pre_commit_rollback": {
    "event_count": 0,
    "position_range": [null, null],
    "aggregate_version_range": [null, null],
    "event_types": []
  },
  "after_retry_commit": {
    "event_count": 3,
    "position_range": [1, 3],
    "aggregate_version_range": [1, 3],
    "event_types": ["run_created", "step_created", "task_created"]
  },
  "after_committed_duplicate_retry": "same as after_retry_commit",
  "after_rebuild": "same as after_retry_commit"
}
```

Service/API dependency proof path (`durable-service-run`):

- Pre-commit projection listener boundary: first accepted append has
  `event_count = 3`, projected task row count `1`, and event types
  `["run_created", "step_created", "task_created"]`.
- Before recovery retry: event count is greater than `3`, and aggregate version
  range is `[1, event_count]`.
- After recovery retry: event count increases again, and aggregate version range
  remains `[1, event_count]`.
- After rebuild from `events_v2` with the JSONL journal removed: event evidence
  is exactly equal to the after-retry evidence.

Duplicate identity tests assert:

- `duplicate-identity-run`: one committed row remains after duplicate version
  retry; stream is `[("run_status_changed", 1)]`.
- `duplicate-sequence-run`: two committed rows remain after duplicate version
  retry; stream is `[("run_status_changed", 1), ("task_status_changed", 2)]`.

## Temporary Paths

Temporary database and journal path patterns used by the tests:

- `tmp_path / "events-v2-migration.sqlite"`
- `tmp_path / "events-v2-ordering.sqlite"`
- `tmp_path / "events-v2-duplicate-identity.sqlite"`
- `tmp_path / "events-v2-duplicate-sequence.sqlite"`
- `tmp_path / "service-api-proof" / "orchestrator.db"`
- `tmp_path / "service-api-proof" / ".orchestrator" / "state" / "history.jsonl"`
- `tmp_path / "crash-retry-drill" / "orchestrator.db"`
- `tmp_path / "projection-failure-proof" / "orchestrator.db"`
- `tmp_path / "jsonl-failure-proof" / "orchestrator.db"`
- `tmp_path / "journal-parent-is-file" / "history.jsonl"` for secondary-sink
  failure proof.

Backup/import behavior was not touched in this slice, so no live database,
backup, or production-like import output is claimed here.

## Reference Conflict Status

No graph-reference conflict was found. The implementation evidence remains
consistent with:

- `docs/graph-approach/execution-graph-prd-plus.md`
- `docs/graph-approach/execution-graph-evaluation.md`
- `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`
- `docs/event-log-durability/step-01-plan.md`

Production-like migration/import cutover is not implemented in this slice.
The JSONL journal remains a secondary sink/import surface for the proven path,
not the authoritative acceptance or rebuild source.

## Next Cycle Recommendation

Broaden event write-path migration next. This slice proves the durable
`events_v2` authority, retry identity, secondary JSONL boundary, and projection
rebuild for one real workflow/service path plus existing event-store
regressions. The next useful step is to migrate additional lifecycle and runner
write paths through the same `events_v2` acceptance boundary, then expand
projection rebuild coverage around those newly migrated paths.
