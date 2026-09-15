# Slice 5D implementation ledger

Status: implemented and validated.

Scope: extend the existing bounded protected-evidence seam to decision-v1
answers and provide no-model local replay. No live server, activation, paid
model execution, historical resume, or commit is authorized.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S5D-1 | Accepted and rejected decision answers retain canonical request/response, answer contract identity, compiler identity, frozen bound context, exact rejection outcome, and exact graph prefix in protected CAS. | `DecisionAnswerReceiptArtifact` captures the bounded prefix plus all six graph-owned answer families. Rejected ingress seals a typed answer-validation or candidate-check outcome before adding the receipt's own CAS reference; accepted staging and rejected ingress each store the opaque ref on one exact durable owner event. | complete | None. |
| S5D-2 | Missing, oversized, or unreceived evidence is explicit and never replayable. | `test_empty_and_oversized_receipts_are_explicitly_incomplete` covers `unreceived` and `evidence_oversize`; omitted bodies and completeness flags are retained in bounded manifests. | complete | None. |
| S5D-3 | Source, contract, receipt, owner, evidence, empty, and unknown-version tampering fails closed. | Receipt tests cover canonical integrity, source/schema/status/request tampering, missing exact ownership, and mismatched owner diagnostic/evidence. Candidate-check replay independently verifies the protected failed gate-audit event's run, node, execution, candidate tree, result, fingerprint, and bounded rejection evidence. | complete | None. |
| S5D-4 | Local replay preserves the original accepted/rejected result and does not authorize or relabel a paid experiment. | Answer-validation rejection must reproduce normalization/compiler failure. Candidate-check rejection must reproduce canonical/schema/compiler acceptance and the exact protected failed gate audit. The product-real work-result test deletes the disposable candidate checkout, replays in an empty DB, and proves no authoritative graph mutation or second runner/model execution. | complete | None. |

## Starting evidence

- Previous implementation: `slice-5c-implementation-ledger.md`.
- Existing bounded CAS/rejection evidence: `src/orchestrator/graph_runtime/rejection_evidence.py`.
- Existing canonical decision contract: `src/orchestrator/graph/decisions.py`.
- Existing focused baseline is recorded in the 5C ledger; unchanged prior tests
  remain the regression baseline for this slice.
- Scope boundary: no live server, activation, paid model execution, historical
  resume, database deletion, or commit was performed.

## Starting source hashes

Final source/test hashes at validation:

```text
6e573f188fd4858ae24f4dfb68fe88f4a4fadc30ca5c0c03e0b55936349b5521  src/orchestrator/graph_runtime/rejection_evidence.py
cd9623b0296f4bc849fdec26c6c3249e9d31d781f49901080eb585fb942f41a6  src/orchestrator/graph_runtime/dispatch.py
6204c00d5ff4a3ecc732988491e9775c0fc6e762ddd78f9a56dabff03f973421  src/orchestrator/graph/models.py
e10d19978ef23eb2ea5cbb676089a63455b5395934ecba55f44e79e87abcd9b1  src/orchestrator/graph/command_models.py
fd2f3b65a94fd41c7b943e81613592b4b12b90c3834aae738c13f61537607662  src/orchestrator/graph/commands/boundary.py
8e2b122decf5cc5e1efcef9a2ba0bb7c950e12d24d6707cd0f5dde30af9705a9  src/orchestrator/graph_runtime/__init__.py
73693d2b1121b1c0cdc1d1f89fc932e2c44b3480f4067e7858d2b1b483a6de29  tests/integration/test_decision_answer_replay.py
72d3fd55b55469b9b64a8303bd5a07b33704faa7c3bff0de53129fa8e315e8d8  tests/integration/test_graph_decision_runtime.py
f77d4d652290b0afaea32a9b78d2f572e69df1331c509d193041cabf10974c21  tests/unit/graph_projection_behavior_cases.py
```

## Validation

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_decision_answer_replay.py tests/integration/test_graph_runner_recovery_dispatch.py tests/integration/test_graph_startup_recovery.py tests/unit/test_graph_recovery_selection.py tests/unit/test_startup_recovery.py tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projection_replay_equivalence.py tests/unit/test_graph_projection_immutability.py tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_integrity.py --override-ini='addopts=' --tb=short
399 passed, 18 skipped in 4.93s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_decision_runtime.py --override-ini='addopts=' --tb=short
73 passed, 9 warnings in 280.64s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph_runtime/rejection_evidence.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/models.py src/orchestrator/graph/command_models.py src/orchestrator/graph/commands/boundary.py src/orchestrator/graph_runtime/__init__.py tests/integration/test_decision_answer_replay.py tests/integration/test_graph_decision_runtime.py tests/unit/graph_projection_behavior_cases.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph_runtime/rejection_evidence.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/models.py src/orchestrator/graph/command_models.py src/orchestrator/graph/commands/boundary.py src/orchestrator/graph_runtime/__init__.py
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
# passed

