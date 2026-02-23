# Step 5: Frontend Prune Mode

Implement the interactive prune experience in the Review & Merge workbench. Users can enter a "Prune Mode" that enables selection of unwanted changes at file, hunk, or line granularity directly in the diff viewer. Selected changes can be previewed and applied with confirmation, creating a prune commit on the run branch.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Prune mode allows selecting files, hunks, and lines for removal with preview modal and apply confirmation. Prune operations are recorded in run events and visible in activity timeline.

**Functionality to Produce**:
- `PruneModeProvider` context managing selection state
- `PruneToolbar` banner indicating prune mode is active with selection count
- `PruneGutter` cells with hunk/line checkboxes in `react-diff-view` gutter
- File-level "Prune File" action in file list context menu
- `PrunePreviewModal` showing summary and resulting diff
- Apply confirmation with post-apply toast and query invalidation
- TanStack Query mutations for prune operations

**Final Verification Criteria**:
- Prune mode toggles on/off with visible banner
- Gutter checkboxes appear/disappear with prune mode
- Hunk and line selection works in the diff viewer
- File-level prune via context menu works
- Preview modal shows accurate summary
- Apply creates a commit and refreshes the diff

---

## Task 1: Create PruneModeProvider Context

**Description**: Create the React context provider that manages prune selection state across the review tab.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/PruneModeProvider.tsx`:
  - Context with state: `isPruneMode`, `selectedFiles`, `selectedHunks`, `selectedLines`
  - Methods: `togglePruneMode()`, `selectHunk()`, `deselectHunk()`, `selectLine()`, `deselectLine()`, `selectFile()`, `clearSelections()`
  - Compute `PruneSelection` object from current selections for API calls
  - Track selection count for display in toolbar

**References**
- `docs/git-ops/step-05-plan.md` — Task 1
- `docs/git-ops/architecture.md` — PruneModeProvider spec

**Functionality (Expected Outcomes)**
- [ ] Context provides prune mode state and selection management to child components
- [ ] Selection state tracks files, hunks, and lines independently

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 2: Create PruneGutter and PruneToolbar Components

**Description**: Create the custom gutter cells for diff viewer selection and the prune mode toolbar banner.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/PruneGutter.tsx`:
  - Custom gutter renderer for `react-diff-view`
  - Hunk-level checkboxes at the start of each hunk
  - Line-level checkboxes for individual lines when hunk is partially selected
  - Uses `PruneModeProvider` context for state

- [ ] Create `ui/src/components/review/PruneToolbar.tsx`:
  - Banner displayed at top of diff area when prune mode is active
  - Shows selection count (N files, N hunks, N lines)
  - "Preview" button (opens preview modal)
  - "Cancel" button (exits prune mode and clears selections)

**Dependencies**
- [ ] Task 1 must be complete (PruneModeProvider exists)

**References**
- `react-diff-view` documentation — custom gutter cells
- `docs/git-ops/step-05-plan.md` — Tasks 2, 3

**Functionality (Expected Outcomes)**
- [ ] Gutter checkboxes appear in diff viewer when prune mode is active
- [ ] Toolbar shows selection count and action buttons
- [ ] Checkbox interactions update selection state correctly

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create PrunePreviewModal and Add API Mutations

**Description**: Create the preview modal that shows a summary of what will be pruned, with an apply confirmation button. Add TanStack Query mutations for prune operations.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/PrunePreviewModal.tsx`:
  - Modal overlay showing prune summary (files affected, hunks/lines removed)
  - Resulting diff preview (fetched from backend)
  - "Apply" confirmation button
  - "Cancel" button
  - Loading state while fetching preview
  - Error state if preview fails

- [ ] Add TanStack Query mutations to `ui/src/hooks/useReview.ts`:

```typescript
export function usePrunePreview(runId: string) { ... }
export function usePruneApply(runId: string) { ... }
export function useRevertFile(runId: string) { ... }
```

- [ ] Add API client functions to `ui/src/api/reviewClient.ts`:

```typescript
export async function prunePreview(runId: string, selection: PruneSelection): Promise<PrunePreviewResponse> { ... }
export async function pruneApply(runId: string, selection: PruneSelection): Promise<PruneApplyResponse> { ... }
export async function revertFile(runId: string, filePath: string): Promise<RevertFileResponse> { ... }
```

- [ ] After successful apply, invalidate diff files and diff queries via TanStack Query

**Dependencies**
- [ ] Tasks 1-2 must be complete

**References**
- `docs/git-ops/step-05-plan.md` — Tasks 4, 6

**Functionality (Expected Outcomes)**
- [ ] Preview modal displays accurate summary of what will be pruned
- [ ] Apply button triggers prune and refreshes data
- [ ] Post-apply toast notification confirms success

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 4: Wire Prune Mode into ReviewMergeTab

**Description**: Integrate prune mode toggle, file context menu, and PruneModeProvider into the ReviewMergeTab.

**Implementation Plan (Do These Steps)**

- [ ] Wrap `ReviewMergeTab` content in `PruneModeProvider`
- [ ] Add prune mode toggle button to `ReviewMergeTab` header
- [ ] Add "Prune File" action to `FileListSection` file item context menu (three-dot button)
- [ ] When prune mode is active, pass `PruneGutter` to `DiffViewer` as custom gutter
- [ ] Show `PruneToolbar` when prune mode is active
- [ ] Show `PrunePreviewModal` when "Preview" is clicked in toolbar

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/git-ops/step-05-plan.md` — Tasks 5, 7

**Functionality (Expected Outcomes)**
- [ ] Prune mode toggle enables/disables selection UI
- [ ] File context menu includes "Prune File" action
- [ ] Full prune flow works: toggle → select → preview → apply → data refreshes

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
