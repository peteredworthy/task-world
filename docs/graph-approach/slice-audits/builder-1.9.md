# Slice 1.9 — Readiness completion + resource matrix (BUILDER)

You are the BUILDER agent for slice 1.9 of the task-world execution-graph kernel. Slice 1.8 (command applier, §14 task projection, callback snapshot/execution checks) is already in the working tree — build on it, do not regress it.

## Ground truth (read first, in order)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §10.5 (edges/input bindings), §15.6 (planner lifecycle), §15.7 (review lifecycle), §17 (readiness criteria 1–8, tie-breaks), §18 (resource claims, path rules 1–4, conflict matrix, §18.2 default policy)
2. `docs/graph-approach/phase-1-punch-list.md` — items P1-4, P1-5, P1-6 define this slice (P1-8 already done in 1.8)
3. Existing kernel: `src/orchestrator/graph/` — especially `scheduler.py`, `projections.py`, `commands.py`, `scenario.py`
4. Tests: `tests/unit/test_scheduler.py`, `tests/unit/test_graph_commands.py`, fixtures in `tests/fixtures/graph/`

## Scope

### 1. P1-4: readiness criteria 3–5 (§17)

Reduce `edge_created` and `input_bound` events into the projection (edges: from/to node+port, required flag; bindings: to_node/to_port satisfied). Extend readiness evaluation (wherever `schedule_tick`/`evaluate_readiness` decides eligibility) so a planned/blocked node is ready only when:

- (criterion 3) every REQUIRED input port has an accepted binding (`input_bound`); optional inputs never block
- (criterion 4) no upstream required dependency (source node of a required edge) is `failed`, `cancelled`, or has a pending appeal — unless the consuming node kind is `recovery`/`oversight` (policy allows those to consume failures), or a revision node consuming a failed verification record
- (criterion 5) any gate input is decided `approved` (rejected or undecided gate blocks)

`evaluate_readiness` should return the failing criterion in its reason string (e.g. `missing_required_input:candidate`, `upstream_failed:build-A-1`, `gate_not_approved:gate-1`) so the scheduler's deferred_reasons explain decisions. `schedule_tick` in `commands.py` must use this: emit `node_ready` only for nodes passing all criteria.

### 2. P1-5: resource matrix completion (§18)

In `scheduler.py`:

- **Glob-aware path overlap.** Replace exact-string `_paths_overlap` with deterministic glob matching: normalize POSIX paths, resolve `.`/`..` segments (reject claims whose normalized path escapes repo root — treat as conflicting), expand `**`/`*` per `fnmatch`-style rules, directory claims match recursively. `src/**` must overlap `src/foo.py`; `src/**` vs `docs/**` must not. Empty path list = whole repo (overlaps everything) — keep that conservative default.
- **Snapshot-aware reads (§18.2).** A `read` claim with a `snapshot_id` (immutable snapshot source) is compatible with an active `write` claim on overlapping paths; a `read` claim with no `snapshot_id` (live worktree) conflicts on overlap. Both directions (existing read vs requested write, existing write vs requested read).
- **Matrix completion.** Implement/verify every §18 cell: review_write row/column (conflicts with read on overlapping live paths, with write, with itself; compatible with graph_write unless review region patched — for v1, treat graph_write×review_write as compatible), graph_write×write stays compatible (controller serialization, document in code), external exclusive flag both directions.
- **Tests: one per testable matrix cell** (25 cells; cells whose v1 semantics are "compatible, controller serializes" still get a test asserting compatibility). Plus glob overlap cases, `..` escape rejection, snapshot-read-during-write grant, live-read-during-write deferral.

### 3. P1-6: planner + review lifecycle fixtures (§15.6, §15.7)

New fixture files `tests/fixtures/graph/node_lifecycle_planner.yaml` and `node_lifecycle_review.yaml` covering every row of the §15.6 and §15.7 transition tables, in the post-1.8 house style: transitions with a command path driven via `when_command` through `apply_command`; pure state-recording rows assert nonempty `then_projection`. Planner completion must NOT imply patch acceptance (separate scenario: planner completes, its patch is rejected, planner node stays `completed`). Add COVERAGE.md rows for §15.6/§15.7.

### 4. Strengthen the two 1.8-deferred invariants

`invariants.yaml::invariant_successor_requires_inputs` and the gate-blocking invariant: rewrite them to drive `schedule_tick` via `when_command` and assert the successor is NOT selected (deferred with `missing_required_input`/`gate_not_approved` reason event or projection state), and a positive twin where the binding/approval exists and the node becomes ready. Remove any `# strengthened-in-1.9` markers left by 1.8.

## Done when

1. §17 criteria 1–8 each have at least one test or fixture that fails if the criterion's check is deleted (criteria 1, 2, 6, 7 already covered by 1.5/1.8 — verify, don't duplicate needlessly).
2. Every testable §18 matrix cell has a test; glob and snapshot semantics implemented.
3. §15.6 and §15.7 fixtures exist, pass, and are indexed in COVERAGE.md.
4. Full kernel suite green and under 5 seconds:
   `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q`
5. `uv run ruff check src/orchestrator/graph tests/unit` and `uv run pyright src/orchestrator/graph` pass.

## Hard constraints

- Pure kernel: no filesystem/network/DB/FastAPI/runner imports in `src/orchestrator/graph/`. Glob logic must be deterministic — use `fnmatch`/`posixpath` stdlib, no filesystem access.
- NO mocks, NO monkeypatching in tests.
- Touch ONLY: `src/orchestrator/graph/**`, `tests/unit/test_graph_*.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_scenario_harness.py`, `tests/unit/test_fixture_corpus.py`, `tests/unit/test_callbacks.py`, `tests/unit/test_patch_validator.py`, `tests/fixtures/graph/**`. Leave all other working-tree modifications untouched.
- No git state mutation (no commit/stash/checkout/reset). No `orchestrator.db`, no `.orchestrator/`, no servers.

## Output

End with: files changed, test count before/after, kernel suite wall clock, honest list of anything incomplete.
