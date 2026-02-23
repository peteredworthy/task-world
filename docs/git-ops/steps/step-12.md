# Step 12: Visual Polish + Edge States + Keyboard Shortcuts + Visual Regression Tests

Final polish pass for the Review & Merge workbench. This step handles edge cases, adds keyboard shortcuts for power users, ensures consistent loading/error states across all components, and establishes Playwright visual regression test baselines.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — All existing tests continue to pass. Playwright visual tests confirm no major layout/styling regressions. `uv run pre-commit run --all-files` passes cleanly.

**Functionality to Produce**:
- Empty states for all panels (no changes, no conflicts, no test config, clean merge)
- Binary file handling (metadata display, restricted actions)
- Large diff lazy rendering with collapsed file sections
- Keyboard shortcuts (j/k, [/], Shift+P, t)
- Skeleton loaders for all data-fetching panels
- Error boundaries with retry actions
- Responsive design (left rail collapse on narrow viewports)
- Updated `docs/ARCHITECTURE.md`
- Playwright visual regression test baselines

**Final Verification Criteria**:
- Empty states display correctly for all scenarios
- Binary files show metadata and limited actions
- Large diffs use collapsed sections with expand/collapse
- Keyboard shortcuts work (inactive in text inputs)
- Loading skeletons appear during data fetching
- Error boundaries catch failures and offer retry
- `docs/ARCHITECTURE.md` updated with new routes and components
- All existing tests still pass
- Visual regression baselines established

---

## Task 1: Implement Empty States and Binary File Handling

**Description**: Add proper empty states across all review panels and handle binary files gracefully in the diff viewer.

**Implementation Plan (Do These Steps)**

- [ ] Add empty states to components:
  - `FileListSection`: "Nothing to review" when no changes
  - `ConflictFileList`: section hidden when no conflicts
  - `TestPanel`: "No test commands configured" when no auto_verify
  - `BackMergeBanner`: "Back merge clean" state
  - `HistoryPanel`: "No commits on this branch" when empty

- [ ] Add binary file handling in `DiffViewer.tsx`:
  - Detect binary files (from diff text patterns or file metadata)
  - Display metadata: file type, size
  - Restricted actions: keep-ours/keep-theirs only (no line-level diff)
  - Clear message: "Binary file — line-level diff not available"

**References**
- `docs/git-ops/step-12-plan.md` — Tasks 1, 2

**Functionality (Expected Outcomes)**
- [ ] All empty states display appropriate messages
- [ ] Binary files handled gracefully with metadata display

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 2: Implement Large Diff Handling and Keyboard Shortcuts

**Description**: Add lazy rendering for large diffs and keyboard shortcuts for power users.

**Implementation Plan (Do These Steps)**

- [ ] Implement large diff handling in `DiffViewer.tsx` / `DiffDialog.tsx`:
  - For diffs >1000 lines: collapse file sections by default
  - "Expand All" / "Collapse All" controls in dialog header
  - Individual file sections expandable/collapsible

- [ ] Implement keyboard shortcut system:
  - Create a `useKeyboardShortcuts()` hook or integrate into `ReviewMergeTab`
  - `j` / `k` — next/previous change in diff viewer
  - `[` / `]` — previous/next conflict file in conflict resolver
  - `Shift+P` — toggle prune mode
  - `t` — run tests
  - Shortcuts only active when Review & Merge tab is focused
  - Shortcuts disabled when focus is in text inputs (input, textarea, contenteditable)

**References**
- `docs/git-ops/step-12-plan.md` — Tasks 3, 4

**Constraints**
- [ ] Keyboard shortcuts must not conflict with browser defaults
- [ ] Shortcuts must be inactive when typing in text inputs

**Functionality (Expected Outcomes)**
- [ ] Large diffs render with collapsed sections
- [ ] Expand/collapse controls work
- [ ] All keyboard shortcuts function correctly
- [ ] Shortcuts are inactive in text inputs

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Add Loading States, Error Boundaries, and Responsive Design

**Description**: Add skeleton loaders, error boundaries, and responsive behavior to all review components.

