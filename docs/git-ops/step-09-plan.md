# Step 09 Plan: Frontend Back Merge + Conflict Resolver

## Purpose

Implement the back merge UI and interactive conflict resolution experience. Users can pull the latest target branch into the run branch, see a post-merge review banner (with undo) for clean merges, and resolve any conflicts through a dedicated near full-screen resolver dialog with per-block ours/theirs/manual choices.

## Prerequisites

- **Step 3** — Diff dialog must exist as the conflict resolver dialog follows a similar near full-screen overlay pattern.
- **Step 8** — Backend conflict resolution endpoints must exist (`GET /conflicts`, `POST /conflicts/{path}/resolve`, `POST /conflicts/agent-resolve`, enhanced `POST /back-merge`, `POST /revert-back-merge`).

## Functional Contract

### Inputs

- User interactions: click "Back Merge", confirm in modal, resolve conflicts per-block, mark files resolved, dispatch agent to resolve, undo back merge
- `POST /api/runs/{id}/back-merge` → trigger back merge
- `GET /api/runs/{id}/review/conflicts` → fetch conflict file list with blocks
- `POST /api/runs/{id}/review/conflicts/{path}/resolve` → apply resolution for a file
- `POST /api/runs/{id}/review/conflicts/agent-resolve` → dispatch agent for conflict resolution
- `POST /api/runs/{id}/review/revert-back-merge` → undo last back merge

### Outputs

- `BackMergeModal` component: confirmation modal showing source/target branches and predicted conflict count
- `BackMergeBanner` component: post-merge review banner with undo option (revert merge commit) — shown after clean merges
- `ConflictFileList` component: conflict files group in left rail with unresolved/resolved status chips
- `ConflictResolverDialog` component: near full-screen overlay with conflict block display
- `ConflictBlock` component: individual block with ours/theirs highlighting (warm/cool tinting), per-block actions ("Keep Run (ours)", "Keep Target (theirs)", "Manual Selection")
- `AgentResolveConflictsModal` component: dispatch modal defaulting to run's agent with Advanced toggle for override
- Prev/next file navigation in conflict resolver
- Merge readiness indicator updates as conflicts are resolved
- TanStack Query hooks: `useConflicts()`, `useResolveConflict()`, `useAgentResolveConflicts()`, `useRevertBackMerge()`

### Errors

- Back merge fails → error toast with git error details
- Conflict resolution fails → error message in resolver dialog
- Agent dispatch fails → error message in modal
- Undo (revert) fails → error toast
- No conflicts → conflict list section hidden or shows "No conflicts"

## Tasks

1. Create `ui/src/components/review/BackMergeModal.tsx` — confirmation modal with branch info and predicted conflicts
2. Create `ui/src/components/review/BackMergeBanner.tsx` — post-merge review banner with undo action
3. Create `ui/src/components/review/ConflictFileList.tsx` — conflict files group in left rail
4. Create `ui/src/components/review/ConflictResolverDialog.tsx` — near full-screen conflict resolution overlay
5. Create `ui/src/components/review/ConflictBlock.tsx` — per-block ours/theirs display with action buttons
6. Create `ui/src/components/review/AgentResolveConflictsModal.tsx` — agent dispatch modal with default + override
7. Add TanStack Query hooks: `useConflicts()`, `useResolveConflict()`, `useAgentResolveConflicts()`, `useRevertBackMerge()`
8. Add API client functions: `getConflicts()`, `resolveConflict()`, `agentResolveConflicts()`, `revertBackMerge()`
9. Wire conflict file list into ReviewMergeTab left rail
10. Write Playwright tests: back merge flow, conflict display, manual resolution, agent resolution

## Verification

### Auto-Verify

- [ ] Playwright test `test_back_merge_clean` — back merge with no conflicts, verify clean result with undo banner
- [ ] Playwright test `test_back_merge_conflicts` — back merge with conflicts, verify conflict file list
- [ ] Playwright test `test_conflict_resolver` — open conflict dialog, choose ours/theirs, mark resolved
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds

### Manual Verify

- [ ] Back merge confirmation modal shows source/target branches and predicted conflict count
- [ ] Clean merge shows review banner with "Undo" button that reverts the merge commit
- [ ] Conflict files appear in a distinct group in the left rail with unresolved/resolved chips
- [ ] Conflict resolver shows ours/theirs blocks with warm/cool tinting
- [ ] "Keep Run (ours)" replaces block with run's version
- [ ] "Keep Target (theirs)" replaces block with target's version
- [ ] "Manual Selection" allows editing the block content
- [ ] "Mark File Resolved" updates status and decrements unresolved count
- [ ] Prev/next navigation moves between conflict files
- [ ] Agent resolve modal defaults to run's agent with Advanced override toggle

## Context & References

- `ui/src/components/review/DiffDialog.tsx` — pattern for near full-screen overlay dialogs
- `ui/src/components/review/ReviewMergeTab.tsx` — parent component for conflict list placement
- `docs/git-ops/clarifications.md` — Q1: agent default + Advanced override; Q6: auto-commit clean merges + undo banner
- `docs/git-ops/architecture.md` — BackMergeModal, BackMergeBanner, ConflictResolverDialog, ConflictBlock specs
