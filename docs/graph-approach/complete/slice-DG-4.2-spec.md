# Slice DG-4.2 - Dynamic Graph UI Panels

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-4,
  Slice DG-4.2.
- `docs/graph-approach/mind-the-gap-skill.md`
- `docs/graph-approach/slice-DG-4.1-spec.md`
- `ui/src/components/GraphPanel.tsx` - existing graph projection side panel.
- `ui/src/components/__tests__/GraphPanel.activity.test.tsx`
- `ui/src/components/__tests__/SchedulerView.test.tsx`
- `ui/src/types/runs.ts`
- `ui/src/types/activity.ts`
- Existing graph API endpoints under `/api/runs/{run_id}/graph*`.
- Existing run activity endpoint `/api/runs/{run_id}/activity`.

## Scope

Make the existing graph panel useful for operating dynamic graph runs. The
operator should be able to answer "why is this run not complete?" from the UI
using existing graph projection, scheduler, decision, file-state, node detail,
raw graph event, and DG-4.1 activity data.

This is a UI surfacing slice only. Do not add backend routes, change graph
scheduling/completion policy, change graph event schemas, change activity API
shape, export metrics, or run the true-comparison plan.

## Orchestrator Runner

Run this slice through the orchestrator using `codex_server` or Claude CLI.
`codex_server` remains the default known-good graph runner:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-4.2",
    "spec_path": "docs/graph-approach/slice-DG-4.2-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.5"
  }
}
```

Use `gpt-5.5` because `gpt-5.3-codex-spark` is quota-limited. If `gpt-5.5`
is unavailable, inspect available Codex models and choose the best Codex option.
Claude CLI may be used for this UI implementation slice because the Claude
limit has reset.

## What To Build

### 1. Operator Summary In `GraphPanel`

Add a compact top-of-panel summary derived from existing props/hooks. It should
surface, at minimum:

- run graph state and event count;
- scheduler counts for ready, blocked, waiting-resource, and waiting-gate nodes;
- active and suspended lease counts;
- pending human gates, appeals, and review blocker counts;
- recent patch accepted/rejected counts from DG-4.1 activity rows;
- recent verifier pass/fail grade counts from DG-4.1 activity rows;
- recent invariant/gap/blocker count from DG-4.1 activity rows.

Use restrained dashboard styling consistent with the existing app. Do not add a
marketing hero, nested cards, decorative gradients, or new route-level layout.

### 2. Patch And Verifier Activity Sections

Inside `GraphPanel`, add concise sections that read from `activityEvents` and
show:

- accepted/rejected graph patches with patch id, proposer, actor, reason, and
  successor planners where present;
- verifier pass/fail rows with candidate id, task region id, verdict, and
  failing/non-A requirement ids where present;
- command rejections and invariant/node blockers with reason and node id.

Keep rows compact and bounded. Do not dump raw graph event JSON, raw prompts,
transcripts, large payloads, or full evidence blobs. The existing raw events
modal can remain available for debugging.

### 3. Existing Panel Compatibility

Preserve the existing graph panel behavior:

- scheduler view remains visible;
- decisions/review readiness remains visible;
- file-state viewer remains visible;
- node-state table still links to node detail;
- activity-derived live output next to node state still works;
- panel close behavior and initial node selection still work.

### 4. Tests

Add or extend focused UI tests that prove:

- graph activity rows from DG-4.1 render as patch, verifier, command rejection,
  and blocker facts;
- the operator summary shows scheduler/lease/decision/activity counts;
- raw prompt/transcript-like payload fields are not rendered in the new summary
  sections;
- existing node-state live activity and node-detail behavior still works.

Prefer extending `ui/src/components/__tests__/GraphPanel.activity.test.tsx` if
that is the narrowest route.

## Required Tests

Run and record:

```bash
# Run from /Users/peter/code/task-world
npm --prefix ui test -- src/components/__tests__/GraphPanel.activity.test.tsx src/components/__tests__/SchedulerView.test.tsx
npm --prefix ui run lint -- --max-warnings=0
npm --prefix ui run typecheck
```

If the repo's UI scripts differ, inspect `ui/package.json` and run the closest
equivalent focused Vitest, lint, and TypeScript checks.

Also run a targeted no-mocks scan over any new or modified UI tests:

```bash
rg -n "vi\\.mock|jest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" ui/src/components/__tests__/GraphPanel.activity.test.tsx ui/src/components/__tests__/SchedulerView.test.tsx
```

## Done When

1. The existing graph panel lets an operator inspect why a dynamic graph run is
   not complete without opening raw graph events first.
2. Patch decisions, verifier grades, command rejections, and invariant/blocker
   facts from DG-4.1 activity rows are visible in compact UI sections.
3. Existing graph panel sections and node-detail interactions still work.
4. No new backend routes, scheduling behavior, graph policy, metric export, or
   true-comparison behavior is added.

## Mind-the-gap Validation Requirements

The validator must confirm:

- the UI answers "why is this run not complete?" using existing API data;
- the UI does not expose raw prompts/transcripts in the new summaries;
- the result is sufficient input for DG-4.3 metric export and DG-5.1 dynamic
  smoke-run observation;
- the implementation remains a narrow UI-only slice.

## Hard Constraints

- No mocks or monkeypatching in new tests.
- Do not edit backend graph policy, scheduler, completion gate, or API routes.
- Do not add metrics export or true-comparison behavior.
- Use `codex_server` or Claude CLI for orchestrator execution.
- Follow existing UI density and modal/action-menu constraints from `AGENTS.md`.
