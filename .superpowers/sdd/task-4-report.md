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

## Review follow-up

- Event migration now rewrites root `token_usage_by_model` and recursively rewrites
  every such list inside recognized `telemetry`, `run_snapshot`, and
  `attempt_snapshot` structures, including nested snapshot steps, tasks, and attempts.
  Unrecognized provider sibling dictionaries remain byte-for-value unchanged.
- The real SQLite fixture contains an `AttemptUpdated` root usage list and a
  `RunCreated` nested snapshot. After upgrade it deserializes and replays both events
  through the public event-store and projection APIs.
- Downgrade coverage asserts restored run/attempt/cost schemas, flat-counter and
  retained cost-column values, every persisted JSON usage list, event payload values,
  and the unchanged provider sibling.
- Equal legacy/canonical key collisions collapse to the canonical key. A differing
  collision raises and leaves every pre-upgrade row intact.
- `test_migrations.py` is an exact historical-fixture path for the OTel vocabulary
  codemod. Its legacy mappings and SQL use the established historical helpers, while
  same-file live mappings remain diagnostic. `--assert-clean` is clean.
- Migration integration imports database and workflow dependencies exclusively through
  their public module interfaces.

## Final review-fixer verification

```text
uv run pytest tests/integration/test_migrations.py \
  tests/integration/test_attempt_store_event_sourcing.py \
  tests/unit/test_run_token_usage_merge.py -q -n 0
12 passed in 1.96s

uv run alembic -c alembic.ini heads
r04a1b2c3d4e (head)

uv run python -m scripts.codemods.r04_otel_vocab --assert-clean
# clean (no output)

uv run pyright
0 errors, 0 warnings, 0 informations

uv run pre-commit run --all-files
# all hooks passed, including pytest, module-imports, signal-routing, and UI checks
```

## Public persistence API follow-up

- `orchestrator.db` now publicly exports the reviewed persistence operations
  `save_run` and `update_latest_attempt` through its lazy public interface.
- The public database API contract now asserts that both functions are included in
  `__all__`, resolve as callables, and are importable from `orchestrator.db`.
- Repository and usage-aggregation tests import the reviewed database symbols from
  `orchestrator.db` and state symbols from `orchestrator.state`; they no longer reach
  into private `db.access` or `state` submodules.

```text
uv run pytest tests/integration/test_repositories.py tests/unit/test_repositories.py \
  tests/unit/test_run_aggregation.py -q -n 0
50 passed in 1.34s

uv run python scripts/check_module_imports.py
# clean (no output)

uv run pyright
0 errors, 0 warnings, 0 informations
```
