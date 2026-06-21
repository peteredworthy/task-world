# Dynamic Graph Current Status

This is the source of truth for current dynamic graph work. Older status logs,
run ledgers, and the five-arm comparison plan are archived in
`docs/dynamic-graph/complete/`.

## What We Are Attempting

We are trying to prove whether the dynamic graph carrier is worth using for
adaptive feature work. The useful comparison is now a three-way comparison:

| Arm | Carrier | Why it matters |
|---|---|---|
| A | Legacy single-agent | Baseline for how far one agent can get in one pass. |
| C | Faithful Mind-the-gap | Non-graph adaptive baseline with repeated plan/build/validate loops. |
| E | Dynamic graph | Graph-native adaptive planning with planner patches, gap analysis, and invariant-gated completion. |

The fixed three-agent routine and static graph carrier are no longer interesting
for the next test. They answer carrier/mechanics questions that have already
been explored enough for this phase. The question now is adaptive planning
quality and cost.

## Current State

- The dynamic graph implementation has the core mechanisms in place: planner
  graph patches, dynamic region creation, gap planner routing, corrective work,
  final invariant checks, compact activity/readback, and comparison metrics.
- The typed-work-graph implementation now includes a shared node/port contract
  registry, typed edge validation/readback, planner-facing macro expansion,
  deterministic check execution, and controller execution for join/final-gate
  nodes. The latest verified slice adds centralized opaque check-command
  binding resolution, typed macro invocation schemas, graph patch proposal/result
  readback at `/api/runs/{id}/graph/patches`, typed final-blocker readback at
  `/api/runs/{id}/graph/final-blockers`, typed output records for
  `human_gate` / `authority_request` decisions, required-output completion
  validation, verifier grade enforcement, task acceptance gating on file-state
  and region check results, planner-patch rejection for hidden command text,
  forbidden-cycle patch rejection, and graph-runner preflight for native graph
  callback support.
- Typed-work-graph cheap validation currently passes:
  `uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py
  tests/unit/test_scheduler.py tests/integration/test_graph_*.py
  tests/unit/test_codex_server_common.py
  tests/unit/test_codex_server_tool_filtering.py -q` (`614 passed`), plus Ruff
  and Pyright on the touched graph/API/runtime surfaces.
- The next comparison scenario is now specified as S3 Active Graph Diagnostics
  Snapshot in
  `docs/dynamic-graph/complete/comparison-s3-active-graph-diagnostics-spec.md`.
  It is admitted only after its weak acceptance and hidden oracle exist and the
  one-shot Arm A baseline fails hidden materially while producing useful partial
  work.
- The S3 admission harness now exists, including backend/UI hidden oracles,
  a one-shot legacy comparison routine, and health metrics in
  `scripts/compare_carriers.py`. The current tree intentionally fails the
  hidden oracle because graph health is not implemented yet; detailed evidence
  is in `docs/dynamic-graph/complete/s3-comparison-ledger.md`.
- S3 is not yet admitted for live A/C/E tokens. The required isolated reference
  proof was attempted but did not produce a clean isolated result. Reference
  prototype changes that appeared in the shared checkout were removed, and Arm A
  remains gated until a reference implementation passes the hidden oracles
  outside the main checkout.
- The verifier-to-final-invariant contract now has deterministic coverage for
  the `verification_result`/`verification_report` alias class. Verifier callback
  records are canonicalized before routing, so final invariant checks waiting on
  `verification_evidence` can bind records emitted through the legacy alias.
- Active readback slowness was traced to request-time projection snapshot
  rebuilds after every graph append. Scheduler/decision reads use bounded light
  paths; `/graph` still rebuilds missing disposable summaries/snapshots to
  preserve read-model recovery, and synthetic profiles remain the cheap guardrail
  before spending live tokens. Evidence and details are in
  `docs/dynamic-graph/complete/dynamic-graph-contract-readback-2026-06-21.md`.
- A non-isolated dynamic smoke run completed end to end and proved the live
  dynamic path on a tiny scenario.
- Hidden-oracle isolated Arm E has not yet been re-proven end to end after the
  latest deterministic lease/readback fixes.
- DG-5.2e cheap validation is covered by deterministic tests: expired active
  graph leases leave explicit failed-node evidence, graph verifier prompts stay
  bounded, and graph projection/events/scheduler/node readback works through
  summary paths while a graph lease is active.
- The S2 live agent-output streaming feature is no longer pending port to main;
  the hidden oracle in
  `docs/graph-approach/complete/oracles/test_stream_output_oracle_v2.py` passes
  against the current tree.
- S1 is smoke evidence only. S2 is rejected as a comparison scenario because
  Arm A completed it in one pass.

## Validation Policy

Validate cheaply whenever possible.

Do not use live agent smoke runs as the default diagnostic loop. If a failure
class can be reproduced with a deterministic unit, integration, profiler, or
local harness test, add that coverage and make it pass before spending model
tokens. In particular, do not kick off agent smoke tests that can produce
multi-million-token prompts or traces when the error can be checked
deterministically.

Live agent runs are for proving already-bounded behavior, not discovering basic
runtime defects.

## What Remains

1. Re-prove isolated Arm E once DG-5.2e is covered.
   - Use the hidden-oracle binding path.
   - Confirm corrective verifier completion.
   - Confirm final invariant scheduling and terminal evidence.
   - Record cost and dynamic graph metrics.

2. Select an actual comparison scenario.
   - The one-shot single-agent baseline must fail the hidden oracle materially.
   - The failed single-agent attempt must still produce useful partial work.
   - The failure should come from missed discovery, weak validation, or missing
     corrective work, not quota, setup problems, or an oracle that encodes a
     preferred implementation seam.
   - The scenario should have enough coupled requirements and repo-state
     discovery that adaptive planning is genuinely relevant.

3. Run the three-way A/C/E comparison.
   - Same starting repo snapshot.
   - Same weak acceptance and hidden oracle, both run outside agents.
   - Comparable model/runner budget where practical.
   - Record pass/fail, cost, tool calls, retries, accepted/rejected graph
     patches, corrective work, and final review result.

4. Update this file after each accepted result.
   - Keep this document compact.
   - Put detailed historical logs and superseded plans under
     `docs/dynamic-graph/complete/`.
