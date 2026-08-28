# Reliable-plan dogfood evaluation protocol

Incident: `fff4f6b7-bf33-475f-8280-31ff5e1ef7ca`  
Deterministic skeleton: `reliable-plan-fff4f6b7-v1`

The deterministic SQLite/controller regression is the qualification gate. It
must mechanically pass numbered scenarios 1-10 from
`reliable-plan-execution-contract.md` before one-horizon Luna successor
planning is enabled. The canonical assignments and scenario manifest live in
`tests/fixtures/graph/reliable_plan_fff4f6b7.json`.
The fixture contains no passing qualification. The executable product-path
runner stores each observation and its receipt through the SQLite-backed graph
controller. The server repeats that canonical qualification before issuing an
opaque, single-use `rpq_…` grant. Run creation atomically consumes and binds the
grant, while caller-supplied qualification facts remain invalid.

## Protocol

1. Run the focused semantic, progressive-batch, snapshot-authority, prompt,
   recovery, read-contract, evaluation, and durable controller suites.
2. Set `RELIABLE_PLAN_E2E_QUALIFICATION_PATH` to a writable evidence directory.
   The live harness reruns the canonical controller-backed qualification there
   and stops before any network request if a scenario fails. Also set
   `RELIABLE_PLAN_E2E_FEATURE_SPEC_PATH` and
   `RELIABLE_PLAN_E2E_ACCEPTANCE_COMMAND`; these are supplied to every graph
   and legacy arm so all three execute the same public contract and gate.
3. With a separately running server, credentials, repository registration,
   graph and legacy routines, writable qualification path, and available Codex
   Server runner, run
   `tests/e2e/test_reliable_plan_live_evaluation.py`. The harness creates both
   graph arms plus the legacy baseline through `POST /api/runs`, starts them
   through the normal run API, and waits at most 3,600 seconds for terminal state.
   Before each run it requests a server-derived qualification grant from
   `POST /api/runs/reliable-plan-qualification` and submits only that opaque
   reference alongside the skeleton ID and model assignments. No enable boolean,
   qualification result, receipt payload, or scenario pass claim crosses the
   public JSON boundary.
4. The harness extracts graph, health, node-contract, usage, hydration, and
   recovery facts through operator read APIs. It pages the canonical bounded
   graph-event API so terminal evidence remains extractable when a derived
   topology or node-detail summary is temporarily stale. Store a
   `ReliablePlanComparisonArtifact` containing correctness, revisions, graph
   node/edge/batch/horizon shape, carrier token/action/duration totals,
   recovery facts, exact model profiles, and the legacy plan-then-execute arm.

## Live results — 2026-08-28

| Arm | Run ID | Evidence | Correct | Revisions | Nodes/edges | Batches/horizons | Tokens | Actions | Duration ms | Recovery | Models |
|---|---|---|---:|---:|---|---|---:|---:|---:|---|---|
| Luna bounded workers | `4ee15ff9-213a-424e-9fc7-82801f5dd16b` | complete readback; manually paused after a 15-minute live worker turn produced no callback | no | 0 | 26/25 | none | 10,823,845 | 145 | 1,390,772 | 1 active lease | Luna discovery/implementation/correction/successor; Sol planner/verifier |
| Alternate workers/verifier | `7f55a7f1-fa13-4fce-8312-54b83309cd85` | complete readback; graph paused as quiescent with missing final corrective verification evidence | no | 0 | 26/30 | none | 8,579,453 | 211 | 1,581,992 | 3 revoked leases | Terra workers; Sol planner/verifier/successor |
| Legacy plan-then-execute | `8fdde514-9720-4b21-8b33-717725f7aa2b` | completed with all three rubric grades A | yes | 0 | 0/0 | none | 2,094,915 | 49 | 476,686 | none | Terra implementation/verifier carrier |

The deterministic scenarios qualified 10/10 through the SQLite/controller
product path. The live hypothesis did not pass: only the legacy arm completed,
while neither dynamic-graph arm reached an accepted terminal state. Relative to
legacy, the Luna arm used 8,728,930 more tokens, 96 more actions, and 914,086 ms
more recorded model duration. The alternate arm used 2,244,392 fewer tokens than
Luna but 66 more actions and 191,220 ms more duration.

The trial exposed two implementation defects that were corrected during the
same run: snapshot-ineligible writers could reserve resource claims before
snapshot resolution and starve runnable writers, and the Codex Server planner
tool list omitted the four reliable-plan macros. Reporting also observed a stale
derived topology/node-detail summary at graph position 225 after the Luna pause;
the canonical graph and bounded event APIs remained current, so the comparison
artifact records exact evidence without treating the stale summary as success.

The machine-readable artifact is
`/private/tmp/reliable-plan-e2e-20260828-3/reliable-plan-comparison.json`.
The harness writes it before asserting arm correctness, preserving failed-trial
evidence. Environment/server skips remain honest, and a live run still fails its
test unless all three arms complete correctly with no active leases.
