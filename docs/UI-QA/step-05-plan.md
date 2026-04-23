# Step Plan: Edge Cases & State Transition Matrix (M3)

## Purpose

Test failure modes, race conditions, and exhaustively cover the state machine. Includes full state transition matrices (valid + invalid transitions), state changes during user interaction, dialog edge cases, connection failures, and stale data handling. This is the second-highest priority per clarification Q6.

## Prerequisites

- Steps 01-04 complete: all infrastructure, page objects, factories, and happy-path lifecycle scenarios.
- FakeWebSocket supports `simulateDisconnect()` and `simulateReconnect()`.
- Route handlers support error responses (500, 404).

## Functional Contract

### Inputs

- All existing fixtures, factories, page objects, and step definitions from Steps 01-04.
- FakeWebSocket with disconnect/reconnect simulation.
- FakeSSE with stream drop simulation.
- Route handlers configurable to return error responses.

### Outputs

- `ui/tests/bdd/features/run-transitions.feature` — Scenario Outline with Examples table covering:
  - All valid run state transitions: draft→active, active→paused, paused→active, active→completed, active→failed, active→cancelled, paused→cancelled
  - Invalid transitions: completed→active, cancelled→paused, failed→active, etc. — verified as no-op or error
- `ui/tests/bdd/features/task-transitions.feature` — Scenario Outline with Examples table covering:
  - All valid task transitions: queued→building, building→verifying, verifying→completed, verifying→failed, failed→building (revision)
  - Invalid transitions: completed→building, queued→verifying, etc.
- `ui/tests/bdd/features/edge-state-change.feature` — scenarios:
  - Run completes via WebSocket while CreateRunModal is open
  - Task moves to VERIFYING while user views BUILDING prompt
  - Run cancelled by another user while current user sets grades
- `ui/tests/bdd/features/edge-dialogs.feature` — scenarios:
  - Rapid double-click on destructive action ConfirmDialog
  - ApprovalModal opens at gate, closes if gate resolved externally
  - ClarificationModal submit during incoming WebSocket clarification
  - Modal open → navigate away → modal closes (no orphan modals)
- `ui/tests/bdd/features/edge-connection.feature` — scenarios:
  - WebSocket disconnect → ConnectionBanner shown → reconnect → data refresh
  - SSE stream drops → fallback to polling → banner shown
  - API request fails with 500 → error boundary → retry works
  - API request fails with 404 → NotFound page shown
- `ui/tests/bdd/features/edge-stale-data.feature` — scenarios:
  - WebSocket updates run status → card updates without page reload
  - Stale cached data → WebSocket event triggers React Query invalidation
- `ui/tests/bdd/steps/edge-cases.steps.ts` — step definitions for edge-case-specific actions (simulating disconnects, pushing conflicting events, triggering error responses).

### Error Cases

- Timing sensitivity: race condition tests need precise event ordering — use Playwright's `waitForSelector` / `waitForResponse` to synchronize.
- Invalid transition behavior varies by implementation — some may show errors, others silently ignore. Tests must match actual app behavior.
- Connection edge cases depend on app reconnection logic — FakeWS must simulate realistic reconnect behavior.

## Tasks

1. Write `run-transitions.feature` with Scenario Outline and full Examples table (valid + invalid transitions).
2. Write `task-transitions.feature` with Scenario Outline and full Examples table.
3. Write `edge-state-change.feature` with race condition scenarios.
4. Write `edge-dialogs.feature` with dialog edge cases.
5. Write `edge-connection.feature` with connection failure scenarios.
6. Write `edge-stale-data.feature` with cache invalidation scenarios.
7. Create `edge-cases.steps.ts` with step definitions for all edge-case actions.
8. Extend `api-handlers.ts` to support configurable error responses.
9. Extend `fake-ws.ts` and `fake-sse.ts` if disconnect/reconnect simulation needs enhancement.
10. Run all BDD tests, verify green.

## Verification Approach

### Auto-Verify

- Full state transition matrix passes (all valid transitions produce expected state; all invalid transitions produce no-op or error).
- All edge-case scenarios pass.
- Each scenario tests a specific race condition or failure mode.
- No regressions in Steps 01-04 features.
- Total BDD suite completes within 3-minute CI budget.

### Manual Verification

- WebSocket disconnect/reconnect shows banner and refreshes data.
- Double-click protection works on destructive dialogs.
- Error boundaries catch and display API errors correctly.

## Context & References

- Plan: `docs/UI-QA/plan.md` — M3 specification (3a through 3e)
- Architecture: `docs/UI-QA/architecture.md` — timing control, Scenario Outline pattern
- Clarification Q3: Full state transition matrix with invalid transitions (not just 5 edge cases)
- Clarification Q4: Scenario Outlines with Examples tables for parameterized coverage
- Clarification Q6: Edge cases are second-highest priority
- Intent traces: [I-03], [I-05], [I-09], [I-10], [I-12], [I-25], [I-28], [I-31]
