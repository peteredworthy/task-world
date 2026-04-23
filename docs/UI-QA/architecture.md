# UI QA Test Suite — Architecture

## Overview

Two-layer testing architecture: **component-level** tests (Vitest + Testing Library, existing) and **workflow-level** tests (Playwright + `playwright-bdd`, new). The workflow layer is the primary deliverable — it exercises full user flows with mocked backend responses and Gherkin-based specifications.

## Test Layers

```
┌─────────────────────────────────────────────┐
│  Gherkin Feature Files (.feature)           │  Human-readable specs
│  ↓ parsed by playwright-bdd                 │
├─────────────────────────────────────────────┤
│  Step Definitions (TypeScript)              │  Playwright actions + assertions
│  ↓ use                                      │
├─────────────────────────────────────────────┤
│  Page Objects                               │  Encapsulate selectors + interactions
│  ↓ run against                              │
├─────────────────────────────────────────────┤
│  Vite Dev Server (no backend)               │  Real React app, mocked network
│  ↓ network intercepted by                   │
├─────────────────────────────────────────────┤
│  Playwright Route Handlers + FakeWS/SSE     │  Typed fixtures, controlled timing
└─────────────────────────────────────────────┘
```

## Directory Structure

```
ui/
├── tests/
│   ├── setup.ts                    # Existing Vitest setup
│   ├── README.md                   # Test suite documentation
│   ├── api/                        # Existing API client tests
│   ├── components/                 # Existing component tests
│   ├── hooks/                      # Existing hook tests
│   ├── lib/                        # Existing lib tests
│   ├── pages/                      # Existing page tests
│   ├── e2e/                        # Existing Playwright visual regression
│   │   └── __snapshots__/
│   └── bdd/                        # NEW: Gherkin workflow tests
│       ├── features/               # .feature files
│       │   ├── dashboard.feature
│       │   ├── run-detail.feature
│       │   ├── run-lifecycle.feature
│       │   ├── task-lifecycle.feature
│       │   ├── routines.feature
│       │   ├── agents.feature
│       │   ├── history.feature
│       │   ├── settings.feature
│       │   ├── run-transitions.feature
│       │   ├── task-transitions.feature
│       │   ├── edge-state-change.feature
│       │   ├── edge-dialogs.feature
│       │   ├── edge-connection.feature
│       │   └── edge-stale-data.feature
│       ├── steps/                  # Step definition files
│       │   ├── common.steps.ts     # Given/When/Then shared across features
│       │   ├── dashboard.steps.ts
│       │   ├── run-detail.steps.ts
│       │   ├── lifecycle.steps.ts
│       │   └── edge-cases.steps.ts
│       └── pages/                  # Page object models
│           ├── dashboard.page.ts
│           ├── run-detail.page.ts
│           ├── routines.page.ts
│           ├── agents.page.ts
│           └── modals.page.ts
├── tests/fixtures/                 # NEW: Shared test infrastructure
│   ├── factories.ts               # Typed factory functions
│   ├── api-handlers.ts            # Playwright route handlers
│   ├── fake-ws.ts                 # WebSocket mock
│   ├── fake-sse.ts                # SSE mock
│   └── scenarios.ts               # Pre-built state configurations
```

## Key Components

### 1. Factory Functions (`fixtures/factories.ts`)

Type-safe builders for API response objects. Each factory produces a valid default object; callers override specific fields.

```typescript
import type { Run, Task, Attempt, Step, Routine } from '../../src/types';

export function buildRun(overrides?: Partial<Run>): Run {
  return {
    id: 'run-001',
    name: 'Test Run',
    status: 'active',
    routine_id: 'routine-001',
    current_step_index: 0,
    steps: [buildStep()],
    // ... all required fields with sensible defaults
    ...overrides,
  };
}

export function buildTask(overrides?: Partial<Task>): Task { /* ... */ }
export function buildAttempt(overrides?: Partial<Attempt>): Attempt { /* ... */ }
export function buildStep(overrides?: Partial<Step>): Step { /* ... */ }
export function buildRoutine(overrides?: Partial<Routine>): Routine { /* ... */ }
```

