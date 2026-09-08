# Reliable-plan controller contracts

This ledger records the focused closure pass completed before live
qualification. It is deliberately limited to the existing routine/compiler,
macro, graph, controller, and projection architecture; it does not define a
general workflow language.

## Closure conclusion

The reliable-plan path is now controller-owned for orchestration mechanics.
The planner supplies one semantic decision payload: operation key, scope,
objective, requirement IDs, declared dependencies, acceptance obligations,
checks, and verifier rubric. The controller derives graph identity and builds
the complete authorized region atomically. It owns node and edge IDs, exact
requirement bindings, snapshot selection, sealed runner/model assignments,
checks, verifier wiring, sequential authority, failed-evidence recovery,
final dynamic acceptance, independent final audit, and the final completion
gate.

Legacy macro and raw authoring remain supported, but reliable-plan patches are
normalized with controller-required failure continuations and are checked by
the same effective-topology invariants. They cannot use an incomplete patch to
avoid the semantic constructor's requirements. The legacy terminalization
sweep no longer guesses that plan or intermediate-batch verification is final
for a reliable-plan skeleton.

## Contract ledger

| ID | Contract | Implemented behavior | Proof in this closure pass | Remaining limitation |
|---|---|---|---|---|
| RP-1 | One semantic planning operation creates a complete authorized region. | `construct_reliable_plan_region` accepts only substantive decisions and derives the initial discovery/plan-verification region, nonfinal checked batch plus successor, or final checked batch plus acceptance/audit/gate. Controller normalization adds the required failed-evidence continuations to semantic, macro, and raw reliable-plan patches. | `test_reliable_plan_region_constructor.py` proves deterministic identity, exact requirement binding, nonfinal and final topology, mechanical checks, completion dependencies, final-audit replacement, and rejection of planner-authored execution identity. `test_graph_patch_acknowledgement_recovery.py` exercises the semantic operation through the real controller/store. The seven sequential product scenarios prove the shared topology and completion invariants through the API/service/controller/driver path. | The full two-horizon product fixture still authors its scripted horizons through legacy macros; semantic construction itself is product-path exercised for the initial region and directly validated for subsequent/final regions. This is regression evidence, not live qualification. |
| RP-2 | Whole-feature acceptance belongs to the exact final candidate and cannot be borrowed across correction. | Acceptance execution and final completion use the same authoritative active batch-report query. A passing receipt must cite exactly the current reports, candidate records, file-state records, and final snapshot. The independent audit must cite that receipt and every authoritative batch report. | `test_final_gate_excludes_stale_acceptance_after_distinct_corrected_candidate` creates A plus a passing receipt, supersedes it with distinct B, proves A cannot authorize B, proves failed B acceptance blocks completion, and proves passed B acceptance plus exact audit permits it. Dispatch regressions reject a stale snapshot before execution. Sequential success and exit-97 scenarios exercise the real acceptance command boundary. | The A/B regression uses the pure production command/projection boundary and dispatch regression rather than a live model run. |
| RP-3 | All final consumers use deterministic typed evidence and completion rules. | Callback validation, dispatch, final acceptance, final audit, and gate evaluation use exact bound record identities and deterministic closure order. The shared authoritative report query applies correction supersession and active topology consistently. | Focused command, dispatch, semantic execution, and replay suites pass. The older sequential-profile fixture was upgraded to exact report/candidate/file-state/snapshot provenance and now passes without weakening closure checks. | No live-model citation-quality claim is made. |
| RP-4 | Retired topology remains historical and cannot constrain active execution. | Effective active topology excludes same-patch and prior retirements. Correction may retain immutable failed evidence while atomically retiring obsolete acceptance/audit/gate nodes and installing replacements. | Final-audit semantic correction is accepted only with exact historical provenance. Every-split replay comparisons cover correction plus retirement and compare active nodes/edges, bindings, snapshot authority, readiness, planner completion, and final decisions. | Archival retention policy is outside this closure pass. |
| RP-5 | Planner completion requires complete outcome-specific continuations. | Initial verification has passed and failed branches. A nonfinal batch/correction has one passed successor and one failed recovery. A final batch/correction has failed batch, failed acceptance, and failed audit recoveries plus acceptance/audit/gate completion dependencies. Reliable-plan correction authority permits only those exact shapes. | Raw/macro/semantic validator tests and the correction product scenario prove incomplete continuations are rejected and exact corrective continuation completes. Passing reliable-plan verification no longer creates the legacy hidden-oracle shortcut. | None known in the supported reliable-plan authoring paths. |
| RP-6 | Ambiguous acknowledgement and retry are exactly once. | Accepted patches persist semantic operation key, intent fingerprint, original patch ID, and successor IDs. Reconciliation occurs only for a matching run, proposer, planner context, operation key, and fingerprint. Semantic IDs do not depend on the transport envelope ID. | Real file-backed SQLite tests interrupt immediately before commit and immediately after commit, reconstruct the controller/store, retry from the caller's stale position with a different transport envelope, and prove one accepted operation, one region, unique nodes/edges/records, one successor generation, preserved remaining-horizon authority, and discoverable committed successor IDs. Missing/wrong context remains stale; conflicting intent raises a typed conflict. | Crash-to-reconciliation and full completion are proven by adjacent real-controller and sequential product regressions rather than one combined long-running test. |
| RP-7 | Checkpoint replay is behaviorally identical to uninterrupted replay. | Projection payload persistence includes idempotency metadata, correction trigger/lineage, declared batches, file-state git data, and sealed assignment fields needed by runtime decisions. | Success, acceptance-failure, correction, and retirement histories are reconstructed at every valid checkpoint split after the atomic seed. Assertions compare full projections plus active topology, evidence bindings, snapshot identity, readiness, planner completion, invariant blockers, and final completion decisions. | Checkpoints cannot split the atomic initial seed command by construction; all valid persisted split positions are covered. |

