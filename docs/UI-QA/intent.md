# UI QA Test Suite — Intent

## Problem Statement

The frontend has undesirable behaviors in edge cases: state updates not handled gracefully, dialogs that fail to close or don't open when expected, and race conditions around form submission when run state changes mid-interaction. These bugs are discovered manually and inconsistently. There is no systematic way to exercise the full set of UI workflows with controlled backend responses, making regressions easy to introduce and hard to catch.

## Goals

1. Build a comprehensive frontend test suite that exercises every user-facing workflow end-to-end using fake (mocked) backend responses. [I-01]
2. Enable rapid, deterministic testing — no real backend required, fast feedback loop. [I-02]
3. Cover edge cases where backend state changes during user interaction (e.g., run completes while user is submitting a form, WebSocket events arrive mid-action). [I-03]
4. Document all UI workflows as readable, executable specifications using a Gherkin-like syntax (Cucumber/Playwright BDD or similar). [I-04]
5. Make it easy to add new edge-case scenarios as they are discovered in production. [I-05]

## Scope

### In Scope

- All pages: Dashboard, RunDetail, RoutineLibrary, Agents, AgentRunners, History, Repos. [I-06]
- All dialogs/modals: CreateRunModal, SettingsModal, RoutineValidatorModal, ConfirmDialog, ApprovalModal, ClarificationModal. [I-07]
- All stateful flows: run lifecycle (draft → active → paused → completed/failed/cancelled), task lifecycle (queued → building → verifying → completed/failed), step progression, attempt/revision cycles. [I-08]
- WebSocket and SSE event handling: batch messages, reconnection, stale-state recovery. [I-09]
- Form submission race conditions: state changes arriving via WebSocket during mutation calls. [I-10]
- Sidebar navigation, search, connection status indicators. [I-11]
- Error boundaries and error states (API failures, 404s, network errors). [I-12]

### Out of Scope

- Backend API testing (covered by existing 565 backend tests). [I-13]
- Visual regression testing (already handled by Playwright snapshot tests in `ui/tests/e2e/`). [I-14]
- Performance/load testing. [I-15]
- Mobile responsiveness testing. [I-16]

## Constraints

- Must not require a running backend server — all API responses mocked or stubbed. [I-17]
- Must integrate with the existing Vitest + Testing Library setup (unit/component tests) and Playwright (flow tests). [I-18]
- Gherkin-style specs must be human-readable by non-engineers (product, QA). [I-19]
- BDD test suite must run in CI in under 3 minutes (stricter than original 5-minute budget). [I-20]
- Must not duplicate existing 221 frontend unit tests — complement them with workflow-level coverage. [I-21]
- All mocked API responses must conform to existing TypeScript types in `ui/src/types/`. [I-22]

## Resolved Design Decisions

The following were originally open questions. All resolved via clarification Q&A (see `clarifications.md`).

- **Gherkin tooling**: `playwright-bdd` selected. Maps `.feature` files to Playwright test steps; reuses existing Playwright infrastructure. [I-23]
- **Mock fidelity**: TypeScript types only — factory functions use `ui/src/types/` interfaces. Catches type drift at compile time. No auto-generation from OpenAPI or snapshot-based fixtures. [I-24]
- **State machine coverage**: Full state transition matrix with invalid transitions tested. Not limited to 5 edge cases — enumerate all valid and invalid run/task lifecycle transitions. [I-25]
- **Maintenance burden**: Mitigated via page objects + shared fixtures (plan default), shared step definitions across features, and scenario outlines with examples tables for parameterized coverage. [I-26]

## Definition of Complete

- Every page has at least one workflow-level test covering its primary happy path. [I-27]
- Every modal/dialog has open, interact, close tests — including edge cases where underlying state changes during interaction. [I-28]
- Run lifecycle (create → start → pause → resume → complete) is tested end-to-end with mocked API. [I-29]
- Task lifecycle (queue → build → verify → grade → complete) is tested with mocked API. [I-30]
- Full state transition matrix tested for run and task lifecycles, including invalid transitions, plus edge-case scenarios covering race conditions (state change during form submit, WebSocket reconnect, stale data). [I-31]
- All workflows documented as Gherkin `.feature` files that serve as both specs and executable tests. [I-32]
- Test suite runs in CI and passes. [I-33]
- Fixture/mock infrastructure is documented so new edge cases can be added in < 15 minutes. [I-34]
