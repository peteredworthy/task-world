# UI QA Test Suite — Plan

## Approach

Iterative, milestone-based. Each milestone produces runnable tests and is independently valuable. Later milestones build on earlier infrastructure but can be descoped without losing prior work.

## Technology Decisions

Confirmed via clarification Q&A (see `clarifications.md`).

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Workflow tests | Playwright + `playwright-bdd` | Gherkin `.feature` files → Playwright test steps. Reuses existing Playwright setup. Confirmed over standalone Cucumber (Q1). |
| Component/unit tests | Vitest + Testing Library | Already in place (221 tests). Extend, don't replace. |
| API mocking (Playwright) | Playwright `route()` API | Intercept fetch/XHR at network level. No MSW dependency needed. |
| API mocking (Vitest) | `vi.mock` / `vi.fn` on fetch | Already used in existing tests. |
| WebSocket mocking | Custom `FakeWebSocket` class | Inject via dependency; tests control message timing. |
| Fixtures | TypeScript factory functions | Type-safe, composable, derived from `ui/src/types/`. No OpenAPI generation — types-only approach (Q2). |
| Step reuse | Shared step definitions across features | Reduce duplication; common Given/When/Then steps in `common.steps.ts` (Q4). |
| Parameterization | Scenario outlines with examples tables | Cover state transition matrix efficiently without duplicating scenario bodies (Q4). |
| CI time budget | < 3 minutes for BDD suite | Stricter than original 5-minute target. Achieved via `--workers=4` parallelism (Q5). |

## Implementation Priority

Based on clarification Q6, implementation priority when time-constrained:

1. **Dashboard + CreateRunModal** (M2a) — highest priority
2. **Edge cases / race conditions** (M3) — second priority
3. **RunDetail + task lifecycle** (M2b, M2c, M2d) — third priority
4. Secondary pages (M2e) — lowest priority, can be descoped

## Milestone 1: Infrastructure and Fixtures (Est. 1–2 tasks)

**Goal**: Shared test infrastructure that all later milestones depend on.

**Deliverables**:
- `ui/tests/fixtures/factories.ts` — factory functions for `Run`, `Task`, `Attempt`, `Step`, `Routine`, `Agent` objects matching API response shapes.
- `ui/tests/fixtures/api-handlers.ts` — reusable Playwright route handlers that serve factory-generated responses for all API endpoints (`/api/runs`, `/api/runs/:id`, `/api/routines`, `/api/agents`, etc.).
- `ui/tests/fixtures/fake-ws.ts` — `FakeWebSocket` that tests can use to push events (run status changed, task status changed, batch events) at controlled times.
- `ui/tests/fixtures/fake-sse.ts` — similar for SSE activity stream.
- `playwright-bdd` installed and configured. One smoke `.feature` file proving the Gherkin → Playwright pipeline works.
- Documentation: `ui/tests/README.md` explaining fixture patterns and how to add new scenarios.

**Traces**: [I-17], [I-18], [I-22], [I-24], [I-34]

**Verification**: Smoke feature file runs green. Factory functions produce valid typed objects. Route handlers respond to Playwright requests.

## Milestone 2: Core Workflow Features (Est. 2–3 tasks)

**Goal**: Gherkin specs covering every primary workflow, happy path.

**Deliverables** (one `.feature` file per workflow area):

### 2a: Dashboard Workflows
- `dashboard.feature`: View runs list, filter by status, search, create new run (modal open → fill → submit → run appears), click run card → navigate to detail.
- Covers: Dashboard.tsx, CreateRunModal (via useCreateRunModal), RunCard, RunFilters, RoutineSelector, BranchSelector.

### 2b: Run Detail Workflows
- `run-detail.feature`: View run detail, see step timeline, see task list, expand task detail, view attempt history, pause/resume run, cancel run.
- Covers: RunDetail page, StepTimeline, TaskDetailCard, AttemptHistory, AttemptTimeline, MetricsBar, ActivityFeed.

### 2c: Run Lifecycle
- `run-lifecycle.feature`: Create run → start → active (tasks building) → verifying → grading → complete. Also: create → start → pause → resume → complete. Also: create → start → cancel.
- State transitions driven by mocked API responses + WebSocket events.

### 2d: Task Lifecycle
- `task-lifecycle.feature`: Task queued → building (prompt shown) → submit → verifying → grades set → complete. Also: verify → fail → revision → re-verify → pass.
- Covers: ChecklistTable, GradeBadge, GradeRow, PromptCopyBox.

### 2e: Secondary Pages
- `routines.feature`: Browse routine library, validate routine.
- `agents.feature`: View agents list, configure agent runner, view quota.
- `history.feature`: View completed runs.
- `settings.feature`: Open settings modal, toggle SSE/polling.

