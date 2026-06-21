# Dynamic Graph Contract And Readback Evidence - 2026-06-21

## Scope

This note records the deterministic foundation added before spending more live
agent tokens on Arm E or A/C/E comparison work.

## Graph Node Contract

| Node type | Prompt source | Tools exposed | Required inputs | Output ports | Command bindings | Graph patch authority | Expected transition |
|---|---|---|---|---|---|---|---|
| `planner` | `GraphDispatchExecutor._prompt_for_node()` planner packet | Codex dynamic tools: `update_checklist`, `submit`, `request_clarification`, `submit_graph_patch`; scoped MCP uses builder workflow tools plus declared tools | Routine snapshot is pre-bound; planner packet includes frontier, evidence, freshness, proposals, allowed ops, templates, examples | No output by default; accepted patches are durable `graph_patch_accepted` events | None | May submit `PLANNER_OPS`; exactly one successor planner is allowed; plain submit is rejected until a graph patch is accepted | Patch accepted/rejected feedback is returned to the agent; accepted non-gap planner patch can complete the node even if the process exits before plain submit |
| `worker` / `builder` | `_worker_like_prompt()` from title/objective/context and dynamic feature fields | Codex builder tools: `update_checklist`, `submit`, `request_clarification`; scoped MCP builder workflow tools | Usually `candidate_under_test` is not required; concrete dynamic patches may add required evidence/file-state inputs | `candidate` implementation record plus file-state boundary | None | None | Submit produces an `ImplementationCandidate`; downstream verifier/check inputs bind by edges |
| `verifier` | `_prompt_for_node()` verifier rubric packet | Codex verifier tools: `submit`, `grade`, `complete_recovery`; scoped MCP verifier workflow tools | `candidate_under_test` must be bound to the candidate id being graded | `verification_report` canonical port; legacy `verification_result` now canonicalizes to `verification_report` | None | None | Submit validates candidate provenance, emits `verification_passed`/`verification_failed`, and binds downstream `verification_evidence` edges |
| `gap_planner` | Planner packet plus `gap_analysis_contract` and `gap_analysis_obligations` | Same planner dynamic tools, including `submit_graph_patch` | `verification_evidence` from a verifier/check result | With an accepted non-empty patch: `gap_plan`, `gap_classification`, `classified_gap` | None | May create corrective worker/verifier/check nodes only in `corrective_work_region`; cannot create planner successors or retire executable nodes; no-op rejected while a required `classified_gap` successor waits | Must submit a patch before plain submit; blocking obligations warn about final invariant checks waiting on `verification_evidence` |
| `corrective` / `fixer` | `_worker_like_prompt()` with corrective dynamic worker instruction | Codex builder tools: `update_checklist`, `submit`, `request_clarification` | Required `classified_gap` edge | `candidate` corrective implementation record plus file-state boundary | None | None | Corrective worker is released only after gap planner classifies a gap; corrective verifier consumes its candidate |
| `invariant` / `check` | `_worker_like_prompt()` for check node payload | Codex builder-phase tools: `update_checklist`, `submit`, `request_clarification`; submit is interpreted by graph runtime as check completion | Required `verification_evidence`; scheduler also requires `has_command_definition` | `check_result` | `command_definition`, `hidden_oracle_command`, or `command_binding: dynamic_feature_hidden_oracle`; command binding is resolved from the stored routine snapshot when the check node is created | None | Completion remains blocked until the check result is accepted; run `complete` is rejected while final invariant blockers remain |

## Contract Failure And Fix

Initial live readback symptom: one Arm E view showed final invariant still
planned/blocked on missing `verification_evidence` while the corrective verifier
had emitted a verifier result. Subsequent API detail for the same run showed the
final invariant completed with `verification_evidence` bound, so that live
symptom was at least partly a stale aggregate read-model problem. The still-real
contract class was reproduced deterministically without another live agent run:

Deterministic failure reproduced locally:

- edge contract uses canonical `from_port: verification_report` and
  `to_port: verification_evidence`;
- planner-created edge aliases already canonicalized `verification_result` to
  `verification_report`;
- callback output records did not canonicalize verifier port aliases, so a
  verifier record on `verification_result` was accepted but did not bind the
  final invariant edge.

Fix:

- `src/orchestrator/graph/commands.py` now canonicalizes verification record
  output port `verification_result` to `verification_report` before storing and
  routing the record.
- `tests/unit/test_graph_commands.py` now proves that a corrective verifier
  record using the legacy alias binds `check-final.verification_evidence` and
  makes the final check schedulable.

Existing coverage still proves structural edge requirements, horizon-template
ports, gap-planner obligations, no-op rejection, hidden-oracle command binding,
and the scripted planner -> worker -> verifier -> gap -> corrective -> check
path.

## Readback Slowness Evidence

The deterministic profiler now measures both the prior snapshot/read-model path
and the active append/read pattern:

```text
uv run python scripts/profile_graph_readback.py --events 1000 --heavy-every 2 --payload-kb 128 --iterations 3
```

Representative result after adding the active-pattern measurement:

```text
read_model.graph_projection_snapshot_after_append median 285.247 ms
endpoint_like.graph_projection_after_append        median 75.339 ms
read_model.graph_projection_snapshot cold max      249.440 ms
read_model.graph_projection_snapshot warm median     1.309 ms
endpoint_like.graph_events_summary median           14.635 ms
endpoint_like.graph_events_full median             228.849 ms
```

Root cause:

- every graph append invalidated `GraphProjectionSnapshotModel`;
- `/graph`, `/graph/scheduler`, and `/graph/decisions` rebuilt disposable read
  models inside GET request handling when the snapshot was stale;
- those rebuilds read the graph stream, reduce projections, and write/delete
  disposable read-model rows, adding SQLite writer contention during active
  callback/appender work;
- summary event and node-detail endpoints were already much better bounded, but
  can still wait behind snapshot rebuild writes.

Fix:

- `/api/runs/{id}/graph` now uses `read_run_projection()` and pure projection
  response building.
- `/api/runs/{id}/graph/scheduler` and `/graph/decisions` now use
  `read_run_light()` and pure response building.
- These aggregate GET endpoints no longer rebuild/write snapshot read models on
  the request path.

Remaining performance work:

- normalize hot graph event fields or maintain incremental snapshots so light
  readers do not need `json_extract` over the whole stream;
- add an event-loop-lag/concurrent writer mode to the profiler if active-run
  traces still show stalls;
- consider SQLite `busy_timeout`/WAL only after endpoint write amplification is
  removed from the hot read path.

## Validation Evidence

Focused checks run during this slice:

```text
uv run pytest tests/unit/test_graph_commands.py::test_verifier_callback_canonicalizes_result_port_for_final_invariant_binding -q
uv run pytest tests/integration/test_graph_api.py::test_active_graph_execution_readback_uses_bounded_summary_paths tests/integration/test_graph_api.py::test_graph_events_from_position tests/integration/test_graph_scheduler_api.py tests/integration/test_graph_read_models.py -q
uv run python scripts/profile_graph_readback.py --events 1000 --heavy-every 2 --payload-kb 128 --iterations 3
```

The first test failed before the port canonicalization fix and passed after it.
The API/read-model checks passed after switching aggregate graph read endpoints
off the snapshot rebuild path.
