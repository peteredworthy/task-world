<<<<<<< HEAD
# Intent: frontend-gaps

## Original Request

Close all 21 gaps identified in `docs/stories/GAP-ANALYSIS-FRONTEND.md`. The gap analysis measures the React/TypeScript frontend against four user stories and a backbone journey map, finding 3 high-severity gaps, 8 medium-severity gaps, and 10 low-severity gaps where the UI either lacks backend-supported functionality entirely or degrades the story experience.

## Goal

Make every user story journey (Happy Path, Revision Loop, Human in the Loop, Long-Running Run) fully executable and comprehensible through the web UI alone, without requiring CLI or direct API access for any operation that the backend already supports.
=======
# Intent: Close All 21 Frontend Gaps

## Original Request

Close ALL 21 gaps identified in `docs/stories/GAP-ANALYSIS-FRONTEND.md`. This gap analysis measures the orchestrator web UI against four user stories and a backbone journey map. The backend APIs for most gaps already exist; the work is frontend-only in `ui/src/`.

## Goal

Make every user story journey (Happy Path, Revision Loop, Human in the Loop, Long-Running Run) fully executable through the web UI with no degraded or missing interactions. After this work, the gap analysis re-run should report zero HIGH, zero MEDIUM, and zero LOW gaps.
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5

## Scope

### In Scope

<<<<<<< HEAD
- **High (3 gaps):** Step-level approval UI, branch status display, back-merge UI
- **Medium (8 gaps):** Merge strategy picker, per-attempt cost breakdown, auto-verify output surfacing, clarification context display, gate type indication, textual step progress on dashboard, history page implementation, live guidance endpoint rendering
- **Low (10 gaps):** Routine inspection depth (gate types, priorities), agent page→run creation flow link, visual revision loop indicator, grade threshold calculation display, "blocked on human" visual state, elapsed time during execution, routine validation from UI, env file management UI, conditional step transition visualization, real-time dashboard updates via SSE
- All changes are frontend-only (React/TypeScript/Vite) — backend endpoints already exist for high/medium items
- Vitest unit tests for new components and hooks
=======
- **3 HIGH gaps** (story-blocking): Step-level approval UI, branch status display, back-merge UI
- **8 MEDIUM gaps** (story-degrading): Merge strategy selection, per-attempt cost breakdown, auto-verify output surfacing, clarification context display, gate type indication, textual step progress on dashboard, History page implementation, live guidance endpoint rendering
- **10 LOW gaps** (friction/polish): Routine inspection depth, agents→run creation flow, revision loop visualization, grade threshold math display, blocked-on-human visual state, elapsed time during execution, routine validation UI, env file management UI, conditional step transition visualization, real-time dashboard updates via WebSocket
- **1 NEW gap** (from human feedback): Design-question UI for LLM-driven questions — enable the frontend to present structured questions from the LLM and capture user answers
- New React components, hooks, and TypeScript types in `ui/src/`
- Wiring to existing backend API endpoints
- WebSocket event handling for real-time features
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5

### Out of Scope

- Backend API changes (all required endpoints already exist)
<<<<<<< HEAD
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
=======
- New backend endpoints or data model changes
- CLI changes
- Routine definition format changes
- Authentication or authorization changes
- Mobile-specific responsive design
- Accessibility audit beyond maintaining current standards

## Definition of Complete

- [ ] All 3 HIGH gaps closed: step-level approval works end-to-end, branch status is displayed on RunDetail, back-merge can be triggered from UI
- [ ] All 8 MEDIUM gaps closed: merge strategy picker on merge dialog, per-attempt tokens/cost in AttemptHistory, auto-verify stdout/stderr inline in ActivityFeed, clarification context rendered in ClarificationModal, gate type badges on pending actions, "Step X of Y" text on dashboard RunCards, History page functional with filters, AgentGuidancePanel polls live guidance
- [ ] All 10 LOW gaps closed: routine detail shows gate types and priorities, agent selection flows into CreateRunModal, attempt timeline visualization, grade threshold explanation, blocked-on-human badge/state, elapsed time counter during active runs, routine validation button in RoutineLibrary, env file management page/modal, non-linear step transitions visualized, dashboard uses WebSocket for real-time updates
- [ ] No TypeScript compilation errors (`tsc --noEmit` passes)
- [ ] Existing functionality not broken (all current UI flows still work)
- [ ] `uv run pre-commit run --all-files` passes cleanly
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5
