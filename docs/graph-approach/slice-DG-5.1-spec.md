# Slice DG-5.1 Spec: Dynamic Smoke Run

## Objective

Run the smallest production-style dynamic graph feature scenario that can prove the dynamic planner path is operational, or record a precise blocker if the current `dynamic-graph-feature` routine cannot yet execute that path.

## Scope

In scope:

- Create a tiny smoke feature specification for a dynamic graph run.
- Launch `dynamic-graph-feature` through the orchestrator in `execution_mode: graph`.
- Use a Codex-backed runner by default; Claude CLI may be used if Codex server is unavailable or stuck.
- Monitor only through API endpoints.
- Record graph events, activity rows, and DG-4.3 comparison metrics for the run.
- If the run blocks, classify the blocker as routine-shape, planner-tool, scheduler, invariant-gate, runner, or stale-worktree.

Out of scope:

- Running the full five-arm comparison.
- Broad runtime rewrites.
- Deleting DBs or manually editing orchestrator state.
- Treating manually injected graph events as proof of operational dynamic planning.

## Smoke Feature

Use a deliberately small feature with weak local validation and a hidden global requirement:

- Build/update a tiny text or code artifact with an initially ambiguous must requirement.
- Local acceptance should be intentionally weak enough that a first worker/verifier path can appear to pass.
- The dynamic gap planner must discover that validation is too weak and append corrective work.
- Final completion must be blocked while the corrective region, stale evidence, unresolved proposal, or invariant blocker remains.

Recommended fixture/spec path:

- `docs/graph-approach/dynamic-smoke-feature-spec.md`

The feature spec should be short and self-contained so the smoke run tests dynamic graph behavior, not domain complexity.

## Required Evidence

Collect and summarize:

- run id, runner, model, routine id, execution mode, worktree path, and terminal status;
- `/api/runs/{run_id}/activity`;
- `/api/runs/{run_id}/graph/events`;
- `uv run python scripts/compare_carriers.py dynamic=<run_id>`;
- accepted/rejected patch counts and rejection reasons;
- whether any planner node called `submit_graph_patch`;
- whether a gap/corrective region was appended;
- whether final completion was blocked before correction and passed after correction.

## Done When

Accepted only if:

1. `dynamic-graph-feature` launches as a graph-backed run.
2. A planner emits at least one real `submit_graph_patch` through the runner/tool path.
3. At least one `graph_patch_accepted` event creates future worker/verifier/gap/corrective or invariant work.
4. A gap planner appends at least one corrective region after initial local verification or weak validation.
5. Final completion is blocked by graph invariant evidence before correction and passes after correction.
6. DG-4.3 comparison metrics report nonzero dynamic graph facts for the run.

If any criterion cannot be met, do not force success. Record the smallest blocker with evidence and define the next repair slice.

## Validation Commands

Use API reads plus the exporter:

```bash
curl -sS http://127.0.0.1:8000/api/runs/<run-id>
curl -sS http://127.0.0.1:8000/api/runs/<run-id>/activity
curl -sS http://127.0.0.1:8000/api/runs/<run-id>/graph/events
uv run python scripts/compare_carriers.py dynamic=<run-id>
```

Run the narrow exporter regression after any local changes:

```bash
uv run pytest tests/unit/test_compare_carriers.py -q
uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py
uv run pyright scripts/compare_carriers.py
```

## Durable Update

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with accepted evidence or a blocker-classified next slice.
