# Slice 6C implementation ledger

> Historical implementation pass. The September 15 integrated review found
> required gaps; [the final closure ledger](slice-6f-final-review.md) supersedes
> the completion status and qualification claims below. Original evidence is preserved.

Status: in progress. This ledger records the joined deterministic correction
and failure cases added after the Slice 6A qualification identity work. It does
not authorize a model call, live activation, historical-run resume, or paid
probe.

## Functional requirements

| ID | Requirement | Acceptance/evidence | Status | Remaining gap |
|---|---|---|---|---|
| S6C-1 | A joined corrective cycle is evidence-backed and bounded. | `run_reliable_plan_joined_cases` exercises the production controller correction path and records accepted/rejected snapshot lineage with no false acceptance. | validated | No model reliability claim; deterministic only. |
| S6C-2 | Blocked decisions stop work and record intervention. | Joined blocked cases preserve durable operator-visible incompleteness/intervention evidence and declare the blocked outcome without false acceptance. | validated | Human action remains an operator concern. |
| S6C-3 | Cancellation and restart preserve terminal ownership and evidence. | The cancellation/restart case issues the durable cancel transition, reconstructs a fresh controller, reads `cancelled`, records lease revocation, and has zero active/suspended leases. | validated | No live server or historical resume. |
| S6C-4 | Defective candidates and verifier negatives fail closed. | Defective-candidate and defective-verifier cases exercise missing mandatory verification and missing-callback recovery; the result asserts blocked outcomes and `false_acceptance == false`. | validated | These are deterministic controller negatives, not paid model outcomes. |
| S6C-5 | Contract compatibility remains explicit. | Generated decision-v1 schema/compiler identity is frozen in the six-case manifest; legacy qualification JSON/hash round-trips unchanged; mismatched receipt identity is rejected. | validated | Unsupported runner behavior remains covered by existing runtime tests. |

## Baseline

Worktree: `/Users/peter/code/task-world/worktrees/recovery-stabilization`

- Existing worktree changes are the reviewed Slice 6A implementation and are
  preserved. No tracked files were restored.
- Baseline focused command:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_recovery_deterministic_lifecycle.py --override-ini='addopts=' --tb=short`
- Baseline result: passed (11 tests; graph boundary hook also passed).
- No live server, activation, historical result rewrite, model evaluation, or
  paid execution was performed.

## Starting source hashes

These hashes are recorded before Slice 6C edits. Slice 6A files already include
their uncommitted final hashes from the preceding ledger.

| File | SHA-256 |
|---|---|
| `docs/intent/31-decision-runtime/implementation.md` | `834ed9d5c286a8ecf2743641679b292ad4c8fcec021764e52acd63d27dcbbc6a` |
| `docs/intent/31-decision-runtime/architecture.md` | `367e1e41c7444e55cd34663c40765fbf03eb9b071a6077c232eeed91dac81512` |
| `docs/intent/31-decision-runtime/contracts.md` | `1bdb7e11ffcdd0a9d4293fe021744f6e29696f1d0b1e49df8d96eb5fa12e19d8` |
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `a3759b2c2055dd59b419877c0096bc32a8a953b5b4c811d457709d29973ab90b` |
| `src/orchestrator/graph_runtime/reliable_plan_scenarios.py` | `c35b898cdce3f6959758673c28a0ee300d624186a5f2228f04d472549c60d897` |
| `tests/integration/test_graph_decision_runtime.py` | `16f722e3117b89fe8c0d72fe360c7530fc87a86a73b1ecd75b92f6e881b6b973` |
| `tests/integration/test_decision_recovery_crash_matrix.py` | `879c9ac195d5a86ba3e5023c0903bb9adecdb6cf70ba23f342ec610374b180a8` |

## Decisions

- The historical ten-scenario qualification manifest remains unchanged. Slice
  6C evidence uses a separate joined-case manifest and identity so it cannot
  silently turn isolated legacy or qualification probes into joined proof.
- Joined results distinguish `unexecuted_node_ids` (not applicable to an
  isolated case) from `unfinished_node_ids` (a failed joined execution).
- Compatibility is checked from the trusted frozen contract identity and
  public serialized round trips; it is not inferred from a model answer.

## Validation log

- `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_reliable_plan_product_path_qualification.py::test_joined_decision_v1_correction_and_failure_cases_are_bounded --override-ini='addopts=' --tb=short` — 13 passed, 1 repository-slow test skipped in 0.41s; the slow case was then run explicitly.
- `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q -n 0 tests/integration/test_reliable_plan_product_path_qualification.py::test_joined_decision_v1_correction_and_failure_cases_are_bounded --override-ini='addopts=' --tb=short` — 1 passed in 2.52s.
- `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q -n 0 tests/integration/test_reliable_plan_product_path_qualification.py tests/integration/test_recovery_deterministic_lifecycle.py --override-ini='addopts=' --tb=short` — 12 passed in 54.54s.
- `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_graph_decision_runtime.py tests/integration/test_decision_recovery_crash_matrix.py --override-ini='addopts=' --tb=short` — 80 passed, 9 warnings in 305.38s.
- Ruff check and format check passed for all changed source/test files.
- Focused Pyright passed with 0 errors and 0 warnings.
- `git diff --check` passed; public import smoke loaded the six-case manifest and joined runner.

## Final hashes and changed files

| File | Final SHA-256 |
|---|---|
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `ac69a694f6f1f33b4e59562f62c48f15a10133427f61541ed84653db8b0670f5` |
| `src/orchestrator/graph_runtime/reliable_plan_scenarios.py` | `79e6c5953c1b87d5c8b0f54b528ec77eb613b1b6bb44d5bec806dfff20632946` |
| `src/orchestrator/graph_runtime/__init__.py` | `4ef344acfc8e654b07e60eb4a00b9604ae605933baa9161fbd266a7edfe36911` |
| `src/orchestrator/graph/__init__.py` | `bb22073d535ee606147735b742b5d6f8e625705b9d67e71e3a63e03d45db34ef` |
| `tests/unit/test_reliable_plan_evaluation.py` | `78f4535af2ff8210e916f0959c4b798a4593810c69161211ca1d8df2a4708dce` |
| `tests/integration/test_reliable_plan_product_path_qualification.py` | `5b7fcdddfad3dd1976469f13475b896697ec40826b032ead8c3fa93f7cbe224a` |

The implementation adds the six-case typed manifest/observation contract,
public exports, the production-controller joined-case entry point, and focused
unit/integration coverage. It does not alter the historical ten-scenario
qualification gate or run a model.

## Independent review and remaining concerns

Read-only review after the focused regressions found no static or behavioral
regression in the existing decision dispatch/crash matrix. The joined driver is
deterministic and reuses the existing production controller scenario machinery;
it is not evidence of model reliability, live-server behavior, or paid
evaluation. The complete repository gate remains the Slice 6F handoff gate.
