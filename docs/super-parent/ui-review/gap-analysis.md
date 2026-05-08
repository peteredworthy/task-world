# Gap Analysis

## Highest Priority

1. Parent/child hierarchy is not visible on the dashboard.

   Child runs appear as ordinary top-level runs, so users must manually infer relationships. The dashboard should group children under parents or provide a parent mission view that makes hierarchy the default.

2. Parent mission state is mostly hidden.

   The model has `current_understanding`, `target_inventory`, decisions, slices, and terminal blockers. The UI shows only a small oversight summary, so users cannot see what the parent believes, what remains unresolved, or why a next action is recommended.

3. Attention and completion blockers are not first-class.

   The "Needs Input" dashboard filter does not include oversight attention, stalled slices, illegal state reasons, or terminal guard blockers. This means a parent can require action while the dashboard does not classify it as needing input.

4. Child acceptance lacks evidence context.

   The accept path exists, but the UI does not put evidence outcome, test commands, changed files, open uncertainties, target inventory impact, and merge risk into one decision surface.

## Medium Priority

5. Super Parent creation is generic.

   The routine is selected like any other routine. A focused intake would make the parent mission clearer: mission instruction, source artifacts, child budget, expected evidence, and completion policy.

6. Child detail does not explain parent intent.

   The child banner links to the parent and shows a slice ID, but the page does not explain the slice goal, affected inventory, expected evidence, or acceptance consequences.

7. Oversight freshness is unclear.

   The UI renders persisted oversight state and offers manual refresh, but it does not clearly show when the snapshot was computed, whether it reflects the live run status, or whether it may be stale.

8. Final validation/reporting is absent.

   The routine expects final validation and a report. The UI does not expose a final validation panel or review-ready completion artifact.

## Iteration Candidates

- Add a parent mission dashboard row with child grouping and status rollup.
- Add a dedicated parent workspace with tabs: Understanding, Inventory, Children, Decisions, Evidence, Validation.
- Extend dashboard attention filtering to include oversight attention and terminal guard blockers.
- Add a child context panel that shows parent slice purpose and expected evidence.
- Add an accept/reject modal that summarizes evidence, merge impact, inventory impact, and unresolved questions.
- Add timestamp/freshness metadata for oversight snapshots.
- Add a final report panel once `final_validation` exists.

## Design Constraint To Preserve

Destructive or irreversible actions, including reject/abandon/reset-style actions, should use modal confirmation. Compact rows should use a three-dot action menu rather than inline confirm/cancel controls.
