# Slice 6E implementation ledger

> Historical implementation pass. The September 15 integrated review found
> required gaps; [the final closure ledger](slice-6f-final-review.md) supersedes
> the completion status and qualification claims below. Original evidence is preserved.

Status: validated. This slice prepares a fixed, operator-gated model
evaluation manifest. It must not run a model, start a server, activate a run,
resume historical work, or authorize paid execution by itself.

## Functional requirements

| ID | Requirement | Acceptance/evidence | Status | Remaining gap |
|---|---|---|---|---|
| S6E-1 | A fixed decision-v1 evaluation card uses the representative product cases and existing model/runner carriers. | `canonical_decision_v1_model_evaluation_manifest()` and `slice-6e-evaluation-manifest.json` round-trip through the typed owner with single-batch, dependent-batch, correction, plan-amendment and verifier-negative cases plus the Luna/Codex Server arm. | validated | None. |
| S6E-2 | Every case and the batch have explicit budgets and stop rules. | Typed per-case limits are one execution, two rejected answers and 180 seconds; total limits are 5, 10 and 900 seconds; automatic retry, false acceptance, unexpected outcome and missing evidence stop the batch. | validated | None. |
| S6E-3 | Evaluation accounting is truthful and does not infer reliability from a small sample. | `ReliablePlanEvaluationReport` derives count/denominator metrics, counts failed attempts, and returns `None` for missing latency, token, action, duration or cost telemetry. No reliability percentage is defined. | validated | None. |
| S6E-4 | Paid execution requires explicit operator authorization outside the prepared public manifest. | The prepared manifest has an immutable `operator_authorization_required: true` marker and no authorization state or paid runner; no model, server or paid batch was run. | validated | Slice 6F may provide final handoff only after independent review. |

## Baseline

Worktree: `/Users/peter/code/task-world/worktrees/recovery-stabilization`.

`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_reliable_plan_product_path_qualification.py::test_joined_decision_v1_correction_and_failure_cases_are_bounded --override-ini='addopts=' --tb=short`

Result: 13 passed, 1 configured slow test skipped in 0.33s. Existing reviewed
Slice 6A–6D changes are preserved.

## Starting hashes

| File | SHA-256 |
|---|---|
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `ac69a694f6f1f33b4e59562f62c48f15a10133427f61541ed84653db8b0670f5` |
| `src/orchestrator/graph/__init__.py` | `bb22073d535ee606147735b742b5d6f8e625705b9d67e71e3a63e03d45db34ef` |
| `tests/unit/test_reliable_plan_evaluation.py` | `78f4535af2ff8210e916f0959c4b798a4593810c69161211ca1d8df2a4708dce` |

## Scope decisions

- The manifest is preparation evidence, not a model-reliability result and not
  a paid-run authorization.
- The fixed denominator is the five declared cases. No aggregate reliability
  percentage is exposed; counts and denominators remain reviewable.
- Missing per-attempt usage, cost, or latency is represented as unknown rather
  than zero. Failed attempts remain part of the accounting denominator.

## Implementation and validation log

- Behavior-first test run before implementation: collection failed because the
  new report and manifest exports did not yet exist (`ImportError`), as expected.
- Focused implementation regression:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py --override-ini='addopts=' --tb=short` — 17 passed.
- Integrated regression:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_recovery_deterministic_lifecycle.py tests/integration/test_reliable_plan_product_path_qualification.py --override-ini='addopts=' --tb=short` — 29 passed in 52.06s.
- Public artifact and canonical owner round-trip:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -c '...'` — `manifest round trip: passed`.
- Static checks:
  focused Pyright — 0 errors, 0 warnings; focused Ruff check and format check
  — passed; graph projection boundary check — passed (`files_checked=254`);
  `git diff --check` — passed.

## Final hashes and changed files

| File | SHA-256 |
|---|---|
| `docs/ARCHITECTURE.md` | `afa08bff75f486c5715968fe644692d31fa2b198bfbd9b355ca6c94193d46dbd` |
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `da5fce252bccd26e6a4c8f94d4260c6a804ce76c510d584a72f4876ad1913c69` |
| `src/orchestrator/graph/__init__.py` | `488a23634129ec5bf4d67443916ea089d406bd01103bc801d1c0b95f68363dab` |
| `tests/unit/test_reliable_plan_evaluation.py` | `3c77d411f6ff668e0e23f965ea7283aa7c4c995eb30a2e8de6608e8b0df37f67` |
| `docs/intent/31-decision-runtime/slice-6e-evaluation-manifest.json` | `2695a84eaee702d5b14c4e6d0e7618fe1ef84e15c02d96c565fce0a3f6aecd92` |

## Independent review and remaining concerns

Read-only review confirms that model/runner assignments reuse the existing
typed arm carrier, the five-case denominator is fixed, budgets are checked at
case and batch level, failed attempts remain counted, and missing telemetry is
not coerced to zero. The report exposes counts and denominators only; it makes
no reliability claim. Existing Slice 6A–6D changes and historical evidence are
preserved. No paid execution, live server, activation, historical resume or
full repository gate was run; the complete gate remains Slice 6F work.
