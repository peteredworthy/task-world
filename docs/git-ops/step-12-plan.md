# Step 12 Plan: Visual Polish + Edge States + Keyboard Shortcuts + Visual Regression Tests

## Purpose

Final polish pass for the Review & Merge workbench. This step handles edge cases, adds keyboard shortcuts for power users, ensures consistent loading/error states across all components, and establishes Playwright visual regression tests as a baseline for future changes.

## Prerequisites

- **Steps 1-11** — All functional implementation must be complete. This step only adds polish, edge state handling, keyboard shortcuts, and visual regression tests on top of the fully functional workbench.

## Functional Contract

### Inputs

- User keyboard input: j/k (next/prev change), [/] (prev/next conflict file), Shift+P (prune mode toggle), t (run tests)
- Various edge-state scenarios: no changes, no conflicts, binary files, large diffs, empty runs

### Outputs

- **Empty states:**
  - "Nothing to review" when run has no changes
  - "Back merge clean" when merge completed without conflicts
  - "No test commands configured" when routine has no auto_verify
- **Binary file handling:** metadata display (file type, size), limited actions (keep-ours/keep-theirs only, no line-level diff)
- **Large diff handling:** lazy rendering with collapsed-by-default file sections for diffs >1000 lines; "Expand All" / "Collapse All" controls
- **Keyboard shortcuts:**
  - `j` / `k` — next/previous change in diff viewer
  - `[` / `]` — previous/next conflict file in conflict resolver
  - `Shift+P` — toggle prune mode
  - `t` — run tests
  - Shortcuts only active when Review & Merge tab is focused (not in text inputs)
- **Loading states:** skeleton loaders for file list, diff viewer, history panel, readiness bar
- **Error states:** consistent error boundaries with retry actions for all panels
- **Responsive behavior:** left rail collapses on narrow viewports; dialogs adapt to screen size
- **Documentation updates:** `docs/ARCHITECTURE.md` updated with new routes, components, directory map entries
- **Playwright visual regression baselines** for all major workbench states

### Errors

- Keyboard shortcut conflicts with browser defaults → use non-conflicting bindings, document overrides
- Visual regression test flakiness → use appropriate tolerance thresholds and stable selectors

## Tasks

1. Implement empty states for all panels (no changes, no conflicts, no test config, clean merge)
2. Implement binary file handling in diff viewer (metadata display, restricted actions)
3. Implement large diff lazy rendering with collapsed file sections and expand/collapse controls
4. Implement keyboard shortcut system with hotkey registration and active-tab scoping
5. Add skeleton loaders for all data-fetching panels
6. Add error boundaries with retry actions to all review components
7. Responsive design pass: left rail collapse, dialog adaptation
8. Update `docs/ARCHITECTURE.md` with new routes, components, and directory map
9. Write Playwright visual regression tests for all major states (8 snapshots per architecture spec)
10. Run full visual regression suite and establish baselines

## Verification

### Auto-Verify

- [ ] All Playwright visual regression tests pass and baselines are established
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds
- [ ] All prior Playwright functional tests still pass (no regressions)

### Manual Verify

- [ ] Empty states display correctly for all scenarios (no changes, clean merge, no test config)
- [ ] Binary files show metadata and limited action set
- [ ] Large diffs render with collapsed sections; expand/collapse works
- [ ] Keyboard shortcuts work correctly: j/k navigate changes, [/] navigate conflicts, Shift+P toggles prune, t runs tests
- [ ] Shortcuts are inactive when typing in text inputs
- [ ] Loading skeletons appear during data fetching
- [ ] Error boundaries catch component failures and offer retry
- [ ] Layout adapts on narrow viewports (left rail collapse)
- [ ] `docs/ARCHITECTURE.md` accurately reflects all new routes and components

## Context & References

- All prior step plan files (steps 01-11) — functional features that this step polishes
- `docs/ARCHITECTURE.md` — documentation to update
- `docs/git-ops/architecture.md` — visual regression test specifications
- Playwright `expect(page).toHaveScreenshot()` — visual regression API
- `AGENTS.md` — documentation maintenance requirements
