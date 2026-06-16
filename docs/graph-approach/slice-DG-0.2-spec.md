# Slice DG-0.2 — Dynamic Metrics Schema

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` — Phase DG-0, Slice DG-0.2.
- `docs/graph-approach/dynamic-graph-baseline.md` — DG-0.1 baseline and current graph-control risk.
- `docs/graph-approach/true-comparison-plan.md` — comparison target, especially dynamic Arm E.
- `scripts/compare_carriers.py` — existing carrier comparison metric extraction and aggregation.
- `tests/unit/test_compare_carriers.py` — current pure aggregation coverage.
- Existing graph event vocabulary in `src/orchestrator/graph/`, especially accepted event types already covered by graph tests.

## Scope

Extend the carrier comparison metric layer so dynamic graph runs expose the facts needed to evaluate planner-driven operation. This slice is instrumentation only. It must not alter graph runtime behavior, scheduler behavior, runner behavior, API semantics, database schema, UI behavior, or graph mutation rules.

Expected code surface:

- `scripts/compare_carriers.py`
- `tests/unit/test_compare_carriers.py`

Adding small pure helper functions in the script is preferred over introducing a new module unless the existing file becomes hard to read.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-0.2",
    "spec_path": "docs/graph-approach/slice-DG-0.2-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

If that exact model is unavailable, choose an available Codex model. Do not use Claude-backed runners.

## What To Build

### 1. Dynamic Graph Metric Extraction

Add pure extraction logic that can summarize graph event dictionaries into dynamic metric fields. It must accept event shapes returned by graph APIs and unit-test fixtures:

- `{"event_type": "...", "payload": {...}}`
- graph API response variants that place payload fields under `payload`.

The extracted metric dictionary must include at least:

- `planner_patches`: count of planner patch submissions accepted or rejected.
- `accepted_patches`: count of `graph_patch_accepted`.
- `rejected_patches`: count of `graph_patch_rejected`.
- `patch_ops`: total count of operations across accepted and rejected patch payloads when an `ops` list is present.
- `patch_rejection_reasons`: mapping of rejection reason string to count.
- `appended_regions`: count of `node_created` events attributable to accepted graph patches or dynamic planner-created regions.
- `suspect_regions`: count of `plan_region_marked_suspect` events and file-state records marked compromised/superseded/suspect.
- `superseded_regions`: count of cleanup/supersede facts such as `cleanup_applied` and file-state records with supersede metadata.
- `gap_findings`: count of graph facts representing gap findings. For this slice, support obvious event names such as `gap_finding_recorded`, plus file-state/gatekeeper records whose classification/verdict indicates a gap.
- `proposal_decisions`: count of decision facts such as `oversight_decision_recorded`, `approval_decision_recorded`, and `appeal_opened`.
- `invariant_gate_failures`: count of gate or invariant failure facts, including failed gatekeeper verdicts and events with invariant/gate failure names.
- `graph_verifier_grades`: mapping from grade string to count, extracted from `verification_passed`/`verification_failed` payload `grades`.
- `tokens_by_node_kind`: mapping from node kind to token totals, using events such as `gatekeeper_cost_recorded` or runner usage events when node kind is available.

Use conservative matching. Unknown graph events must not crash extraction and must not inflate counts.

### 2. Run Metric Integration

Integrate dynamic metrics into `run_metrics(run_id)`:

- Continue returning all existing fields unchanged.
- Fetch graph events from `/api/runs/{run_id}/graph/events` when available.
- If the graph endpoint is missing, returns 404, or returns an incompatible shape, dynamic fields should default to zero/empty values rather than failing the existing carrier comparison.
- The script should remain useful for legacy runs and graph runs.

### 3. Aggregation Compatibility

Extend `aggregate_bucket` so dynamic metric fields aggregate sensibly:

- Count fields are summed across rows.
- `patch_rejection_reasons`, `graph_verifier_grades`, and `tokens_by_node_kind` are merged by key.
- Existing aggregate keys and existing printed CLI columns remain compatible with current users.
- It is acceptable to add extra CLI columns or a secondary JSON/text detail block for dynamic graph fields, but existing columns must not be removed or renamed.

## Required Tests

Add focused unit tests with hand-written fixtures only; no mocks, monkeypatching, network calls, or TestClient.

At minimum:

1. A seeded/fake graph event stream produces expected totals for:
   - accepted patch count;
   - rejected patch count;
   - patch op count;
   - rejection reason counts;
   - appended region count;
   - suspect/superseded region count;
   - gap finding count;
   - proposal decision count;
   - invariant failure count;
   - verifier grade counts;
   - token totals by node kind.
2. Existing `aggregate_bucket` behavior still passes for completion, all-A, tokens, tools, cost, and empty buckets.
3. Aggregation merges dynamic metric dictionaries across multiple rows.
4. Missing or malformed graph event payloads produce zero/empty dynamic metrics and do not raise.

## Acceptance Commands

Run and record:

```bash
uv run pytest tests/unit/test_compare_carriers.py -q
uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py
uv run pyright scripts/compare_carriers.py
```

If `pyright` cannot type-check a standalone script in this repo configuration, run the narrowest meaningful pyright command and record the reason.

## Done When

1. A seeded/fake graph event stream produces expected dynamic metric totals.
2. Existing carrier comparison aggregate metrics still pass.
3. `run_metrics` can include dynamic graph metrics without breaking legacy runs.
4. Dynamic metric fields are documented by test names and readable code.
5. No source behavior changes outside comparison metric extraction are made.
6. No DB, API, runner, scheduler, graph kernel, or graph runtime behavior is changed.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-0.2 measures dynamic graph facts; it does not implement planner operation.
- Unknown event types and missing graph endpoints are handled conservatively.
- Metric names are stable enough to use in later true-comparison runs.
- The implementation does not claim dynamic graph operational readiness.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git mutation.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not change graph runtime behavior as part of this slice.

## Validation Outcome

- Status: accepted by independent validation on 2026-06-14.
- Accepted implementation surface:
  - `scripts/compare_carriers.py`
  - `tests/unit/test_compare_carriers.py`
- Codex-backed orchestration:
  - Standard run `f9fba1df-1249-4117-9d5f-c530e16fa829` was cancelled because
    stale worktree docs caused the builder to follow legacy `slice-0.2` context
    and edit an unrelated test.
  - Embedded graph run `1c7c7fd6-c8c4-48b0-9d4d-6bd6a00218e8` produced the
    scoped implementation with `codex_server` and `gpt-5.3-codex-spark`.
  - Its verifier node failed before grading because the Codex server invoked the
    model with unsupported tool `image_generation`; this is a control-plane
    blocker, not a DG-0.2 behavior failure.
- Acceptance commands run in both the run worktree and main checkout:

```bash
uv run pytest tests/unit/test_compare_carriers.py -q
uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py
uv run pyright scripts/compare_carriers.py
```

- Results:
  - `6 passed` for `tests/unit/test_compare_carriers.py`
  - Ruff: `All checks passed!`
  - Pyright: `0 errors, 0 warnings, 0 informations`

Remaining risk: graph-mode verifier execution with Codex server must be fixed
or worked around before relying on orchestrator verifier grades for later
dynamic slices.
