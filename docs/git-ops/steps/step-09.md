# Step 9: Frontend Back Merge + Conflict Resolver

Implement the back merge UI and interactive conflict resolution experience. Users can pull the latest target branch into the run branch, see a post-merge review banner for clean merges, and resolve any conflicts through a dedicated near full-screen resolver dialog.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Back merge action merges target branch into run branch with confirmation modal and impact summary. Conflict resolver displays conflict blocks with keep-ours/keep-theirs/manual-selection actions per block. "Use Agent to Resolve Conflicts" dispatches agent work scoped to unresolved conflicts.

**Functionality to Produce**:
- `BackMergeModal` confirmation dialog with branch info and predicted conflicts
- `BackMergeBanner` post-merge review banner with undo option
- `ConflictFileList` in left rail with unresolved/resolved status
- `ConflictResolverDialog` near full-screen overlay for resolving conflicts
- `ConflictBlock` component with ours/theirs display and per-block actions
- `AgentResolveConflictsModal` for dispatching agent resolution
- TanStack Query hooks for all conflict operations

**Final Verification Criteria**:
- Back merge confirmation modal shows correct branch info
- Clean merge shows review banner with undo button
- Conflict files display in left rail with status chips
- Conflict resolver shows ours/theirs blocks with action buttons
- Resolution updates status and decrements unresolved count
- Agent resolve modal defaults to run's agent with Advanced toggle

---

## Task 1: Create BackMergeModal and BackMergeBanner

**Description**: Create the back merge confirmation modal and post-merge review banner.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/BackMergeModal.tsx`:
  - Modal overlay showing source branch (target) and destination branch (run branch)
  - Display predicted conflict count from branch status
  - "Confirm" button triggers `POST /api/runs/{id}/back-merge`
  - Loading state during merge
  - Error state if merge fails

- [ ] Create `ui/src/components/review/BackMergeBanner.tsx`:
  - Banner displayed after successful clean merge
  - Shows merge commit SHA
  - "Undo" button triggers `POST /api/runs/{id}/review/revert-back-merge`
  - Banner dismisses after undo or manual dismissal

- [ ] Add API client functions to `ui/src/api/reviewClient.ts`:

```typescript
export async function getConflicts(runId: string): Promise<ConflictFile[]> { ... }
export async function resolveConflict(runId: string, filePath: string, resolutions: BlockResolution[]): Promise<ConflictResolutionResponse> { ... }
export async function agentResolveConflicts(runId: string, agentType?: string): Promise<AgentJobResponse> { ... }
export async function revertBackMerge(runId: string): Promise<RevertBackMergeResponse> { ... }
```

- [ ] Add TanStack Query hooks to `ui/src/hooks/useReview.ts`:

```typescript
export function useConflicts(runId: string) { ... }
export function useResolveConflict(runId: string) { ... }
export function useAgentResolveConflicts(runId: string) { ... }
export function useRevertBackMerge(runId: string) { ... }
```

**References**
- `docs/git-ops/step-09-plan.md` — Tasks 1, 2, 7, 8
- `docs/git-ops/clarifications.md` — Q6: auto-commit clean merges with undo banner

**Functionality (Expected Outcomes)**
- [ ] Back merge modal shows branch info and triggers merge
- [ ] Banner appears after clean merge with undo action
- [ ] Undo reverts the merge commit

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 2: Create ConflictFileList Component

**Description**: Create the conflict files section in the left rail with status chips.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/ConflictFileList.tsx`:
  - Section header "Conflicts (N)"
  - List of conflict files with unresolved/resolved status chips
  - Unresolved: red chip, Resolved: green chip
  - Clicking a file opens the conflict resolver dialog
  - Hidden when there are no conflicts

**References**
- `docs/git-ops/step-09-plan.md` — Task 3

**Functionality (Expected Outcomes)**
- [ ] Conflict files listed with correct status
- [ ] Status updates as conflicts are resolved
- [ ] Section hidden when no conflicts exist

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create ConflictResolverDialog and ConflictBlock

**Description**: Create the near full-screen conflict resolution dialog with per-block ours/theirs/manual actions.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/ConflictBlock.tsx`:
  - Display ours content with warm tinting (left/top)
  - Display theirs content with cool tinting (right/bottom)
  - Per-block action buttons: "Keep Run (ours)", "Keep Target (theirs)", "Manual Selection"
  - "Manual Selection" opens inline editor for custom content
  - Block resolved state indicator

- [ ] Create `ui/src/components/review/ConflictResolverDialog.tsx`:
  - Near full-screen overlay (similar pattern to DiffDialog)
  - File name in header
  - List of `ConflictBlock` components for the file
  - "Mark File Resolved" button (enabled when all blocks resolved)
  - Prev/next file navigation between conflict files
  - Merge readiness indicator updates as conflicts are resolved
  - Close button

**Dependencies**
- [ ] Task 2 must be complete (ConflictFileList exists for navigation)

**References**
- `ui/src/components/review/DiffDialog.tsx` — pattern for near full-screen overlay
- `docs/git-ops/step-09-plan.md` — Tasks 4, 5

**Functionality (Expected Outcomes)**
- [ ] Conflict blocks display ours/theirs content with distinct styling
- [ ] Per-block actions correctly set resolution choice
- [ ] "Mark File Resolved" triggers resolution API call
- [ ] Prev/next navigates between conflict files

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 4: Create AgentResolveConflictsModal and Wire into ReviewMergeTab

**Description**: Create the agent dispatch modal for conflict resolution and integrate all conflict components into the review tab.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/AgentResolveConflictsModal.tsx`:
  - Modal with scope description ("Resolve N unresolved conflicts")
  - Default: shows run's configured agent
  - "Advanced" toggle reveals agent picker for override
  - "Confirm" dispatches agent
  - Progress indicator while agent is working
  - On completion: invalidate conflicts, diff files queries

- [ ] Wire into `ReviewMergeTab.tsx`:
  - Add `ConflictFileList` to left rail (below file list, above test panel)
  - Add "Back Merge" button to tab header
  - Add state management for BackMergeModal, BackMergeBanner, ConflictResolverDialog, AgentResolveConflictsModal
  - Show BackMergeBanner after clean merge
  - Show ConflictFileList when conflicts exist

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/git-ops/clarifications.md` — Q1: agent defaults with Advanced toggle
- `docs/git-ops/step-09-plan.md` — Tasks 6, 9

**Functionality (Expected Outcomes)**
- [ ] Agent resolve modal dispatches agent with correct configuration
- [ ] All conflict components integrated into the review tab layout
- [ ] Full back merge flow: confirm → merge → resolve conflicts (or see clean banner) → merge readiness updates

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
