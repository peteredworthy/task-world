# Conflicts & Unresolved Decisions: Close All 21 Frontend Gaps

## Resolved Conflicts

All seven original design questions (Q1–Q7) have been resolved with human feedback. No conflicts remain between the plan, architecture, and design-questions artifacts.

## Open Items Requiring Further Design

### 1. Dashboard-level WebSocket/SSE endpoint (Q4→B)

The human chose Option B (dashboard-level aggregate channel) for real-time dashboard updates. This may require a **new backend endpoint** (`/ws/dashboard` or similar) that broadcasts status changes for all runs. The current backend only supports per-run WebSocket channels (`/ws/runs/{runId}`). If a backend endpoint does not already exist, this gap cannot be fully closed without backend work — which is currently out of scope.

**Status:** Implementation may be blocked pending backend endpoint verification. If unavailable, fall back to reduced polling interval as interim solution.

### 2. Env file management location change (Q5→custom)

The human chose to place env file management in the config/settings area (not RunDetail) with CreateRunModal overrides. This changes the original architecture assumption. The backend endpoints (`/api/runs/{id}/env-files/*`) are run-scoped, so a config-area UI for base templates may need a different backend endpoint for template CRUD (e.g., `/api/env-templates`). If no such endpoint exists, this feature may need backend work.

**Status:** Verify whether a template-level env file API exists. If not, the config-area template management is blocked; per-run overrides in CreateRunModal can still proceed using existing run-scoped endpoints.

### 3. Design-question UI (Q8 — NEW gap from human feedback)

The human identified a missing capability: the frontend has no way to present LLM-generated design questions to users and capture answers. This is a new gap (Gap 22) that was not part of the original 21. It requires:
- A question schema definition
- A backend endpoint for submitting answers
- A new frontend component

**Status:** Open — requires further design. Not blocking the original 21 gaps but should be prioritized as HIGH for future work.
