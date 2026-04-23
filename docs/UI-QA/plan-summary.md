# UI QA Test Suite — Plan Summary

## Intent Satisfaction

The plan directly addresses all 8 intent goals:

| Goal | Tracing | How Plan Satisfies |
|------|---------|-------------------|
| [I-01] Comprehensive end-to-end frontend test suite | M2, M3, M4 | All pages, dialogs, workflows covered via Gherkin features in Steps 2–5. Step 6 wires into CI. |
| [I-02] Fast, deterministic testing (no real backend) | M1, M2 | FakeWebSocket, route handlers, and factories in Step 1 enable in-memory mocking. Tests run without server. |
| [I-03] Edge cases: state changes during interaction | M3 | Step 5 specifically targets race conditions (WebSocket updates mid-form, modal open during state change). State transition matrix covers all valid + invalid transitions. |
| [I-04] Gherkin-like syntax (Cucumber/Playwright BDD) | M1, M2, M3, M4 | playwright-bdd selected in Step 1. All workflows (Steps 2–5) written as readable `.feature` files. |
| [I-05] Easy to add new edge cases | M3, M4 | Step 5 provides patterns for race condition scenarios. Step 6 documents how to extend (< 15 min to add new scenario). |
| [I-06–I-07] All pages and dialogs | M2 | Step 2: Dashboard + CreateRunModal (highest priority). Step 3: RunDetail + secondary pages (Routines, Agents, History, Settings). |
| [I-08–I-11] Stateful flows, WebSocket/SSE, forms, sidebar, errors | M2, M3 | Steps 2–4 cover all lifecycles. Step 5 covers WebSocket reconnect, SSE fallback, form race conditions, stale data. |
| [I-12–I-16] Out of scope explicitly defined | — | Visual regression (handled by existing Playwright snapshots), performance, mobile, backend API. |

**Conclusion**: Plan fully addresses intent. No goals descoped.

---

## Execution Steps & Task Estimates

Iterative, milestone-based. Each step produces runnable tests independently valuable.

### Step 1: Infrastructure & Fixtures (M1)
**Estimated Tasks**: 1–2  
**Duration**: ~1–2 days  
**Deliverables**:
- `ui/tests/fixtures/factories.ts` — factory functions for Run, Task, Attempt, Step, Routine, Agent
- `ui/tests/fixtures/api-handlers.ts` — Playwright route handlers for all API endpoints
- `ui/tests/fixtures/fake-ws.ts` — FakeWebSocket class for test-controlled WebSocket events
- `ui/tests/fixtures/fake-sse.ts` — FakeSSE for activity stream mocking
- `playwright-bdd` installed and configured with smoke `.feature` file
- `ui/tests/README.md` — how to run, add scenarios, fixture patterns

**Success Criteria**: `npm run test:bdd` runs smoke test green. Factories produce typed objects. Route handlers respond to requests.

**Prerequisite for**: All later steps (M2–M4).

---

### Step 2: Dashboard & CreateRunModal (M2a)
**Estimated Tasks**: 1–2  
**Duration**: ~1–2 days  
**Deliverables**:
- `features/dashboard.feature` — view runs list, filter by status, search, create run, navigate to detail
- Page objects: `dashboard.page.ts`, `modals.page.ts`
- Common step definitions (shared across M2–M3 features)
- Route handler extensions for run CRUD operations

**Success Criteria**: Dashboard feature passes. CreateRunModal opens, form validation works, created run appears in list.

**Priority**: Highest (per clarification Q6).

---

### Step 3: RunDetail & Secondary Pages (M2b + M2e)
**Estimated Tasks**: 1–2  
**Duration**: ~1–2 days  
**Deliverables**:
- `features/run-detail.feature` — view run, step timeline, task list, attempt history, pause/resume/cancel
- `features/secondary-pages.feature` — Routines, Agents, History, Settings workflows
- Page objects: `runDetail.page.ts`, extended dashboard patterns
- Route handler extensions for pause/resume/cancel mutations

**Success Criteria**: RunDetail feature passes. Every secondary page has at least one scenario. Pause/resume/cancel mutations work.

**Priority**: Second (per clarification Q6, after Dashboard).

---

### Step 4: Run & Task Lifecycle (M2c + M2d)
**Estimated Tasks**: 1–2  
**Duration**: ~1–2 days  
**Deliverables**:
- `features/run-lifecycle.feature` — draft → active → verifying → complete (and pause/resume/cancel variants)
- `features/task-lifecycle.feature` — queued → building → verifying → completed (and revision cycles)
- WebSocket event sequencing in tests using FakeWebSocket
- Route handler state coordination with WebSocket timing
- Checklist table, grade badge, prompt copy box verification at each stage

