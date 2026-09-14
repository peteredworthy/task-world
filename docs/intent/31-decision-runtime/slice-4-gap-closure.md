# Slice 4A–4C gap closure

Scope: close the known qualification regression and review the implemented
4A–4C acceptance criteria before continuing with 4D. Earlier ledgers and
historical recovery evidence remain intact. Starting source and ledger hashes
are in `slice-4-gap-starting-hashes.json`.

| ID | Required behavior | Acceptance / product proof | Status | Remaining work |
|---|---|---|---|---|
| G1 | Legacy qualification final audit preserves its bound candidate/report contract while typed audits retain exact candidate authority. | All seven sequential product cases and all nine qualification cases pass; typed final-audit negatives remain enforced. | validated | None in this cleanup. |
| G2 | Worker ready, blocked, required semantic products, failed checks and post-answer mutation behave through production dispatch. | Real Git/SQLite, actual Codex ingress and registered Claude MCP; custom YAML product and blocker evidence cases; finalized successful attempts and removed MCP routes; failure publishes no accepted result. | validated | Recovery consumption and joined verification integration retain their assigned later slices. |
| G3 | Verifier obligations and evidence remain frozen, complete and candidate-scoped through actual submission and finalization. | Both transports execute mandatory receipts, before/after-stage requirement changes and unrelated controls; incomplete/unknown findings reject; immutable public evidence survives restart. | validated | None in the reviewed 4A/4B boundary. |
| G4 | Current 4A–4C work receives a fresh independent review, with honest evidence and a clear continuation point. | Independent PASS plus 383-test combined regression; exact commands, log and final source hashes below. | validated | Continue with slice 4D. |

Validation uses the prescribed `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run
--no-sync` prefix. No live server/state, paid model, activation or commit is part
of this cleanup. The full repository gate belongs to the final integrated slice.

## Corrective passes

1. Qualification: final-audit evidence narrowing introduced by 4B applied to
   legacy snapshots as well. The callback and prompt now select that narrowing
   only when the graph-owned applicability resolver selects typed verification.
   The existing qualification scenario and its candidate/report values remain
   unchanged. A later endpoint assertion used an obsolete rejection message;
   it now checks the current precise rejection and absence of the rejected node.
   Full evidence is in `slice-4-gap-qualification.md`.
2. Worker identity: identical ready or blocked answers from distinct workers or
   executions shared a global answer-record identity. Two new behavioral tests
   failed before correction. IDs now include the logical request, node, schema,
   compiler version and canonical answer; redelivery, reordered object keys,
   unrelated graph positions and replay retain stable identities.
3. Frozen requirements: worker staging/finalization skipped the shared read-set
   check, and worker/verifier read sets omitted logical requirement identities.
   Four product cases demonstrated wrong acceptance before correction. Both
   worker boundaries now use the existing checker. A shared pure helper includes
   bound requirement IDs, versions and producer nodes. Real Codex and Claude
   cases cover revisions before and after staging, with unrelated revisions as
   positive controls. No second authority mechanism was introduced.
4. Blocker evidence: workers accepted `e999` despite having no offered alias.
   Both real submission paths reproduced the defect. Worker context now freezes
   meaningful exact-bound evidence aliases, the prompt presents them, and the
   compiler validates references. Corrective work excludes evidence for other
   candidates; no offered evidence requires an empty evidence list.
5. Product proof: worker tests now execute real Codex submission handling with
   an injected JSON-RPC transport and Claude's registered ASGI/SSE MCP route.
   They cover ready, blocked, missing products, failed commands, post-answer
   edits and stale requirements. The custom product comes from a separate
   YAML-declared `worker.release-note` schema; a built-in plan-shaped answer is
   rejected. Typed verifier tests use the same transport paths for actual runtime
   receipts, mutation, stale requirements and invalid findings.

## Validation record

All commands below run in the recovery worktree with
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync`.

| Check | Exact selection / result |
|---|---|
| Initial worker baseline | `pytest -q -n 0 tests/integration/test_graph_decision_runtime.py -k work_result --override-ini=addopts=` — 4 passed. |
| Actual worker transports | Same selection after ingress expansion — 8 passed. |
| Failed command / post-answer edit | `-k work_result_failure` — 4 passed, no accepted candidate or decision. |
| Worker authority regression before fix | `-k work_result_preserves` — 4 expected failures, 4 unrelated-movement controls passed. |
| Worker authority and transport coverage after fix | `-k work_result` — 20 passed. |
| Verifier real receipts and requirement authority | `-k 'runtime_check_executes or typed_verifier_preserves'` — 14 passed. |
| YAML products and blocker evidence before final fix | `-k 'semantic_product or semantic-product or custom_product or blocker_evidence'` — 6 passed, 2 expected unknown-blocker-evidence failures. |
| Verifier finding negatives and fixed worker evidence | `-k 'incomplete_or_unknown or blocker_evidence'` — 12 passed. |
| Unit boundary/compiler/prompt closure | `pytest -q -n 0 tests/unit/test_graph_decisions.py tests/unit/test_graph_runner_boundary_commands.py tests/unit/test_graph_verifier_prompt.py --override-ini=addopts=` — 163 passed. |
| Legacy sequential product qualification | Seven formerly failing fixture cases passed. Combined qualification/sequential/prompt run: 21 passed, one obsolete-message assertion failed; corrected qualification file subsequently passed all 9 tests with `--run-slow`. |
| Static checks | Scoped Ruff and Pyright across all eight cleanup source/test files passed; graph projection boundary checker and `git diff --check` passed. All changed source/test files are tracked, so the boundary scan includes them. |

Source hashes are in `slice-4-gap-final-hashes.json`; all three
preceding slice ledgers match their starting hashes. This document supersedes
their open cleanup/review concerns without rewriting their historical results.

## Final combined regression and independent verdict

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_decisions.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_graph_verifier_prompt.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/integration/test_graph_decision_runtime.py \
  --override-ini=addopts= --tb=short
# 383 passed, 19 warnings in 254.48s; exit 0
```

Full output is preserved in `slice-4-gap-regression.log`. The warnings are
Pydantic serializer/schema warnings; no check failed or was suppressed. The
eight cleanup source/test hashes remained unchanged during this run.

The independent validator passed review criteria 1–6 and 8–10 for the 4A–4C
cleanup. It independently exercised the previously failing logical-requirement
and unknown-evidence reproductions, reviewed the final identity and evidence
owners, and inspected the custom YAML/transport coverage. Its only final
condition was a passing combined regression, now satisfied. Budget and diagnostic
implementation remains assigned to slice 5; this review makes no claim for it.

**Handoff: the 4A–4C cleanup is complete and slice 4D can proceed.** Changes
remain uncommitted and unactivated. The complete repository gate remains at the
planned final integrated checkpoint. All product evidence here is deterministic
infrastructure proof with scripted transports, not a paid-model reliability
result.
