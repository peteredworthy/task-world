# Integrated verification and closure — September 15, 2026

User authorization: verify the complete decision-runtime implementation, commit,
and merge to main. After initial review found missing joined behavior, the user
explicitly requested completion of the missing work before verification and merge.
No paid model execution, activation, or historical-run mutation is included.

## Requirements and initial findings

| Requirement | Required proof | Initial status | Closure work |
|---|---|---|---|
| Slices 1–5 | Canonical answer ownership, typed runtime paths, exact authority, staged/witnessed atomic completion, durable budgets/recovery and legacy compatibility | Independent integrated review in progress | Inspect committed implementation and concrete regressions |
| 6A | Qualification identity must describe the interaction actually executed | Failed: identity stamped onto legacy controller scenarios | Bind qualification to actual decision-v1 execution |
| 6B | One batch, dependent batches, verified amendment through production create/start, signal consumer, driver, dispatch and completion | Located in main checkout after initial worktree-only review | Incorporate original API-path tests and readiness fix; join them with qualification cases |
| 6C | Joined correction, blocker, cancellation/restart, defective candidate/verifier and compatibility controls with observed outcomes | Failed: synthetic completed/qualified flags | Use actual runtime and derive observations from durable state |
| 6D | Decision-v1 smoke exact file oracle and public readback with terminal ownership | Failed: probe remains legacy | Add typed smoke while retaining explicit legacy control |
| 6E | Fixed evaluation cases, feasible phase/case/total budgets, accounting and stop rules | Review in progress | Align with joined driver, preserve unknown telemetry |
| 6F | Independent review, final hashes, compatibility evidence, unmodified full gate | Pending | Complete only after functional gaps close; pause edits for gate |

## Reproduced false qualification

Using `run_reliable_plan_joined_cases` against fresh temporary SQLite followed by
fresh `GraphController.read_projection` for its correction run:

- Reported qualification: true; outcome: completed; unfinished node list: empty.
- Stored run state: active; three active leases and running downstream nodes.
- Actual execution attempts: zero.

This is a blocking mismatch, not model reliability evidence. The existing tests
assert the wrapper's flags without verifying the underlying lifecycle. Original
proof: temporary `decision-final-review-9phkvtj8/review-result.json`; the closure
must retain a regression asserting durable state against reported completion.

## Validation log

Final independent review and closure evidence are recorded below. Earlier slice
ledgers remain historical claims; this ledger supersedes their completion status
where the findings above contradict them.

## Additional runtime authority finding

Independent review found that successor and correction baseline resolution,
including the trusted macro path, accepted membership in `evaluated_record_ids`
as plan-verification authority. The verifier's direct `semantic_artifact` input
must identify the selected plan; transitive evidence membership is insufficient.
The correction pass must test a report directly judging B while citing A and
reject using that report to authorize A. This also closes a required slice 4
review lesson, not just qualification infrastructure.

## Initial closure checks

- Baseline evaluation unit tests: 17 passed.
- New joined completion/manifest and phase-budget requirements: 13 expected
  failures, 14 passes before implementation; after owner changes, 27 passed.
- New decision manifest case-description test: expected failure before the
  manifest derived its descriptions from joined cases; then 2 targeted tests
  passed, including unchanged legacy manifest hash compatibility.
- Current implementation branch fast-forwarded to existing main `1cf10fc72`;
  this preserved uncommitted changes and incorporated earlier merge documentation.

## Evaluation and authority closure

- Evaluation/report regressions now cover phase/case/batch allowance, repeated
  execution identities for one node, rejected-answer deliveries, stop-on-first
  partial reports, absent evidence, missing accounting, overrun retention and
  false completion with zero runner starts. Final evaluation unit set: 37 passed;
  Ruff, formatting, focused Pyright and canonical manifest equality passed.
- Phase caps remain one start, two received rejected answers and 180 seconds.
  Multi-phase case caps are separately bounded; the prepared manifest remains
  unexecuted and requires explicit operator authorization.
