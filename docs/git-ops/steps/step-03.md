# Step 3: Diff Dialog with react-diff-view

Implement the core diff viewing experience: a near full-screen overlay dialog that renders unified diffs using `react-diff-view`. This component is the primary surface for reviewing code changes and is reused across multiple features (aggregate branch diff, per-commit diff, per-task diff, prune mode, conflict resolution).

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Diff viewer renders unified diffs using `react-diff-view` with inline/side-by-side toggle, supporting branch-aggregate, per-commit, and per-task scopes. Near full-screen diff dialog opens from file list clicks with scope selector.

**Functionality to Produce**:
- `DiffViewer` component wrapping `react-diff-view` for parsing and rendering unified diffs
- `DiffDialog` component as a near full-screen overlay with file header, scope selector, and view mode toggle
- File list clicks open `DiffDialog` with correct file and scope
- Scope switching (aggregate/commit/task) re-fetches and re-renders diff
- View mode toggle switches between inline and side-by-side rendering

**Final Verification Criteria**:
- Diff dialog opens from file list clicks
- Unified diff renders with correct line numbers
- Inline/side-by-side toggle works
- Scope selector switches diff content
- Dialog closes with Escape key or close button
- TypeScript compiles without errors
- Frontend builds without errors

---

## Task 1: Install Diff Rendering Dependencies

**Description**: Install the npm packages needed for diff parsing and rendering.

**Implementation Plan (Do These Steps)**

- [ ] Install `react-diff-view` and a diff parser package:

```bash
cd ui && npm install react-diff-view unidiff
```

- [ ] Verify the packages are added to `package.json`

**References**
- `react-diff-view` documentation — hunk rendering, custom gutters, view modes
- `docs/git-ops/step-03-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `react-diff-view` and `unidiff` are installed and importable

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors after installing types

---

## Task 2: Create DiffViewer Component

**Description**: Create the core `react-diff-view` wrapper component that parses unified diff text and renders hunks with line numbers.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/DiffViewer.tsx`:
  - Accept `diffText` (string) and `viewType` ("unified" | "split") props
  - Parse unified diff text using the diff parser into structured hunks
  - Render hunks via `react-diff-view`'s `Diff` and `Hunk` components
  - Support inline (unified) and side-by-side (split) view modes
  - Handle empty diff: display "No changes in this scope" message
  - Handle unparseable diff: fallback to raw text display with warning

**References**
- `react-diff-view` documentation — Diff, Hunk, parseDiff APIs
- `docs/git-ops/step-03-plan.md` — Task 2
- `docs/git-ops/architecture.md` — DiffViewer component spec

**Functionality (Expected Outcomes)**
- [ ] Component renders unified diff with correct line numbers
- [ ] Inline and split view modes render correctly
- [ ] Empty and error states handled gracefully

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create DiffDialog Component

**Description**: Create the near full-screen overlay dialog that contains the DiffViewer with a file header, scope selector, and view mode toggle.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/DiffDialog.tsx`:
  - Near full-screen overlay (dark backdrop, centered, large width/height)
  - File name in header bar
  - Scope selector dropdown: aggregate, commit, task
  - Inline/side-by-side toggle button
  - Close via Escape key or close button
  - Fetch diff data via `useDiff()` hook (add to `useReview.ts`)
  - Pass diff text and view type to `DiffViewer`
  - Loading state while fetching diff
  - Error state on fetch failure

- [ ] Add `useDiff()` hook to `ui/src/hooks/useReview.ts`:

```typescript
export function useDiff(runId: string, scope: string, ref?: string) {
  // TanStack Query hook fetching diff content by scope
}
```

**Dependencies**
- [ ] Task 2 must be complete (DiffViewer component exists)

**References**
- `docs/git-ops/step-03-plan.md` — Tasks 3, 5, 6
- `docs/git-ops/architecture.md` — DiffDialog component spec

**Functionality (Expected Outcomes)**
- [ ] Dialog opens as a near full-screen overlay
- [ ] File name displayed in header
- [ ] Scope selector changes the diff being displayed
- [ ] View mode toggle switches between inline and split
- [ ] Dialog closes with Escape or close button

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 4: Wire File List Clicks to DiffDialog

**Description**: Connect the `FileListSection` file clicks to open the `DiffDialog` with the correct file and scope.

**Implementation Plan (Do These Steps)**

- [ ] Update `ui/src/components/review/FileListSection.tsx`:
  - Add `onFileClick` handler that sets selected file state
  - On click, open `DiffDialog` with the selected file path

- [ ] Update `ui/src/components/review/ReviewMergeTab.tsx`:
  - Add state for selected file and dialog visibility
  - Render `DiffDialog` conditionally based on state
  - Pass file selection handler to `FileListSection`

**Dependencies**
- [ ] Task 3 must be complete (DiffDialog exists)

**References**
- `docs/git-ops/step-03-plan.md` — Task 4

**Functionality (Expected Outcomes)**
- [ ] Clicking a file in the file list opens the diff dialog
- [ ] Dialog shows the correct diff content for the selected file
- [ ] Closing the dialog returns to the file list view

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
