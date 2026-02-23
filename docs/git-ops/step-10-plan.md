# Step 10 Plan: Merge Readiness Gating + Final Merge

## Purpose

Implement the merge readiness system that gates the final merge-back action. A persistent bar at the bottom of the Review & Merge tab shows all gate statuses and only enables the merge button when every condition is satisfied. The merge confirmation modal lets the user choose between squash merge (default) and merge commit strategies.

## Prerequisites

- **Step 5** — Frontend prune mode must exist (prune operations affect readiness state).
- **Step 7** — Frontend test panel must exist (test results are a readiness gate).
- **Step 9** — Frontend conflict resolver must exist (no unresolved conflicts is a readiness gate).

## Functional Contract

### Inputs

- `GET /api/runs/{id}/review/merge-readiness` → fetch all gate statuses
- `POST /api/runs/{id}/merge-back` → enhanced with pre-flight readiness check and merge strategy parameter
- User interaction: view readiness bar, click "Commit Merge Back", select merge strategy in confirmation modal

### Outputs

- `GET /merge-readiness` → `MergeReadiness { ready: bool, gates: list[Gate] }` where `Gate { name: str, status: "pass"|"fail"|"pending", description: str }`. Gates include:
  - `clean_merge` — merge prediction is clean (no predicted conflicts)
  - `no_unresolved_conflicts` — no unresolved merge conflicts exist
  - `tests_pass` — most recent test run passed (or no tests configured)
  - `no_active_jobs` — no agent jobs currently running
- `MergeReadinessBar` component: sticky bar at bottom of Review & Merge tab with gate indicators
- Gate status indicators: green check (pass), red X (fail), spinner (pending) with explanatory text for each
- "Commit Merge Back" button: disabled with tooltip when gates unmet, enabled when all pass
- Merge confirmation modal: merge strategy choice (squash default, merge commit option), final confirmation
- Enhanced `POST /merge-back` accepts `{ strategy: "squash"|"merge" }` and performs pre-flight readiness check server-side
- Readiness auto-refresh: `useMergeReadiness()` hook with TanStack Query invalidation on related mutations (prune, test, back merge, conflict resolution, agent actions)

### Errors

- `GET /merge-readiness` returns gate failures → displayed as individual gate status items
- `POST /merge-back` with unmet gates → `409 Conflict` with gate failure details (server-side enforcement)
- `POST /merge-back` merge execution failure → error toast with git error details
- Merge strategy not supported → `422 Unprocessable Entity`

## Tasks

1. Add `GET /review/merge-readiness` endpoint to review router — computes all gate statuses
2. Implement `ReviewService.compute_readiness()` — evaluates each gate against current state
3. Enhance `merge_back()` in `branch_ops.py` to accept `strategy` parameter (squash or merge commit) and pre-flight readiness check
4. Create `MergeReadiness`, `Gate` schemas in `schemas/review.py`
5. Create `ui/src/components/review/MergeReadinessBar.tsx` — sticky bottom bar with gates and merge CTA
6. Add merge strategy selector to the merge confirmation modal
7. Add `useMergeReadiness()` hook with invalidation on prune/test/conflict/agent mutations
8. Wire readiness bar into ReviewMergeTab layout
9. Write Playwright tests: gating logic, disabled/enabled states, successful merge
10. Write integration tests for merge-readiness endpoint across various states

## Verification

### Auto-Verify

- [ ] `uv run pytest tests/integration/test_review_merge_readiness.py -v` — integration tests pass
- [ ] Playwright test `test_merge_readiness_gating` — merge button disabled when gates unmet, enabled when all green
- [ ] Playwright test `test_final_merge` — all gates green, click merge, verify success
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds

### Manual Verify

- [ ] Readiness bar is sticky at the bottom of the tab and always visible
- [ ] Each gate shows current status with clear icon and explanation
- [ ] "Commit Merge Back" button is disabled with tooltip when any gate fails
- [ ] Button enables when all gates pass
- [ ] Confirmation modal shows squash (default) and merge commit options
- [ ] Squash merge creates a single commit on the target branch
- [ ] Merge commit preserves run branch history
- [ ] Readiness bar updates automatically after prune, test, conflict resolution, and agent actions
- [ ] Server-side readiness check prevents merge even if frontend gates are bypassed

## Context & References

- `src/orchestrator/git/branch_ops.py` — `merge_back()` to enhance with strategy parameter
- `docs/git-ops/clarifications.md` — Q3: user chooses merge strategy (squash default)
- `docs/git-ops/architecture.md` — MergeReadinessBar spec, merge readiness computation
- `ui/src/hooks/useReview.ts` — TanStack Query invalidation patterns