- Projection evaluation now derives interaction identity from its frozen routine
  snapshot. Explicit caller mismatch fails. Comparisons require qualified
  interaction identities for dynamic arms while retaining a legacy baseline's
  own legacy identity. Both changes had failing behavioral regressions first.
- Plan authority now checks the report producer's exact direct plan input and
  report candidate identities. The helper is shared by successor resolution,
  correction baseline selection, repair and trusted macro compilation. Historical
  untrusted legacy macro lookup retains its prior behavior.
- Authority builder validation: 174 focused pure/regression tests plus 18 schema
  consumer tests passed; focused Ruff and Pyright passed.
- Independent production integration after the authority change:
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_graph_decision_runtime.py::test_decision_dispatch_stages_cas_then_atomically_finalizes --override-ini='addopts=' --tb=short`
  — 7 passed in 32.12 seconds. Cases include proceeding, final/nonfinal amendment,
  rejected amendment, blocker, and cancellation winning the finalization race.

### Integration attempt during concurrent edits

The authority builder also ran
`uv run pytest -n 0 tests/integration/test_graph_decision_runtime.py -q`.
Result: 71 passed, 2 failed, 9 warnings in 297.94 seconds. Failed tests:

- `test_work_result_failure_publishes_no_candidate_or_decision[failed-check-cli_subprocess]`
- `test_initial_discovery_brief_runs_through_production_dispatch_and_finalization[post-answer-mutation-cli_subprocess]`

Both reported `BoundaryValidationError: decision answer receipt source identity mismatch`.
Source files were changing while the suite ran. This attempt does not close those
regressions; they must run again after source edits pause. The builder retained
stdout only in its tool transcript, so no separate raw log is available for that
attempt. Subsequent stable validation and the commit gate will retain raw logs.

## Slice 6B checkout discovery and preservation

The original slice 6B changes were present in the main checkout, not in the
implementation worktree. The initial worktree-only review's claim that 6B was
wholly absent was incorrect. Its ledger and source hashes match the main files.
The original change includes three API-start joined decision-v1 success cases,
a worker-only dependency precondition and scheduler support for that generated
precondition, plus scheduler regressions. These are being incorporated into the
implementation worktree and the final validation.

Original main changes were preserved before integration in
`/tmp/decision-runtime-main-preserve-m0qn5rvv/`, including all five modified/new
files, their SHA-256 manifest, and `main-diff.patch`. No original main file was
changed by this preservation step. The preserved slice 6B ledger is included in
this directory with its original evidence intact.

## Evaluation negative oracle closure

Independent review reproduced a verifier-negative result qualifying after an
unrelated provider outage. The negative case now declares its intended failure
classes and requires evidence of that cause from an execution that actually
started. An empty attempt list or provider outage cannot establish bounded
semantic failure. Partial and failed reports retain their observations and
violations. All 41 evaluation unit tests pass; independent review confirmed the
provider-outage and empty-attempt cases fail qualification as required.

## Independent integrated review

A fresh Sol reviewer inspected the actual changes and retained evidence using
`review-prompt.md`. Its intermediate verdict passes criteria 1–9: substantive
typed answers, one submit channel, canonical schema consumers, staged/witnessed
atomic completion, exact authority and replay identity, verification coverage,
durable runtime budgets, frozen legacy compatibility, and existing runtime
ownership boundaries. Supporting checks are the 174 authority regressions,
18 schema-consumer cases, seven production finalization cases and evaluation
regressions above. Criterion 10 remains open until joined closure and the gate.

The reviewer confirmed another real joined correction defect: the original
failure and corrective product were terminal, but the completed, candidate-free
recovery planner's region remained pending. That prevented final run completion.
The required fix must derive acceptance only from the accepted corrective
candidate's direct classified-gap binding to that completed planner. It must
preserve unrelated pending regions and failed-candidate evidence.

The cancellation fixture also had its shutdown callbacks connected incorrectly:
it supplied the driver's safe-effect drainer as the process-quiescence callback.
The fixture must use the production sequence: prepare exact-owner shutdown,
quiesce the process registry, then drain the driver's recovery effects.

## Stable closure regressions

- Both exact tests from the concurrent-edit integration attempt passed after
  source edits paused: 2 passed, one Pydantic schema warning, 7.31 seconds.
  Command used the prescribed UV prefix, `pytest -q -n 0`, both full node IDs
  above, `--override-ini='addopts=' --tb=short`. Raw output:
  `/tmp/decision-runtime-final-verification/stable-receipt-regressions.log`.
- The prescribed ten-file immutable-projection closure passed: 809 tests in
  10.73 seconds, including behavior, flexible JSON, every-split replay,
  immutability, queries, duplicate IDs, codec, integrity, boundaries and direct
  performance. Command used the AGENTS.md focused projection command with the
  prescribed UV prefix. Raw output:
  `/tmp/decision-runtime-final-verification/projection-closure.log`.

## Cancellation and timing review

The joined restart case stops the live consumer, records exact-owner recovery
with reason `runner_died`, queues cancellation while the consumer is down, and
starts a fresh consumer. Acceptance requires the durable cancellation event,
cancelled graph/workflow state, no additional execution attempt after restart,
and zero active/suspended leases, process owners and pending outbox entries.
The independent reviewer passed this shutdown/restart-redelivery scenario;
active cancellation/finalization races are covered by the separate production
integration cases above.

The fixture's graph and liveness clocks now share the injected clock. It retains
the normal reconciliation interval; a longer fixture-specific interval must not
hide stale-execution detection.

Raw focused logs and the untouched original main-checkout snapshot also have
persistent local copies under
`.orchestrator/review-evidence/decision-runtime-final/` in the implementation
worktree. This ignored evidence directory allows the commit gate to write its
exact log and result without changing tracked files while hooks run.

## Original slice 6B integration

The original one-batch, dependent-batches and independently verified amendment
API tests all passed on the integrated source: 3 passed in 103.36 seconds.

Command:
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_graph_sequential_product_path.py::test_decision_v1_joined_success_cases_use_production_driver --override-ini='addopts=' --tb=short`.
Raw log: `.orchestrator/review-evidence/decision-runtime-final/original-slice-6b-api.log`.

