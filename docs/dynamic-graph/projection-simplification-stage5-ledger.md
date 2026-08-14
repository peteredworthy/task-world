# Projection Simplification Stage 5 Ledger

Status: AR-A and AR-A-deprecation prepared; destructive retirement remains gated
Date: 2026-08-14
Baseline: merged Stage 3 main `ceff00c519f10504799c1d7a89b80d60795bb6af`
Feature specification: `docs/dynamic-graph/archival-view-consumer-audit-2026-08-13.md`

## Run, configuration, ownership, and dependencies

| Field | Recorded value |
|---|---|
| Run/worktree | `r403`; implementation worktree `/Users/peter/code/task-world/worktrees/r403` |
| Configuration | Authorized Stage 5 AR-A plus non-destructive topology/regions deprecation preparation; exactly one implementation worker, one fresh independent read-only verifier, and one final invariant; no discovery, gap, corrective, AR-B, AR-C, AR-D, AR-E, or AR-F nodes |
| Implementation worker | `stage5-ara-ui-deprecation-worker`, lease generation `1`; write authority is limited to the exact paths listed below |
| Verification authority | Fresh independent read-only verifier with claim `read/repo/[.]` |
| Callback boundary | Submit records, request clarification, or raise appeal; one final submission after validation |
| Baseline dependencies | Existing graph projection, runtime checkpoint, archival rebuild, ORM tables, public routes, Python exports, UI client methods, response types, and `useArchivalGraphSnapshot` remain compatibility owners |
| Policy dependencies | External-consumer evidence, route telemetry, support window, replacement diagnostics policy, and failed-outbox terminal semantics are unresolved; this ledger makes no claims about them |

Exact implementation write claim paths:

`docs/dynamic-graph/archival-view-consumer-audit-2026-08-13.md`,
`docs/dynamic-graph/projection-simplification-stage5-ledger.md`,
`src/orchestrator/api/routers/graph.py`,
`tests/integration/test_graph_api.py`,
`ui/src/components/GraphPanel.tsx`,
`ui/src/components/__tests__/GraphPanel.decisions.test.tsx`,
`ui/src/components/__tests__/GraphPanel.activity.test.tsx`,
`ui/src/components/__tests__/GraphDiagnostics.hidden.test.tsx`,
`ui/src/hooks/useApi.ts`, and
`ui/src/hooks/useApi.graphEvents.test.tsx`.

## Fresh audit and evidence

The accepted Stage 3 source was re-read before patching. Repository evidence found
`GraphPanel -> useArchivalGraphSnapshot` as the only first-party product path, but
also found the hook's independent retry/coherence tests and all public client,
type, route, export, ORM, worker, and archival rebuild owners. The absence of an
in-repository caller is not evidence that deployed REST or Python consumers do not
exist.

The product-facing proof mounts the actual `GraphPanel` through the real React
Query/client stack and records the existing network test harness. It proves the
panel remains usable, preserves projection/health/activity/decision behavior, and
does not issue an extra `/graph` anchor or any `/graph/topology`,
`/graph/final-blockers`, or `/graph/regions` request. No browser session was
available in this worktree environment; no product claim is made beyond the real
React Query/client path exercised by the tests. The public archival hook remains
covered independently.

## Stage 5 rows

| Row | Status | Scope and evidence | Explicit non-scope |
|---|---|---|---|
| AR-A — UI decoupling | Complete | Removed only the GraphPanel archival hook invocation and “Archival graph views” card. Product tests prove no archival request bundle and continued panel usability. | Do not delete or rename hook, client methods, response types, routes, exports, ORM tables, workers, rebuild code, or graph projection internals. Do not infer unavailable values as zero. |
| AR-A-deprecation — topology/regions metadata | Complete | Topology and regions are `deprecated` in OpenAPI and successful responses carry `Deprecation: true`. Existing response bodies, status behavior, pagination, position, partial, and hash semantics remain unchanged. | No `Sunset` date, replacement `Link`, support window, external-consumer owner, telemetry claim, route removal, materialization change, or invented replacement policy. |
| AR-B — exact compact blocker count | Deferred/gated | Requires a separately authorized owner decision for exact canonical plus failed-outbox count semantics. | Not part of this Stage 5 node set. |
| AR-E — final-blocker decoupling | Sequenced after AR-B | Retain the bounded final-blocker capability and failed-outbox visibility until a replacement owner is proven. | No shared checkpoint, store, worker, or ORM change in this slice. |
| AR-C — region retirement | Gated | Only after deprecation/support and semantic proof gates are answered; preserve task states and `task_region_id`. | No route/client/type/builder/table removal now. |
| AR-D — topology narrow/conditional retirement | Gated | Only after external-consumer and diagnostics gates are answered; preserve canonical topology indexes. | No topology route/client/type/builder/table removal now. |
| AR-F — dead archival infrastructure cleanup | Last | Only after retained owners and all AR-C/AR-D decisions are complete. | Never delete or recreate `orchestrator.db`; no cleanup now. |

Required sequence is `AR-A/AR-A-deprecation -> AR-B -> AR-E -> AR-C -> AR-D
decision -> AR-F`. AR-C and AR-D remain gated by the unresolved decisions below;
AR-F is last.

## Acceptance gates

The focused acceptance command is:

```text
npm --prefix ui test -- ui/src/components/__tests__/GraphPanel.decisions.test.tsx ui/src/components/__tests__/GraphPanel.activity.test.tsx ui/src/components/__tests__/GraphDiagnostics.hidden.test.tsx ui/src/hooks/useApi.graphEvents.test.tsx && npm --prefix ui run lint && npm --prefix ui run typecheck && uv run pytest -n 0 tests/integration/test_graph_api.py -k 'topology or regions or archival'
```

The full gate additionally includes full Vitest, Ruff, Pyright, and `uv run
pytest`. Verification must independently prove network behavior, truthful health,
compatibility preservation, deprecation metadata, exact scope, all available gates,
and the unresolved decisions before grading and submitting.

## Unresolved decisions

1. **External compatibility gate:** who can confirm deployed REST/Python consumers,
   what telemetry is available, and what deprecation window applies? Until answered,
   topology and regions may be deprecated and removed from first-party UI use but
   must not be hard-deleted.
2. **Topology diagnostics:** does the product require a supported aggregate edge and
   binding diagnostic after deprecation? If yes, keep the current endpoint or define
   an explicit export before removing its materialization.
3. **Failed-outbox terminal semantics:** current code makes failed rows visible in
   final blockers but does not prove they veto lifecycle completion. Decide separately
   whether “blocked” is an operator-health classification or a hard completion rule.
4. **Requeue drift:** current source lacks the historically documented arbitrary
   failed-outbox requeue endpoint. Decide whether to restore a supported remediation
   action; this audit does not authorize that expansion.

These four decisions remain unresolved verbatim from the archival consumer audit.