## Alternate-path review

The review found and closed these gaps independently of the original tests:

- Plan verification was incorrectly eligible for the legacy automatic hidden
  invariant sweep. That could run implementation acceptance before effectful
  work and leave a stale failure blocking the final gate. Reliable-plan
  verifiers now rely exclusively on their controller-built finalization graph.
- Controller-added recovery planners in corrective patches were rejected by
  an older generic gap-planner rule. Sealed reliable-plan correction authority
  now permits successor and recovery planners only before exact reliable-plan
  topology validation enforces their count and wiring.
- Same-patch retirement removed old final-audit producers from active topology
  too early for correction-provenance validation. Active execution still
  excludes them, while patch-local exact record edges retain their immutable
  evidence for the replacement correction.
- Legacy finalization nodes did not always carry declared batch IDs. Controller
  normalization now stamps them from the accepted plan, and dispatch has a
  typed compatibility derivation from bound report producers.
- Acceptance execution and completion previously selected current reports by
  separate logic. They now share `authoritative_batch_verification_report_ids`.
- The nested project-gate fixture now ignores transient `orchestrator.db-*`
  sidecars while copying a repository; no database or sidecar was modified.

## Validation record

All commands ran from the authorized checkout with `uv run` for Python. Tests
used real temporary repositories, files, SQLite databases, controller/store
instances, and dependency injection. No server was started or restarted, and
no production database was modified.

| Command | Result |
|---|---|
| `uv run pytest -n 0 tests/unit/test_reliable_plan_region_constructor.py tests/unit/test_reliable_plan_tool_exposure.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_patch_validator.py tests/unit/test_graph_projection_replay_equivalence.py tests/unit/test_reliable_plan_execution_semantics.py tests/integration/test_graph_patch_acknowledgement_recovery.py tests/integration/test_reliable_plan_execution_contract.py -q` | `586 passed, 1 deselected in 4.88s` |
| `uv run pytest -n 0 tests/integration/test_graph_sequential_product_path.py -q` | `7 passed in 290.56s` |
| `uv run pytest -n 0 tests/integration/test_graph_submission_gate_nested_regressions.py::test_configured_project_gate_runs_journal_and_cleanup_regressions_nested -q` | `1 passed in 63.06s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| `make test` | `5972 passed, 5 skipped, 4 warnings in 426.13s` |

The warnings are the existing Pydantic serialization warning in the cache-root
fixture and three Python 3.12 `aiosqlite` datetime-adapter deprecations. They do
not alter the reliable-plan results.

## One bounded live qualification trial

Do not expand directly to five trials. First run exactly one existing
reliable-plan routine with the already selected runner and sealed model/profile
assignments; do not substitute models during the run.

Freeze these acceptance criteria before launch:

1. The planner uses `construct_reliable_plan_region` and supplies only scope,
   objective, requirements, dependencies, acceptance, checks, and rubric.
2. Exactly two declared effectful horizons materialize sequentially; each has
   one mechanical check, one independent verifier, and its required failure
   continuation.
3. The final acceptance command runs once against the exact final snapshot,
   the independent audit cites its receipt and both authoritative batch
   reports, and the final gate completes only after both pass.
4. There are no duplicate operation keys, patch decisions, nodes, edges, or
   records, and sealed runner/model/profile assignments are unchanged on every
   generated node.
5. Manual intervention count is zero. Any approval, operator resume, graph
   repair, model reassignment, or hand-edited evidence fails the trial.

Collect a bounded evidence bundle from the run API and durable event stream:

- correctness: final output inspection, requirement grades, authoritative
  report IDs, acceptance receipt snapshot/candidate/file-state IDs, audit
  evaluated IDs, final completion decision, and final run state;
- rejected planning calls: count and reason for every `graph_patch_rejected` or
  `command_rejected` event (target zero; any rejection must be classified);
- retries: planner/worker/verifier attempt counts, operation-key reconciliation
  events, callback idempotency outcomes, and agent-death/recovery events;
- manual intervention: approvals, pauses/resumes, operator patches, assignment
  changes, and any out-of-band filesystem repair (target zero).
- economy: elapsed wall time, model/token usage, and estimated cost for the
  single run. Use provisional expansion caps of 15 minutes and USD 1.00 per
  trial unless the operator sets stricter caps before launch.

Only if this first live run satisfies every frozen criterion should the same
unchanged protocol be considered for five consecutive trials. Do not start
those trials automatically: first prove from the recorded run that the trial
finished within the time and cost caps, then obtain explicit operator approval.
Scripted tests in this ledger are readiness evidence only and are not a live
qualification result.
