# Five-run live qualification — 7 September 2026

Status: qualification not achieved. The first live trial automatically paused
with `graph_blocked` before implementation; zero of five trials completed.
Run ID: `c15e02ab-052c-45af-ab65-b3334b2c9ffb`.
Trials 2–5 were not launched after this conclusive failure. The diagnosis and
archived evidence are in `live-qualification-result-2026-09-07.md` and
`live-qualification-2026-09-07/`.

Correction to preparation diagnosis: the initial sandboxed curl failure did not
establish that the server was offline. A subsequent health request returned
`{"status":"ok"}`, a listener was observed on port 8000, and access outside the
sandbox successfully returned the runner/repository APIs. The existing server
is being used; no server was started or restarted by this campaign.

The user selected Luna workers. Assignments are Codex Server with Luna for
discovery/implementation/correction and Sol for planner/verifier/successor.
The controlled restart has not occurred. This is failed live qualification
evidence, not a successful reliability claim.

## Execution contract

Use the normal repository/routine discovery, qualification-grant, run creation,
start, event, health, and completion APIs. Use the checked-in
`dynamic-graph-feature` routine and the bounded sequential reliable-plan profile.
Resolve the source branch and commit through the repository API; preserve the
same controller source throughout the attempt sequence. Record the routine SHA
and actual model assignments, including successor planning.

Run one task at a time in its orchestrator-created worktree. Tasks create small
standalone developer utilities and their tests; they do not edit server code or
production state. Keep resulting changes in their run branches for review. Check
completion actions before starting so that qualification does not auto-deploy or
merge a candidate into the supervising checkout.

Each task must use discovery, independently reviewed planning, implementation,
mechanical checks, fresh-context verification, and final acceptance. Exercise
two bounded planning horizons where the supported profile requires them. Use
the project's unchanged submission gate in addition to task-specific checks.

## Bounded software tasks

The specifications below will be embedded in each create-run request so a new
worktree does not depend on this uncommitted preparation document. Utilities
read explicit input files; they must not read the production journal or database.
Use Python through `uv run`, real temporary files, and no mocking.

| Trial | Deliverable | Fixed acceptance obligations | Status |
| --- | --- | --- | --- |
| 1 | Standalone JSONL validation utility | Accept valid object records and blank lines; reject malformed JSON and non-object records; report one-based line numbers; return nonzero on invalid input; test empty input, Unicode, and multiple errors. | Failed qualification: paused `graph_blocked` before implementation |
| 2 | Standalone JSONL-to-CSV conversion utility | Explicit ordered column selection; correct CSV quoting for commas, quotes, and newlines; deterministic rendering of nested values; missing cells remain empty; malformed input produces an actionable error; real-file round-trip tests. | Not started |
| 3 | Standalone usage aggregation utility | Aggregate input, output, and cached-input tokens by model; do not add cached-input tokens twice; deduplicate repeated usage IDs; distinguish missing usage from zero; reject invalid negative/count values; order-independent real-fixture tests. | Not started |
| 4 | Standalone run-duration summary utility | Pair explicit start/end records by run ID; normalize timezone-aware timestamps; represent unfinished runs explicitly; reject end-before-start and conflicting duplicates; test interleaved runs and UTC offsets. Perform the controlled server restart during this trial if it has not already been exercised. | Not started |
| 5 | Standalone qualification-result comparison utility | Compare two explicit result files; include failed and incomplete trials; report completion and intervention counts, token totals, and wall time; represent unavailable dollar costs as unavailable; deterministic output; reject incompatible units and malformed records. | Not started |

## Correction and restart proof

A correction counts only when a real candidate fails a mechanical acceptance
check or independent verification, the runtime binds that exact failure evidence
to corrective work, and a corrected candidate subsequently passes. A seeded
bug repaired on the first attempt, a transport retry, a fabricated bad grade,
or a plan claiming correction does not count. Preserve the failed and corrected
candidate identities and receipts. If the five runs contain no genuine
correction, report this criterion as unproven; do not label the campaign passed.

After authorization, restart only the server process owned by this campaign,
while a qualification run is executing. Record process identity and lifecycle
events before and after. Recover through normal lifecycle APIs, including an
explicit resume if the supported shutdown policy requires it. Verify that work
completes with no duplicate accepted records or active leases. Do not patch the
graph or restore state manually. Avoid restarting while unrelated work is active.

## Evidence and stop conditions

For every attempted trial, retain run ID; controller/source/routine versions;
runner and models; initial and final snapshots; accepted requirements and
candidate-bound check/verifier receipts; canonical event pages; terminal run and
health readbacks; intervention/correction/retry counts; token/cache counts;
available cost readback; wall time; and restart lifecycle evidence when relevant.
Dollar costs remain unavailable unless a supported priced readback provides them.

Success requires five consecutive completed, independently accepted real tasks,
zero unresolved final blockers, zero active leases, no manual graph/state repair,
and both correction and restart proof. Preserve unsuccessful attempts. If a run
blocks or fails, collect the first meaningful cause and stop the sequence for
diagnosis rather than launching more equivalent model work. A failed sequence is
a qualification result, not grounds to silently change the criteria or claim
completion from offline tests.

## Preparation evidence

- Read the September 4 architecture review and September 5 closure matrix.
- Read the September 6 graph execution repair ledger and diagnosis addendum.
- Inspected the existing three-arm live harness and the default-collected
  sequential product-path tests. The three-arm harness is a reference for API
  collection, not evidence for five consecutive live tasks.
- Inspected the checked-in dynamic graph routine and run API schemas.
- Initial sandboxed API connection failed; later health and API checks succeeded.
- Server-owned qualification preflight passed all ten scenarios before run 1.
- Repository API resolved `task-world-current/main` to `13b6ebd07`; run readback
  must provide the final pinned source SHA after start.
- No active runs were listed before creating trial 1.
- Request, fixed specification, operator-owned acceptance script, qualification
  grant, and API responses are retained under
  `/private/tmp/qualification-20260907/` (the grant response is initially at
  `/private/tmp/qualification-grant-1.json`).

## Trial 1 observations

- Start applied at `2026-09-07T14:53:45Z`; worktree `worktrees/r199`, source
  `13b6ebd07678ed404ebf8024013af2374699700d`.
- Initial planner: two rejected graph patches, then accepted skeleton at graph
  position 35. Its usage record identifies `gpt-5.6-sol`.
- Discovery plan artifact accepted at positions 81–82; worker usage identifies
  `gpt-5.6-luna`.
- Plan verification failed at position 108. Sol graded the plan D because it
  omitted explicit recovery obligations after failed checks despite otherwise
  covering the feature and two horizons.
- Runtime automatically created a recovery planner at position 112. Its first
  two patches were rejected for corrective-region and failed-check input rules.
  Its eighth patch was accepted at position 167. The nested revision worker and
  verifier lacked sealed model assignments, and dispatch failed before the
  corrective worker could execute. The run automatically paused at
  `2026-09-07T15:07:57Z`, with zero active leases and no implementation candidate.
  No operator graph edits or state repairs occurred.
- API routine SHA/commit fields are null. Evidence therefore retains the source
  SHA, full embedded routine, and checked-in YAML content hash rather than
  inventing a routine-version value.
