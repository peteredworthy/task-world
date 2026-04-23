# UI QA Test Suite — Dry-Run Notes

Consolidated simulation results, failure mode analysis, and hardening recommendations for all six steps.

---

## Step 1: Infrastructure and Fixtures (M1)

### Simulation Results

**What Happens**: Installing `playwright-bdd`, configuring a separate Playwright config for BDD tests, creating factory functions, route handlers, WebSocket/SSE mocks, and a smoke test feature file to prove the Gherkin pipeline works.

**Expected Outcomes**:
- `npm run test:bdd` succeeds
- Factory functions produce valid typed objects matching `ui/src/types/` interfaces
- Route handlers respond correctly to Playwright network interception
- FakeWebSocket can push events and trigger app event handlers
- Smoke feature file runs green end-to-end

**Test Points**:
- Factories imported types; compile-time type safety verified
- Port 5398 used for BDD config (configurable)
- Workers set to 4 for parallel test execution
- `addInitScript` injects FakeWebSocket before app initialization

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| Factory function state | `ui/tests/fixtures/factories.ts` | RW | In-memory only; no persistence needed. Factories recreate state for each test. |
| Route handler state | `ui/tests/fixtures/api-handlers.ts` | RW | In-memory map; mutations update state for subsequent reads within a test. Reset between tests. |
| FakeWebSocket events | `ui/tests/fixtures/fake-ws.ts` | W | Event buffer; app reads via standard WebSocket.onmessage. |
| FakeSSE stream | `ui/tests/fixtures/fake-sse.ts` | W | Stream object; app reads via EventSource. |
| **Conclusion** | N/A | N/A | **No new DB columns needed.** All state is test-scoped, in-memory. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| Port 5398 conflict during local dev | Medium | Make BDD test port configurable via env var `PLAYWRIGHT_BDD_PORT`. |
| `playwright-bdd` version incompatibility | Low | Pin `playwright-bdd` to known-compatible version; document in package.json. |
| Type drift between factories and actual API response types | Low | Factories import from `ui/src/types/` directly → compile-time catch. |
| FakeWebSocket injection races with app startup | Low | `addInitScript` runs before any page JS; race window is negligible. Confirm in smoke test. |
| Route handler selector specificity fails on minor component changes | Medium | Use page objects to centralize selectors; smoke test catches breakage. |
| Duplicate route handlers for same endpoint cause conflicts | Low | Document that later-registered handlers override earlier ones; test setup must be explicit. |

### Cross-Step Dependencies

- **Step 2 depends on Step 1**: Dashboard workflows require factories, route handlers, and common step definitions from Step 1.
- **Steps 3–5 depend on Step 1**: All workflow features depend on infrastructure.
- **Step 4 (CI integration) depends on Step 1**: Must verify BDD pipeline is wired correctly in CI.

### Plan Changes Recommended

**No changes to Step 1 plan recommended.** Core infrastructure is stable. Potential enhancements (post-M1):
- Add fixtures for multi-user scenarios (concurrent API requests from different agents).
- Document how to extend route handlers for custom endpoints (if future workflows need them).

---

## Step 2: Dashboard & CreateRunModal Workflows (M2a)

### Simulation Results

**What Happens**: Implement Gherkin features for the highest-priority workflows: Dashboard browsing (run list, filtering, search) and CreateRunModal (open, fill, submit). Use page objects to isolate selectors.

**Expected Outcomes**:
- Dashboard shows run cards from mocked API response
- Filter by status, search by name work correctly
- Clicking a run card navigates to run detail
- CreateRunModal opens via "New Run" button
- Form validation prevents invalid submissions
- Created run appears in list after submission
- Modal closes on cancel or successful submission

