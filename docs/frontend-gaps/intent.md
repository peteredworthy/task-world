# Intent: frontend-gaps

## Original Request

Close all 21 gaps identified in `docs/stories/GAP-ANALYSIS-FRONTEND.md`. The gap analysis measures the React/TypeScript frontend against four user stories and a backbone journey map, finding 3 high-severity gaps, 8 medium-severity gaps, and 10 low-severity gaps where the UI either lacks backend-supported functionality entirely or degrades the story experience.

## Goal

Make every user story journey (Happy Path, Revision Loop, Human in the Loop, Long-Running Run) fully executable and comprehensible through the web UI alone, without requiring CLI or direct API access for any operation that the backend already supports.

## Scope

### In Scope

- **High (3 gaps):** Step-level approval UI, branch status display, back-merge UI
- **Medium (8 gaps):** Merge strategy picker, per-attempt cost breakdown, auto-verify output surfacing, clarification context display, gate type indication, textual step progress on dashboard, history page implementation, live guidance endpoint rendering
- **Low (10 gaps):** Routine inspection depth (gate types, priorities), agent page→run creation flow link, visual revision loop indicator, grade threshold calculation display, "blocked on human" visual state, elapsed time during execution, routine validation from UI, env file management UI, conditional step transition visualization, real-time dashboard updates via SSE
- All changes are frontend-only (React/TypeScript/Vite) — backend endpoints already exist for high/medium items
- Vitest unit tests for new components and hooks

### Out of Scope

- Backend API changes (all required endpoints already exist)
- Backend bug fixes or new endpoint creation
- Mobile/responsive design overhaul
- Accessibility audit (a11y improvements welcome but not the goal)
- Performance optimization of existing components
- Authentication/authorization changes

## Definition of Complete

- [ ] Step-level approval works end-to-end through the UI (step gate blocks → user sees prompt → approves/rejects → run continues)
- [ ] Branch status (ahead/behind) is visible on RunDetail page
- [ ] Back-merge operation is accessible from RunDetail with confirmation dialog
- [ ] Merge strategy picker (squash/merge/rebase) appears in merge-back flow
- [ ] Per-attempt token/cost breakdown visible in AttemptHistory
- [ ] Auto-verify stdout/stderr displayed inline in ActivityFeed
- [ ] Clarification context field rendered in ClarificationModal
- [ ] Gate type (human_approval, grade_threshold, checklist) indicated on pending actions
- [ ] Dashboard RunCard shows "Step X of Y" text alongside progress bar
- [ ] History page is functional with filters (status, date range, search)
- [ ] AgentGuidancePanel polls and displays live guidance response
- [ ] RoutineDetail shows gate types, auto-verify commands, and requirement priorities
- [ ] Agents page selection carries into CreateRunModal
- [ ] AttemptHistory shows visual timeline/flow (not just flat list)
- [ ] Grade threshold math shown when verification fails
- [ ] "Waiting for human input" visual state on RunDetail when blocked
- [ ] Elapsed time display during active run execution
- [ ] Routine validation button on RoutineDetail page
- [ ] Env file management section in settings or run config
- [ ] Step progress bar handles non-linear transitions (backward jumps)
- [ ] Dashboard uses SSE for real-time updates (replaces 10s polling)
- [ ] All new components have Vitest unit tests
