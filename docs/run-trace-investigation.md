# Run Trace Investigation

## What Remained

The old run-detail surface no longer exposed a detail button from the run page; the current page only showed cost and the change-review panel. The useful tracing data still exists in the backend:

- `Attempt.action_log` stores parsed agent messages, thinking blocks, tool calls, tool results, result records, and per-request token metrics.
- `Attempt.builder_prompt`, `Attempt.verifier_prompt`, `Attempt.verifier_comment`, `Attempt.metrics`, and `Attempt.token_usage_by_model` remain available.
- `Run.token_usage_by_model` and the legacy aggregate token fields remain available for whole-run summaries.
- `GET /api/runs/{run_id}/tasks/{task_id}/attempts/{attempt_num}/logs` still returns per-attempt raw and structured logs.

There is no separate canonical transcript table. Message-level inspection currently means prompts plus parsed `action_log` entries and raw `agent_output` fallback.

## Reused

- The structured action log schema is the canonical call/message source for the new run trace endpoint.
- The existing per-attempt log viewer remains useful for narrow task inspection.
- Existing model-cost display remains useful for aggregate cost by model.

## Added

- `GET /api/runs/{run_id}/trace` returns all attempts for a run with step/task metadata, builder/verifier phase records, attempt metadata, per-attempt token usage, prompts, verifier feedback, and action logs.
- The run detail page now includes a `Run Trace` panel before `View Changes`.
- The trace panel provides three accounting views:
  - `Attempt context`: repeats accumulated context at each call to expose cache pressure.
  - `Request charged`: uses reported per-request token usage and shares a request across tool calls in that request.
  - `Call delta`: estimates only tool-call input/output caused by that call.
- The visualization uses one row per attempt and a horizontally scrollable token-position axis. Initial zoom fits the whole run.
- The lower panel exposes step -> task -> attempt -> message drilldown, including prompts, verifier feedback, assistant text, tool call arguments, and tool results.

## Cleaned Up

Removed disconnected older detail components that had no import consumers:

- `ui/src/components/detail/AttemptHistory.tsx`
- `ui/src/components/detail/MetricsBar.tsx`
- `ui/src/components/detail/StepAccordion.tsx`
- `ui/src/components/detail/TaskCard.tsx`
- `ui/tests/components/AttemptHistory.test.tsx`

## Remaining Limits

- Tool-call token attribution is only exact when the runner emits metrics on the same action-log entry. Otherwise the UI derives a defensible estimate from nearby request metrics and tool-result sizes.
- Action-log timestamps are parse-time timestamps, not authoritative API request start/end spans. The graph is token-position based, not wall-clock based.
- Claude sub-agent logs are stored in the domain model but are not yet expanded into separate trace rows.