**Test Points**:
- Page objects (dashboard.page.ts, modals.page.ts) encapsulate selectors
- Step definitions reuse common patterns from Step 1
- Route handlers stateful: POST creates run, subsequent GET reflects it
- Empty state handled when no runs exist

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| Run list (in-memory) | Route handler state | RW | Array of Run objects; POST adds, GET returns filtered list. Reset per test. |
| Filter/search params | URL state or component state | R | Tests don't persist; each scenario starts fresh. |
| **Conclusion** | N/A | N/A | **No new DB columns.** In-memory mocking sufficient. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| Run card selectors change if RunCard component markup changes | Medium | Page objects isolate selectors; update one place if markup changes. |
| CreateRunModal form validation not triggered for invalid input | Low | Test both valid and invalid submissions; assert error messages appear. |
| Route handler state not reset between scenarios | Low | Playwright creates fresh page + fresh route handlers per scenario. No shared state leaks. |
| Navigation to run detail fails if ID in URL is not in route handler state | Medium | Ensure route handler serves data for the ID in the URL; use dynamic route matching. |
| CreateRunModal doesn't honor RoutineSelector/BranchSelector async loads | Medium | Mock selectors to return instant data; avoid real async logic in tests. |

### Cross-Step Dependencies

- **Step 2 depends on Step 1**: Factories, route handlers, and common steps are prerequisites.
- **Step 3 depends on Step 2**: Run detail page objects extend dashboard patterns.
- **Steps 4–5 depend on Step 2**: Run lifecycle and edge cases build on dashboard setup.

### Plan Changes Recommended

**No changes to core plan.** Refinements based on implementation:
- If RoutineSelector or BranchSelector have async logic, mock those endpoints to return instant responses (avoid flaky timeouts).
- If CreateRunModal has complex validation, consider writing unit tests in Vitest separately; BDD tests verify happy path + one validation error scenario.

---

## Step 3: Run Detail & Secondary Pages (M2b + M2e)

### Simulation Results

**What Happens**: Implement features for Run Detail page (step timeline, task list, attempt history, pause/resume/cancel) and secondary pages (Routines, Agents, History, Settings).

**Expected Outcomes**:
- Run detail page shows step timeline with tasks
- Task cards can be expanded to show detail
- Attempt history and timeline displayed
- Pause/resume/cancel buttons trigger state changes
- Secondary pages (Routines, Agents, History, Settings) render with mocked data
- Every page has at least one scenario

**Test Points**:
- Run detail page requires valid run ID in URL → route handlers serve correct run data
- Pause/resume/cancel are POST mutations → route handlers update in-memory state
- Secondary pages may have minimal data → empty state scenarios
- Modal open/close patterns (Settings) tested

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| Run detail (in-memory) | Route handler state | RW | Single Run object; mutations update its status. |
| Task list (in-memory) | Route handler state (nested in Run) | RW | Array of Task objects nested in Run; updates propagate. |
| Attempt history (in-memory) | Route handler state (nested in Task) | RW | Array of Attempt objects; grade updates add new Attempt. |
| Secondary page data | Route handler state | RW | Routines, Agents, History lists; all in-memory. |
| **Conclusion** | N/A | N/A | **No new DB columns.** All mocked. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| Run detail URL has invalid ID → 404 or blank page | Low | Route handler should detect invalid ID and return 404; test error boundary. |
| Pause/resume API endpoint requires specific payload | Medium | Document expected payload in route handler; test both valid and invalid payloads. |
| StepTimeline or TaskDetailCard selectors brittle to markup changes | Medium | Page objects encapsulate; update test selectors if component changes. |
| Secondary pages have no API endpoints mocked → 404 errors | Medium | Ensure `api-handlers.ts` mocks all secondary page endpoints (routines list, agents list, etc.). |
| Settings modal doesn't persist preference change (toggle SSE/polling) | Low | Mocked API; test that toggle changes route behavior, not that setting persists on reload. |

### Cross-Step Dependencies

- **Step 3 depends on Step 1-2**: Uses factories, route handlers, and page object patterns.
- **Step 4 (lifecycle) depends on Step 3**: Run detail page objects used in lifecycle scenarios.
- **Step 5 (edge cases) depends on Step 3**: Dialog and state-change edge cases use run detail setup.

### Plan Changes Recommended

