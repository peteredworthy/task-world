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
   through the normal run API, and waits at most 900 seconds for terminal state.
   Before each run it requests a server-derived qualification grant from
   `POST /api/runs/reliable-plan-qualification` and submits only that opaque
   reference alongside the skeleton ID and model assignments. No enable boolean,
   qualification result, receipt payload, or scenario pass claim crosses the
   public JSON boundary.
4. The harness extracts projection, topology, health, node-contract, usage,
   hydration, and recovery facts through operator read APIs. Store a
   `ReliablePlanComparisonArtifact` containing correctness, revisions, graph
   node/edge/batch/horizon shape, carrier token/action/duration totals,
   recovery facts, exact model profiles, and the legacy plan-then-execute arm.

## Results template

| Arm | Run ID | Evidence | Correct | Revisions | Nodes/edges | Batches/horizons | Tokens | Actions | Duration ms | Recovery | Models |
|---|---|---|---:|---:|---|---|---:|---:|---:|---|---|
| Luna bounded workers | _required_ | blocked | — | — | — | — | — | — | — | — | Luna workers; independent verifier |
| Alternate workers/verifier | _required_ | blocked | — | — | — | — | — | — | — | — | alternate explicit assignments |
| Legacy plan-then-execute | _required_ | blocked | — | — | — | — | — | — | — | — | recorded legacy profiles |

Current live evidence is explicitly **blocked**: this implementation session
did not have an authorized running server plus the required live routine/repo
registration, writable qualification evidence directory, and runner execution
evidence. No server was started and no run IDs or model results are fabricated.
The harness retains honest environment/server skips and requires all three arms
to complete correctly with no active lease before constructing comparison deltas.
