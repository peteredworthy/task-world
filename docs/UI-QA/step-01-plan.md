# Step Plan: Infrastructure and Fixtures (M1)

## Purpose

Set up shared test infrastructure that all later milestones depend on: typed factory functions, Playwright route handlers, WebSocket/SSE mocks, and `playwright-bdd` configuration. One smoke `.feature` file proves the Gherkin-to-Playwright pipeline works end-to-end.

## Prerequisites

- None — this is the first step with no dependencies.
- Existing Playwright config at `ui/playwright.config.ts` (visual regression tests).
- Existing types at `ui/src/types/` (Run, Task, Attempt, Step, Routine, Agent).

## Functional Contract

### Inputs

- TypeScript type definitions from `ui/src/types/` (Run, Task, Attempt, Step, Routine, Agent, etc.)
- Existing Playwright setup in `ui/tests/e2e/`
- Existing Vitest test infrastructure in `ui/tests/`

### Outputs

- `ui/tests/fixtures/factories.ts` — factory functions (`buildRun`, `buildTask`, `buildAttempt`, `buildStep`, `buildRoutine`, `buildAgent`) producing valid typed objects with sensible defaults and `Partial<T>` overrides.
- `ui/tests/fixtures/api-handlers.ts` — reusable Playwright `route()` interceptors for all API endpoints (`/api/runs`, `/api/runs/:id`, `/api/routines`, `/api/agents`). Stateful: mutations update in-memory state, subsequent GETs reflect changes.
- `ui/tests/fixtures/fake-ws.ts` — `FakeWebSocket` class injected via `page.addInitScript()`. Supports `pushEvent()`, `pushBatch()`, `simulateDisconnect()`, `simulateReconnect()`.
- `ui/tests/fixtures/fake-sse.ts` — SSE mock for `/api/activity/stream`. Controllable `ReadableStream` with event push and drop simulation.
- `ui/playwright.bdd.config.ts` — separate Playwright config for BDD tests (port 5398, `--workers=4`).
- `ui/tests/bdd/features/smoke.feature` — smoke test proving Gherkin pipeline works.
- `ui/tests/bdd/steps/common.steps.ts` — shared step definitions (Given API returns runs, Given WebSocket connected, etc.).
- `ui/tests/README.md` — documentation of fixture patterns, how to add scenarios.
- `playwright-bdd` added to `devDependencies`.
- npm scripts: `test:bdd`, `test:bdd:ui`.

### Error Cases

- `playwright-bdd` version incompatibility with existing Playwright version — pin compatible version.
- Port 5398 conflict with other dev servers — configurable via env var.
- Type drift between `ui/src/types/` and factory functions — caught at compile time since factories import and return the same types.
- `FakeWebSocket` injection races with app initialization — `addInitScript` runs before any page JS, so WebSocket constructor is replaced before React mounts.

## Tasks

1. Install `playwright-bdd` as devDependency in `ui/package.json`.
2. Create `ui/playwright.bdd.config.ts` with BDD-specific config (features glob, steps glob, webServer on port 5398, workers=4).
3. Create `ui/tests/fixtures/factories.ts` with typed factory functions for all API response types.
4. Create `ui/tests/fixtures/api-handlers.ts` with stateful route interceptors.
5. Create `ui/tests/fixtures/fake-ws.ts` with `FakeWebSocket` class.
6. Create `ui/tests/fixtures/fake-sse.ts` with SSE mock.
7. Create `ui/tests/bdd/steps/common.steps.ts` with shared Given/When/Then definitions.
8. Create `ui/tests/bdd/features/smoke.feature` — minimal scenario that loads dashboard with mocked data and verifies a run card appears.
9. Create `ui/tests/README.md` documenting fixture patterns and how to extend.
10. Add `test:bdd` and `test:bdd:ui` scripts to `package.json`.
11. Verify smoke feature runs green.

## Verification Approach

### Auto-Verify

- `npm run test:bdd` passes — smoke feature file runs green.
- TypeScript compilation succeeds for all fixture files (no type errors).
- Factory functions produce objects matching `ui/src/types/` interfaces.

### Manual Verification

- `npx playwright test --config playwright.bdd.config.ts` executes smoke.feature.
- Route handlers respond correctly when Playwright intercepts requests.
- `FakeWebSocket.pushEvent()` triggers app event handlers.

## Context & References

- Plan: `docs/UI-QA/plan.md` — Milestone 1 specification
- Architecture: `docs/UI-QA/architecture.md` — directory structure, mock strategy, config
- Clarification Q1: Use `playwright-bdd` (confirmed)
- Clarification Q2: TypeScript types only for fixtures (no OpenAPI generation)
- Clarification Q5: CI budget < 3 minutes (workers=4)
- Intent traces: [I-17], [I-18], [I-22], [I-24], [I-34]