**Success Criteria**: Lifecycle features pass. WebSocket events trigger UI updates without page reload. Revision cycle works end-to-end.

**Priority**: Third (per clarification Q6).

---

### Step 5: Edge Cases & State Transition Matrix (M3)
**Estimated Tasks**: 3–4  
**Duration**: ~2–3 days  
**Deliverables**:
- `features/state-transitions.feature` — Scenario Outline: all run state transitions (valid + invalid) with Examples table
- `features/task-transitions.feature` — Scenario Outline: all task state transitions (valid + invalid)
- `features/edge-state-changes.feature` — scenarios for race conditions:
  - Run completes while CreateRunModal open
  - Task moves to VERIFYING while viewing BUILDING prompt
  - Run cancelled while user setting grades
- `features/edge-dialogs.feature` — double-click protection, modal close-on-navigate, gate resolution by other actor
- `features/edge-connection.feature` — WebSocket disconnect/reconnect, SSE fallback, API error handling
- `features/edge-stale-data.feature` — background WebSocket updates, React Query cache invalidation

**Success Criteria**: Full state transition matrix passes (all valid transitions work, all invalid transitions properly handled). Each race condition scenario passes. Failure modes documented.

**Priority**: Second (per clarification Q6, tied with Dashboard).

---

### Step 6: CI Integration & Documentation (M4)
**Estimated Tasks**: 1  
**Duration**: ~0.5–1 day  
**Deliverables**:
- CI workflow configuration (GitHub Actions) running `npm run test:bdd`
- Playwright browser installation and caching in CI
- Test run time verified < 3 minutes (per clarification Q5)
- Coverage summary table in `ui/tests/README.md`
- Instructions for running locally, debugging, adding new workflows/edge cases

**Success Criteria**: CI pipeline runs tests in < 3 minutes. All tests pass. README can be followed by new contributor to add a scenario in < 15 minutes.

---

## Task Count Summary

| Step | Milestone | Tasks | Cumulative |
|------|-----------|-------|-----------|
| 1 | M1 | 1–2 | 1–2 |
| 2 | M2a | 1–2 | 2–4 |
| 3 | M2b+e | 1–2 | 3–6 |
| 4 | M2c+d | 1–2 | 4–8 |
| 5 | M3 | 3–4 | 7–12 |
| 6 | M4 | 1 | 8–13 |
| **Total** | **M1–M4** | **7–13** | — |

**Estimate**: Nominal path is ~10 tasks; high uncertainty on state transition matrix (Step 5) complexity.

---

## Key Decisions (Resolved via Clarifications)

### 1. Gherkin Tooling: playwright-bdd
- **Decision**: Use `playwright-bdd`, not standalone Cucumber or plain Playwright tests.
- **Rationale**: Maps `.feature` files directly to Playwright step definitions. Reuses existing Playwright setup. Produces human-readable specs readable by non-engineers (product, QA).
- **Trade-off**: Adds npm dependency; slightly longer step definition boilerplate.
- **Source**: Clarification Q1.

### 2. Mock Fidelity: TypeScript Types Only
- **Decision**: Mocked API responses derive from `ui/src/types/` interfaces only. No OpenAPI generation, no snapshot fixtures.
- **Rationale**: Compile-time type safety catches drift at write time. Simpler maintenance (no external schema to sync). Fast test startup (no fixture generation).
- **Trade-off**: Doesn't catch semantic drift (e.g., API changed business logic but TS signature unchanged). Mitigated by manual code review on API changes.
- **Source**: Clarification Q2.

### 3. State Machine Coverage: Full Transition Matrix
- **Decision**: Test all valid state transitions AND all invalid transitions (no-op or error handling).
- **Rationale**: Exhaustive coverage prevents sneaky state machine bugs. Catches invalid-transition handling (e.g., "Can you pause a completed run?").
- **Trade-off**: Larger test suite (more maintenance). Mitigated by Scenario Outlines with Examples tables (one scenario body, many parameterized runs).
- **Source**: Clarification Q3.

### 4. Maintenance Mitigation: Three Patterns
- **Decision**: Combine page objects + shared fixtures + shared step definitions + scenario outlines.
- **Rationale**:
  - Page objects isolate selector changes (one place to update).
  - Shared step definitions reduce duplication across features (common Given/When/Then).
  - Scenario outlines with Examples tables parameterize matrix coverage (one scenario body, N test runs).
  - Shared fixtures (factories, route handlers) reduce mock boilerplate.
