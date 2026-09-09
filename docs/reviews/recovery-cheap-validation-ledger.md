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

Current corrected result: the harness suite passes **9 tests in 5.60s**. The
combined harness, dispatch-packet, tool-exposure, and Codex transport command
passes **54 tests, 1 deselected, 1 known schema warning in 7.19s** under fresh
independent validation. It includes
negative proof for missing planner submit/finalization, weak or duplicate
verifier grades, planner/verifier timeout draining, and bounded unexpected-error
JSON. Scoped Ruff and Pyright pass. A clean commit is required before either
invocation card is recorded or a model is called.

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