git diff --check
# passed
```

## Review notes

- Receipt content is bounded by the existing 96 KiB request/response/context
  boundary and 512 KiB protected-evidence ceiling. Completeness is explicit;
  omission never becomes replayable.
- Receipt integrity seals the complete canonical manifest, including original
  status, metadata, contract identity, and all protected hashes. Replay checks
  the generated answer schema and compiler identity from `orchestrator.graph`.
- Accepted receipt refs are canonical event evidence; the existing execution
  attempt projection intentionally remains backward-compatible and does not
  duplicate the protected receipt model.
- Upstream transport failures that never reach decision ingress remain outside
  this receipt and use the existing provider-specific dynamic-tool receipt
  seam; no arguments are invented for those failures.

## Merge-blocker correction pass

The prior receipt implementation trusted the stored status too much. The
regression `test_receipt_cannot_self_declare_invalid_answer_as_accepted` now
proves that an accepted receipt containing an invalid batch disposition fails
replay. Missing/oversized graph prefixes and failed captures are explicit and
non-replayable. A missing protected receipt blocks the public retry preflight
before runner creation.

Focused receipt tests: `4 passed`; combined correction suite: `50 passed in
22.25s`. Current hashes:

```text
fc5d0ab89f3fef63bfae3186015ed125557ade19b83547fcb4482ebec7d63d2d  src/orchestrator/graph_runtime/rejection_evidence.py
d4ee548543a29f63881d46e477d4b00eeeb282f39936523dbae8599cc7b20ad4  src/orchestrator/graph_runtime/store.py
e1f2a49e58fd4be8bc67991329c60c4269397e1f945776ee6536c6ba276a4461  tests/integration/test_decision_answer_replay.py
```

## Builder correction pass 2

- A negative replay test proves protected bytes alone are insufficient before
  a durable event authorizes the receipt.
- The production rejection-budget bridge obtains both receipt owners from real
  dispatch ingress (`decision_answer_rejected`) and replays each receipt in a
  separate empty database; it does not manufacture ownership with a manual
  artifact-reference append.
- Incompleteness regressions explicitly cover `graph_prefix_incomplete`,
  `question_context_incomplete`, `source_boundary_incomplete`, `unreceived`
  and `evidence_oversize`; none is replayable.
- The paid-retry preflight is exercised through scheduled dispatch with an
  empty receipt store and proves the runner factory/create count remains zero.

Receipt/recovery correctness is included in the **138 passed, 1 skipped**
correction suite recorded in the Slice 5E pass-2 validation manifest. Current
pass-2 hashes:

```text
fc5d0ab89f3fef63bfae3186015ed125557ade19b83547fcb4482ebec7d63d2d  src/orchestrator/graph_runtime/rejection_evidence.py
ddd67d41a084a0097080405cc20476a8097a03d9b2d8fdef31f27ab3ae350fdd  src/orchestrator/graph_runtime/dispatch.py
e731b07305d3cbd2e3bec948032b0aa9efead22c4f28dc1ddad820c5774e799c  tests/integration/test_decision_answer_replay.py
70a81833eaf728c4a8154494859dbfe9b3d45c66cdae76fb29c437946a4b57a9  tests/integration/test_decision_recovery_crash_matrix.py
```

## Builder correction pass 3

Validator pass 2 found that a real `work_result` answer could pass canonical
answer compilation and then fail a mandatory candidate check. The receipt was
event-authorized, but replay incorrectly required all rejected answers to fail
the compiler. The correction adds a protected typed rejection outcome and two
explicit replay branches:

- `answer_validation` reproduces normalization or compiler rejection;
- `candidate_check` reproduces canonical/schema/compiler acceptance, then
  validates the exact failed `graph_submission_gate_audited` event bound to the
  same run, node, execution, and candidate tree.

Replay now resolves exactly one `runner_submission_staged` or
`decision_answer_rejected` owner instead of treating the generic artifact index
as semantic authorization. Rejected-owner identity includes answer attempt,
delivery, raw submitted-answer hash, and typed failure diagnostic. The receipt
is sealed before its own content hash exists; the owner diagnostic is required
to equal that sealed diagnostic plus exactly the derived receipt CAS reference,
avoiding a self-hash cycle.

Product-real proof uses the existing real work-result failed-check fixture for
both Codex Server and CLI-subprocess transport. It deletes the disposable
candidate worktree before replay, uses an empty isolated database, preserves
the original `candidate_check` rejection and corrective next action, leaves the
authoritative graph position unchanged, and observes one runner execution.
Negative receipt tests reject mismatched owner diagnostics and protected
evidence references.

```text
# Focused replay, crash/restart, work-result gate, diagnostics and adapters
146 passed, 1 skipped, 1 existing serializer warning in 37.07s

# Complete decision-runtime integration
73 passed, 9 existing JSON-schema warnings in 294.56s

ruff check (focused): All checks passed
pyright: 0 errors, 0 warnings, 0 informations
scripts/check_graph_projection_boundaries.py: passed
git diff --check: passed
```

Current pass-3 hashes:

```text
2279c2469b4e1a568c74f0bf9a66a4b55d1102a84781fdee8be0fc72ea406cd6  src/orchestrator/graph_runtime/rejection_evidence.py
cdfafd64da14a37408e206db2b3e76944c3151257f12a5649908db5e65c84a83  src/orchestrator/graph_runtime/dispatch.py
40c5f9430d9fc60bbdea6211f39afc253d0cf051ac6054cc5ce6c6f8eab50de4  src/orchestrator/graph_runtime/store.py
49fb2ed31d8fc9678af2a9961a4b962f3214927540a9018851f271896eb6c7ab  src/orchestrator/graph_runtime/__init__.py
f6bccf4b49696c99f4353c99920ffa6eb9a292b6bc4e578eeb2e7e90f2b6fbb6  tests/integration/test_decision_answer_replay.py
16f722e3117b89fe8c0d72fe360c7530fc87a86a73b1ecd75b92f6e881b6b973  tests/integration/test_graph_decision_runtime.py
```

No live server, activation, paid execution, historical-run resume, commit, or
merge was performed in this correction pass.
