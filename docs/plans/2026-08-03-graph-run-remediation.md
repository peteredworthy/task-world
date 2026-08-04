# Graph Run Remediation Plan

## Objective

Make graph-driven runs recoverable, bounded, and honestly mergeable, then remove
the active Superpowers integration. Work proceeds strictly sequentially: one
builder tranche is followed by an independent verifier. A failed verification
returns to the same builder tranche before any later tranche starts.

The completed run at `worktrees/r359` is evidence only. Its dirty files may be
consulted, but the worktree must not be modified or merged wholesale.

## Global Constraints

- Preserve unrelated worktree changes.
- Do not modify or delete `orchestrator.db`.
- Use `uv run` for every Python command.
- Keep event projection behavior deterministic across live reduction and replay.
- Keep graph projection values deeply immutable.
- Validate constrained API inputs at the schema boundary.
- Add no mocks, monkeypatches, or process-global state.
- Import across top-level module boundaries only through public exports.
- Run focused tests after each correction and the full required checks at the end.

## Sequential Role Contract

For each tranche:

1. The builder inspects the current checkout and implements only that tranche.
2. The builder runs focused tests and reports files changed and evidence.
3. A fresh verifier reviews the diff and reruns appropriate checks.
4. Any verifier finding returns to the builder for correction.
5. The tranche closes only after the verifier reports no findings.

After all tranches, a fresh planner/gap finder reviews the aggregate diff and
runtime invariants. Any new gap becomes another builder/verifier tranche. This
loop ends only when the gap finder and final verifier both report no findings.

## Tranche 1: Remove Obsolete Node-Creation Payload View

Remove `node_creation_payloads_view` from graph queries and public exports.
Delete or update tests whose only purpose is that obsolete view while retaining
coverage for canonical record and payload queries.

Primary files:

- `src/orchestrator/graph/projection_queries.py`
- `src/orchestrator/graph/__init__.py`
- `tests/unit/graph_projection_behavior_cases.py`
- `tests/unit/test_graph_projection_queries.py`
- `tests/unit/test_graph_projections.py`
- `tests/unit/test_graph_public_exports.py`
- `tests/unit/test_node_created_event_payloads.py`

Verification:

- Search confirms no production or test references remain.
- Focused graph projection query, behavior, export, and payload tests pass.
- Graph projection boundary check passes.

## Tranche 2: Stabilize File-State Replay Identity

Ensure two accepted file-state events with the same logical record but different
event delivery timestamps replay without a duplicate-record conflict. Exclude
transport metadata such as `created_at` from logical file-state identity while
retaining conflict detection for actual content differences.

Primary files:

- `src/orchestrator/graph/projections.py`
- `tests/unit/test_graph_projection_duplicate_ids.py`

Verification:

- Paired acceptance events with distinct timestamps replay successfully.
- Materially conflicting duplicate records still fail.
- Pure projection, replay equivalence, duplicate-ID, integrity, and codec tests pass.

## Tranche 3: Fix Authority and File-State Residue

Make graph task authority include all intended implementation files and exclude
runner-generated residue. Ensure candidate file discovery, baseline capture, and
tool-cache handling use one consistent policy. In particular, a legitimate
helper file must not be omitted, and `.hypothesis` or equivalent transient files
must not cause authority rejection.

Primary areas:

- `src/orchestrator/graph_runtime/file_state.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- graph task authority models and prompt construction
- focused graph runtime authority and file-state tests

Verification:

- Intended helper files are represented in the lease authority.
- Test/tool residue is ignored consistently before and after execution.
- A real unauthorized source edit is still rejected.
- Authority, dispatch, file-state, and task-execution tests pass.

### Execution-Boundary Protocol

The shared-worktree baseline cannot be safe while `submit_callback` terminally
accepts output before the runner exits. Managed runner execution therefore uses
this durable protocol:

1. Capture a recoverable baseline snapshot and typed manifest before starting
   the runner, then record it canonically.
2. `on_submit` validates and stages output and its boundary without publishing
   records, binding downstream inputs, completing the node, or releasing its
   lease.
3. After `runner.execute()` exits successfully, capture the final boundary and
   finalize only if it matches the staged boundary.
4. A mismatch, failure, no-submit exit, exception, or cancellation emits a typed
   recovery request. It never publishes staged records.
5. An idempotent outbox effect selectively restores only execution-attributed
   paths from the durable baseline, including removing execution-created paths.
   Unrelated pre-existing dirt must remain byte-for-byte unchanged.
6. Recovery completion precedes lease revocation/retry. Pending recovery blocks
   new shared-worktree leases and graph completion.

Required graph facts include baseline recorded, submission staged, boundary
mismatch, recovery requested/completed, and execution finalized. Store immutable
execution-attempt state in the graph projection and register strict payloads.
Retain the old terminal callback only for synchronous non-managed paths; managed
runners with a recorded baseline cannot bypass staging.

Selective restore must reject absolute, traversal, root, and `.git` paths;
handle additions, modifications, deletions, renames, copies, symlinks, modes,
and file/directory transitions; and be idempotent across crash points. Restart
recovery derives pending finalize/restore work from canonical projection state,
not process-local caches.

The executor's injected repository lock covers baseline capture, runner
execution, final capture, check worktree setup/teardown, snapshot cleanup, and
restoration. Cancellation fences late finalization but cannot suppress cleanup.

Protocol verification must prove that no canonical event sequence accepts a
managed runner's output while that runner can still mutate the submitted
filesystem boundary. It must include real-repository tests for matching submit,
post-submit mutation, crash/no-submit, unsuccessful result, cancellation,
selective restoration, restart at each recovery crash point, scheduler gating,
narrow authority, source-kind transitions, rename/copy parsing, and cache policy.

## Tranche 4: Bound Graph Reads and Event Payloads

Stop graph endpoints and runtime status paths from loading or returning an
unbounded event history. Add explicit bounded query behavior and return only the
payload needed by current consumers. Preserve deterministic ordering and expose
pagination or truncation metadata when callers need to continue reading.

Primary files:

- `src/orchestrator/api/routers/graph.py`
- graph event database/query accessors and public exports
- graph API schemas
- graph endpoint and query tests
- affected UI API types and consumers, if the response contract changes

Verification:

- API input bounds are validated by Pydantic and invalid values return 422.
- Large histories do not require full materialization for bounded requests.
- Ordering, continuation, empty-history, and limit-boundary tests pass.
- Existing UI graph views continue to load correctly.

## Tranche 5: Repair Pause/Resume Ownership

Make pause and resume transitions preserve a single authoritative owner for the
active graph driver. Pausing must quiesce dispatch safely, and resuming must
recover or requeue an interrupted lease rather than leave a permanently leased
node. Keep lifecycle writes routed through the signal queue.

Primary files:

- `src/orchestrator/workflow/signals/consumer.py`
- `src/orchestrator/workflow/graph_driver.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- signal, graph-driver recovery, redelivery, and lifecycle tests

