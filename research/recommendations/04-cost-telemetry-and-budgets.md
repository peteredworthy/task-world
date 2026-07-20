# R04 — Complete Cost Telemetry, Then Enforce Budgets at Dispatch

**Priority: P1 (telemetry), P1-P2 (budgets). Telemetry is a prerequisite for
half of this recommendation set.**

## Problem

Cost data has structural holes, and nothing enforces spend limits:

- Repo evidence: claude_sdk produces no `ActionLog` → no cache/sub-agent
  accounting, undercounted cost (`agents/claude_sdk/agent.py:689`); unknown
  models silently cost $0 (`runners/costs.py:73-95`, see R01c); no
  finish_reason or reasoning-token capture anywhere; routing decisions logged
  only at debug level (`executor.py:993`); no cross-run rollup surface; the
  journal grows unbounded.
- External evidence: the consensus minimum per-call record is model + params,
  input/output/**reasoning** tokens, latency, **finish_reason**, cost, parent
  span, error status (Langfuse/LangSmith/OTel, High). Budget enforcement
  belongs at a chokepoint the agent cannot bypass (Med-High). OTel GenAI
  attribute names are stable enough to bet on even though the spec is
  pre-stabilization (High).

## Proposed change

### Phase 1 — capture (do with W5 typed-payload slices)

1. Extend the per-attempt usage record with `finish_reason`,
   `reasoning_tokens`, `latency_ms`, `rate_missing` — using OTel GenAI
   attribute names (`gen_ai.usage.input_tokens`, etc.) inside the W5 typed
   payload work so a future exporter is a mapping, not a migration.
2. Close the claude_sdk gap *or* formally demote it: if the SDK cannot
   provide an action log, record its usage as `telemetry_degraded=true` so
   rollups can exclude/flag it (decision in OQ-5).
3. Add a cost rollup read model: tokens/$ by run, node kind, model, profile,
   day. (Answers OQ-3 — is the gap_planner earning its cost — and feeds R03
   validation.)
4. Journal retention: size-based rotation for `history.jsonl` (the events_v2
   table is the durable store; the JSONL is an audit mirror).

### Phase 2 — enforce

5. Per-run and per-node budget fields (tokens and dollars, enforce whichever
   is defined — OQ-8), checked in the drive loop before each dispatch — the
   natural chokepoint (`GraphRunDriver.drive_to_quiescence`). Exceeding →
   typed blocker (`budget_exhausted`), ALERT-then-REJECT semantics: warn
   event at 80%, refuse dispatch at 100%.
6. Per-profile **effort settings** (low for summarizer/verifier rubric
   checks, high for architect) stored alongside the model-profile defaults
   table — the cheapest cost lever per the external evidence, orthogonal to
   model choice.

## Expected benefit

- Every other recommendation becomes measurable (R02, R03, R07 all consume
  this data).
- Runaway-cost class of failure becomes structurally impossible.
- Effort tiering yields immediate savings without model churn.

## Cost / complexity

Phase 1 is schema + parser work riding an existing migration path (W5).
Phase 2 is a small drive-loop check + two config fields. The rollup read
model is the largest piece (new query surface).

## Risks

- Budget defaults set wrong will pause legitimate runs; start with generous
  defaults and ALERT-only for the first weeks.
- Effort knobs vary by provider/runner; keep them best-effort per runner
  (ignore where unsupported) rather than a hard abstraction.

## Validation

- Reconcile a week of recorded costs against provider dashboards/subscription
  usage; discrepancy < 10% for action-log runners.
- Induced-runaway test: a looping mock node must hit the budget blocker.

## Dependencies

R01c (loud-fail rates) first. Aligned with (not blocked by) remaining W5
slices.

## Claude SDK supersession — 2026-07-18

The Claude SDK telemetry findings above remain historical evidence, but Phase 1
item 2 is resolved by removal, not demotion: the runtime and dependency are
gone, and `retired` exists only for historical readback. Cost capture work now
targets `openhands_local`, `openhands_docker`, `cli_subprocess`, and
`codex_server`; no new telemetry path should be built for retired records.

## Phase 1 completion evidence — 2026-07-20

Phase 1 is complete for the graph execution carrier:

- `ModelTokenUsage` is an immutable execution × model fact with canonical OTel
  fields: `gen_ai_usage_input_tokens`, `gen_ai_usage_output_tokens`,
  `gen_ai_usage_cache_read_input_tokens`,
  `gen_ai_usage_cache_creation_input_tokens`,
  `gen_ai_usage_reasoning_output_tokens`, and plural
  `gen_ai_response_finish_reasons`. Cache components remain part of input and
  reasoning is observable without a second output charge. `cost_usd`,
  `latency_ms`, and `rate_missing` are captured with the fact.
- Graph usage is persisted as idempotent `node_usage_recorded` events. The
  read surface is `GET /api/runs/cost-rollup`; its Phase-1 scope is explicitly
  graph-only, uses UTC event days and half-open time bounds, and does not merge
  legacy attempt/run totals.
- The journal rotates into position-ranged archive segments. Bootstrap and
  restore replay archived segments plus the active journal in position order,
  so rotation is not retention or a recovery downgrade. The active path can be
  relocated with `ORCHESTRATOR_EVENT_JOURNAL_PATH`.
- Runner-default reconciliation reads the selectable runners' built-in config
  schemas. Provider-billed defaults (currently `gpt-5-mini` for both
  OpenHands runners) have matched nonzero input/output rates in
  `model_costs.yaml`; intentional local/no-provider-cost models require an
  explicit zero-rate entry. An unmatched name remains `rate_missing=true`, and
  runners with no static model (currently CLI subprocess and Codex Server) are
  explicitly classified `no_static_default` rather than treated as local or
  silently zero-priced.

Phase 2 depends on these immutable graph facts and the graph rollup: add
per-run/per-node token and dollar limits at the dispatch chokepoint, emit the
80% alert and reject dispatch at 100%, then add provider-aware per-profile
effort settings. It must not infer a zero cost from an unmatched model or use
legacy totals as the graph budget authority.
