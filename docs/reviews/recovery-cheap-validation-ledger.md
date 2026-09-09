# Recovery cheap-validation ledger

Updated September 9, 2026. Scope is Stage 1 of
`recovery-restart-plan-2026-09-09.md`; no model executions are admitted by this
ledger. Committed source under test is repair branch
`codex/recovery-stabilization` at
`a2a6e02805e72a64c860c93d55fa613d76508c16`; the current Stage 1 closure adds
only the test and ledger changes described below.

| ID | Required behavior | Current evidence | Product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|---|
| C1 check admission | Blank, missing, malformed, explicit and bound commands cross authoritative admission and dispatch; invalid work stops before runner creation. | `command_bindings.py`, task API validation, check dispatch, and patch validation use the shared executable-command contract from commit `751d3a7`. | The parameterized integration matrix calls the registered `construct_reliable_plan_region` MCP tool, routes through `GraphDispatchExecutor._submit_graph_patch_callback`, `GraphController`, SQLite and `GraphEventStore`. Missing command, blank `cmd`, blank first `argv` token, valid explicit `cmd`, configured canonical `dynamic_feature_hidden_oracle`, and absent optional oracle with an available acceptance command are all exercised. Invalid cases expose typed safe code/path diagnostics, persist no matching acceptance, preserve the exact lease-event ID set, and never call the injected fail-if-called agent factory. Valid cases persist exactly one matching acceptance. | `test_check_admission_matrix_crosses_mcp_controller_and_store` passes all six cases in the focused integration file. | validated | None in the incident-backed Stage 1 scope. |
| C2 verifier contract | Fresh verification receives requirements, exact commands and bounded current-attempt evidence; stale receipts cannot become current proof. | Shared verifier context resolution and reliable-plan verifier contract validation from `751d3a7`. | Prompt/executor tests construct real run/task/Pydantic records through the production prompt and dispatch paths. | Included in the 464-test focused baseline below. | validated | None in the incident-backed Stage 1 scope. |
| C3 responsive submission | Submit, duplicate submit, reset and cancellation use exclusive asynchronous worktree ownership and drain cancelled operations. | `worktree_mutations.py` and workflow/executor integration from `751d3a7`; retained live auto-commit/pytest observation reported 12–37 ms API reads. | Real Git worktrees, subprocess hooks and ASGI HTTP requests are used by the focused tests. | Included in the 464-test focused baseline below. | validated | None in the incident-backed Stage 1 scope. |
| C4 macro/tool parity | Valid and malformed initial/successor requests cross exposed MCP, dispatcher and controller paths with safe typed paths/codes; omitted raw `ops` differs from explicit null. | The shared reliable-plan `checks` item schema is derived from `ReliablePlanCheckDecision`, normalizes its command alternatives to non-null public schemas, and enforces exactly one binding/definition. The flat MCP patch contract again requires typed string/integer identity fields and advertises typed optional arrays without a sentinel default; omitted `ops` is absent from routed arguments while explicit null reaches authoritative rejection. Optional `dependencies` and `requested_authority` retain omission semantics. Nested patch-envelope transport is not advertised or claimed. | Public `list_tools()` and real `call_tool()` cover schema-valid binding and explicit-definition checks. Registered MCP calls cross dispatcher/controller/SQLite for the initial cases already recorded and for a persisted successor-authorized planner with a matching skeleton, sealed model-assignment carrier, horizon/generation 1, and bound accepted-plan verification. The successor call persists its effectful worker/check/verifier region and a controller-stamped horizon/generation-2 successor while adding no lease. | The focused recovery integration file passes 10 tests, including the six-case C1 matrix and the new successor public-path fixture. Prior C4/C5 focused, Ruff, Pyright and diff-check evidence remains applicable to committed source. | validated | No incident-backed Stage 1 gap. The public successor contract correctly assigns its first effectful batch to the proposing horizon-1 planner, then advances the next successor to horizon/generation 2; unrelated adapter-owned fields and nested raw patch-envelope transport remain unclaimed. |
| C5 diagnostic completeness | Missing `node_states`, malformed graph shape, mismatched identity, absent failure events, empty valid state and bounded data never produce a false complete report. | The bounded diagnostic from `95b7a33d0`/`ad46b7f0` is ported with strict Pydantic run/graph/node boundary models. `node_states` is required; malformed state values, optional graph `run_id` mismatch, and top-level or `collection_meta.node_states` truncation are partial. Empty complete mappings remain valid. | Real loopback HTTP plus the actual CLI subprocess proves missing `{}` exits 1 while a present empty mapping exits 0; the same path covers malformed/identity/truncation/node-evidence cases and the 2 MB/10-node caps. | 8 pure tests pass; 15 real HTTP/subprocess tests pass. | validated | None in the bounded Stage 1 diagnostic scope. |
| C6 gate accounting | Attribute unavoidable baseline, submission, explicit checks, verifier checks and final audit to command/source/tree/candidate identity. | Retained evidence accounts for every known phase, source, tree, command and candidate identity. The comparable project-test total and latest exact baseline command identity are retained; discovery baseline/submission correctly record no configured commands. Historical explicit-check, verifier-check and final-audit timings are explicitly unknown rather than inferred. | Public API-derived `runtime-final.json` retains the latest probe timing and command identity without another run. | Evidence integrity hashes remain under `recovery-2026-09-09/`; no timing rerun or cache implementation was performed. Commit `a2a6e0280` passed every configured commit hook after the prior C4/C5 repair. | validated-limited | Stage 2 must prospectively record command/source/tree/candidate identity and duration for each explicit check, verifier check or final audit it actually executes. Do not rerun historical phases only to fill missing timing, infer caching, or treat repeated command text as reusable proof. |

