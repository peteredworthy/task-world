# Task 4 Evidence: Persisted Usage Migration and Flat-Counter Removal

## TDD evidence

1. Added the real-SQLite pre-cutover fixture in `tests/integration/test_migrations.py` before creating the revision.
2. Ran the required RED command:

   ```text
   uv run pytest tests/integration/test_migrations.py -q -n 0 -k otel_usage_cutover
   ```

   Expected result: **failed** with `alembic.util.exc.CommandError: Can't locate revision identified by 'r04a1b2c3d4e'`.
3. Implemented revision `r04a1b2c3d4e`, with down revision `zg1h2i3j4k5l`.
4. Reran the same command GREEN: `1 passed, 3 deselected`.

## Migration coverage

- Upgrade transforms legacy usage keys in `runs.token_usage_by_model`,
  `attempts.token_usage_by_model`, `cost_records.token_usage_by_model`, and recursively
  through `events_v2.payload` telemetry/snapshot structures.
- Upgrade drops the six run/attempt flat token columns and renames all four retained
  cost-record token columns to canonical OTel names.
- Downgrade reverses JSON and cost-column vocabulary and recomputes available flat
  counters from canonical immutable usage facts (including both cache categories).
- The fixture asserts values, costs, and unknown provider raw data are retained.

## Persistence/replay coverage

- Run and attempt projector usage lists append one canonical record for each execution;
  they no longer merge records by model.
- Repository and presenter totals derive token values from immutable usage entries.
- `duration_ms` and `num_actions` remain independently persisted/accumulated.
- Targeted replay integration coverage passed after rebuilding all read models from events.

## Fresh verification

```text
uv run pytest tests/integration/test_migrations.py tests/integration/test_attempt_store_event_sourcing.py tests/unit/test_run_token_usage_merge.py -q -n 0
11 passed in 1.79s

uv run pytest tests/integration/test_migrations.py tests/integration/test_attempt_store_event_sourcing.py tests/unit/test_run_token_usage_merge.py tests/unit/test_command_handlers.py tests/unit/test_projectors.py tests/integration/test_cost_records.py -q -n 0
77 passed, 3 warnings in 4.83s

uv run alembic -c alembic.ini heads
r04a1b2c3d4e (head)

uv run ruff check .
All checks passed!

uv run pyright
0 errors, 0 warnings, 0 informations
```

Final full hook evidence: `uv run pre-commit run --all-files` passed every hook,
including its full pytest run. Stale tests now construct immutable canonical usage facts
where derived token behavior matters and otherwise no longer construct or assert the
removed persistence fields.

## Broader-suite note

`uv run pytest tests/unit tests/integration -q -n 0` was started and exceeded the
120-second execution limit after reporting pre-cutover flat-counter assertions in
unrelated legacy tests. The affected command-handler, projector, and cost-record
tests were updated to the new persistence contract and their focused suites pass.
The complete suite was not rerun to completion within this task session.
