# Recovery deterministic closure

September 9, 2026. Owner: supervising agent. This pass implements the user's
request to supervise cheaper agents following the failed Stage 3 smoke.
No paid orchestrator phase, live activation, server start, historical-run resume,
or new graph experiment is part of this work. Existing historical evidence stays intact.

## Functional target

| ID | Required behavior and acceptance | Implementation / regression evidence | Product-path proof | Status / remaining gap |
|---|---|---|---|---|
| D1 | A rejected reliable-plan request retains bounded protected reproduction evidence with request/response and graph/source identity; public events remain safe. Replaying captured evidence reproduces the rejection. | Eight integration cases pass independently: automatic capture, authorized private artifact, exact replay, oversize retention and identity mismatch refusal. Request/response preservation is independent from graph/source completeness. | Fresh validator exercised `build_graph_runtime` and public `GraphController.handle_command`: automatic exact-replay evidence, safe public payload, exact private request/response, actual executing source identity. | Validated. |
| D2 | Configured proposal and execution limits stop further work; recovery and repeated calls cannot reset the allowance. Invalid planning is distinguished from transient runner failure. | Strict config, durable reconstruction, stalled Codex receive cancellation, compiler and managed outbox regressions pass. Independent acknowledgement suite: 17 passed. | Managed outbox tests pass live exhaustion and crash-window reconstruction with proposal cap 1 / execution cap 3. Terminal invalid-plan recovery, no retry event, one dispatch intent; reconstructed case sends zero model transport messages. | Validated. |
| D3 | Reliable-plan planners receive only the current semantic contract; controller-owned work and unavailable choices do not appear as model obligations. Compatibility/gap paths retain their contracts. | Independent prompt/tool suite: 29 passed. Supervisor corrected unavailable acceptance binding, first-successor scope mode and omitted-role prompt; focused regressions pass. | Production dispatch, Codex tool schemas and initial/successor MCP/controller calls agree on constructor plus submit. Full deterministic lifecycle uses both planner phases. | Validated. |
| D4 | A no-model tiny lifecycle completes through real dispatch/controller/store/worktree/submission/check/finalization paths, with exact allowed file change and quiescent cleanup. Scaffolding cannot silently violate the fixture contract. | Scaffolding uses Git-local excludes. Macro places effectful work in the authoritative successor region, fixing the pending-region final-gate blocker without relaxing the gate. Lifecycle/scaffolding/constructor regressions pass. | Independent CLI and supervisor's final saved CLI both pass: completed graph/workflow, sole committed regular file with exact bytes, clean checkout, 7 finalized executions, 3 fresh verifier instances, 2 passed checks, no remaining nodes/leases/owners/outbox. Supervisor independently proved linked-worktree scaffolding behavior. | Validated. |
| D5 | Verifier probe does not disclose candidate verdicts or expected defect; pass requires evidence the model executed required commands. No paid execution in this pass. | Independent 13-case integration suite passes. Neutral candidate names; current thread/turn, exact command/cwd/exit/output receipts required before grades and submission. Grade-only, late and wrong-turn proof rejected. | Production Codex transport with injected scripted notifications. Fresh reviewer also injected receipt-shaped agent prose: it produced zero receipts and failed the probe. Live model behavior is outside this pass. | Validated. |

## Baseline and constraints

- Repair worktree: `/Users/peter/code/task-world/worktrees/recovery-stabilization`.
- Initial source/tests are clean; pre-existing modified/untracked recovery documentation is preserved.
- Read `AGENTS.md`; use `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync`.
- Real injected dependencies, SQLite/files/Git/subprocesses; no monkeypatching or mock objects.
- Narrow extension of existing paths; no new planning framework, live DB changes, or weakening gates.
- Builders own disjoint files where possible; supervisor resolves shared edits and performs integration.
- Independent validator must review the whole target after builders finish. A test count alone does not close a row.

## Current pass

Baseline at `a849d2434`: 51 tests passed in 11.88s (2 existing omission-sentinel
schema warnings), covering real MCP recovery admission, isolated probe harness,
production planner packets and reliable-plan tool exposure. Command:

`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 -q tests/integration/test_graph_patch_acknowledgement_recovery.py tests/integration/test_recovery_model_phase_probe.py tests/unit/test_graph_planner_packet.py tests/unit/test_reliable_plan_tool_exposure.py`

Three initial bounded builder assignments: failure evidence/limits,
planner contract, and deterministic lifecycle/probe. After the planner handoff,
failure evidence was split to a fresh Sol builder so the first builder can finish
persisted limits and cancellation without adding capture/replay scope. D3 used
Luna; cross-boundary builders use Sol. Supervisor owns this ledger
and integration decisions. Final completion requires relevant regressions,
repository checks, and independent product-path validation.

## Independent validation

