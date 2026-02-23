# Step 10: Merge Readiness Gating + Final Merge

Implement the merge readiness system that gates the final merge-back action. A persistent bar at the bottom of the Review & Merge tab shows all gate statuses and only enables the merge button when every condition is satisfied. The merge confirmation modal lets the user choose between squash merge and merge commit strategies.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Merge readiness bar shows all gate statuses and disables final merge when gates are not met. "Commit Merge Back" is only enabled when all readiness gates pass; it merges the run branch back to the target. Confirmation modal offers merge strategy choice.

**Functionality to Produce**:
- `GET /api/runs/{id}/review/merge-readiness` endpoint computing all gate statuses
- Enhanced `POST /api/runs/{id}/merge-back` with pre-flight readiness check and strategy parameter
- `MergeReadinessBar` sticky component with gate indicators and merge CTA
- Merge confirmation modal with squash (default) and merge commit options
- `useMergeReadiness()` hook with invalidation on related mutations
- Server-side readiness enforcement

**Final Verification Criteria**:
- Merge readiness endpoint returns correct gate statuses
- Merge button disabled when any gate fails
- Merge button enabled when all gates pass
- Confirmation modal shows merge strategy options
- Server-side readiness check prevents merge with unmet gates
- Readiness bar auto-updates after state-changing operations

---

## Task 1: Add Merge Readiness Backend Endpoint

**Description**: Create the merge readiness computation endpoint and enhance the merge-back endpoint with strategy and pre-flight check.

**Implementation Plan (Do These Steps)**

- [ ] Add `MergeReadiness` and `Gate` schemas to `src/orchestrator/api/schemas/review.py`:

```python
class Gate(BaseModel):
    name: str
    status: str  # "pass" | "fail" | "pending"
    description: str

class MergeReadiness(BaseModel):
    ready: bool
    gates: list[Gate]
```

- [ ] Implement `ReviewService.compute_readiness()` (or standalone function) that evaluates gates:
  - `clean_merge` — merge prediction is clean (no predicted conflicts)
  - `no_unresolved_conflicts` — no unresolved merge conflicts exist
  - `tests_pass` — most recent test run passed (or no tests configured)
  - `no_active_jobs` — no agent jobs currently running

- [ ] Add `GET /api/runs/{run_id}/review/merge-readiness` endpoint to review router

- [ ] Enhance `merge_back()` in `src/orchestrator/git/branch_ops.py`:
  - Accept `strategy` parameter: `"squash"` or `"merge"`
  - Squash: use `git merge --squash` followed by `git commit`
  - Merge: use `git merge --no-ff` (existing behavior)

- [ ] Add pre-flight readiness check to the merge-back API endpoint (return 409 if gates not met)

**References**
- `src/orchestrator/git/branch_ops.py` — `merge_back()` to enhance
- `docs/git-ops/clarifications.md` — Q3: user chooses merge strategy (squash default)
- `docs/git-ops/step-10-plan.md` — Tasks 1, 2, 3

**Functionality (Expected Outcomes)**
- [ ] Merge readiness endpoint returns correct gate statuses
- [ ] Merge-back accepts strategy parameter
- [ ] Server-side pre-flight check prevents merge with unmet gates

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/branch_ops.py src/orchestrator/api/routers/review.py` — no type errors

---

## Task 2: Create MergeReadinessBar Frontend Component

**Description**: Create the sticky bottom bar showing gate statuses and the merge CTA button.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/MergeReadinessBar.tsx`:
  - Sticky bar at the bottom of the Review & Merge tab
  - Gate indicators: green check (pass), red X (fail), spinner (pending)
  - Each gate shows name and description
  - "Commit Merge Back" button: disabled with tooltip when gates unmet, enabled when all pass
  - Click opens merge confirmation modal

- [ ] Add `useMergeReadiness()` hook to `ui/src/hooks/useReview.ts`:
  - Fetches merge readiness from backend
  - Invalidated on: prune apply, test completion, conflict resolution, agent completion, back merge

- [ ] Add API client function to `ui/src/api/reviewClient.ts`:

```typescript
export async function getMergeReadiness(runId: string): Promise<MergeReadiness> { ... }
```

**References**
- `docs/git-ops/step-10-plan.md` — Tasks 4, 5, 7
- `docs/git-ops/architecture.md` — MergeReadinessBar spec

**Functionality (Expected Outcomes)**
- [ ] Bar shows current gate statuses
- [ ] Button state reflects gate pass/fail
- [ ] Readiness refreshes on related mutations

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create Merge Confirmation Modal and Wire into ReviewMergeTab

**Description**: Create the merge confirmation modal with strategy selection and integrate the readiness bar into the tab.

**Implementation Plan (Do These Steps)**

- [ ] Add merge strategy selector to the merge confirmation modal:
  - Radio buttons: "Squash merge (recommended)" and "Merge commit"
  - Default selection: squash
  - "Merge" confirmation button
  - Loading state during merge execution
  - Success state with link to target branch
  - Error state with details

- [ ] Wire `MergeReadinessBar` into `ReviewMergeTab.tsx`:
  - Add as sticky bottom element
  - Connect merge button click to confirmation modal
  - Handle post-merge success state

- [ ] Ensure invalidation chain works:
  - Prune apply → invalidate merge readiness
  - Test completion → invalidate merge readiness
  - Conflict resolution → invalidate merge readiness
  - Agent completion → invalidate merge readiness
  - Back merge → invalidate merge readiness

**Dependencies**
- [ ] Tasks 1-2 must be complete

**References**
- `docs/git-ops/clarifications.md` — Q3: squash default, merge commit option
- `docs/git-ops/step-10-plan.md` — Tasks 6, 8

**Functionality (Expected Outcomes)**
- [ ] Confirmation modal shows merge strategy options
- [ ] Merge executes with selected strategy
- [ ] Readiness bar updates automatically after all state-changing operations

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors

---

## Task 4: Write Merge Readiness Integration Tests

**Description**: Write integration tests for the merge readiness endpoint across various states.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/integration/test_review_merge_readiness.py`:
  - `test_merge_readiness_all_pass` — clean state returns ready=true with all gates passing
  - `test_merge_readiness_conflicts_fail` — unresolved conflicts fail the gate
  - `test_merge_readiness_tests_fail` — failed test run fails the gate
  - `test_merge_back_with_strategy_squash` — squash merge creates single commit
  - `test_merge_back_with_strategy_merge` — merge commit preserves history
  - `test_merge_back_rejects_unmet_gates` — 409 when gates not met

**References**
- `docs/git-ops/step-10-plan.md` — Tasks 9, 10

**Functionality (Expected Outcomes)**
- [ ] Integration tests verify gate computation across various states
- [ ] Merge strategy selection produces correct git behavior
- [ ] Server-side enforcement tested

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_review_merge_readiness.py -v` — all tests pass (verify test count > 0)
