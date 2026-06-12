# Slice 2.4 — File-state boundary, warn-and-capture (BUILDER)

You are the BUILDER agent for slice 2.4 of the task-world execution-graph kernel (Phase 2).

## Ground truth (read these first, in order — note the AMENDMENTS)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §20 (file-state & snapshot policy: boundary check steps, §20.3 classification taxonomy + table, §20.4 downstream consumption, §20.5 retention), §11.2 (file-state record), §27.1 (`classify_file_state` is a required pure-core API), §27.2 (file-state invariants)
2. `docs/graph-approach/execution-graph-evaluation.md` §6.3 — AMENDS §20.2 rule 4: v1 is WARN-AND-CAPTURE. Classify and record everything, reject nearly nothing; only secret-suspects and repo-escaping paths are hard-rejected. Undeclared residue is CAPTURED with its classification, not rejected. §6.4 — git-plumbing snapshots replace patch bundles (no patch_bundle machinery; `no_commit_reason` shrinks to `verification_only`/`empty_change`).
3. The slice definition (sequencing deck): "2.4 File-state boundary — Warn-and-capture classifier; residue recorded never rejected (except secret-suspects); snapshot via 0.3 plumbing; classification data accumulates. Done when: deterministic outcomes for tracked/untracked/ignored/secret-like fixtures; real-run residue report exists."
4. Existing snapshot plumbing (slice 0.3): `src/orchestrator/git/snapshot.py` — `snapshot(worktree_path, message) -> SnapshotResult` (GIT_INDEX_FILE + write-tree + commit-tree + refs/orchestrator/snapshots/<id>, hooks never fire), `restore(worktree_path, snapshot_id)`. Use it; do not reimplement.
5. Existing graph kernel/runtime: `src/orchestrator/graph/` (commands.py callback path, models, projections), `src/orchestrator/graph_runtime/` (dispatch.py — the worker-callback path where the boundary check belongs), slice 2.3's e2e drill `tests/integration/test_graph_runner_e2e.py`.

## Scope — what to build

### 1. Pure classifier in the kernel (`src/orchestrator/graph/file_state.py`)

The §27.1 pure function:

```python
classify_file_state(status: WorktreeStatus, policy: FileStatePolicy) -> FileStateClassification
```

- `WorktreeStatus` is a pure data input: lists of tracked-modified, untracked, ignored paths (built by the effectful collector, point 2). NO filesystem access in this module.
- `FileStatePolicy`: declared routine/project patterns with configured classifications, built-in known tool-cache patterns (e.g. `__pycache__/`, `.pytest_cache/`, `node_modules/`, `.ruff_cache/`, `.venv/`), secret-suspect detectors (name patterns like `*.pem`, `.env*`, `id_rsa*`, `*credentials*`, plus size/entropy METADATA fields supplied by the collector — the classifier never reads content), and repo-escape detection (paths resolving outside the worktree, `..`, absolute, symlink-escape flagged by collector metadata).
- Output: per-path classification into the §20.3 taxonomy (`tool_cache`, `build_output`, `test_artifact`, `secret`, `external_artifact`, `unknown_ignored` — plus `declared` / `tracked_change` for matched declarations and tracked modifications), each with the matched pattern/rule, and an overall verdict: `captured` (the warn-and-capture default) or `rejected` ONLY for secret-suspects and repo-escaping paths. Unmatched residue gets `unknown_ignored`/`unknown_untracked` with `needs_gatekeeper: true` (consumed by slice 2.5; no LLM call in this slice).
- Deterministic: same input → same output; classification ordering stable.

### 2. Effectful boundary in graph_runtime (`src/orchestrator/graph_runtime/file_state.py`)