## Current pass

C1 and C4 are closed by the real MCP/dispatcher/controller/SQLite admission
matrix and successor-construction fixture. C5 remains closed by the bounded
local fixture. Unrelated MCP/Codex tool schemas and nested raw patch transport
are not claimed equal. C6 is closed only to the limit of retained evidence:
missing historical timings remain unknown, with prospective identity and timing
capture carried into Stage 2. The Stage 1 no-model evidence gate is satisfied;
this ledger does not itself authorize more than the bounded Stage 2 allowance.

## Stage 2 isolated harness

The deterministic harness is implemented at
`examples/recovery/model_phase_probe.py`; no paid invocation has occurred yet.
One CLI invocation performs exactly one phase with Luna medium and no automatic
retry. Planner mode uses a disposable real Git repository, SQLite event store,
`OutboxDispatcher`, `GraphDispatchExecutor`, `RunnerOwnedProcessRegistry`, and
the non-injected Codex Server runner; it stops scheduling after the single
planner dispatch. Verifier mode uses a fresh direct Codex Server context over a
committed good/defective fixture pair whose independent oracle results are
recorded before the model starts. Both modes emit source, fixture, timing,
callback, usage, timeout, and cleanup evidence. The 180-second limit is
operator-enforced because this runner has no native token/action cap; expiry is
reported as incomplete and is not retried.