Verification:

- Pause during an active lease reaches a stable paused state.
- Resume creates exactly one active driver and no duplicate dispatch.
- Interrupted leases are recovered deterministically.
- Cancel and server-shutdown behavior remain correct.
- Signal-routing boundary check passes.

## Tranche 6: Finalize Completed Graph Runs

Completion must turn accepted task work into a durable run branch commit before
the run reports `completed`. Define explicit failure behavior when finalization
cannot produce a clean commit. Do not silently mark dirty, uncommitted work as
complete.

Primary files:

- `src/orchestrator/workflow/graph_driver.py`
- workflow completion/finalization services
- git worktree/commit public APIs
- run and graph completion tests using real temporary repositories

Verification:

- A successful graph run records a non-empty end commit when files changed.
- The worktree is clean after successful completion.
- No-change completion is handled explicitly and remains truthful.
- Commit/finalization failure prevents a false completed state and records a
  recoverable domain-specific error.

## Tranche 7: Make Merge Readiness Truthful

Represent run disposition independently from `ahead_count`. A completed run with
dirty uncommitted work is not merged, and the merge API must reject it with a
clear reason. The UI must distinguish merged, ready to merge, no changes, dirty,
and blocked states.

Primary files:

- `src/orchestrator/api/routers/runs.py`
- run response and branch-status schemas
- merge workflow/service logic
- `ui/src/components/dashboard/RunDetail.tsx`
- associated backend integration and UI tests

Verification:

- `ahead_count == 0` alone never renders `Merged`.
- Dirty or unfinalized completed runs cannot be merged.
- Already-merged and legitimate no-change runs are distinguishable.
- Merge disposition derives from explicit backend facts, not UI inference.

## Tranche 8: Eliminate JSONL Archive Collisions

Generate archive names that cannot collide when multiple rotations cover the
same event range. Rotation must be atomic, preserve every event exactly once,
and remain restart-safe. Do not rely on range-only archive filenames.

Primary files:

- `src/orchestrator/db/access/jsonl_outbox.py`
- JSONL outbox rotation, recovery, and bootstrap tests

Verification:

- Repeated same-range rotations produce distinct archives.
- Existing archives are never overwritten.
- Crash/restart scenarios retain all events without duplication or loss.
- Concurrent or rapid rotations have deterministic, tested behavior.

## Tranche 9: Remove Active Superpowers Integration

Delete active vendored skills and discovery shims, remove OpenCode plugin/config
references, and revise active repository guidance so agents no longer invoke
Superpowers. Preserve historical design evidence unless it participates in
active discovery or enforcement.

Primary paths:

- `vendor/superpowers/`
- `.agents/skills/superpowers/`
- `.claude/skills/`
- `opencode.json`
- `AGENTS.md`
- active checks, scripts, or documentation that require those paths

Verification:

- No active configuration or guidance loads or mandates Superpowers.
- No dangling discovery symlinks remain.
- Repository checks do not depend on deleted content.
- Historical documents remain readable where preservation is useful.

## Final Gap Analysis and Merge Gate

A fresh planner reviews the aggregate diff against every incident observed in
run `86b98d75-540b-4d6a-ba4a-fa35863b2923`. Additional findings are implemented
through the same sequential builder/verifier loop.

Final verification includes:

- focused tests for every tranche
- `uv run ruff check .`
- `uv run pyright`
- `uv run python scripts/check_graph_projection_boundaries.py`
- `uv run python scripts/check_signal_routing.py`
- backend full test suite
- UI lint, typecheck, and test suite
- repository search for removed Superpowers integration and obsolete query names
- final worktree diff review for unrelated or generated files
