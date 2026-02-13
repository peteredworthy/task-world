# Partially Implemented Features

Features where backend endpoints exist and have test coverage but are not yet wired into the frontend UI or MCP tools.

## Step-Level Human Approval

**Backend:** `POST /api/runs/{id}/steps/{step_id}/approve`
**Tests:** `tests/integration/test_approval_workflow.py`
**What exists:** Steps can have an `approval_gate` that blocks progression until a human approves. The backend transitions the step and emits an `ApprovalDecision` event.
**Missing:** UI has no step-level approval prompt or button. Only task-level approve/reject is wired.

## Activity SSE Streaming

**Backend:** `GET /api/runs/{id}/activity/stream`
**Tests:** `tests/integration/test_api_runs.py`
**What exists:** Server-Sent Events endpoint that streams activity events in real-time.
**Missing:** UI polls `GET /api/runs/{id}/activity` instead of subscribing to the SSE stream. The WebSocket provides run-level updates but not the full activity feed.

## External Agent Lifecycle Hooks

**Backend:** `POST /api/runs/{id}/agent-started`, `POST /api/runs/{id}/agent-cancelled`
**Tests:** `tests/integration/test_api_runs.py`
**What exists:** For user-managed agents, these endpoints signal that the external agent has started working or that the user has cancelled. Sets `agent_started_at` timestamp.
**Missing:** UI shows guidance for external agents but has no explicit "I've started my agent" / "Cancel" buttons mapped to these endpoints.

## External Agent Guidance

**Backend:** `GET /api/runs/{id}/guidance`
**Tests:** `tests/integration/test_api_runs.py`
**What exists:** Returns an aggregate guidance object with the current task prompt, MCP URL, callback instructions, and expected next actions. Designed for external agents to poll for work.
**Missing:** UI has its own guidance panel but doesn't use this aggregate endpoint.

## Backward Step Transitions

**Backend:** `POST /api/runs/{id}/transition-back`
**Tests:** `tests/integration/test_api_runs.py`
**What exists:** Transitions a run backward to an earlier step (e.g., to redo work). Resets task states in the target step.
**Missing:** UI has no control to go back to a previous step.

## Branch Status and Merge Operations

**Backend:** `GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`
**Tests:** `tests/integration/test_api_runs.py`
**What exists:** Branch-status returns ahead/behind counts and merge-ability. Back-merge pulls source branch changes into the run's worktree branch. Merge-back (run→source) IS wired in the UI.
**Missing:** UI has no display for branch drift or a button to back-merge. Only merge-back (completing a run) is connected.

## Environment File Management

**Backend:** `GET /api/runs/{id}/env-files`, `GET .../snapshots`, `POST .../revert`, `POST .../copy-back`, `GET .../default-target`
**Tests:** `tests/integration/test_api_runs_envfiles.py`
**What exists:** Full lifecycle for managing `.env` files across run attempts. Snapshots are taken at task boundaries; users can revert to a prior snapshot or copy env files back to their project.
**Missing:** UI has no env file management panel.

## Routine YAML Validation

**Backend:** `POST /api/routines/validate`
**Tests:** `tests/integration/test_api_routines.py`
**What exists:** Accepts raw YAML, parses it, validates against `RoutineConfig`, and returns structured errors with builder-friendly feedback.
**Missing:** UI has no routine editor or validation interface.

## Global Configuration Endpoint

**Backend:** `GET /api/config`
**Tests:** None found.
**What exists:** Returns the global config.json settings.
**Missing:** UI doesn't fetch or display configuration. Frontend settings are local-only.
