# Task 18 Report: Final Gates and Human Checkpoint

## Final state

`complete-blocked`. This is mechanical: 9 canonical conflicts are unresolved, Q-1 through Q-5 are open and blocking, and 57 capability classifications remain `unknown`. No unresolved fact was promoted.

## Publication

- Review path: `research/ui-foundation/reviews/phase-3-reality-capability-01.html`
- Review batches: 1
- Review items: 5, ordered `Q-5`, `Q-4`, `Q-1`, `Q-2`, `Q-3`
- Active evidence snapshot: `snapshot-2026-07-26-task-18-phase-3-final`
- Snapshot declaration: one append-only child snapshot after formatting; it records the five stable tracked changes (`.superpowers/sdd/progress.md`, `research/ui-foundation/index.md`, `research/ui-foundation/status.md`, `research/ui-foundation/tools/validate.py`, and `tests/integration/test_ui_foundation_tools.py`) and explicitly includes the required generated manifests `research/ui-foundation/catalog/status-test-nodes.yaml` and `research/ui-foundation/catalog/status-evidence-reviews.yaml`.

## Counts

- Entities: 30; relationships: 35; states: 74; actions: 86.
- Capabilities: 132 (1 current, 0 derived, 25 proposed, 49 gap, 57 unknown).
- Derivations: 0; conflicts: 9 unresolved; questions: 7 total / 5 open blocking; review items: 5.

## Required human decisions

1. Settle product-role authorization and per-action authority (`Q-5`).
2. Settle the live-WAL-safe backup and replay contract (`Q-4`).
3. Choose the canonical persisted attempt identity (`Q-1`).
4. Define typed cross-mode conversion and selection contracts (`Q-2`).
5. Reconcile JSONL documentation with executable SQL authority (`Q-3`).

## Verification

```text
uv run python research/ui-foundation/tools/validate.py --phase 3
exit 0 (no output)

uv run pytest tests/integration/test_ui_foundation_tools.py -v
268 passed in 1125.77s (0:18:45)

npm --prefix ui run test:e2e -- tests/e2e/ui-foundation-review.spec.ts
5 passed (4.8s)

uv run pytest tests/integration/test_ui_foundation_review_tools.py -v
22 passed in 3.95s

uv run ruff check research/ui-foundation/tools/build_review.py research/ui-foundation/tools/validate.py tests/integration/test_ui_foundation_review_tools.py tests/integration/test_ui_foundation_tools.py
All checks passed!

uv run pyright research/ui-foundation/tools/build_review.py tests/integration/test_ui_foundation_review_tools.py
0 errors, 0 warnings, 0 informations

npm --prefix ui run lint && npm --prefix ui run typecheck
eslint .; tsc -b; exit 0
```