Fresh Sol validator reproduced the current combined D1–D4 paths:

- Public acknowledgement/recovery integration: 17 passed, including live cap
  exhaustion and crash-window reconstruction with rejection cap 1 / execution cap 3.
- Rejection capture/replay: 8 passed, including automatic recording, source
  identity, position-160 replay and oversized-prefix request retention.
- Planner prompt/tool tests: 29 passed. Supervisor corrected an additional
  first-successor scope-mode error; its two focused cases pass.
- Direct no-model lifecycle CLI: exit 0 in 20.9s; graph and workflow completed;
  exact sole committed file, regular mode 100644, seven finalized executions,
  three fresh verifiers, two passing checks, no remaining nodes/leases/owners/outbox.
- Earlier three combined-suite failures no longer reproduce after the managed
  cancellation guard and production-shaped successor fixtures were completed.

The validator's final D1–D5 verdict is PASS, with no blocking findings. D5's
13 integration cases and an additional receipt-shaped prose attack pass their
expected positive/negative outcomes. Default-role prompt coverage brings the
independent D3 suite to 30 passing cases. Additional focused D2/config/boundary
coverage is 86 passed, and D4 scaffolding/constructor coverage is 25 passed.

Final supervisor lifecycle proof is saved in
`recovery-deterministic-lifecycle-result.json`: exit 0 in 35.825 seconds under
concurrent repository-test load, with hashes for all changed source, examples,
routine and regression files. This identifies the dirty repair source in addition
to its base commit. No paid model transport was used.

## Repository gate

Ruff, format, gitleaks, full Pyright, graph projection boundaries, module import
boundaries, signal routing, UI lint and UI typecheck passed. The initial full
pytest hook stopped at 3,221 passes on two sandbox restrictions: macOS `sysctl`
process-group inspection and downloading `hatchling` for a disposable dependency
fixture. A focused retry confirmed the exact process permission error. The
unmodified pytest hook reran with those permissions; no test was skipped or
suppressed to work around either restriction. It reached 6,064 passes and five
configured skips before failing
`test_api_cancel_waits_for_runner_recovery_before_terminal_state`: the scripted
worker did not reach its start latch within ten seconds. A fresh Sol builder
measured normal startup at 9.228/9.335 seconds after `drain_start`, including
four roughly two-second scheduler waits. Both tests passed unchanged in
isolation; ordinary parallel load could exceed the nested ten-second deadline.
The correction waits for the actual worker-ready event under the existing
60/90-second test deadlines. All cancellation/recovery/redispatch assertions
remain intact. The adjacent pair passes (2 tests in 44.75 seconds), full Pyright
and Ruff pass, and independent review approves the synchronization correction.
No production source changed. The final complete repository gate passed:
**6,067 passed, 5 skipped, 15 warnings in 478.51 seconds**. Every applicable
pre-commit hook passed, including full Pyright and UI checks; enum-drift had no
matching changed files. The durable summary and verified source hashes are in
`recovery-deterministic-validation-result.json`; the complete local log is
`/tmp/recovery-final-precommit.log`. All D1–D5 rows are validated within the
no-model scope. Changes remain uncommitted and have not been activated.

## Operational limits and next experiment

- Proposal/execution caps are explicit optional routine inputs, each an integer
  from 1 to 100. Omission preserves existing compatibility. The recovery probes
  explicitly use two rejected proposals and one planner execution. Transport
  schema rejection before the controller callback is outside the durable
  proposal count; the execution and wall limits still bound that phase.
- Rejection artifacts are bounded at 512 KiB, request/response at 96 KiB, graph
  prefix at 384 KiB and source fingerprint input at 2 MiB. Oversize/incomplete
  evidence is labeled non-replayable; a bounded request is retained even when
  its graph prefix is too large. Replay requires a fresh isolated store and the
  exact executing source identity.
- These results prove the production orchestration path with scripted agents
  and the probe's evidence contract. They do not prove that a real model can
  plan or verify reliably. No activation, live run or paid probe occurred.
- The next paid experiment should be one isolated phase with explicit limits
  and captured evidence. A rejection should be replayed locally before another
  paid attempt. A broad graph retry is not supported by this evidence yet.

## Successor preparation resumed September 11, 2026

The supervisor inspected the requested worktree before delegating implementation.
HEAD remains `a849d24344c6832a4e2e6ac68dd37d5a6f84042e`. All 41 hashes in
`recovery-deterministic-validation-result.json` match, as do the lifecycle-result
artifact hash and its source hashes. The checkout retains the prior uncommitted
implementation and recovery documents. The initial porcelain status, comparison,
and hashes of 85 historical artifacts are saved separately in
`recovery-successor-baseline-2026-09-11.json`; prior evidence is preserved.