### 2. API Route Handlers (`fixtures/api-handlers.ts`)

Playwright `route()` interceptors that serve factory-generated responses. Stateful where needed (e.g., POST to create a run adds it to the in-memory list).

```typescript
export function setupApiHandlers(page: Page, options?: {
  runs?: Run[];
  routines?: Routine[];
  agents?: Agent[];
}) {
  const state = {
    runs: options?.runs ?? [buildRun()],
    routines: options?.routines ?? [buildRoutine()],
    agents: options?.agents ?? [],
  };

  page.route('**/api/runs', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ json: state.runs });
    }
    // POST, PATCH, etc.
  });

  page.route('**/api/runs/*', (route) => { /* ... */ });
  page.route('**/api/routines', (route) => { /* ... */ });
  page.route('**/api/agents', (route) => { /* ... */ });

  return state; // allow tests to mutate state between steps
}
```

### 3. FakeWebSocket (`fixtures/fake-ws.ts`)

Intercepts the real WebSocket connection and gives tests control over when events arrive.

```typescript
export class FakeWebSocket {
  private listeners: Map<string, Function[]> = new Map();

  pushEvent(event: { type: string; data: unknown }) {
    // Triggers registered handlers as if server sent this message
  }

  pushBatch(events: Array<{ type: string; data: unknown }>) {
    this.pushEvent({ type: 'batch', data: { events } });
  }

  simulateDisconnect() { /* ... */ }
  simulateReconnect() { /* ... */ }
}
```

Injected via Playwright's `page.addInitScript()` to replace the native WebSocket constructor before the app loads.

### 4. Page Objects (`bdd/pages/`)

Encapsulate DOM selectors and interaction patterns. Insulate step definitions from markup changes.

```typescript
export class DashboardPage {
  constructor(private page: Page) {}

  async goto() { await this.page.goto('/'); }
  async getRunCards() { return this.page.locator('[data-testid="run-card"]').all(); }
  async clickCreateRun() { await this.page.click('[data-testid="create-run-btn"]'); }
  async getRunCardByName(name: string) { /* ... */ }
}
```

### 5. Gherkin Features (`bdd/features/`)

Human-readable specifications that double as executable tests. Use Scenario Outlines with Examples tables for parameterized coverage (e.g., state transition matrices). Shared step definitions in `common.steps.ts` reduce duplication across features.

```gherkin
Feature: Run Lifecycle
  As a developer using the orchestrator
  I want to manage run state transitions
  So that I can control agent execution

  Background:
    Given the API returns a routine "planning"
    And the WebSocket is connected

  Scenario: Create and start a new run
    Given I am on the Dashboard
    When I click "New Run"
    And I select routine "planning"
    And I fill in the run name "My Feature"
    And I click "Create"
    Then I should see a run card "My Feature" with status "draft"
    When I click "Start" on run "My Feature"
    Then I should see run "My Feature" with status "active"

  Scenario: Run completes while viewing detail
    Given I am viewing run "run-001" in detail
    And the run status is "active"
    When the server sends a WebSocket event "run_status_changed" with status "completed"
    Then the run status badge should show "completed"
    And the pause/resume buttons should be hidden
```

## Integration Strategy

### With Existing Vitest Tests

No overlap. Vitest tests cover component rendering, prop handling, utility functions. BDD tests cover user workflows across multiple components with mocked backend. Existing tests remain untouched.

### With Existing Playwright E2E Tests

Existing `ui/tests/e2e/` tests do visual regression (screenshot comparison). BDD tests do behavioral verification (interactions, state transitions, assertions on DOM content). They share the Playwright runner but use separate configs:

```
playwright.config.ts        → existing visual regression (port 5399)
playwright.bdd.config.ts    → new BDD workflow tests (port 5398)
```