An AST comparison against the preserved main-checkout file found no removed or
added functions. Only the scripted `_answer` body changed, replacing an escaped
literal newline with an actual newline in its product. Test ordering and comments
also changed during integration. The five original main files still matched
their preservation hashes before final integration.

## Final independent source review

The fresh Sol reviewer reports no remaining source blocker. Criteria 1–9 pass;
criterion 10's source review passes, with final evidence conditional on the
frozen-source ten-case run and unmodified commit gate.

| Area | Review conclusion and evidence |
|---|---|
| Authored contracts and schema ownership | Substantive typed answers remain model-authored; graph/lifecycle facts stay in code. One submit channel and canonical generated schema consumers remain intact. Custom YAML schemas are unchanged. |
| Atomic completion and authority | Exact witness, staged publication, serialized finalization and direct plan authority remain enforced. Seven production boundary cases, 174 authority tests and 18 schema-consumer tests support the review. |
| Correction and negative evidence | Observations follow durable failed reports/checks, classification or escalation, and candidate citations. Unrelated runner recovery cannot qualify a non-cancellation case. |
| Recovery-region closure | Only the exact completed gap planner consumed by accepted corrective work can close its single-node region. Replay with another unfinished region member stays pending; the 809-test projection closure passes. |
| Cancellation and restart | Exact-owner shutdown recovery followed by durable cancel redelivery is distinct from the separately tested active finalization race. Both consumers are cleaned up on exception paths. |
| Evaluation accounting | Durable limits, actual starts, partial reports, unknown telemetry and semantic failure causes remain explicit. The reviewer personally reran the provider-outage and empty-attempt exploits; neither qualifies. |
| Compatibility | Frozen legacy interpretation and legacy manifest hashes remain separate from decision-v1 schema/compiler identity. Supported transport and original API tests remain present; the original three success cases pass. |
| Runtime structure | The fixture uses the existing graph driver, signal consumer, dispatcher, controller, event store and public projection APIs. No second authority registry, scheduler or event store was introduced. |