**Potential enhancement**: If secondary pages share common patterns (list view, detail view, filters), define a generic page object base class to reduce duplication. **Apply if time permits; defer if Step 3 is on schedule.**

---

## Step 4: Run & Task Lifecycle (M2c + M2d)

### Simulation Results

**What Happens**: Implement Gherkin specs for full run and task lifecycle workflows. Lifecycles driven by mocked API responses and WebSocket events. Verify UI reflects backend state changes in real-time.

**Expected Outcomes**:
- Run lifecycle: draft → active → verifying → grading → completed (or paused ↔ active, or cancelled)
- Task lifecycle: queued → building → verifying → completed (or failed → revision)
- WebSocket events trigger UI updates without page reload
- Attempt/revision cycles work end-to-end
- Checklist table, grade badges, and prompt copy box display correctly at each stage

**Test Points**:
- FakeWebSocket pushes `run_status_changed` and `task_status_changed` events
- Route handlers coordinate with WebSocket events (don't race)
- Status badges update in real-time on WebSocket event
- Revision cycle (fail → retry) tests full loop
- Grades submission accepted by route handler

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| Run status | Route handler state | RW | Transitioned by mutations; WebSocket event pushed to sync UI. |
| Task status | Route handler state (nested) | RW | Transitioned by mutations; WebSocket event pushed. |
| Attempt/Revision count | Route handler state (nested in Task) | RW | Incremented on revision; grades stored in Attempt. |
| WebSocket event history | FakeWebSocket buffer | W | Event log for debugging; not persisted. |
| **Conclusion** | N/A | N/A | **No new DB columns.** Mocked state machine. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| WebSocket event arrives before API response → UI shows stale state | Medium | Test must wait for route handler response before asserting on WebSocket update. Use `page.waitForResponse()` before `pushEvent()`. |
| Task lifecycle depends on run being in correct state | Low | Scenario Background sets up correct run state before task transitions. |
| Grade submission payload mismatch → route handler rejects | Medium | Define expected grade payload in route handler; test valid and invalid submissions. |
| WebSocket event timing causes race in tests | Medium | FakeWebSocket.pushEvent() is synchronous; Playwright waits for UI updates via locator assertions (built-in waits). |
| Status badge doesn't update after WebSocket event | Low | Test uses `page.waitForSelector()` to wait for updated badge; catch if badge selector changes. |
| Revision counter doesn't increment correctly | Low | Factory produces tasks with `attempts[]`; each revision adds Attempt; test counts before/after. |

### Cross-Step Dependencies

- **Step 4 depends on Steps 1-3**: Uses all existing infrastructure, page objects, and factories.
- **Step 5 (edge cases) depends on Step 4**: Lifecycle scenarios provide baseline; edge cases inject failure modes. State transition matrix depends on lifecycle happy paths being stable.

### Plan Changes Recommended

**No changes.** If lifecycle scenarios are flaky due to timing, enhance FakeWebSocket or route handlers to support explicit event ordering:
- Add `page.pushEventSequence(events)` method to FakeWebSocket for orchestrated event chains.
- Document timing patterns in `ui/tests/README.md` (Step 6).

---

## Step 5: Edge Cases & State Transition Matrix (M3)

### Simulation Results

**What Happens**: Test failure modes, race conditions, and exhaustively cover the state machine with full transition matrices (valid + invalid), state changes during interaction, dialog edge cases, connection failures, and stale data handling.

**Expected Outcomes**:
- Full run state transition matrix passes: all valid transitions work, invalid transitions produce no-op or error
- Full task state transition matrix passes: similar coverage
- Race condition scenarios execute: run completes while modal open, task state changes during form submit, etc.
- Dialog edge cases: double-click protection, modal closes on navigate-away, etc.
- Connection edge cases: WebSocket disconnect/reconnect shows banner, SSE fallback to polling, API errors handled
- Stale data: WebSocket updates run card without page reload, cache invalidation triggers

**Test Points**:
- Scenario Outlines with Examples tables cover state transitions parameterized
- FakeWebSocket.simulateDisconnect() / simulateReconnect() for connection tests
- Route handlers configurable to return error responses (500, 404)
- Each edge case scenario documents specific race condition it tests

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| State transition history | In-memory (route handler) | W | Logged for debugging; not persisted. |
| Connection state (WS connected/disconnected) | FakeWebSocket | RW | Simulated; app detects via onclose/onopen. |
| Error response config | Route handler config | RW | Set per test to return 500, 404, etc. |
| **Conclusion** | N/A | N/A | **No new DB columns.** Test-scoped state only. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| State transition matrix incomplete → missing edge cases | Medium | Use clarification Q3 as source of truth: enumerate all valid/invalid transitions exhaustively. Verify matrix is complete before writing tests. |
| Race condition test flaky due to timing | High | Use `page.waitForResponse()` and `page.waitForSelector()` to synchronize; avoid arbitrary delays (sleep). |
| Invalid transition behavior inconsistent → test assumes wrong behavior | Medium | Run each invalid transition scenario and document actual app behavior (error vs. no-op). Update test accordingly. |
| Dialog double-click protection not implemented → test fails | Low | If test fails, either implement protection or mark test as "expected to fail" with issue reference. |
| Connection edge cases depend on reconnection logic not yet written | Medium | Write minimal reconnection logic in app before tests; tests validate that logic. Or mock reconnection in FakeWebSocket. |
| Stale data scenario expects React Query invalidation → component doesn't trigger | Low | Test may reveal missing cache invalidation; use as input to component fix. |

### Cross-Step Dependencies

- **Step 5 depends on Steps 1-4**: All infrastructure and happy-path scenarios are prerequisites.
- **Step 6 (CI integration) depends on Step 5**: Full test suite must pass before wiring into CI.
- **Critical dependency**: State transition matrix must be correct before tests are written; any missing transitions will cause false passes or failures.

### Plan Changes Recommended

**Before writing tests, audit state transition matrix**:
1. Enumerate all valid run state transitions → map to test scenarios
2. Enumerate all invalid run state transitions → map to error/no-op test scenarios
3. Repeat for task state transitions
4. Cross-reference with implementation to confirm behavior

**If transition behavior differs from expected**, document why in test comment and align with product/engineering team.

---

## Step 6: CI Integration & Documentation (M4)

### Simulation Results

**What Happens**: Wire the BDD test suite into CI so tests run automatically on every push. Update documentation. Verify < 3-minute execution time.

**Expected Outcomes**:
- CI workflow configuration updated to install Playwright browsers and run `npm run test:bdd`
- BDD suite completes in < 3 minutes in CI environment
- Trace artifacts uploaded on test failure
- `ui/tests/README.md` updated with comprehensive documentation
- Coverage summary table shows which pages/components have workflow-level coverage

**Test Points**:
- CI runner installs Playwright browsers correctly
- `npm run test:bdd` runs with `--workers=4` parallelism
- Test time measured and verified < 3 minutes
- Trace viewer artifact download works on failure
- README instructions can be followed by new contributor

### Persistence Mapping Audit

| State Field | Location | R/W | Notes |
|---|---|---|---|
| CI configuration | `.github/workflows/test.yml` (or equivalent) | RW | Source-controlled; static config. |
| Playwright browser cache | CI runner filesystem | RW | Cached between runs; cleared if cache keys change. |
| Test results and logs | CI artifact storage | W | Uploaded on failure; read for debugging. |
| Coverage summary | `ui/tests/README.md` | W | Documentation; updated at end of Step 6. |
| **Conclusion** | N/A | N/A | **No new DB columns.** CI infrastructure. |

### Failure Mode Analysis

| Failure Mode | Likelihood | Hardening |
|---|---|---|
| CI runner lacks Playwright browsers → tests fail to start | Low | CI workflow must include `npx playwright install --with-deps` step. |
| BDD suite exceeds 3-minute budget in CI | Medium | Profile slow tests locally; optimize (increase workers, split features, reduce waits) or accept longer budget with product sign-off. |
| CI cache doesn't cache Playwright binaries → every run installs browsers | Medium | Configure cache key to include Playwright version; document in workflow. |
| Trace artifact upload fails on flaky test → hard to debug | Low | Verify artifact upload syntax is correct; test locally with `npx playwright test --trace on`. |
| README documentation is incomplete or outdated | Medium | Have non-engineer (QA/product) follow README to run tests; collect feedback before merging. |

### Cross-Step Dependencies

- **Step 6 depends on Steps 1-5**: All test artifacts must be in place and passing locally before wiring into CI.
- **No dependencies on Step 6**: CI integration is final step; no later steps depend on it.

### Plan Changes Recommended

**If BDD suite exceeds 3-minute budget in CI**:
1. Profile slow tests: run `npm run test:bdd -- --reporter=list` to see per-feature times
2. Parallelize further: increase `--workers` beyond 4 (if CI runner supports it)
3. Split slow features: split `run-transitions.feature` or `edge-cases.feature` into separate files to parallelize
4. Reduce waits: audit Playwright waits; confirm none are arbitrary delays

**Document all CI tuning decisions in `ui/tests/README.md` for future maintainers.**

---

## Consolidated Failure Mode Analysis

### High-Risk Failure Modes (Likelihood: Medium–High)

| Failure Mode | Steps Affected | Impact | Mitigation |
|---|---|---|---|
| State transition matrix incomplete | 5 | Tests pass but edge cases untested in prod | Enumerate all transitions exhaustively before writing tests; cross-check with product team |
| Race condition tests flaky due to timing | 4, 5 | Tests fail intermittently; hard to debug | Use `page.waitForResponse()` and `waitForSelector()` to synchronize; avoid sleep() |
| Port conflicts or resource contention in CI | 1, 6 | CI fails sporadically | Make ports configurable; reserve test port ranges; document in workflow |
| Selectors brittle to component markup changes | 2, 3, 5 | Tests break when UI changes unrelated to test | Encapsulate selectors in page objects; review on component changes |
| Grade submission payload mismatch | 4 | Lifecycle tests fail; payload format unclear | Document expected payload; test both valid and invalid submissions |
| WebSocket event timing causes races | 4, 5 | Tests pass locally but fail in CI | Ensure FakeWebSocket.pushEvent() coordinates with route handler; use explicit waits |

### Medium-Risk Failure Modes (Likelihood: Low–Medium)

| Failure Mode | Steps Affected | Mitigation |
|---|---|---|
| Route handler state leaks between tests | 1–5 | Playwright creates fresh page per scenario; reset route handlers explicitly if needed |
| Type drift between factories and actual API types | 1 | Factories import from `ui/src/types/` directly; compile-time catch |
| Secondary page endpoints not mocked | 3 | Ensure `api-handlers.ts` mocks all secondary endpoints; test 404 scenarios |
| FakeWebSocket injection races with app startup | 1 | `addInitScript` runs before any app JS; race window negligible; smoke test confirms |
| Invalid transition behavior undocumented | 5 | Test may fail if app behavior differs from test assumptions | Document actual behavior in test comment; align with implementation |

---

## Cross-Step Risk Synthesis

### Dependencies Chain

```
Step 1 (Infrastructure)
  ↓
  ├─→ Step 2 (Dashboard)
  ├─→ Step 3 (Run Detail)
  └─→ Steps 4–5 (Lifecycle & Edge Cases)
        ↓
        → Step 6 (CI Integration)
```

**Risk**: If Step 1 infrastructure is incomplete (missing FakeWebSocket, route handlers, factories), all later steps are blocked. **Mitigation**: Step 1 smoke test validates pipeline end-to-end; no blocking surprises in later steps.

### Cross-Step State Consistency

**Issue**: Route handler state must be consistent across multiple steps. Example:
- Step 2 (Dashboard) creates a run via POST
- Step 3 (Run Detail) expects that run in route handler state
- Step 4 (Lifecycle) transitions that run through states

**Risk**: If route handler state is reset between steps, state is lost. **Mitigation**: Route handler state is per-test (per page/test context); each step starts with fresh state. Factories produce correct initial state. No state leaks between tests.

### Edge Case Interaction with Lifecycle

**Issue**: Step 5 edge cases assume Step 4 happy-path scenarios are stable. Example:
- Run lifecycle happy path works (Step 4)
- Edge case: run completes while modal open (Step 5)

**Risk**: If lifecycle is broken, edge case test is unreliable. **Mitigation**: Edge case tests don't depend on Step 4 tests passing; they set up their own state via factories and route handlers. Tests are independent.

### Timing Issues Cascade

**Issue**: FakeWebSocket timing is critical:
- Step 1: FakeWebSocket defined
- Step 4: FakeWebSocket.pushEvent() used in lifecycle
- Step 5: FakeWebSocket.simulateDisconnect() used in connection edge cases

**Risk**: If FakeWebSocket has timing bugs, failures cascade through Steps 4–5. **Mitigation**: Step 1 smoke test exercises FakeWebSocket.pushEvent(); Step 4 confirms WebSocket-driven UI updates work. Step 5 adds disconnect simulation; simpler than basic event push, so lower risk.

---

## Plan Changes Recommended

### Critical Changes (Must Apply)

1. **Step 1**: Ensure FakeWebSocket.pushEvent() is synchronous and test-friendly. If async, switch to synchronous implementation or document precise timing expectations.
   - **Confirmation**: Apply — FakeWebSocket designed as synchronous in-memory class.

2. **Step 5**: Before writing state transition matrix tests, enumerate all valid + invalid transitions exhaustively. Use a matrix document (separate from feature files) to confirm completeness.
   - **Confirmation**: Apply — create `docs/UI-QA/state-transition-matrix.md` before Step 5 implementation.

### Expected Changes (Plan to Apply)

3. **Step 2**: If RoutineSelector or BranchSelector have async logic, mock to return instant data. Defer async testing to unit tests (Vitest).
   - **Confirmation**: Apply if selector logic is async; defer otherwise.

4. **Step 3**: Consolidate secondary page patterns (Routines, Agents, History) into reusable page object base class if duplication appears during implementation.
   - **Confirmation**: Apply if 3+ pages share selectors; otherwise inline selectors in respective page objects.

5. **Step 4**: Document expected payload format for grade submission in route handler comment. Test both valid and invalid payloads.
   - **Confirmation**: Apply — document payload in `api-handlers.ts` before Step 4 tests write.

6. **Step 5**: Create `state-transition-matrix.md` mapping all valid + invalid transitions to test scenarios. Use as checklist for feature files.
   - **Confirmation**: Apply — ensures completeness and prevents missing edge cases.

7. **Step 6**: If BDD suite exceeds 3-minute CI budget, implement one of: (a) increase `--workers` beyond 4, (b) split slow features, (c) optimize Playwright waits, (d) accept longer budget with product sign-off.
   - **Confirmation**: Measure locally first; apply optimization strategy if needed.

### Nice-to-Have Changes (Defer if Time-Constrained)

8. **Post-M3**: Add fixtures for multi-user scenarios (concurrent API requests from different agents; tests current single-agent mocking).

9. **Post-M4**: Integrate BDD test coverage metrics into CI dashboard (show % of pages/components covered).

---

## Summary: Simulation-Based Validation

### What Works as Designed

✅ Step 1 infrastructure (factories, route handlers, FakeWebSocket) is sound and type-safe.

✅ Page object pattern encapsulates selectors; reduces maintenance burden if components change.

✅ Scenario Outline with Examples tables (Step 5) efficiently covers state transition matrix without duplication.

✅ FakeWebSocket enables real-time event testing without actual WebSocket server.

✅ In-memory route handler state is sufficient for test scope; no persistence layer needed.

### What Needs Careful Attention

⚠️ **State transition matrix completeness** (Step 5): Must enumerate all transitions before writing tests. Missing transitions = untested edge cases.

⚠️ **Race condition timing** (Steps 4–5): Tests must use explicit synchronization (waitForResponse, waitForSelector); avoid sleep().

⚠️ **CI time budget** (Step 6): Measure locally with `--workers=4` and extrapolate to CI environment. Profile if > 3 minutes.

⚠️ **Selector brittleness** (Steps 2–3): Page objects reduce risk but don't eliminate it. Review selectors if component markup changes.

### What Needs Validation in Actual Implementation

- FakeWebSocket synchronicity and timing correctness
- Route handler payload validation (especially grades)
- CI environment browser installation and caching
- Actual state transition behavior (some invalid transitions might error vs. no-op)

---

## Approval Gate

**Plan changes recommended above are ready for approval.**

Before proceeding with implementation:

- [x] Confirm Step 1 FakeWebSocket will be synchronous (no timing issues)
- [x] Confirm state-transition-matrix.md will be created as source of truth for Step 5
- [x] Confirm grade submission payload format is documented in api-handlers.ts
- [x] Confirm Step 6 CI time budget and optimization strategy

All conditions met: **Ready to implement Steps 1–6.**

---

## Gap Application Status

All critical and significant gaps from this dry-run analysis have been applied to
YAML step files in `routines/UI-QA/steps/`. Status per gap:

### Critical Changes

1. **Step 1 — FakeWebSocket must be synchronous**
   - Applied to step files: YES
   - Location: `step-01-infrastructure.yaml` T-04 — requirement R11 requires synchronous
     documentation; auto_verify checks for the comment; task_context mandates synchronous
     pushEvent() with explicit consequence (timing races in Steps 4–5).

2. **Step 5 — Create state-transition-matrix.md before writing tests**
   - Applied to step files: YES
   - Location: `step-05-edge-cases.yaml` T-01 — blocking task that creates the matrix
     document BEFORE any transition feature files are written. R1 is critical requirement.

### Expected Changes

3. **Step 2 — Mock RoutineSelector/BranchSelector async logic**
   - Applied to step files: YES
   - Location: `step-02-dashboard.yaml` T-01 — task_context explicitly requires mocking
     /api/routines and /api/agents to return instant responses; Background step added.

4. **Step 3 — Consolidate secondary page base class if 3+ pages share selectors**
   - Applied to step files: YES
   - Location: `step-03-run-detail.yaml` T-01 — explicit rule: extract base-list.page.ts
     if routines, agents, and history pages all need the same selectors.

5. **Step 4 — Document grade submission payload in api-handlers.ts**
   - Applied to step files: YES
   - Location: `step-04-lifecycle.yaml` T-01 — blocking task that reads TaskDetailCard
     component, documents the exact payload shape as a comment in api-handlers.ts,
     and adds the grades endpoint handler. R1 is critical.

6. **Step 5 — state-transition-matrix.md as checklist for feature files**
   - Applied to step files: YES (same as Critical Change #2 above)

7. **Step 6 — CI time budget and optimization strategy**
   - Applied to step files: YES
   - Location: `step-06-ci.yaml` T-02 — dedicated task to measure execution time,
     document it, and apply one of four optimization strategies if > 2 min locally.

### High-Risk Failure Mode Hardenings

- **Port conflict** → `step-01-infrastructure.yaml` R2 + auto_verify checks PLAYWRIGHT_BDD_PORT env var
- **Dynamic route matching** → `step-01-infrastructure.yaml` R7 + auto_verify for wildcard pattern; reinforced in `step-02-dashboard.yaml` T-01
- **Secondary page endpoints not mocked** → `step-03-run-detail.yaml` T-01 with explicit endpoint list
- **WS event before API response** → `step-04-lifecycle.yaml` T-02 timing rule, T-04 step definition requirement
- **Race condition timing (no sleep)** → `step-04-lifecycle.yaml` and `step-05-edge-cases.yaml` auto_verify checks for sleep() usage
- **CI browser install** → `step-06-ci.yaml` T-01 mandates --with-deps flag
- **CI browser caching** → `step-06-ci.yaml` T-01 requires version-aware cache key
- **Error injection for edge cases** → `step-05-edge-cases.yaml` T-04 R8 requires errorRoutes config in api-handlers.ts

