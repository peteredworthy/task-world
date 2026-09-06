**Diagnosis of run `ca8faa94-f22c-4645-aab6-b5d6aca56d4b`, 6 September 2026**

The run failed because the production submission environment breaks the repository's own tests, useful failure details are truncated before they reach the agent, and recovery treats an agent stopping after rejection as a retryable runner death. Before implementation, the plan verifier also received an incomplete representation of its declared task and graded the missing implementation instead of the plan.

The recent fixes were present. The run's source commit was `08c8cd5e6` ("Close immediate architecture review gaps"), following `9774a84df` ("Implement reliable graph execution safeguards"). This is evidence of remaining integration defects on the patched version, not an old run accidentally using the previous code.

Evidence came from 1,089 activity events retrieved through the REST API, full node declarations and runtime-health readbacks, the unchanged `r195` source, and focused real-object reproductions. The bounded [evidence file](graph-run-ca8faa94-diagnosis-2026-09-06-evidence.json) contains audit IDs, test failures, candidate-tree hashes, and reproduction results. No production database was accessed directly. No source fix or run resume was performed.

The run was active from 14:30:03 to 16:34:59 EDT on 5 September. The API records 600 actions, 55,389,323 input tokens including 53,819,392 cache-read tokens, and 313,709 output tokens. These are reported usage, not a dollar-cost estimate. It ended paused with `graph_blocked`, no active leases, and no accepted implementation candidate.

1. **The submission gate makes at least five existing tests fail on an unchanged baseline.**

   The first worker baseline audit, event 95431, already recorded eight failures before the agent changed any code. Candidate submissions repeatedly hit the same family. The last submission audit, event 96197, reported 8 failed, 5,907 passed, and 5 skipped. The full project command comes from checked-in project configuration and is additional to the feature's focused acceptance command.

   Four failures are caused by `_isolated_gate_environment` injecting `ORCHESTRATOR_EVENT_JOURNAL_PATH` into every subprocess. `resolve_default_journal_path` gives that variable precedence over each test database's location. Tests expecting their own journal instead write to the shared gate journal. This also compromises isolation between independent test databases.

   Reproduction against the unchanged run source: the four affected journal tests pass without the override (4 passed in 0.60s) and fail with the gate's override (4 failed in 0.69s). Failures are missing journals and absent rotation segments, not feature assertions. See [gate environment](../../src/orchestrator/graph_runtime/submission_gate.py:933) and [journal resolution](../../src/orchestrator/db/access/jsonl_outbox.py:135).

   A fifth failure is a non-composable test assertion. `test_gate_unlocks_its_exact_checkout_before_cleanup` asserts that the string `orchestrator-submission-gate-` appears nowhere in `git worktree list`. Inside an outer gate, the test's legitimate root repository already lives beneath a directory with that name. The assertion reports a leak even after the inner worktree is correctly removed. The test passes directly and fails when invoked through the real `enforce_submission_quality_gate`, outside the Codex sandbox. See [assertion](../../tests/unit/test_graph_submission_gate.py:841).

   Three additional original failures concern supervisor relaunch after SIGKILL. They were not separately reproduced in this diagnosis. The agent's own sandboxed reproduction hit a different supervisor test, so its claim that one macOS permission failure explained the submission rejection was incomplete. The five independently reproduced failures are sufficient to make the actual gate fail deterministically.

2. **The callback removes the error information needed to repair the gate failure.**

   The gate captures the final output, including failed test names. `on_submit` then wraps the error in an acknowledgement using `detail[:4_096]`. The first 4,096 characters contain pytest progress dots and end around 57%; the failed-test summary is later. All four failed submission audit messages are exactly 4,096 characters and contain no `FAILED tests/` summary. See [callback](../../src/orchestrator/graph_runtime/dispatch.py:1966) and [failure rendering](../../src/orchestrator/graph_runtime/submission_gate.py:1225).

   This matches the agent's recorded statement that the bounded output omitted the failing test name. Running the command inside the agent's different sandbox produced different failures, so it investigated macOS process permissions rather than the gate's journal override and nested-directory assertion. The full structured result survived in the audit; the repair feedback did not.

3. **Recovery repeats completed effort after a submission rejection.**

   All three implementation attempts reached locally passing focused checks. The last reported 101 focused tests plus Ruff, Pyright, and a boundary scan. More strongly, the ordered submission gate got past the dynamic acceptance command and failed at the subsequent project command. This does not establish feature correctness: independent implementation verification never ran.

   Each agent eventually returned a final answer after its rejected submission. The runner returned normally, but `submitted_callback` remained false. `_run_agent` recorded `runner_died` with the generic detail `agent exited without a successful submit`. Recovery restored the baseline, then scheduled the same worker again. The three attempts produced different candidate trees; `r195` is now clean at its original commit. Candidate hashes remain in the audit, but the changes are no longer in the active worktree.

   The three-attempt cap added by the last fixes did work. It bounded the waste, but the loop still restarted model work for a validation-environment failure that was present before the first attempt. A typed rejection and an agent ending after that rejection need different treatment from an unexpectedly lost process. Preserve the last gate cause and candidate evidence, block for the necessary repair, and avoid rerunning implementation against unchanged infrastructure. See [normal return without submission](../../src/orchestrator/graph_runtime/dispatch.py:2100) and [retry scheduling](../../src/orchestrator/graph/commands/boundary.py:829).

