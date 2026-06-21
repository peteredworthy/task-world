# Dynamic Graph Context Brief

Last updated: 2026-06-18

This is the compact starting point for continuing dynamic graph operational work.
The full durable log is `docs/graph-approach/dynamic-graph-operational-plan.md`;
do not load it wholesale unless a specific section is needed.

## Operating Rules

- Follow `AGENTS.md`: use `uv run` for Python, interact with orchestrator state
  through REST APIs only, do not touch `orchestrator.db`, do not delete DBs, do
  not run git operations on the main tree, and do not bypass hooks.
- Prefer `codex_server` with model `gpt-5.3-codex-spark` for new orchestrator
  runs unless the user explicitly changes direction.
- Use Mind-the-gap discipline: establish baseline, choose one verifiable chunk,
  build only that chunk, independently validate, and update compact durable
  evidence before continuing.
- Stop using expensive live agent runs as the diagnostic loop. Known dynamic
  graph smoke failures must be covered by deterministic harness checks before
  another live Arm E retry.

## Current State

- Dynamic graph is partially operational. A non-isolated Arm E smoke run
  completed successfully, proving live dynamic patching and invariant
  completion on a tiny scenario.
- Hidden-oracle isolated Arm E is not operational yet. The latest Spark run
  progressed past the previous Claude quota blocker but stuck in a running
  verifier lease after expiry.
- The active/problem run is
  `498f23f3-aadc-4b88-91b0-145ade3dd6f0`, routine
  `dynamic-graph-feature`, execution mode `graph`, runner `codex_server`, model
  `gpt-5.3-codex-spark`, worktree `worktrees/r306`.
- Verified Spark evidence: root planner accepted two patches, implementation
  completed, weak verifier passed, gap planner accepted corrective wiring, and
  corrective worker completed.
- Verified blocker: `verifier-corrective-dynamic-smoke` reached `running` at
  graph position 113, but had no output records after lease expiry
  `2026-06-18T10:47:26Z`. The run stayed API `active` with no pause reason.
- The corrective artifact contains `dynamic-smoke` but lacks
  `validation-strengthened: true`, so the hidden oracle still fails.
- Spark run counters were extreme for smoke-sized work:
  `5,002,238` input tokens, `50,170` output tokens, `4,546,816` cache tokens,
  and `102` actions.

## Immediate Next Slice

**DG-5.2e: Codex Verifier Lease Timeout Harness** now has local deterministic
coverage. Do not run another live Arm E retry until the focused checks below
remain green.

Implemented local evidence:

- `schedule_tick` turns an active lease whose `expires_at` is in the past into
  durable `lease_expired` plus failed-node evidence with reason
  `lease_expired_without_callback`.
- The same tick excludes just-expired leases from resource accounting, so an
  expired verifier lease no longer keeps same-path work blocked indefinitely.
- Graph driver blocked-reason classification now surfaces failed node evidence,
  so a run pauses with an explicit reason instead of staying silently active.
- Graph prompt generation now caps oversized planner/worker/verifier prompt
  sections; a verifier rubric with multi-megabyte content is truncated under a
  fixed prompt budget.

Verified locally:

- `uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py -q`
- `uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py`
- `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py`

Remaining before a live Arm E retry:

- Run the existing graph API readback integration coverage, including
  `/api/runs/{id}/graph`, `/api/runs/{id}/graph/events?payload_mode=summary`,
  and node readback, against an active graph run.
- Profile the slow active-run API paths if latency still spikes.

Original DG-5.2e deliverables:

Deliverables:

- Deterministic harness/test for an active graph lease that expires without a
  callback, especially under `codex_server`.
- Graph driver behavior that reports, pauses, retries, or recovers explicitly
  instead of leaving a run indefinitely `active`.
- Prompt/context budget check for graph verifier nodes so smoke-sized work
  cannot build multi-million-token packets.
- Bounded readback check for `/api/runs/{id}/graph`,
  `/api/runs/{id}/graph/events?payload_mode=summary`, and node read endpoints
  while graph agent execution is active.

Done when focused tests reproduce the failure class without a live LLM and prove
the outcome is bounded and explicit.

## Profiling Lead

The slow API responses during the Spark verifier run likely indicate
read-contention, oversized graph prompt/readback packets, blocked subprocess
interaction, or projection serialization cost. Initial observation showed the
backend process running a `codex app-server` child, while the active Codex
verifier itself had child `curl` probes against `/api/runs/<run-id>`.

2026-06-18 local profiling update:

