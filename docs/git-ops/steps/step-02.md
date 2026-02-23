# Step 2: Frontend Review & Merge Tab Skeleton + Branch Status Panel

Create the foundational frontend surface for the Review & Merge workbench. This step adds a new tab to the RunDetail page that renders when the run has an active worktree (regardless of run status). The tab contains a left rail layout with branch status information and a modified files list.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Run detail page has a "Review & Merge" tab with branch status summary, file lists, and worktree path with copy action.

**Functionality to Produce**:
- `ReviewMergeTab` component rendered as a new tab on `RunDetail.tsx`
- `BranchStatusSection` showing branch name, target branch, SHAs, ahead/behind counts, worktree path with copy-to-clipboard
- `FileListSection` showing modified files with change stats and status icons
- Tab only visible when the run has a worktree (any run status)
- API client functions and TanStack Query hooks for review endpoints

**Final Verification Criteria**:
- Tab renders on run detail page for runs with worktrees
- Tab does NOT render for runs without worktrees
- Branch status displays correct data
- File list populates with correct entries
- TypeScript compiles without errors
- Frontend builds without errors

---

## Task 1: Create TypeScript Types and API Client

**Description**: Create TypeScript type definitions matching backend review schemas and API client functions for the review endpoints.

**Implementation Plan (Do These Steps)**

Types and API client are created first so subsequent components can import them immediately.

- [ ] Create `ui/src/types/review.ts` with TypeScript types:

```typescript
// Types matching backend schemas
export interface DiffResponse {
  diff_text: string;
  scope: string;
  base_ref: string;
  head_ref: string;
  file_count: number;
}

export interface DiffFileEntry {
  path: string;
  status: "added" | "modified" | "deleted" | "renamed";
  additions: number;
  deletions: number;
  tasks: string[];
}

export interface CommitEntry {
  sha: string;
  short_sha: string;
  message: string;
  author: string;
  timestamp: string;
  badges: string[];
}
```

- [ ] Create `ui/src/api/reviewClient.ts` with API client functions:

```typescript
export async function getDiffFiles(runId: string): Promise<DiffFileEntry[]> { ... }
export async function getCommits(runId: string): Promise<CommitEntry[]> { ... }
export async function getDiff(runId: string, scope: string, ref?: string): Promise<DiffResponse> { ... }
```

**References**
- `ui/src/api/client.ts` — existing API client patterns
- `src/orchestrator/api/schemas/review.py` — backend schemas to match
- `docs/git-ops/step-02-plan.md` — Tasks 1, 3

**Functionality (Expected Outcomes)**
- [ ] TypeScript types are defined and importable
- [ ] API client functions correctly call backend endpoints

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors in new files

---

## Task 2: Create TanStack Query Hooks

**Description**: Create TanStack Query hooks for fetching review data from the backend.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/hooks/useReview.ts` with hooks:

```typescript
export function useDiffFiles(runId: string) { ... }
export function useCommits(runId: string) { ... }
// Enhanced branch status hook that includes new merge readiness fields
```

- [ ] Follow patterns from `ui/src/hooks/useApi.ts`
- [ ] Configure appropriate stale times and error handling

**Dependencies**
- [ ] Task 1 must be complete (types and API client exist)

**References**
- `ui/src/hooks/useApi.ts` — existing TanStack Query patterns
- `docs/git-ops/step-02-plan.md` — Task 2

**Functionality (Expected Outcomes)**
- [ ] `useDiffFiles()` fetches and returns file list data
- [ ] `useCommits()` fetches and returns commit history data
- [ ] Hooks handle loading, error, and success states

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create BranchStatusSection Component

**Description**: Create the branch status display component for the Review & Merge tab left rail.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/BranchStatusSection.tsx`:
  - Display branch name, target branch, base/head SHAs
  - Display ahead/behind counts
  - Display worktree path with copy-to-clipboard button
  - Use data from the existing `useBranchStatus()` hook (enhanced with new fields)

**References**
- `ui/src/components/detail/BranchStatusPanel.tsx` — existing branch status component (pattern reference)
- `docs/git-ops/step-02-plan.md` — Task 5

**Functionality (Expected Outcomes)**
- [ ] Component renders branch summary information
- [ ] Copy-to-clipboard button copies worktree path

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 4: Create FileListSection Component

**Description**: Create the modified files list component showing files with change stats and status icons.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/FileListSection.tsx`:
  - Render list of modified files from `useDiffFiles()` hook
  - Show file status icon (added/modified/deleted)
  - Show addition/deletion line counts
  - Handle empty state: "No changes to review"
  - Each file item is clickable (click handler prop for opening diff dialog in later steps)

**Dependencies**
- [ ] Tasks 1-2 must be complete (types, API client, hooks)

**References**
- `docs/git-ops/step-02-plan.md` — Task 6

**Functionality (Expected Outcomes)**
- [ ] File list renders with correct file names, status icons, and +/- counts
- [ ] Empty state shows appropriate message

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 5: Create ReviewMergeTab and Add to RunDetail

**Description**: Create the top-level ReviewMergeTab component and add it as a tab on the RunDetail page. The tab should only be visible when the run has an active worktree.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/ReviewMergeTab.tsx`:
  - Left rail + main panel layout
  - Render `BranchStatusSection` and `FileListSection` in the left rail
  - Placeholder sections for conflicts, history, and tasks (filled in later steps)

- [ ] Modify `ui/src/pages/RunDetail.tsx`:
  - Add "Review & Merge" tab to the tab bar
  - Only render the tab when the run has a worktree (check worktree path exists)
  - Render `ReviewMergeTab` when the tab is selected

**Dependencies**
- [ ] Tasks 3-4 must be complete (BranchStatusSection and FileListSection exist)

**References**
- `ui/src/pages/RunDetail.tsx` — existing run detail page
- `docs/git-ops/step-02-plan.md` — Tasks 4, 7
- `docs/git-ops/clarifications.md` — Q4: tab available on any run status as long as worktree exists

**Constraints**
- [ ] Tab must be visible for runs in any status (active, completed, failed) as long as worktree exists
- [ ] Tab must NOT be visible for runs without a worktree

**Functionality (Expected Outcomes)**
- [ ] "Review & Merge" tab appears on run detail page for runs with worktrees
- [ ] Tab does NOT appear for runs without worktrees
- [ ] Tab renders branch status and file list when selected

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