Inspection confirms `model_phase_probe.py` planner mode seeds and dispatches the
initial `planner-s-01`. Its passing evidence does not cover successor planning.
The resumed target is a separately identified successor probe reached through
scripted initial planning, discovery, and plan verification on disposable stores
and Git fixtures. One Sol builder owns the harness and tests; a fresh Sol reviewer
owns independent review. The supervisor owns integration and this ledger.

| ID | Concrete closure requirement | Current status |
|---|---|---|
| S1 | A production-created successor has bound accepted discovery/plan-verification evidence and successor authority; initial planning cannot satisfy the phase predicate. | PASS: production-created horizon-1 successor, exact setup order and source bindings; independently reviewed. |
| S2 | Exactly one isolated successor execution can construct the effectful final horizon and complete plain submission; no downstream agent is dispatched. | PASS: one observed execution, exact accepted final horizon and finalized plain submission; no downstream dispatch. |
| S3 | Explicit two-rejection/one-execution caps and bounded timeout drain ownership without automatic paid retry; failures cannot pass. | PASS: cap, missing-submit and timeout negatives; complete repository gate passed after fixture repair. |
| S4 | Exact bounded private rejection evidence survives workspace disposal, binds executing source, and replays through the production controller in an empty isolated store. | PASS: protected CAS survives disposal; controller and pre-controller replay, source/prompt/authority and receipt integrity checked. |
| S5 | A concrete experiment card binds identities, commands, limits, pass/fail predicates and the single paid authorization boundary. | Independent review PASS; concrete experiment card prepared. Final repository gate PASS; paid execution unauthorized. |

No paid orchestration probe, live database/history mutation, server start,
activation or historical-run resume is authorized or performed in this pass.
The prior full gate is baseline evidence only. New results will distinguish
deterministic infrastructure proof from real-model behavior.

The first independent review found that controller capture alone misses a
normalization error before the graph callback. A Luna builder added an optional
Codex dynamic-tool receipt observer with immutable canonical request/response
JSON, per-side 96 KiB content limits and explicit incomplete/hash/size metadata.
The supervisor caught and corrected capture-after-routing mutation risk and
observer exception-chain disclosure before handoff. Three focused cases pass,
including constructor normalization, callback mutation, oversized evidence and
fail-closed observer storage failure; the existing Codex coverage passes 87
tests including the receipt cases, with one configured deselection. Scoped Ruff and Pyright pass. Fresh Sol
code review finds no blocking receipt issue. Schemas and default runner behavior
remain unchanged. These receipts record a prepared response before transport
send, not proof of delivery. The full successor harness remains under validation.

Receipt validation commands (no repeat requested):