Deterministic validation command:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 -q tests/integration/test_recovery_model_phase_probe.py
```

Current corrected result: the harness suite passes **10 tests in 6.70s**. The
combined harness, dispatch-packet, tool-exposure, and Codex transport command
passes **55 tests, 1 deselected, 1 known schema warning in 8.54s** under fresh
independent validation. It includes
negative proof for missing planner submit/finalization, weak or duplicate
verifier grades, planner/verifier timeout draining, and bounded unexpected-error
JSON. Scoped Ruff and Pyright pass. Commit `89bcb4be0` passed every configured
hook, including the full test suite and UI checks.

### Stage 2 invocation 1 — planner/tool-use (executed, failed)

- Hypothesis: a fresh Luna-medium planner can consume the production planner
  packet, call the actual Codex dynamic tool `construct_reliable_plan_region`
  exactly once with a valid explicit `true` check, receive authoritative
  acceptance, then call plain `submit` and stop without editing the fixture.
- Deterministic limit: Stage 1 and the harness tests prove schema exposure,
  routing, acceptance, finalization, and cleanup, but cannot establish that the
  real model selects and authors the supported tool contract.
- Source: commit `89bcb4be0d8883dcf6de05d65ba2075d0f29f248`, tree
  `d4282ee9a9f2dafc4f4024582a026777601d9066`; harness SHA-256
  `3863dbaba7b4a50668b23255d491ba7c0dd590472d3f162c9d5d3c8e6b1f05a2`;
  routine SHA-256
  `53a3d9a559833b9791a6a34f5fe8d3e6738994b28e3e626b228caf8228f6af48`.
- Invocation: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync
  python examples/recovery/model_phase_probe.py planner`; role `planner`, model
  `gpt-5.6-luna`, reasoning `medium`, one paid execution, no retry.
- Expected evidence: one successful runner result; one accepted macro patch;
  exact submit/witness/finalize/callback/lease-release facts; one planner lease
  and dispatch; zero downstream leases/dispatches; unchanged committed fixture;
  source/fixture identities plus setup/model/total durations and usage.
- Budget: 180 seconds of operator-enforced model wall time; no native
  token/action cap is available. Deterministic setup is timed separately.
- Stop: accepted macro followed by one plain submit and turn completion, or
  exact-owner quiescence at 180 seconds. Timeout is incomplete and still counts
  as invocation 1. No unchanged retry.
- Next decision: pass admits the separately prepared verifier invocation; a
  typed contract rejection may use one reserved correction/retest only after
  its smallest cause is recorded. Any other failure stops planner spending.
- Environment note: the local REST server became unreachable immediately before
  this card. The probe does not use the REST lifecycle, and no server was
  started; this fact is retained rather than inferred as live-run state.

Result recorded immediately after invocation 1: **failed**, not timed out. Luna
called the real macro and produced accepted patch
`dynamic-feature-read-only-discovery-region-v2` at graph position 24, then the
plain submit callback rejected with `submission_format_rejected: generic
artifact lock parent is not a safe directory`. The runner returned success, but
no submit/witness/finalization/callback/lease-release facts were recorded and a
`runner_recovery_requested` fact was present, so the strict harness correctly
did not pass the probe. The single planner lease/dispatch had no downstream
lease/dispatch, the fixture commit/tree remained unchanged, and owned process
count returned to zero. Model wall time was 27,686 ms; usage was 110,325 input,
1,491 output, 83,968 cache-read input and 429 reasoning-output tokens across 13
actions. Durable result:
`recovery-2026-09-09/stage2-planner-invocation-1.json`, an operator-curated
bounded summary transcribed from the CLI result rather than raw stdout; the
unbounded graph event-ID list is intentionally omitted. This counts as paid
invocation 1. It is positive evidence for Luna's supported macro selection and
authoring, but not for completed planner phase behavior. No unchanged retry is
allowed; the reserved correction/retest requires a deterministic diagnosis and
validated harness repair first.

Deterministic diagnosis confirmed a harness-only cause: on macOS,
`tempfile.gettempdir()` supplied the symlinked `/var/folders/...` spelling, so
the planner artifact root reached `ArtifactRootLock` through a path component
that its no-follow traversal correctly rejects. The harness now resolves the
system temp parent with `Path(tempfile.gettempdir()).resolve(strict=True)`
*before* creating its disposable workspace, so the artifact root is passed
under the canonical `/private/var/...` spelling. Artifact coordination itself
is unchanged. A real regression creates a workspace through the helper, proves
that it is a direct child of the canonical temp parent, and completes a
`FilesystemArtifactStore.publication()` plus put/read round trip. This is a
deterministic harness repair only; invocation 2 is neither recorded nor
authorized by this entry.