### With CI

Both suites run in parallel in CI. BDD suite must complete in under 3 minutes (per clarification Q5). Uses `--workers=4` for parallelism across feature files (each feature is independent given its own route handler state).

## Mock Strategy

### API Mocking

All HTTP requests intercepted at the Playwright network layer via `page.route()`. No MSW, no service worker complexity. Route handlers are stateful — mutations (POST, PATCH, DELETE) update in-memory state, subsequent GETs reflect changes.

### WebSocket Mocking

`page.addInitScript()` replaces `window.WebSocket` with `FakeWebSocket` before React mounts. Tests push events via the fake instance. The app code sees a standard WebSocket interface.

### SSE Mocking

Similar to WebSocket — intercept the `/api/activity/stream` route and serve a controllable `ReadableStream`. Tests can push events, simulate drops, and test reconnection.

### Timing Control

Edge-case tests need precise control over when events arrive relative to user actions. Pattern:

```typescript
// User clicks submit (mutation in flight)
await dashboardPage.clickCreateRun();
// While mutation is pending, push a state change
fakeWs.pushEvent({ type: 'run_status_changed', data: { id: 'run-001', status: 'cancelled' } });
// Verify UI handles the conflict gracefully
await expect(page.locator('.error-toast')).toBeVisible();
```

## Configuration

### `playwright.bdd.config.ts`

```typescript
import { defineConfig } from '@playwright/test';
import { defineBddConfig } from 'playwright-bdd';

const testDir = defineBddConfig({
  features: 'tests/bdd/features/**/*.feature',
  steps: 'tests/bdd/steps/**/*.steps.ts',
});

export default defineConfig({
  testDir,
  use: {
    baseURL: 'http://localhost:5398',
  },
  webServer: {
    command: 'npm run dev -- --port 5398',
    url: 'http://localhost:5398',
    reuseExistingServer: false,
  },
});
```

### Package additions

```json
{
  "devDependencies": {
    "playwright-bdd": "^8.0.0"
  },
  "scripts": {
    "test:bdd": "playwright test --config playwright.bdd.config.ts",
    "test:bdd:ui": "playwright test --config playwright.bdd.config.ts --ui"
  }
}
```

## Scenario Outline Pattern for State Transitions

Per clarification Q3, run and task lifecycles are tested exhaustively via Scenario Outlines with Examples tables. This covers all valid transitions and verifies invalid transitions are rejected or ignored.

```gherkin
Scenario Outline: Run state transition <from> → <to>
  Given a run in "<from>" state
  When the transition "<action>" is triggered
  Then the run state should be "<to>"

  Examples:
    | from      | action   | to        |
    | draft     | start    | active    |
    | active    | pause    | paused    |
    | paused    | resume   | active    |
    | active    | complete | completed |
    | active    | cancel   | cancelled |
    # Invalid transitions
    | completed | start    | completed |
    | cancelled | resume   | cancelled |
```

## Traceability

All decisions confirmed via clarification Q&A (see `clarifications.md`).

| Architecture Decision | Intent Traces | Clarification |
|----------------------|---------------|---------------|
| Playwright + playwright-bdd | [I-04], [I-18], [I-19], [I-23] | Q1 |
| Playwright route() mocking | [I-17], [I-22], [I-24] | Q2 |
| FakeWebSocket/SSE | [I-03], [I-09], [I-10], [I-24] | — |
| Factory functions (types-only) | [I-22], [I-34] | Q2 |
| Page objects + shared steps | [I-26], [I-34] | Q4 |
| Scenario outlines with examples | [I-25], [I-31] | Q3, Q4 |
| Full state transition matrix | [I-25], [I-31] | Q3 |
| Separate BDD config | [I-18], [I-21] | — |
| Feature files as specs | [I-04], [I-19], [I-32] | — |
| CI budget < 3 min | [I-20] | Q5 |
| Priority: Dashboard → Edge cases → RunDetail | [I-06] | Q6 |
