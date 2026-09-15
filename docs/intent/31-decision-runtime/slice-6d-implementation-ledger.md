# Slice 6D implementation ledger

> Historical implementation pass. The September 15 integrated review found
> required gaps; [the final closure ledger](slice-6f-final-review.md) supersedes
> the completion status and qualification claims below. Original evidence is preserved.

Status: validated. This slice closes the deterministic smoke result and
public-readback contract. It does not run a model, start a server, activate a
run, resume historical work, or perform a paid probe.

## Functional requirements

| ID | Requirement | Acceptance/evidence | Status | Remaining gap |
|---|---|---|---|---|
| S6D-1 | The deterministic smoke candidate contains only `stage3-smoke.txt`, with exact bytes and regular mode `100644`, and the checkout is clean. | The smoke evidence derives the path, bytes, mode, and clean-status facts from the candidate checkout and the independent oracle. Direct CLI smoke passed. | validated | None. |
| S6D-2 | Phase accounting follows observed runtime semantics rather than assuming seven model phases. | `LifecyclePhaseCounts` reports observed model phases, finalized executions, and node-kind counts; tests assert relationships to dispatch/finalization evidence and no longer require seven phases. | validated | None. |
| S6D-3 | Public readback explains why the accepted result is complete. | `LifecyclePublicReadback` binds completed graph/workflow state, candidate, checks, completion decision, finalized executions, active/suspended leases, owned processes, and pending outbox; its explanation is derived from those facts and JSON round-trips. | validated | None. |
| S6D-4 | Isolated-probe nodes are distinct from unfinished joined execution. | Smoke readback carries separate intentionally-unexecuted and unfinished node lists; joined-case qualification JSON round-trip preserves the compatibility probe's isolated node and empty unfinished set. | validated | None. |

## Baseline

Worktree: `/Users/peter/code/task-world/worktrees/recovery-stabilization`.

Baseline command:

`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_recovery_deterministic_lifecycle.py tests/integration/test_reliable_plan_product_path_qualification.py::test_joined_decision_v1_correction_and_failure_cases_are_bounded --override-ini='addopts=' --tb=short`

Result: 14 passed, 1 configured slow test skipped in 19.07s. The graph
projection boundary check passed (`files_checked=254`).

## Starting hashes

| File | SHA-256 |
|---|---|
| `examples/recovery/deterministic_lifecycle.py` | `ad886caf89ab8e3c90fd961ea05740aa2d8234fbdce2fbb77e06ca6aa4a4eceb` |
| `tests/integration/test_recovery_deterministic_lifecycle.py` | `5039d6864e1ec1b00421618761323afc28c840d6be221e5c70b26a47dcb37716` |
| `tests/integration/test_reliable_plan_product_path_qualification.py` | `5b7fcdddfad3dd1976469f13475b896697ec40826b032ead8c3fa93f7cbe224a` |
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `ac69a694f6f1f33b4e59562f62c48f15a10133427f61541ed84653db8b0670f5` |
| `src/orchestrator/graph_runtime/reliable_plan_scenarios.py` | `79e6c5953c1b87d5c8b0f54b528ec77eb613b1b6bb44d5bec806dfff20632946` |

## Decisions

- The existing lifecycle remains a deterministic legacy compatibility fixture;
  its result must not be relabeled as decision-v1 qualification evidence.
- Phase counts are observations of dispatched runtime nodes and lifecycle
  receipts. They are not a success predicate and do not encode a required
  number of model phases.
- Public readback is a typed, serialized explanation assembled from the
  already-authoritative candidate, checks, completion, graph, and ownership
  facts. It does not create a second lifecycle authority.

## Validation log

- Behavior-first test before implementation: the lifecycle test failed with
  `LifecycleEvidence` missing `phase_counts`, as expected.
- Focused regression after implementation:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_recovery_deterministic_lifecycle.py tests/integration/test_reliable_plan_product_path_qualification.py::test_joined_decision_v1_correction_and_failure_cases_are_bounded --override-ini='addopts=' --tb=short` — 1 passed, 1 configured slow skip in 18.78s.
- Joined and qualification regression:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_recovery_deterministic_lifecycle.py tests/integration/test_reliable_plan_product_path_qualification.py --override-ini='addopts=' --tb=short` — 25 passed in 51.97s; graph boundary check passed (`files_checked=254`).
- Product-real smoke:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python examples/recovery/deterministic_lifecycle.py --workspace /private/tmp/recovery-slice-6d-smoke.ULwfo7` — exit 0. JSON readback reported `stage3-smoke.txt`, exact candidate, mode `100644`, clean checkout, graph/workflow `completed`, passed checks, 7 observed/finalized phases, zero active/suspended leases, zero owned processes, zero pending outbox, and empty unfinished-node list. The seven is observed output only; no test or acceptance predicate requires it.
- Static checks:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check ...` and format check passed; focused Pyright passed with 0 errors and 0 warnings; `git diff --check` passed.

## Final hashes and changed files

| File | Final SHA-256 |
|---|---|
| `examples/recovery/deterministic_lifecycle.py` | `236ced0ec71f22792c38dc6e3f78de913b93e1bf932b002d29d91f00cd32d5da` |
| `tests/integration/test_recovery_deterministic_lifecycle.py` | `e69736e19830727b04472e0807e7db373674110bf987a41c2116fb13090e150e` |
| `tests/integration/test_reliable_plan_product_path_qualification.py` | `184b55188eb8f0b397f3048b3b3c692d91fb207da8ae2b737808531df5a15d21` |

## Independent review and remaining concerns

Read-only review confirms that the smoke success predicate is assembled from
authoritative lifecycle, candidate, check, completion, and ownership facts;
the public explanation is not an independent success flag. The old legacy
qualification identity remains explicit, and the joined decision-v1 model
continues to distinguish intentionally unexecuted isolated nodes from
unfinished joined work. No model reliability claim is made. The complete
repository gate remains the Slice 6F handoff gate.