Focused post-repair validation passes: the 10-test harness file completes in
6.70s; the real artifact-store and artifact-coordination unit files pass 20
tests in 0.48s; the combined phase-boundary command passes 55 tests with one
deselection and one known schema warning in 8.54s; scoped Ruff passes; scoped
Pyright reports 0 errors and 0 warnings; and `git diff --check` passes. A fresh
validator also reproduced the exact pre-fix artifact-store exception and found
the reserved correction/retest justified after this clean repair boundary.

### Stage 2 invocation 2 — planner correction/retest (executed, passed)

- Hypothesis: with only the probe workspace spelling corrected, a fresh
  Luna-medium planner will again call `construct_reliable_plan_region` with an
  accepted explicit check and will now complete the subsequent plain-submit
  callback/finalization sequence without changing the committed fixture.
- Why another model execution is necessary: invocation 1 already answered the
  model-selection and macro-authoring question positively, but its deterministic
  harness failure prevented observation of completed phase behavior. Real
  artifact-store regression tests prove the corrected publication boundary;
  they cannot prove how the fresh model turn behaves after accepted planning.
- Correction basis: the exact pre-fix exception was independently reproduced
  through public `FilesystemArtifactStore.publication()`. The repair only
  canonicalizes the disposable temp parent and leaves `ArtifactRootLock` and its
  no-follow protection unchanged. Commit `9285529a2` passed every configured
  hook after focused and independent validation.
- Source: commit `9285529a2cd70827eaacc9783566ac94cd701da3`, tree
  `695c78d2cd4147adbceaf95764ac77cbe4fd1dad`; harness SHA-256
  `1bea679ad83943887c0bdda2164d1fab06a87f26174ee5326e362216297ffde2`;
  routine SHA-256
  `53a3d9a559833b9791a6a34f5fe8d3e6738994b28e3e626b228caf8228f6af48`.
- Invocation: the same planner CLI as invocation 1; role `planner`, model
  `gpt-5.6-luna`, reasoning `medium`, one paid execution, no retry. This is paid
  Stage 2 invocation 2 and consumes one of the two reserved correction/retests.
- Expected evidence: one successful result; one accepted macro patch; exactly
  one each of submit staged, completion witnessed, execution finalized,
  callback accepted, and lease released; no runner failure/recovery event; one
  planner lease/dispatch; zero downstream work; unchanged fixture; zero owned
  processes; bound source/fixture identities, durations, and usage.
- Budget and stop: 180 seconds operator-enforced model wall time, with setup
  measured separately and no native token/action limit. Stop at the completed
  accepted callback or exact-owner quiescence on timeout. Do not retry this
  planner question again if it fails.
- Next decision: a strict pass admits the prepared verifier probe as paid
  invocation 3. Any failure stops planner spending and requires an evidence
  review before a different Stage 2 question is considered.
- Environment note: this isolated probe does not use the local REST lifecycle;
  no server start or historical-run resume is authorized or required.

Result recorded immediately after invocation 2: **passed**, not timed out.
Luna called the real `construct_reliable_plan_region` macro and produced accepted
patch `dynamic-feature-discovery-region-corrected` at graph position 30. The
strict harness then observed exactly one each of `runner_submission_staged`,
`runner_completion_witnessed`, `runner_execution_finalized`,
`callback_accepted`, and `lease_released`, with no runner failure/recovery event.
There was one planner lease/dispatch, zero downstream leases/dispatches, one
successful execution result, an unchanged committed fixture, and zero owned
processes after cleanup. Model wall time was 61,000 ms; usage was 184,416 input,
3,592 output, 155,904 cache-read input, and 1,037 reasoning-output tokens across
25 actions. The exact emitted JSON, including its bounded graph event-ID list,
is retained as
`recovery-2026-09-09/stage2-planner-invocation-2.json`. This counts as paid
invocation 2 and answers the isolated completed-planner-phase question. Fresh
evidence validation parsed the record as `ProbeEvidence`, independently matched
the source tree plus harness/routine hashes, and confirmed every serialized pass
predicate and the 2-of-4 paid-execution accounting. `source_dirty: true` is
limited to documentation/evidence outside the committed harness and routine;
the exact dirty-file list is not serialized. Verifier invocation 3 is admitted,
one reserve remains, and no further planner retry is allowed.