The reviewer also ran `git diff --check` successfully and inspected the final
restart cleanup. It did not duplicate trustworthy focused runs or execute
source-bound suites while source files were changing.

Final verdict after the completed runs: **PASS; no blocking findings remain.**
All ten review criteria pass. The unmodified commit hooks remain the merge gate.

## Frozen-source joined result

The full ten-case integration test passed in 203.29 seconds:
`test_joined_decision_v1_correction_and_failure_cases_are_bounded`.
The passing run checks the four ordinary success/smoke cases, correction,
blocker, cancellation/restart, both false-acceptance negatives and the explicit
isolated compatibility control. Raw log:
`.orchestrator/review-evidence/decision-runtime-final/joined-ten-case-final.log`.

The earlier complete-set attempt failed after 163.38 seconds because the
cancellation oracle expected the wrong lifecycle event field and recovery
reason. Its unchanged raw output remains in `joined-ten-case.log`. The final
case observes `to_state=cancelled` after exact-owner `runner_died` recovery and
cancel redelivery; it does not relabel that recovery as a cancellation race.

The saved paid evaluation JSON exactly matches the canonical unexecuted manifest.
The [final source manifest](slice-6f-final-source-manifest.json) records all 22
changed source/example/test files, their review-base hashes and final hashes.
Unchanged source is identified by review-base commit `1cf10fc72`.

The server qualification-receipt path also passed:
`test_product_path_runner_records_decision_v1_identity_separately_from_legacy`
— 1 passed in 204.38 seconds. Its decision-v1 branch executes the joined cases
before accepting the receipt; it cannot qualify by relabeling legacy scenarios.
Log: `decision-v1-numbered-qualification.log` in the local evidence directory.

After replacing the lifecycle example's private consumer call with public
start/stop and moving its file read off the event loop, both lifecycle tests
passed in 41.94 seconds. Ruff check, Ruff format check and focused Pyright pass
on that final source. Logs are retained in the same evidence directory.

The exact no-model smoke CLI also exited 0 in 23.24 seconds. Its
[saved result](slice-6f-smoke-result.json) records decision-v1, completed
graph/workflow state, seven finalized executions and zero remaining ownership or
outbox work. The final reviewer independently checked the persistent CLI
worktree's exact `stage3-smoke-ok\n` bytes, mode 100644 and clean Git status.

The [joined result summary](slice-6f-deterministic-results.json) preserves
post-test readback for nine runtime cases and the isolated compatibility control.
Pytest's temporary database/worktree paths are disposable, not permanent replay
artifacts. A later attempt to reread an expired temporary path could not proceed;
the retained passing test logs and captured readback remain the evidence, and
the separate persistent CLI workspace was checked directly.

## Commit gate evidence

The operator explicitly authorized commit and merge. The commit must run the
repository's unmodified hooks with all tracked-file edits paused. The exact
command log and exit/result record are saved in the implementation worktree at
`.orchestrator/review-evidence/decision-runtime-final/commit-gate.log` and
`commit-gate-result.json`; this ignored location permits gate logging without
changing the reviewed tracked files. A failed hook blocks commit and merge.

The first actual hook attempt stopped at Ruff format after reformatting one
expression in `graph/decisions.py`; later hooks did not run. Its log and input
source manifest remain in `commit-gate-attempt-1.log` and
`commit-gate-attempt-1-source-manifest.json`. The formatter's change preserves
the exact Python AST. It was accepted and the final source manifest updated
before restaging and rerunning the unmodified hooks. An earlier approval-review
capacity error prevented execution altogether; it did not run a hook.

No live server, live database/history, historical run or model evaluation was
started or changed. Scripted execution proves deterministic infrastructure
behavior; it provides no real-model reliability estimate.