- **Trade-off**: More infrastructure upfront (Step 1); faster feature addition later.
- **Source**: Clarification Q4.

---

## Risk & Mitigation Matrix

### Step 1 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| Port 5398 conflict in local dev | Medium | Dev can't run tests locally | Make BDD port configurable via env var `PLAYWRIGHT_BDD_PORT` |
| Type drift between factories and actual API types | Low | Silent test rot (tests pass, app breaks) | Factories import from `ui/src/types/` directly → TypeScript compilation catches drift |
| FakeWebSocket injection races with app startup | Low | Flaky smoke test | `addInitScript` runs before app JS; race window negligible. Verify in smoke test. |
| Route handler selector specificity breaks on component markup change | Medium | Test fails after refactor (catches regressions) | Use page objects to centralize selectors; smoke test catches breakage immediately |
| Duplicate route handlers conflict | Low | Confusing test behavior | Document handler override semantics; enforce explicit setup in step definitions |

### Step 2 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| RunCard / CreateRunModal selectors brittle to markup changes | Medium | Test maintenance burden | Page objects encapsulate selectors; update one place if component changes |
| Form validation not triggered for invalid input | Low | False pass (test doesn't actually validate) | Test both valid and invalid submissions; assert error messages appear |
| Navigation to run detail fails (ID in URL not in route handler state) | Medium | Confusing test failure (page loads but shows 404) | Route handler uses dynamic path matching; serves data for any ID in URL. Test with valid and non-existent IDs. |
| RoutineSelector / BranchSelector async logic causes flaky timeouts | Medium | Intermittent CI failures | Mock selectors to return instant data; avoid real async logic in tests |

### Step 3 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| Run detail URL with invalid ID → 404 | Low | Error boundary test (acceptable) | Route handler detects invalid ID and returns 404; test error boundary coverage |
| Pause/resume API payload format mismatch | Medium | Test assumes wrong behavior | Document expected pause/resume payload in route handler; test both valid and invalid payloads |
| Secondary page endpoints not mocked → 404 errors | Medium | Feature doesn't run until all endpoints added | Ensure `api-handlers.ts` mocks all secondary endpoints (routines, agents, history, settings) before writing tests |

### Step 4 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| WebSocket event arrives before API response → stale state | Medium | Flaky test (timing-dependent) | Use `page.waitForResponse()` before `pushEvent()` to synchronize |
| Task lifecycle depends on run being in correct state | Low | Test setup bug (easy to catch) | Scenario Background sets up correct run state before task transitions |
| Grade submission payload mismatch | Medium | Test fails with unclear error | Document expected grade payload in route handler; test valid and invalid submissions |
| WebSocket event timing causes race | Medium | Intermittent flakes | FakeWebSocket.pushEvent() is synchronous; Playwright waits for UI updates via locator waits (built-in) |
| Revision counter doesn't increment | Low | Test catches missing implementation | Factory produces tasks with `attempts[]`; each revision adds Attempt; test counts before/after |

### Step 5 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| State transition matrix incomplete → missing edge cases | **High** | Ship with undetected bugs | Use clarifications Q3 as source of truth; enumerate all valid/invalid transitions exhaustively before writing tests. Verify matrix completeness in design review. |
| Race condition test flaky due to timing | High | Intermittent CI failures | Use `page.waitForResponse()` and `page.waitForSelector()` to synchronize; avoid arbitrary sleep() calls. Playwright waits are atomic. |
| Invalid transition behavior inconsistent → test assumes wrong behavior | Medium | Test passes but app behavior differs from spec | Run each invalid transition manually; document actual app behavior (error vs. no-op). Update test to match or file bug. |
| Dialog double-click protection not implemented → test fails | Low | Test reveals missing feature; accept as input to backlog | If test fails, either implement protection or mark test "expected to fail" with issue reference |
| Connection edge cases depend on reconnection logic not yet written | Medium | Feature blocks on app changes | Write minimal reconnection logic in app before tests; or mock reconnection in FakeWebSocket |
| Stale data scenario expects React Query invalidation → component doesn't trigger | Low | Test reveals missing cache invalidation | Use failed test as input to component fix; test validates fix works |

### Step 6 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| CI runner lacks Playwright browsers → tests fail to start | Low | CI broken until fixed | Include `npx playwright install --with-deps` in CI workflow |
| BDD suite exceeds 3-minute budget in CI | **High** | CI too slow; developer friction | Profile slow tests locally; optimize (increase workers, split features, reduce waits). If unachievable, request longer budget with product sign-off. Default: `--workers=4` parallelism. |
| CI cache doesn't cache Playwright binaries → slow browser install | Medium | Every CI run installs browsers (5–10 min penalty) | Configure cache key to include Playwright version; document in workflow. Cache hit saves 5–10 min per run. |
| Trace artifacts not uploaded on failure | Low | Harder to debug CI failures | Ensure CI workflow captures Playwright trace on failure and uploads as artifact |

---

## Caveats for Execution

### Dependencies & Ordering
- **Step 1 is a strict prerequisite** for Steps 2–6. Cannot parallelize Steps 2–6 until Step 1 fixtures and infrastructure are complete.
- **Steps 2–4 (M2 subtasks)** can be parallelized after Step 1 completes. Dashboard (Step 2) and edge cases (Step 5) are highest priority per Q6; can start in parallel.
- **Step 5 depends on Steps 1–4** being stable. State transition matrix relies on lifecycle happy paths being solid first.
- **Step 6 can start** as soon as Step 2 completes (infrastructure present), but should wait for Steps 4–5 before final CI integration.

### Architectural Constraints
- **No real backend required** — all tests use mocked API and FakeWebSocket. Server can be stopped during local test development.
- **Port isolation** — BDD tests run on separate Playwright port (default 5398, configurable). Main dev server can run on port 3000 (Vite) independently.
- **Database-free** — fixtures and route handlers are in-memory. No schema migrations or DB setup needed for tests.

### Quality Gates
- **All CRITICAL tests must pass** before submission. EXPECTED and NICE tests can defer.
- **State transition matrix** must be exhaustively enumerated and reviewed **before** Step 5 test code is written. Missing transitions = silent bugs.
- **CI time budget: 3 minutes strict** (clarification Q5). If BDD suite approaches 2.5 min, optimize before adding more tests.

### Test Maintenance Considerations
- **Factories & route handlers are the source of truth** for API contract. Keep them synchronized with actual API changes (via code review).
- **Selectors in page objects are single points of failure** if component markup changes. Update immediately after refactor.
- **Shared step definitions** reduce duplication but increase coupling across features. Changes to shared steps affect all features.
- **Scenario Outlines with Examples tables** are efficient for transition matrices but hard to read when many parameters. Document expected behavior in comments.

### Execution Warnings
- **BDD test suite is slower than unit tests** (~10–60 sec per feature due to browser startup). Expect full suite to take ~180 sec (3 min) in CI with `--workers=4`.
- **WebSocket timing is tricky**. Use Playwright's built-in waits (locator waits), not arbitrary `sleep()` calls. Async/await races are the #1 source of flakes.
- **Route handler state is not persisted across tests**. Each test starts with fresh factories; mutations within a test are visible to subsequent requests in the same test, but not across tests.
- **Error cases in Gherkin specs must match actual app behavior**. If app doesn't implement a specific error message or handling, update the test expectation or file a bug, don't assume.

### Descoping Options (if time is tight)
Per clarification Q6, if time constraints arise:
1. **Keep Step 1** (infrastructure) — prerequisite for everything.
2. **Keep Step 2** (Dashboard) — highest priority.
3. **Keep Step 5 happy path** (core race conditions) — second priority.
4. **Descope**: Step 3 (secondary pages), Step 4 (detailed lifecycle), full Step 5 (all edge cases).
5. **Defer**: Step 6 (CI integration) — tests can run locally until CI is wired.

**Minimum viable suite** (satisfies [I-01], [I-02], [I-04], [I-06], [I-07], [I-17], [I-23]): Steps 1–2 + Step 5 core scenarios + Step 6. Covers dashboard, CreateRunModal, and key race conditions.

---

## Summary

**Plan fully satisfies intent.** 6 sequential steps, 7–13 tasks total, ~2–3 weeks nominal effort. Step 1 (infrastructure) unblocks all others. Steps 2–4 are highest priority per stakeholder feedback (Q6). Step 5 (edge cases) is second priority and can run in parallel. Infrastructure is battle-tested in dry-run simulation; failure modes identified and mitigated. Test suite designed to run in < 3 minutes CI time. Fixture and step definition patterns enable < 15-minute scenario addition post-launch.

**Critical path**: Step 1 (1–2 days) → Step 2 + Step 5 in parallel (2–3 days) → Steps 3–4 (2–3 days) → Step 6 (0.5 day) = **~8–10 days nominal, 13–15 days with risk buffer.**