4. **Baseline recording does not provide a practical unchanged-failure comparison.**

   `_ensure_submission_gate_baseline` records failing results and still proceeds to the agent. Exemptions require an explicitly declared fingerprint matching the exact baseline. The fingerprint hashes complete stdout/stderr identities and byte counts. Pytest timings, temporary paths, progress ordering, and additional passing tests change those identities even when the failed test set is identical.

   The first baseline and first submission have exactly the same eight failed test names but different exemption fingerprints. No exemption was declared in this run; the mismatch is an additional defect in the intended comparison mechanism, not the direct cause of this rejection. Raw output hashes are useful integrity evidence but unsuitable as the sole identity of an unchanged test failure. Fix the environment errors; do not automatically waive checks merely because they failed once. See [baseline handling](../../src/orchestrator/graph_runtime/dispatch.py:2900) and [fingerprint](../../src/orchestrator/graph_runtime/submission_gate.py:553).

5. **The plan verifier's task definition is lost in prompt construction.**

   The first verifier's accepted declaration explicitly says to verify the discovery artifact before implementation. Its `objective` and `acceptance` describe plan adequacy, but it has no `rubric`. `_verifier_packet` and the verifier prompt render requirements, bound records, and rubric; they omit the node's objective, acceptance, and semantic stage. Production rendering of this declaration confirms all three are absent and `Rubric: []` is present. The saved prompt summary corroborates the packet shape. This reproduction tests field propagation; it does not claim to reconstruct the entire historical bound-record packet.

   Event 94752 failed this *plan* because `test_work_plan_compiler.py` and the implementation were missing. The resulting gap planner tried to implement prematurely, then fought corrective-region and evidence requirements. Eventually it created another discovery/verification skeleton. The replacement verifier had an explicit plan-specific rubric and passed. See [verifier packet and renderer](../../src/orchestrator/graph_runtime/prompts.py:98).

   The supported profile should provide an explicit plan-review contract regardless of whether a planner happens to fill the rubric field. A plan review must assess coverage, feasibility, and obligations while treating implementation tests as downstream work.

6. **The supported path still requires live models to repair low-level graph mechanics.**

   The run recorded 25 rejected graph patches and five malformed command rejections. The first skeleton was accepted at 14:35; replacement discovery was accepted at 15:03; the implementation patch was accepted at 15:15. Errors included invalid selector fields, unknown ports, missing exact correction evidence, and recovery patches falling into initial-skeleton requirements.

   These rejections do not prove that each validator is wrong. They show that the admitted planner surface and repair feedback still impose considerable topology work. The prompt says to *prefer* macros, while raw ops remain available. The bounded sequential workflow exists, but live planning can still spend dozens of calls discovering its constraints. Preserve the validators and make the supported authoring path construct the required identities and wiring deterministically.

**Why the last fixes did not establish reliability**

`9774a84df` introduced the submission gate and its environment isolation, including the journal override, and the cleanup assertion that fails when nested. `08c8cd5e6` added the rejection acknowledgement containing the 4,096-character prefix truncation. The changes addressed real safety and lifecycle concerns, but also introduced or exposed the interactions above.

The new default-collected sequential tests are useful: they exercise the public API, durable signals, real graph machinery, correction, cancellation, restart, and bounded exhaustion. Their model behavior is scripted, their planner supplies the correct macro payload and rubric, and their target acceptance is a simple file-existence command. They do not run task-world's own configured suite inside its submission gate or test a valid plan-verifier declaration with objective/acceptance but no rubric. See [scripted planner](../../tests/integration/test_graph_sequential_product_path.py:355) and [acceptance configuration](../../tests/integration/test_graph_sequential_product_path.py:720).

The architecture review already marked five consecutive live runs as unproven. This failed run is the missing evidence: offline lifecycle correctness and schema enforcement have improved, while the full agent-to-gate-to-recovery path still fails to deliver accepted software.

**Repair order before another paid run**

1. Make gate isolation compatible with per-test journal injection and nested worktrees. Prove the relevant task-world tests pass inside the actual gate, with no skipped checks or blanket baseline exemptions.
2. Return structured failed-command evidence, failing test names, and the end of the output before truncating. Keep an audit reference for the rest.
3. Preserve the last rejection through normal agent return. Distinguish environment blockage, correctable candidate failure, submission-format repair, and actual runner loss. Retain rejected candidate evidence without advancing accepted snapshot authority.
4. Include semantic stage, objective, acceptance, and a stage-specific rubric in verifier contracts. Regress the exact admitted no-rubric plan verifier from this run.
5. Regress the combined failure sequence through the production API and gate: valid plan, implementation, gate-environment failure, normal agent exit, preserved cause/candidate, bounded stop, and successful continuation after repair. Then exercise real model completion before declaring the path reliable.