### Stage 2 invocation 3 — verifier behavior (executed, passed)

- Hypothesis: in one fresh Luna-medium verifier context, the model will run the
  two exact independent oracle commands, grade the committed good control
  `R-GOOD` exactly once as A, grade the deliberately defective
  `R-MISSING-NODE-STATES` exactly once as D or F with a reason naming
  `node_states`, call submit exactly once, and leave the fixture unchanged.
- Deterministic limit: the harness and independent setup commands prove the two
  fixtures separate: inside the oracle, the good candidate rejects missing
  `node_states` and the defective candidate falsely exits zero; the outer oracle
  therefore exits 0 for the good control and 1 for the defective fixture. These
  deterministic results cannot establish that a real fresh verifier notices the
  defect and authors the exact bounded grade contract.
- Source: commit `0e6e5e88c829da679cf09b72d1031f44eb09577b`, tree
  `9b14064ed07d77c1198b1d2c30d7da7b4e7517cc`; harness SHA-256
  `1bea679ad83943887c0bdda2164d1fab06a87f26174ee5326e362216297ffde2`;
  routine SHA-256
  `53a3d9a559833b9791a6a34f5fe8d3e6738994b28e3e626b228caf8228f6af48`.
- Invocation: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync
  python examples/recovery/model_phase_probe.py verifier`; role `verifier`,
  model `gpt-5.6-luna`, reasoning `medium`, one paid execution, no retry. This
  is paid Stage 2 invocation 3; one reserve remains unspent.
- Expected evidence: both independent command identities, return codes,
  durations, and output hashes; one successful runner result; the exact two
  grades and defect reason; one submit; unchanged committed fixture; drained
  execution task; source/fixture identities, setup/model/total durations, and
  usage.
- Budget and stop: 180 seconds operator-enforced model wall time, setup measured
  separately, and no native token/action limit. Stop after the one accepted
  submit or after cancellation/draining at timeout. An expiry is incomplete.
- Next decision: a strict pass completes the Stage 2 initial planner/verifier
  evidence gate and admits Stage 3 planning, not an automatic live run. A
  failure gets an evidence review; the final reserve may be used only for a
  specific demonstrated correctable contract or reasoning gap, never an
  unchanged retry.
- Environment note: the verifier probe is a direct isolated Codex Server agent
  phase and does not use the local REST lifecycle. No server start, live run, or
  historical-run resume is part of this invocation.

Result recorded immediately after invocation 3: **passed**, not timed out.
Luna graded `R-GOOD` exactly once as A, graded
`R-MISSING-NODE-STATES` exactly once as F with a reason explicitly identifying
the missing `node_states` false-complete defect, and submitted exactly once. The
independent oracle returned 0 for the good control and 1 for the defective
fixture, matching the harness setup contract; both command identities, output
hashes, and 50 ms durations are retained. The runner result succeeded, no
cancellation was requested, the task drained, and the committed fixture was
unchanged. Model and total wall times were 21,201 ms and 21,790 ms. Usage was
74,462 input, 870 output, 42,240 cache-read input, and 129 reasoning-output
tokens across 13 actions. The exact emitted JSON is retained as
`recovery-2026-09-09/stage2-verifier-invocation-3.json`. This counts as paid
invocation 3; the initial Stage 2 planner/verifier questions are answered, one
reserve remains unspent, and no additional model execution is automatically
authorized. Fresh evidence validation parsed the JSON as `ProbeEvidence`,
matched the source/harness/routine/fixture/Git-tree identities, replayed the
oracle exits and command/output hashes exactly, and confirmed every strict pass
predicate. The bounded record proves Luna's exact grading and submission
behavior; it does not retain a model shell-tool transcript independently proving
that Luna itself ran both commands. Stage 2 is complete. Stage 3 is admitted
only after its separate experiment/budget card and live readiness check.

## Retained gate accounting

All values below are retained observations, not projections. The repeated
project-test command's exact SHA-256 is
`7714bebfc86365742356469e70d62c2a2560b04342975e3c8482df2697568f1b`.

| Evidence arm | Comparable project-test phases | Retained duration | Identity/accounting limit |
|---|---:|---:|---|
| Original graph run `d20ff4dd-9cd1-4f29-9df1-d344a0582907` | 4 | 1,748,291 ms (`456,500 + 446,308 + 437,331 + 408,152`) | Same-command historical phases; no missing phase is inferred. |
| Earlier completed graph evidence | 4 | 837,906 ms total | Same four project-test phases; retained evidence only. |
| Latest probe `4f89c845-3f82-4b79-856d-41b52bf0ff53` | baseline only | 488,081 ms | `runtime-final.json` binds the command SHA, source/tree and baseline result. |

The comparable records do **not** provide explicit-check, verifier-check, or
final-audit timing for the latest probe. No value is assigned to those missing
phases, and no cache/reuse conclusion is drawn from timing alone.

## Verification log

- Baseline at `98ca9f6`: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run
  --no-sync pytest -n 0 -q` over the ten focused command, prompt, worktree,
  MCP/controller and API files named by C1–C4: **464 passed, 15 deselected in
  10.94s**. This establishes a clean deterministic baseline before the C5 edit.
