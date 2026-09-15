# Slice 6B implementation ledger

Scope: exercise the core joined decision-v1 planning and execution cases through
the existing API, durable signal consumer, `GraphRunDriver`, graph dispatcher,
controller, and deterministic runner routing. This slice uses disposable
Git/SQLite state only; it does not run a model evaluation or touch live history.

| ID | Required behavior | Acceptance evidence | Status |
|---|---|---|---|
| S6B-1 | A one-batch decision-v1 plan completes through the production driver. | Passing parameterized production-path case `one-batch`: API-created run reaches `completed`, with the decision plan, passing plan report, candidate/file state, check, verifier report, final audit, and completion decision. | passed |
| S6B-2 | A dependent multi-batch plan materializes and executes only after the prior batch is independently accepted. | Passing case `dependent-batches`: exact `core → api` order, distinct candidate/file-state/check/report evidence, API worker creation after core verifier completion, clean leases, completed outbox, and clean checkout. | passed |
| S6B-3 | A plan amendment is independently verified before amended execution proceeds. | Passing case `verified-plan-amendment`: one superseding plan record, at least two passing plan-verification reports, amended `core → api` execution, and amendment lineage retained after fresh readback. | passed |
| S6B-4 | Production completion is restart-safe and ownership is drained. | Each case re-reads the terminal run through a fresh `GraphController`; all leases are non-active, the process registry has no run owner, every outbox row is `completed`, and the candidate checkout is clean. | passed |
| S6B-5 | Existing legacy joined coverage remains compatible. | `test_api_start_serializes_two_bounded_horizons_with_durable_signals` and `test_api_correction_uses_exact_failure_evidence_then_completes_horizon_two` both pass. | passed |

Known baseline: the existing joined production test covers the legacy
constructor/graph-patch path. The new Slice 6B coverage must select
`agent_interaction_contract: decision-v1` and must not treat that legacy proof as
decision-v1 evidence.

## Implementation and evidence

The joined harness now routes deterministic typed `decision-v1` answers through
the existing API-start, durable-signal, `GraphRunDriver`, dispatcher, controller,
and runner callback path. It covers one batch, a dependent second batch, and a
`revise_plan` amendment. Each case checks exact semantic records and evidence,
batch ordering, public completion, fresh-controller projection replay, clean Git,
drained ownership, and completed graph outbox rows.

The production fix was in reliable-plan macro readiness. Dependency verification
is represented by the required passed-report edge and a worker-only declared-batch
precondition. The scheduler now satisfies that precondition from the corresponding
typed dependency input. Copying it onto verifier, check, and finalization nodes
had left later horizons permanently planned because those nodes do not carry
dependency-verification ports.

Starting point: commit `1cf10fc7267107c314bcffef0fd716716c498f6b`.
Starting Git blob hashes:

| File | Starting blob |
|---|---|
| `src/orchestrator/graph/macros.py` | `8692459fe8908c2e6041a1797327f3ea4057b494` |
| `src/orchestrator/graph/scheduler.py` | `9c9fe1000381261c00c2796e3640a3615e9fac65` |
| `tests/integration/test_graph_sequential_product_path.py` | `1b077cbf0f5f2564c1fea1046f257ce77ba366dd` |
| `tests/unit/test_scheduler.py` | `f482d05246ec37207575afcaedeb43bb3695e5ef` |

Exact validation commands and results:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_scheduler.py --override-ini='addopts=' --tb=short
50 passed in 1.04s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_graph_sequential_product_path.py -k 'decision_v1_joined_success_cases_use_production_driver' --override-ini='addopts=' --tb=short
3 passed, 7 deselected in 102.05s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_graph_sequential_product_path.py -k 'api_start_serializes_two_bounded_horizons_with_durable_signals or api_correction_uses_exact_failure_evidence_then_completes_horizon_two' --override-ini='addopts=' --tb=short
2 passed, 8 deselected in 200.28s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph/scheduler.py src/orchestrator/graph/macros.py tests/unit/test_scheduler.py
0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph/macros.py tests/integration/test_graph_sequential_product_path.py
All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check src/orchestrator/graph/macros.py tests/integration/test_graph_sequential_product_path.py
2 files already formatted
```

Final SHA-256 hashes after implementation (before this ledger's final edit):

| File | SHA-256 |
|---|---|
| `src/orchestrator/graph/macros.py` | `b22ebb7d947199932ca689e24b625427f2c8b49eb071bff9a1e0ed11d106f2fe` |
| `src/orchestrator/graph/scheduler.py` | `c8b803cf3d7e8e99f7af1c1de72343c64131d3a35a1589e2756a8eb07ea039c5` |
| `tests/integration/test_graph_sequential_product_path.py` | `9722bfa0f053e0c38910960e130efe0061ae8e1da52fcfd7a242f3ec3c760c4b` |
| `tests/unit/test_scheduler.py` | `6c68823f61d0d527b20e1ad1a33768b0631d4cbedd4f72c7caa623ac876452b3` |
```

No model-reliability claim is made; all answers were deterministic injected
runner responses in disposable real Git/SQLite integration state.
