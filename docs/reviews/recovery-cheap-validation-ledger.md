# Recovery cheap-validation ledger

Updated September 9, 2026. Scope is Stage 1 of
`recovery-restart-plan-2026-09-09.md`; no model executions are admitted by this
ledger. Source under test is repair branch `codex/recovery-stabilization` at
`98ca9f6cb74cebd527540dc9a9207c661eaa89cc` unless a later row says otherwise.

| ID | Required behavior | Current evidence | Product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|---|
| C1 check admission | Blank, missing, malformed, explicit and bound commands cross authoritative admission and dispatch; invalid work stops before runner creation. | `command_bindings.py`, task API validation, check dispatch, and patch validation use the shared executable-command contract from commit `751d3a7`. | Existing real Pydantic graph/task requests and a real check subprocess traverse API/controller/dispatcher tests, but the four-shape authoritative controller/dispatch matrix has not been assembled in one proof. | Included in the 464-test focused baseline below. | partial | Add the compact blank/missing/wrong-shaped/valid explicit-and-bound matrix and assert each invalid contract creates neither a runner nor a worker lease; retain the existing proof that an absent optional oracle is never replaced by final acceptance. |
| C2 verifier contract | Fresh verification receives requirements, exact commands and bounded current-attempt evidence; stale receipts cannot become current proof. | Shared verifier context resolution and reliable-plan verifier contract validation from `751d3a7`. | Prompt/executor tests construct real run/task/Pydantic records through the production prompt and dispatch paths. | Included in the 464-test focused baseline below. | validated | None in the incident-backed Stage 1 scope. |
| C3 responsive submission | Submit, duplicate submit, reset and cancellation use exclusive asynchronous worktree ownership and drain cancelled operations. | `worktree_mutations.py` and workflow/executor integration from `751d3a7`; retained live auto-commit/pytest observation reported 12–37 ms API reads. | Real Git worktrees, subprocess hooks and ASGI HTTP requests are used by the focused tests. | Included in the 464-test focused baseline below. | validated | None in the incident-backed Stage 1 scope. |
| C4 macro/tool parity | Valid and malformed initial/successor requests cross exposed MCP, dispatcher and controller paths with safe typed paths/codes; omitted raw `ops` differs from explicit null. | The shared reliable-plan `checks` item schema is derived from `ReliablePlanCheckDecision`, normalizes its command alternatives to non-null public schemas, and enforces exactly one binding/definition. The flat MCP patch contract again requires typed string/integer identity fields and advertises typed optional arrays without a sentinel default; omitted `ops` is absent from routed arguments while explicit null reaches authoritative rejection. Optional `dependencies` and `requested_authority` retain omission semantics. Nested patch-envelope transport is not advertised or claimed. | Public `list_tools()` and real `call_tool()` cover schema-valid binding and explicit-definition checks. A registered MCP call crosses dispatcher/controller/SQLite for accepted explicit-definition initial construction, null command rejection, unavailable binding, unknown requirements, nested-check safe diagnostics, and explicit-null `ops` rejection; the rejected null call adds neither a `graph_patch_accepted` event nor any `lease_granted` event ID. | The focused C4+C5 command passes 47 tests; scoped Ruff, Pyright, and diff-check pass. | partial | Add the equivalent real MCP→dispatcher/controller successor-construction fixture; current successor behavior is covered only below the complete public path. Do not claim parity for unrelated adapter-owned fields or nested raw patch-envelope transport. |
| C5 diagnostic completeness | Missing `node_states`, malformed graph shape, mismatched identity, absent failure events, empty valid state and bounded data never produce a false complete report. | The bounded diagnostic from `95b7a33d0`/`ad46b7f0` is ported with strict Pydantic run/graph/node boundary models. `node_states` is required; malformed state values, optional graph `run_id` mismatch, and top-level or `collection_meta.node_states` truncation are partial. Empty complete mappings remain valid. | Real loopback HTTP plus the actual CLI subprocess proves missing `{}` exits 1 while a present empty mapping exits 0; the same path covers malformed/identity/truncation/node-evidence cases and the 2 MB/10-node caps. | 8 pure tests pass; 15 real HTTP/subprocess tests pass. | validated | None in the bounded Stage 1 diagnostic scope. |
| C6 gate accounting | Attribute unavoidable baseline, submission, explicit checks, verifier checks and final audit to command/source/tree/candidate identity. | Retained evidence supplies comparable project-test totals and the latest exact baseline command identity; discovery baseline/submission correctly record no configured commands. | Public API-derived `runtime-final.json` retains the latest probe timing and command identity without another run. | Evidence integrity hashes remain under `recovery-2026-09-09/`; no timing rerun or cache implementation was performed. | partial | Explicit-check, verifier-check, and final-audit timings are absent from the comparable records. Do not infer them, infer caching, or treat repeated command text as reusable proof. |

## Current pass

C5 is closed by the bounded local fixture. C4 now has non-null shared check-item
schema evidence, restored typed flat patch-tool exposure, and real
initial-path/null/error/no-lease proof, but its successor-path proof remains
explicit; unrelated MCP/Codex tool schemas and nested raw patch transport are
not claimed equal.
C1 remains partial until the compact authoritative admission matrix exists. No
Stage 2 model call may begin while C1 and C4 retain those gaps.

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
