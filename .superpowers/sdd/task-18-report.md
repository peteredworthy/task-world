# Task 18 Report: Final Gates and Human Checkpoint

## Final state

`complete-blocked`. This is mechanical: 9 canonical conflicts are unresolved, Q-1 through Q-5 are open and blocking, and 57 capability classifications remain `unknown`. The post-merge re-audit refreshed evidence only; no unresolved fact was promoted.

## Publication

- Review path: `research/ui-foundation/reviews/phase-3-reality-capability-01.html`
- Review batches: 1
- Review items: 5, ordered `Q-5`, `Q-4`, `Q-1`, `Q-2`, `Q-3`
- Active evidence snapshot: `snapshot-2026-07-26-post-merge-main`
- Snapshot declaration: one append-only post-merge child snapshot after formatting. It refreshes all drifted current source/test hashes, tombstones the intentionally deleted `tests/integration/test_branch_ops.py` and `tests/integration/test_conflict_back_merge.py`, tombstones the two superseded untracked Task 15 scratch notes, and explicitly declares generated manifests `research/ui-foundation/catalog/status-test-nodes.yaml` and `research/ui-foundation/catalog/status-evidence-reviews.yaml`. Reserved self files remain excluded.

## Counts

- Entities: 30; relationships: 35; states: 74; actions: 86.
- Capabilities: 132 (1 current, 0 derived, 25 proposed, 49 gap, 57 unknown).
- Derivations: 0; conflicts: 9 unresolved; questions: 7 total / 5 open blocking; review items: 5. Post-merge locator mappings: 9 exact consolidated replacements, 2 preserved bounded rows, and 0 capability-classification changes. The collected manifest is 117 bases/nodes with 137 exact and 50 bounded locators.

## Required human decisions

1. Settle product-role authorization and per-action authority (`Q-5`).
2. Settle the live-WAL-safe backup and replay contract (`Q-4`).
3. Choose the canonical persisted attempt identity (`Q-1`).
4. Define typed cross-mode conversion and selection contracts (`Q-2`).
5. Reconcile JSONL documentation with executable SQL authority (`Q-3`).

## Verification

Post-merge verification is recorded after the refreshed snapshot is created. Required gates: Phase 1/2/3 validation, focused foundation and exact review tests, Ruff, Pyright, and UI lint/typecheck.

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
