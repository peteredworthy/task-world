# Test Suite Performance Design

## Goal

Create durable timing margin without removing any test case that currently runs
in the default unit or full suite. The optimized suite must retain the current
default test-case set, preserve per-test isolation, and keep all existing slow
and E2E coverage runnable through its opt-in flags.

The current measured wall times are:

- Unit: 29.74 seconds
- Full default suite: 59.46 seconds

The implementation targets are deliberately below the requested limits:

- Unit: at most 25 seconds wall time
- Full default suite: at most 50 seconds wall time

The final timing gate will run each command three times on an otherwise idle
machine. Every run must remain below the target, rather than accepting only a
favorable median.

## Constraints

- Do not move additional tests behind `slow` or `e2e` markers.
- Do not weaken assertions, reduce parameter matrices, or replace real objects
  with mocks.
- Keep function-level isolation unless a replacement gives equivalent isolation
  by construction.
- Production file databases must continue to run Alembic migrations.
- Retain `uv run pytest` as the canonical command and preserve pre-commit parity.
- Make one measured optimization at a time and discard changes that do not
  improve repeatable wall time.

## Baseline And Measurement

Before optimization, capture the selected default node IDs for `tests/unit` and
for the full suite. Compare that baseline after every stage. New regression
tests may add IDs. A test-file split may remap a node ID's file prefix, but must
preserve its test function or parameter identity and record the old-to-new path
mapping; no test case may disappear.

Add a small local profiling plugin or script that aggregates setup, call, and
teardown durations by file. It is diagnostic tooling, not a timing assertion
inside pytest. Timing assertions inside tests would be load-sensitive and
flaky.

Each stage follows the same loop:

1. Run the relevant suite once to warm package and filesystem caches.
2. Run it three timed times without other concurrent test commands.
3. Record wall time, pytest time, and the slowest aggregate files.
4. Keep the stage only if it improves repeatable wall time without removing a
   selected test case.

## Stage 1: Avoid Importing Existing Opt-In Suites

Whole modules already marked `slow` or `e2e` are currently imported and
collected by every xdist worker before marker filtering. Add an explicit,
tested pre-collection manifest for those existing whole-module opt-in suites.
`pytest_ignore_collect` will skip them before import unless `--run-slow` or
`--run-e2e` enables the corresponding category.

Keep the files in their current directories so integration conftest fixtures
remain in scope. Mixed modules containing only individual slow tests remain
collectable; the optimization applies only when the entire module is already
opt-in.

Regression tests will verify that every manifest entry exists, declares the
matching module marker, is omitted by the default collector, and is collected
when its opt-in flag is present.

## Stage 2: Fast Schema Creation For Fresh Test Databases

Most test databases are guaranteed empty but use `init_db()`, which performs
schema existence checks for in-memory databases and full Alembic migration work
for file databases. The measured fresh-file comparison was approximately 1.99
seconds for ten migration initializations versus 0.25 seconds for ten direct
metadata initializations.

Add a test-only helper under `tests/integration/` that initializes a guaranteed
fresh database with:

```python
await connection.run_sync(
    lambda sync_connection: Base.metadata.create_all(
        sync_connection,
        checkfirst=False,
    )
)
```

Use it only in fixtures that create a new unique in-memory database or new temp
file. Keep `init_db()` in migration tests and any test whose purpose is to prove
migration, upgrade, bootstrap, or production initialization behavior. Calling
the helper against a non-empty schema should fail naturally, making misuse
visible rather than silently accepting it.

Tests will prove that the helper creates the complete schema, supports normal
repository operations, and fails when reused against an initialized database.

## Stage 3: Profile And Slim Repeated App Construction

Cached route construction still measured about 3.5 seconds per 100
`create_app()` calls. Profile repeated cached app creation and optimize only the
measured expensive components.

Valid cache candidates are immutable compiled structures that depend solely on
configuration, such as route metadata or parsed static routine definitions.
Per-app engines, session factories, transports, registries, lock managers,
connection managers, and background-task state must never be shared.

Existing route-cache isolation tests remain the model. Add equivalent identity
and mutation-isolation tests for any newly cached object. Retain a diagnostic
environment switch that disables caches so cache-related failures can be
reproduced in one command.

## Stage 4: Remove Xdist Tail Imbalance

`--dist loadfile` avoids repeated module setup, but a few large files become
indivisible work units and leave other workers idle near the end. Use aggregate
durations to identify default files that consistently dominate the final tail.

Split only files with independent scenarios and no valuable module-scoped
fixture reuse. Organize splits by behavior, not arbitrary test counts. Extract
shared test builders into a focused helper module when necessary, without
changing production APIs or assertions.

After each split, confirm that the union of selected node IDs is unchanged apart
from file paths and that aggregate execution work did not increase enough to
offset the scheduling gain.

## Stage 5: Consolidate Real-Git Setup

Several remaining unit and integration files still initialize and configure a
repository independently. Replace repeated `git init`, user configuration, and
initial commit sequences with copies of the existing session-scoped repository
templates.

Tests that need a special initial history will copy the template and add only
the commits relevant to their scenario. Tests whose purpose is specifically to
verify repository initialization retain direct initialization.

The copied repositories must remain test-local, and no test may mutate the
session template.

## Stage Ordering And Stop Conditions

Implement stages in order because earlier stages reduce noise in later
profiles. Stop when all three unit runs are at most 25 seconds and all three full
runs are at most 50 seconds. Do not perform speculative refactors after reaching
those targets.

If Stage 3 requires sharing mutable app state, reject that optimization and
continue to Stage 4. If file splitting increases total CPU time or duplicates
expensive setup, revert that split and choose the next measured tail file.

## Verification

Required final checks:

```bash
uv run ruff check .
uv run pyright
uv run pytest tests/unit -q
uv run pytest -q
uv run pytest --run-slow -n 0 tests/unit/test_graph_projection_performance.py tests/integration/test_migrations.py
uv run pytest --run-e2e -n 0 tests/integration/test_graph_dynamic_e2e.py
```

Run the unit and full default commands three timed times and report all six wall
times. Compare the final default selected test cases with the captured baseline,
applying any recorded file-split path mappings. The work is complete only if
coverage selection is unchanged, opt-in collection still works, all checks
pass, and every measured run meets its timing target.