- Final focused file: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync
  pytest -n 0 tests/integration/test_codex_dynamic_tool_receipts.py -q`:
  **3 passed in 0.13s** after final fixture/import corrections.
- Combined receipt/Codex regression run: same prefix with
  `pytest -n 0 tests/integration/test_codex_dynamic_tool_receipts.py
  tests/unit/test_codex_server_agent.py tests/unit/test_codex_server_transport.py
  -q`: **87 passed, 1 deselected in 0.80s** after production implementation,
  before the last test-only fixture edits and public export adjustment.
- Final scoped Ruff passes for the runner export, agent and new receipt test;
  scoped Pyright for the agent/test reports **0 errors, 0 warnings**.

The first successor harness execution reached a real production-created
successor, completed its final-horizon contract and finalized one target attempt.
It retained and locally replayed one controller rejection, with unchanged fixture
and zero process owners/downstream dispatches. The harness correctly reported
failure while two evidence predicates were wrong: maintenance outbox rows had
not been drained, and plan binding was queried from payload keys instead of
production input records. The builder is correcting those issues and moving the
scripted target through injected Codex transport. This intermediate observation
does not close S1–S5 or authorize spending.

Main harness handoff: the current seven successor cases and the lifecycle helper
regression pass **8 tests in 62.92s** with the required UV prefix and
`pytest -n 0 -q tests/integration/test_recovery_successor_planner_probe.py
tests/integration/test_recovery_deterministic_lifecycle.py`. Scoped Ruff passes;
scoped Pyright reports **0 errors, 0 warnings**. The helper's change exposes
existing fixture/factory functions publicly; it does not change lifecycle
behavior. A prior cap case reached its 90-second test deadline because receipt
publication attempted to reacquire the controller recorder's artifact lock.
The builder removed nested publication and persists atomic CAS objects directly
before adding their references. The cap case subsequently passed in 9.43s and
is covered by the eight-test result above. No deadline or recovery assertion was
weakened. A new lint suppression was rejected at supervision; standard module
invocation replaces import-path bootstrapping. Final independent CLI evidence
and the repository gate are still pending.

The next independent audit reached the correct successor and retained three
complete receipts, but found two evidence-boundary failures before the full gate:
offline replay incorrectly treated a failed source probe as a replay failure,
and unexpected harness errors printed exception text that could contain private
request values. Both were returned to their builders. The same review required
observed execution counts, explicit no-recovery and setup-sequence predicates,
and full protected-context/result binding. The first independent result is
retained as initial evidence; final proof must bind the corrected source.

Those fixes now include failed-source replay status separated from source probe
success, empty-receipt rejection, protected prompt/authority/source/fixture
binding, static safe CLI errors, and observed runner-creation counts separately
from recorded execution attempts. The stricter setup check initially assumed a
nonexistent initial-planner semantic-stage field; it now recognizes only the
exact initial node ID and planner kind, while requiring the later discovery and
plan-verification stages. Final scoped Pyright and Ruff pass. The combined
successor/replay run produced **11 passes and one failure in 48.68s**: the cap
test incorrectly expected zero recorded attempts. Readback showed one, and the
corrected assertion passes in **7.80s**. It still requires two rejected proposals,
no acceptance, exactly one observed execution, no downstream dispatch and drained
ownership. No assertion was removed. The full gate will validate the final files.

Final independent CLI and offline replay pass against result SHA-256
`89ee7f6f15741a6d85de82aa1507abd9ce7ab9c6ffbdf40ff101a5c872472a78`.
All 18 strict predicates pass; exactly one rejection replays and correlates with
three complete receipts. A fresh Sol review reports no blocking S1–S5 findings.
The first complete gate attempt then passed every static/UI hook but stopped at
**3,559 tests passed, one skipped, one failure in 60.55s**. The zombie-leader
fixture observed its PID file between creation and content publication, read an
empty string, and then timed out waiting for a leader it had not yet killed.
This concrete race is being fixed with atomic fixture publication and exact
owned-child cleanup; the refusal/identity assertions and deadlines remain.
The full failure log and command summary are preserved as
`recovery-successor-gate-attempt-1.log` and `.json`. No gate was bypassed.

The PID fixture repair passed Ruff, formatting, Pyright and all three focused
cases in **0.71s** with required macOS process-inspection permission. Its first
sandboxed run failed on `sysctl` permission; the same cases passed after the
permission was granted. Independent Sol review approves atomic publication and
owned-leader cleanup with no assertion/deadline changes. The complete unmodified
gate is running again because of that concrete failure and repair.

The second gate's full suite passed **6,082 tests, five skips, 15 warnings in
526.67s**, and every applicable static/UI check passed. The pre-commit wrapper
still returned failure because the supervisor edited the tracked cheap-validation
ledger while pytest was running. Source and regression hashes did not change.
This avoidable supervision error is preserved in
`recovery-successor-gate-attempt-2.log` and `.json`; it is not reported as a clean
gate. All edits are paused for an unchanged complete gate rerun.

Final complete pre-commit gate: **PASS, exit 0**. The suite passed **6,082 tests,
five skipped, 15 warnings in 538.00s**. Ruff, format, secrets scan, full Pyright,
graph projection and module boundaries, signal routing, UI lint and UI typecheck
all passed; enum-drift had no matching files. Source hashes stayed unchanged
through the gate. Final logs and command/source snapshots are preserved in
`recovery-successor-gate-final.log` and `.json`; the 49-file manifest, independent
review, replay and all gate attempts are in `recovery-successor-validation-result.json`.
All S1–S5 requirements are validated within deterministic infrastructure scope.
All 85 historical artifact hashes and both original deterministic result files
remain unchanged. No paid orchestration probe, live mutation, server start,
activation, historical resume or commit occurred. The reviewable next action is
exactly the one-execution Luna-medium experiment in `recovery-successor-experiment.md`,
subject to explicit paid authorization. Model reliability remains unproven.

## Decision/runtime architecture preparation — September 11, 2026

The user redirected the next step to architectural preparation: isolate model
judgment in every partially mechanical step and prepare implementation prompts
for Sol. The proposed package is
[31-decision-runtime](../intent/31-decision-runtime/README.md). It defines one
typed terminal answer, runtime-derived graph consequences, one owner for each
answer schema, explicit legacy compatibility and six ordered implementation
assignments with independent review. Runtime must close a successfully answered
phase without another model completion action. Plan amendments contain only
proposed changes; code preserves existing obligations.

The old paid successor card above remains unauthorized and is now held pending
this design work. It tests the old interaction and cannot qualify decision-v1.
The new contracts are proposed, not implemented. This preparation changed only
documentation; all 49 saved baseline hashes and 85 historical artifact hashes
matched. No test suite was repeated, and no paid orchestration probe, live
mutation, server start, activation, historical resume or commit occurred.
The package's preparation result records the independent design review and
final document hashes separately from the prior implementation evidence.