- Added `scripts/profile_graph_readback.py`, a deterministic SQLite-backed
  single-run graph readback profiler. It generates synthetic heavy graph events
  and times full event reads, summary reads, projection response building, full
  event serialization, and node-detail serialization without a live LLM or
  running server.
- Default profile (`300` events, heavy payload every `2`, `64 KiB`, `5`
  iterations) showed:
  - full event materialization median `13.874 ms`, `11.2 MB` output;
  - summary readback median `8.783 ms`, `73.7 KB` output;
  - projection endpoint-like path median `21.434 ms` despite an `806 B`
    response;
  - full events endpoint-like path median `35.409 ms`;
  - node detail endpoint-like path median `20.770 ms`, `3.8 MB` output.
- Heavier profile (`1000` events, `128 KiB`, `3` iterations) showed:
  - full event materialization median `82.405 ms`, `75.1 MB` output;
  - summary readback median `38.856 ms`, `246 KB` output;
  - projection endpoint-like path median `103.441 ms` for a `790 B` response;
  - full events endpoint-like path median `214.313 ms`;
  - node detail endpoint-like path median `109.111 ms`, `26.0 MB` output.
- Initial conclusion: the most deterministic local bottleneck is not projection
  JSON size; it is endpoints that need tiny projections or one node detail but
  still load, JSON-parse, and Pydantic-validate the entire heavy graph event
  stream. Summary events avoid most response bloat but still perform two
  queries and JSON extraction over the same event table.

2026-06-19 readback optimization update:

- Added light graph event readers that avoid selecting full `events_v2.payload`
  unless the caller explicitly asks for it:
  - `read_run_projection()` for the compact `/api/runs/{id}/graph` projection;
  - `read_run_light()` for scheduler, decision, and default node-detail
    readback;
  - existing `read_run()` remains the explicit full-payload path.
- Changed `/api/runs/{id}/graph/events` default `payload_mode` to `summary`.
  Full event bodies now require `payload_mode=full`.
- Changed `/api/runs/{id}/graph/nodes/{node_id}` default `payload_mode` to
  `summary`. Full node event/output/file-state payloads now require
  `payload_mode=full`.
- `/api/runs/{id}/graph/file-state` remains the explicit detailed file-state
  inspection endpoint and still reads full event payloads.
- Heavy profile after optimization (`1000` events, `128 KiB`, `3` iterations):
  - full event materialization median `86.846 ms`, `75.1 MB` output;
  - projection minimal reader median `40.871 ms`, `368 KB` intermediate output;
  - `/graph` endpoint-like path median `69.855 ms` for a `790 B` response;
  - `/graph` full-payload baseline median `108.614 ms`;
  - full events endpoint-like path median `224.334 ms`, while summary events
    median `42.189 ms`;
  - node detail summary median `88.956 ms`, `33 KB` output, versus full node
    detail median `116.835 ms`, `26.0 MB` output.
- Remaining deterministic bottleneck: SQLite `json_extract` over many rows is
  still a cost even when payload bodies are not selected. A later normalization
  pass can split stable event metadata columns or projection tables if this
  remains too slow.

Useful next profiling work:

- Run a small HTTP latency matrix for run, graph summary, graph events summary,
  node readback, and activity endpoints while the run is active.
- Sample backend and `codex app-server` process stacks if OS permissions allow.
- Add deterministic microprofiles/tests around graph event projection,
  summary serialization, prompt packet construction, and active-lease timeout
  handling.
- Fix the largest deterministic bottleneck before spending more live agent
  tokens.

`py-spy`, `yappi`, and `pyinstrument` were not installed when last checked.

## Comparison Planning

Do not start the A/C/E comparison arms until the scenario passes the admission
gate in `docs/graph-approach/true-comparison-plan.md`.

Key constraints:

- The scenario must be large enough that a single agent should not reasonably
  carry all work in one prompt: roughly 5-8 active requirements, repo-state
  discovery, cross-feature interactions, and at least one required
  post-validation correction.
- A one-shot single-agent baseline must fail the hidden oracle materially while
  producing useful partial work.
- Failure must come from missed discovery, weak local validation, or missing
  corrective work, not quota, tool setup, or an oracle that encodes a preferred
  implementation seam.
- Weak acceptance and hidden oracle must run outside all agents.
- DG-5.1x/DG-5.2x invariants must be covered by local harness checks before Arm
  E spends tokens.

See `docs/graph-approach/true-comparison-results.md` for accepted run evidence
and current Arm E status.