**Implementation Plan (Do These Steps)**

- [ ] Add skeleton loaders:
  - File list: placeholder rows with shimmer animation
  - Diff viewer: placeholder content area
  - History panel: placeholder commit entries
  - Readiness bar: placeholder gate indicators
  - Test panel: placeholder status area

- [ ] Add error boundaries with retry:
  - Wrap each major panel section in an error boundary
  - Error state shows friendly message with "Retry" button
  - Retry button re-fetches data

- [ ] Responsive design pass:
  - Left rail collapses on narrow viewports (< 768px breakpoint)
  - Toggle button to show/hide left rail on narrow screens
  - Dialogs adapt to screen size (reduce padding, full-width on mobile)

**References**
- `docs/git-ops/step-12-plan.md` — Tasks 5, 6, 7

**Functionality (Expected Outcomes)**
- [ ] Loading skeletons appear during data fetching
- [ ] Error boundaries catch component failures and offer retry
- [ ] Layout adapts on narrow viewports

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors

---

## Task 4: Update Documentation

**Description**: Update `docs/ARCHITECTURE.md` with all new routes, components, and directory map entries.

**Implementation Plan (Do These Steps)**

- [ ] Update `docs/ARCHITECTURE.md`:
  - Add all `/api/runs/{id}/review/` routes to the API routes table
  - Add `src/orchestrator/git/diff_ops.py`, `prune_ops.py`, `conflict_ops.py` to directory map
  - Add `src/orchestrator/review/` package to directory map
  - Add `src/orchestrator/api/routers/review.py` to directory map
  - Add `src/orchestrator/api/schemas/review.py` to directory map
  - Add `ui/src/components/review/` directory with all component files
  - Add `ui/src/api/reviewClient.ts` and `ui/src/hooks/useReview.ts`
  - Add new event types to the event documentation section

**References**
- `docs/ARCHITECTURE.md` — existing documentation to update
- `AGENTS.md` — documentation maintenance requirements
- `docs/git-ops/step-12-plan.md` — Task 8

**Functionality (Expected Outcomes)**
- [ ] ARCHITECTURE.md accurately reflects all new routes, components, and files

**Final Verification (Proof of Completion)**
- [ ] Verify all new API routes are listed in ARCHITECTURE.md
- [ ] Verify all new source files are in the directory map

---

## Task 5: Create Playwright Visual Regression Tests

**Description**: Create visual regression tests for all major workbench states to establish baselines.

**Implementation Plan (Do These Steps)**

- [ ] Create visual regression test file(s) using Playwright:

```
# Visual regression snapshots to create:
# 1. visual_review_tab_clean — Review tab with no conflicts, tests passing
# 2. visual_review_tab_conflicts — Review tab with conflict indicators
# 3. visual_diff_dialog_inline — Diff dialog in inline mode
# 4. visual_diff_dialog_split — Diff dialog in side-by-side mode
# 5. visual_prune_mode_active — Prune mode with selections
# 6. visual_conflict_resolver — Conflict resolver with ours/theirs blocks
# 7. visual_merge_readiness_ready — Readiness bar with all gates green
# 8. visual_merge_readiness_blocked — Readiness bar with gates unmet
```

- [ ] Use `expect(page).toHaveScreenshot()` for visual regression
- [ ] Set appropriate tolerance thresholds for pixel comparison
- [ ] Use stable selectors to avoid flakiness

**References**
- `docs/git-ops/architecture.md` — visual regression test specifications
- Playwright `toHaveScreenshot()` documentation
- `docs/git-ops/step-12-plan.md` — Tasks 9, 10

**Functionality (Expected Outcomes)**
- [ ] Visual regression baselines established for all 8 major states
- [ ] Tests can detect layout/styling regressions in future changes

**Final Verification (Proof of Completion)**
- [ ] All Playwright visual regression tests pass and baselines are stored
- [ ] All prior Playwright functional tests still pass
- [ ] `cd ui && npm run build` — frontend builds without errors
- [ ] `uv run pre-commit run --all-files` — passes cleanly (if configured)