**Traces**: [I-01], [I-04], [I-06], [I-07], [I-08], [I-11], [I-27], [I-29], [I-30], [I-32]

**Verification**: All feature files pass. Every page has at least one scenario. Every modal has open/close coverage.

## Milestone 3: Edge Cases, Race Conditions, and State Transition Matrix (Est. 3–4 tasks)

**Goal**: Test failure modes, timing issues, and exhaustively cover the state machine. Per clarification Q3, this includes a full state transition matrix with invalid transitions — not just 5 edge cases.

**Deliverables**:

### 3a: State Transition Matrix
- `run-transitions.feature`: Scenario Outline covering all valid run state transitions (draft→active, active→paused, paused→active, active→completed, active→failed, active→cancelled, paused→cancelled) plus invalid transitions (completed→active, cancelled→paused, etc.) verified to show appropriate error/no-op behavior.
- `task-transitions.feature`: Scenario Outline covering all valid task state transitions (queued→building, building→verifying, verifying→completed, verifying→failed, failed→building [revision]) plus invalid transitions.
- Uses Scenario Outlines with Examples tables (Q4) for efficient parameterized coverage.

### 3b: State Change During Interaction
- `edge-state-change.feature`:
  - Scenario: Run completes via WebSocket while CreateRunModal is open — modal should reflect new state or close gracefully.
  - Scenario: Task moves to VERIFYING while user is viewing BUILDING prompt — UI updates without losing context.
  - Scenario: Run is cancelled by another user while current user is setting grades — form submission fails gracefully with error feedback.

### 3c: Dialog Edge Cases
- `edge-dialogs.feature`:
  - Scenario: ConfirmDialog for destructive action — rapid double-click doesn't fire twice.
  - Scenario: ApprovalModal opens when gate is reached, closes if gate is resolved by another actor.
  - Scenario: ClarificationModal — submit while WebSocket pushes a new clarification request.
  - Scenario: Modal open → navigate away → modal should close (no orphan modals).

### 3d: Connection Edge Cases
- `edge-connection.feature`:
  - Scenario: WebSocket disconnects and reconnects — ConnectionBanner shows, data refreshes on reconnect.
  - Scenario: SSE stream drops — fallback to polling, banner shown.
  - Scenario: API request fails with 500 — error boundary catches, retry works.
  - Scenario: API request fails with 404 — NotFound page shown.

### 3e: Stale Data
- `edge-stale-data.feature`:
  - Scenario: User views run list, background WebSocket updates a run's status — card updates without full page reload.
  - Scenario: Run detail data is stale (cached) — WebSocket event triggers React Query invalidation.

**Traces**: [I-03], [I-05], [I-09], [I-10], [I-12], [I-25], [I-28], [I-31]

**Verification**: Full state transition matrix passes. All edge-case scenarios pass. Each scenario tests a specific race condition or failure mode documented in the feature file.

## Milestone 4: CI Integration and Documentation (Est. 1 task)

**Goal**: Tests run automatically, suite is maintainable.

**Deliverables**:
- CI configuration (GitHub Actions or equivalent) running the Playwright BDD suite.
- Test run time verified < 3 minutes for BDD suite alone (per clarification Q5).
- `ui/tests/README.md` updated with: how to run locally, how to add a new workflow, how to add a new edge case, fixture patterns, debugging tips.
- Coverage summary showing which pages/components have workflow-level coverage.

**Traces**: [I-02], [I-19], [I-20], [I-21], [I-26], [I-33], [I-34]

**Verification**: CI pipeline green. README reviewed for completeness.

## Implementation Order

```
M1 (Infrastructure) ──→ M2 (Core Workflows) ──→ M3 (Edge Cases) ──→ M4 (CI + Docs)
                         ├── 2a (Dashboard)
                         ├── 2b (Run Detail)
                         ├── 2c (Run Lifecycle)
                         ├── 2d (Task Lifecycle)
                         └── 2e (Secondary Pages)
```

M1 is prerequisite for all others. M2 subtasks (2a–2e) can be parallelized. M3 depends on M2 fixtures being stable. M4 can start as soon as M2 is complete.

## Estimated Effort

| Milestone | Tasks | Notes |
|-----------|-------|-------|
| M1 | 1–2 | Mostly boilerplate + tooling config |
| M2 | 2–3 | Largest milestone; parallelizable subtasks |
| M3 | 3–4 | Full state transition matrix + edge cases; larger scope per Q3 |
| M4 | 1 | CI config + docs |
| **Total** | **7–10 tasks** | |