- Current C5/C4 pass: the pure diagnostic and graph-tool schema tests pass
  **29 tests**; the real loopback HTTP/CLI subprocess suite passes **15 tests**;
  the real MCP→dispatcher/controller patch recovery suite passes **3 tests**.
- C4 correction validation: the diagnostic unit test plus the requested MCP,
  Codex exposure, command binding, patch validation, reliable-plan constructor,
  controller recovery, and graph dispatch files pass **364 tests** with `-n 0`;
  the loopback diagnostic CLI file passes **15 tests** separately. Scoped Ruff
  passes, and scoped Pyright reports **0 errors, 0 warnings**. The loopback file
  requires permission to bind a temporary local HTTP socket in the sandbox.
- C4 correction pass 3: the focused C4+C5 command passes **47 tests** in
  **12.49s** with loopback permission. The 10 emitted Pydantic warnings document
  the intentionally unserializable omission sentinel being excluded from the
  advertised schema; assertions confirm no default or sentinel value is exposed.
  Scoped Ruff passes, scoped Pyright reports **0 errors, 0 warnings**, and
  `git diff --check` passes. The generated `examples/recovery/__pycache__`
  artifact was removed after validation.
- Commit `a2a6e0280` (the C4/C5 diagnostic and tool-contract repair) passed every
  configured commit hook, including the default test suite, type/lint,
  architecture boundaries and UI checks.
- Current Stage 1 closure: the real MCP/controller recovery integration file
  passes **10 tests**, including all six C1 admission cases and the C4 persisted
  successor path. The reproducible combined command below passes **313 tests**
  with **11 known Pydantic schema warnings** in **6.62s**:

  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 -q tests/integration/test_graph_patch_acknowledgement_recovery.py tests/unit/test_command_bindings.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_reliable_plan_region_constructor.py tests/unit/test_reliable_plan_tool_exposure.py tests/unit/test_graph_mcp_tools.py tests/unit/test_graph_planner_packet.py tests/unit/test_reliable_plan_execution_semantics.py`

  Scoped Ruff passes, scoped Pyright reports **0 errors, 0 warnings**, and
  `git diff --check` passes.
