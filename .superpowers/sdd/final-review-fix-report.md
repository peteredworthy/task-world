# Final Whole-Branch Review Fix Report

## Scope and design

The review findings were corrected without changing reducers, projections, or
command handlers. `ArtifactRootResolver` maps a persisted run worktree to its
linked main checkout's `.orchestrator/artifacts` CAS. The resolver is composed
into graph dispatch, authenticated artifact reads, deletion GC, and both request
and factory-created `WorkflowService` paths. `ProjectArtifactGarbageCollector`
loads and marks only surviving runs with the same resolved root before sweeping.

`ArtifactRootLock` uses a root-identified advisory filesystem `flock`, with no
process-global state. Check dispatch holds it across deduplicated `put()` and the
durable check-result callback append. GC acquires it before loading events and
until sweep completes. A completed append is included in marking; a failed append
releases the lock and leaves the blob unmarked for normal grace-period collection.

## RED evidence

1. `uv run pytest tests/unit/test_artifact_gc.py -q`
   - Result: collection error: `ImportError: cannot import name 'ArtifactRootLock'`.
2. `uv run pytest tests/integration/test_artifact_api.py::test_multi_project_artifact_read_and_delete_gc_use_the_run_project_root -q`
   - Result: failed `assert 404 == 206`; the server-composed project-A store did
     not contain the project-B run reference.

## GREEN evidence

1. `uv run pytest tests/unit/test_artifact_gc.py tests/integration/test_artifact_api.py tests/integration/test_check_output_artifacts.py tests/integration/test_workflow_service.py -q`
   - Result: `61 passed in 6.00s`.
2. Targeted type check: `uv run pyright src/orchestrator/artifacts src/orchestrator/api/deps.py src/orchestrator/api/routers/graph.py src/orchestrator/workflow/service.py src/orchestrator/workflow/graph_driver.py`
   - Result: `0 errors, 0 warnings, 0 informations`.

## Concurrency ordering proof

`test_sweep_waits_for_deduplicated_publication_before_deleting_old_blob` creates
an old valid CAS blob, enters the real root lock, calls deduplicating `put()`, and
starts a real sweep. The sweep task is incomplete while publication is held. The
test records the reference as published, releases the lock, confirms the sweep
retains it, and reads the final reference. The append-failure test raises inside
the real publication context, then proves a grace-zero sweep deletes the released
orphan.

## Multi-project and factory evidence

`test_multi_project_artifact_read_and_delete_gc_use_the_run_project_root` creates
two real git repositories and a linked project-B worktree while the server is
composed with project A. It seeds the canonical reference in project B, performs
an authenticated range read through the API, then deletes through
`app.state.service_factory`. The range returns project-B bytes; project-B's old
orphan is swept and project-A's old orphan remains readable.

## Files

- `src/orchestrator/artifacts/{coordination,resolution,__init__,gc,store}.py`
- `src/orchestrator/api/{app,deps}.py` and `api/routers/graph.py`
- `src/orchestrator/workflow/{graph_driver,service}.py`
- `tests/unit/test_artifact_gc.py`
- `tests/integration/{test_artifact_api,test_check_output_artifacts}.py`
- `docs/ARCHITECTURE.md` and `docs/dynamic-graph/w5-progress-ledger.md`

## Self-review and concerns

The publication lock serializes same-root output publication and GC; unrelated
project roots use different lock files. The lock file uses the nearest existing
ancestor so inline-only output does not materialize an artifact directory. Full
repository verification completed: graph/artifact selection `1021 passed in
58.46s`; full suite `4819 passed, 3 skipped, 3 warnings in 103.77s`; Ruff,
Pyright, format check, and `git diff --check` passed. The warnings are existing
Python 3.12 `aiosqlite` datetime-adapter deprecations. Final approval is not
claimed.

## Commits

- `0770197e6 Fix artifact project-root lifecycle coordination` — implementation,
  regressions, documentation, and verification evidence.

## Second Final Review Fix

Status: implemented; final approval remains pending. RED:
`uv run pytest tests/unit/test_artifact_gc.py::test_absent_root_uses_one_lock_through_publication_and_sweep -q`
failed because publication and sweep selected different lock files when the CAS
root appeared. GREEN: `uv run pytest tests/unit/test_artifact_gc.py tests/integration/test_artifact_api.py -q`
reported `17 passed`. The lock now always uses the private `.orchestrator`
metadata parent. Root resolution now retries persisted repository identity when a
persisted worktree path is absent, removed, or unresolvable; Task 3 and Task 4
plan checkboxes were reconciled. The real linked-worktree removal API/GC
regression passed with the focused suite: `10 passed in 3.86s`. Commit and
complete gate evidence:

- `uv run pytest tests/ -k "graph or artifact" -q -n auto --dist worksteal`:
  `1023 passed in 60.78s`.
- `uv run pytest tests/ -q -n auto --dist worksteal`: `4821 passed, 3 skipped,
  3 warnings in 104.90s` (existing `aiosqlite` datetime-adapter deprecations).
- `uv run ruff check .`: passed; `uv run pyright`: `0 errors, 0 warnings`;
  `uv run ruff format --check .`: `714 files already formatted`;
  `git diff --check`: passed.

Hook-verified implementation commit: `36129a3ae Harden artifact root fallback
and locking`. Final approval remains pending.