The immediate corrective work is concentrated at those boundaries. Adding more generic retries or launching the same feature run again would repeat the observed failure conditions.

## Resolution addendum — 6 September 2026

The offline defects above are repaired on `codex/graph-execution-repair`. This
addendum does not revise the historical evidence and does not claim live-model
reliability. It records what changed and how the supported product path was
exercised.

| Incident finding | Resolution | Exact product-path/regression evidence | Result |
|---|---|---|---|
| Four journal failures | The gate no longer overrides `ORCHESTRATOR_EVENT_JOURNAL_PATH`; test-owned per-database journal routing is preserved while HOME, XDG, cache, temp, and checkout isolation remain. | `test_configured_project_gate_runs_journal_and_cleanup_regressions_nested` runs the four named journal tests through `enforce_submission_quality_gate`. | All four pass directly and inside the actual gate. |
| Nested cleanup failure | The cleanup assertion examines parsed registered worktree paths, not an outer temporary directory substring. This was a test-composition defect, not a leaked checkout. | The same nested production-gate test includes `test_gate_unlocks_its_exact_checkout_before_cleanup`. | Passes nested; disposable checkout is removed. |
| Three supervisor failures | No supervisor source change was justified by the original evidence. The same three parametrized relaunch cases were instead exercised in the repaired gate environment. | The nested production-gate test includes all `[0]`, `[1]`, and `[2]` supervisor cases; they also run directly. | `3 passed` direct and all three pass nested. Earlier sandbox-specific process restrictions are classified as runner-environment observations, not application defects. |
| Rejection detail truncated before the failure summary | Submission acknowledgement now carries a typed category and structured bounded evidence: command/source, exit or timeout, failed IDs/evidence, tail diagnostic, explicit truncation and byte counts, full-output hashes, semantic fingerprint, and durable graph-event reference. | `test_codex_execute_retains_late_real_gate_failure_and_durable_audit` drives a concrete Codex JSON-RPC transport through the actual callback and gate with the summary after 4,096 characters. | The tool response retains the late failed ID/diagnostic and the durable audit reference. |
| Normal return overwritten as `runner_died` | A public typed rejection exception preserves the first meaningful cause and latest evidence. Candidate, format, and validation-environment outcomes remain distinct from transport loss and cancellation. | `test_normal_return_after_gate_rejection_preserves_candidate_failure` and the joined API scenario inspect durable events and public runtime health. | Cause and rejected candidate survive; no false `runner_died`; no active lease remains. |
| Unchanged environment failure caused rebuild loops | Complete structured project-test failures receive a semantic identity separate from integrity hashes. Matching baseline/submission failures block without retry; timeout, unknown, changed/added failures, and missing feature tests do not compare equal. Baseline failure is never an automatic exemption. | Unit identity matrix plus `test_api_environment_blockage_restores_rejected_candidate_and_continues`. The API test repairs an external sentinel, submits the exact identity/position, restores the rejected snapshot through the real outbox, and resumes. | No redispatch occurs while blocked. Continuation reaches acceptance with one implementation mutation; explicit operator action is required. |
| Plan-verifier contract omitted its declared task | Verifier packets render semantic stage, objective, acceptance obligations, resolved requirements, exact candidate/artifact records, and effective rubric. A missing plan rubric gets a deterministic coverage/feasibility/evidence rubric; missing objective or acceptance fails before runner dispatch. | Exact fixture `ca8faa94_plan_verifier.json`, prompt regressions, and `test_dispatch_rejects_incomplete_incident_plan_verifier_before_runner_execute`. | Independent focused validation: `49 passed`; incomplete contract executes no runner and schedules no recovery/retry. |
| No joined supported-path proof | A default-collected real-object scenario now crosses public create/start, plan verification, actual prompts and callback, committed pytest gate, blocked readback, operator resolution, exact outbox restoration, resume, independent verification, and acceptance. Repository-specific journal/cleanup/supervisor commands are separately run by the nested actual-gate regression to keep the joined scenario bounded. | `test_api_environment_blockage_restores_rejected_candidate_and_continues`; adjacent genuine correction tests; nested gate regression. | Joined case `1 passed in 39.16s`; adjacent correction cases `2 passed`; focused aggregate `158 passed, 101 deselected`. |

Static validation passed: `uv run ruff check .`, `uv run pyright` (zero errors
and warnings), `uv run python scripts/check_graph_projection_boundaries.py`, and
`git diff --check`. The focused graph execution suite passed 158 tests with one
existing Pydantic serializer warning. The final default-collected suite passed
5,930 tests with five credential-dependent skips and four warnings. The
checked-in repository project command is recorded in the evidence JSON after its
exact committed submission-gate run.

The remaining qualification is deliberately narrow: no live-model execution was
performed. A future paid run may establish live planner/runner reliability, but
the offline tests here do not make that claim.