- Collector: run `git status --porcelain=v2 --ignored` (subprocess, real git) in the worktree → build `WorktreeStatus` with metadata (file size; entropy only for secret-suspect name matches, computed without retaining content).
- Boundary check at the worker-callback boundary (wire into the 2.3 dispatch flow where the worker's submit becomes `submit_callback`): collect → classify → snapshot via 0.3 plumbing (`snapshot()` captures the tree INCLUDING residue; secret-suspect paths must NOT be captured — exclude them from the snapshot index or document precisely why exclusion is impossible and reject instead per §20.3 rule 4) → attach to the callback payload a `file_state` output record (`record_kind: "file_state"`): snapshot_id, base/parent, per-path classifications, residue report, rejected paths. The KERNEL accepts it as an output record on the worker's `file_state` port (extend the pure kernel minimally if a dedicated record kind needs validation — same provenance rules as 2.3 verification records).
- `file_state_rejected` path: secret-suspect or repo-escape → the callback still happens but carries the rejection record (`file_state_rejected` event with paths + classifications + reason); node does NOT complete (worker boundary fails → kernel keeps lease/node per §20.2 rejection semantics — decide the exact node outcome per §15.1 worker lifecycle and document it).
- Replay determinism: classifications live in accepted events; rebuilding projections never re-runs git or the classifier.

### 3. Classification data accumulates

A queryable projection/report: per-run residue report derived from accepted file-state records (path → classification → matched rule → run/node), exposed as a pure projection function (`project_residue_report(events)`) in the kernel. This is the "classification data accumulates" hook that 2.5's pattern library feeds on. No DB tables needed beyond the event log.

### 4. Tests

`tests/unit/test_graph_file_state.py` (pure, part of kernel suite):
- Deterministic outcomes for the four fixture families from the done-when: tracked changes, untracked residue (captured + classified), ignored files (each §20.3 taxonomy row exercised: known tool cache → tool_cache; declared build output → build_output; declared test artifact → test_artifact; undeclared ignored → unknown_ignored captured with needs_gatekeeper), secret-like (name-pattern + high-entropy metadata → secret, verdict rejected) and repo-escaping (rejected).
- Determinism: same WorktreeStatus + policy → identical classification list (run twice, compare).
- §20.3 table: one test per row (6 rows).
- `project_residue_report` over synthetic events.

`tests/integration/test_graph_file_state_boundary.py` (real git in tmp dirs, real SQLite):
- Real worktree: tmp git repo; agent-simulated changes: a tracked-file edit, an untracked residue file, a `__pycache__/` dir, an undeclared `.gitignore`d file, and a `fake_key.pem` (random bytes). Boundary check → callback through the controller → assert: snapshot ref exists (refs/orchestrator/snapshots/...), restore() round-trips the captured tree, file_state record accepted with correct per-path classifications, pem file NOT in the captured tree, residue report from `project_residue_report` over the stored events matches.
- Secret-rejection variant: callback carries file_state_rejected; worker does not complete; lease/node state per your documented §15.1 choice.
- Extend (do not rewrite) the 2.3 e2e drill: the happy-path builder→verifier run now produces an accepted file-state record at the worker boundary and still reaches task `accepted` — this is the "real-run residue report exists" done-when item: print/assert the residue report for that run.

## Done when (all must hold)

1. Deterministic classification outcomes for tracked/untracked/ignored/secret-like fixture families (unit, pure, in kernel suite <5s total).
2. Warn-and-capture semantics: residue is recorded + classified, never rejected — EXCEPT secret-suspects and repo-escaping paths, which are rejected and never captured into snapshot storage.
3. Boundary wired at the worker callback through the controller; file-state record accepted as kernel output record; replay never re-runs git/classifier.
4. Real-run residue report exists: e2e drill produces it from stored events.
5. Snapshots via 0.3 plumbing only (no patch_bundle, no porcelain `git commit`, no stash).
6. Kernel purity: `src/orchestrator/graph/file_state.py` has NO subprocess/filesystem imports; collector lives in graph_runtime.
7. Fresh green: `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `uv run ruff check src tests`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`.

## Hard constraints

- NO unittest.mock / monkeypatching. Real git repos in tmp dirs (full git freedom there), real tmp SQLite. NEVER the main repo's git state, never main `orchestrator.db`, no server.
- Touch ONLY: `src/orchestrator/graph/file_state.py` (new) + `__init__.py` export + `models.py`/`commands.py`/`projections.py` (minimal file-state record/report additions), `src/orchestrator/graph_runtime/file_state.py` (new) + `dispatch.py` (boundary wiring) + `__init__.py`, `src/orchestrator/git/snapshot.py` ONLY if a parameter is genuinely missing (e.g. path exclusion) — keep any change additive and tested, `tests/unit/test_graph_file_state.py` (new), `tests/integration/test_graph_file_state_boundary.py` (new), `tests/integration/test_graph_runner_e2e.py` (extend), `tests/fixtures/graph/**` + COVERAGE.md if fixtures added.
- Do not run the orchestrator server. No git mutation of THIS repo.

When done: summary (classifier design, secret-exclusion mechanics, boundary node-outcome choice, residue report shape), fresh test output.
