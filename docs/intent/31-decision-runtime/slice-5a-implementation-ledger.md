# Slice 5A implementation ledger

Status: implemented and validated.

Scope: centralize provider-neutral failure classification and bounded
diagnostics at the graph/runner boundary. Preserve the existing rejection
categories and protected evidence carriers; the new diagnostic is additive.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S5A-1 | Bad answer shape and stale binding have distinct observable paths. | `test_classify_failure_has_distinct_actionable_paths` covers `answer_validation` and `stale_binding`, with different next actions and bounded messages. Dispatch persists the diagnostic on `SubmissionAcknowledgement` or `AgentErrorEvent`. | complete | None. |
| S5A-2 | Candidate/check failure is distinct from infrastructure/environment blockage. | The same behavior test covers authoritative candidate failure versus validation-environment blockage. The real sequential graph test `test_api_environment_blockage_restores_rejected_candidate_and_continues` passes. | complete | None. |
| S5A-3 | Process failure and exhaustion are classified separately. | The behavior test covers runner execution failure and bounded submission-repair exhaustion as `execution` and `budget_exhaustion`. | complete | None. |
| S5A-4 | Diagnostics are concise and point to protected evidence, when available. | `FailureDiagnostic` is frozen, extra-forbidden, length-bounded, scheme-validates protected references, and round-trips through `AgentErrorEvent`. Dispatch carries the gate’s durable graph-event reference into the diagnostic. | complete | None. |
| S5A-5 | Environment failure never dispatches authored-code correction. | `test_environment_rejection_does_not_reprompt_for_code_correction` proves the CLI path performs one submit and one process. `test_noncorrectable_decision_rejection_enters_and_completes_recovery` proves production graph dispatch requests and completes recovery, fails the node, and revokes the lease. | complete | None. |

## Implementation

- Added `FailureDiagnostic`, `FailureCategory`, and `FailureNextAction` as
  provider-neutral bounded Pydantic contracts.
- Added one `classify_failure` owner covering answer validation, stale binding,
  execution, candidate checks, infrastructure/environment, and budget
  exhaustion.
- Added diagnostics to runner submission acknowledgements and durable agent
  error events while retaining existing detailed evidence and error carriers.
- Reused the shared stop policy in both CLI and Codex correction loops so an
  environment blockage is surfaced for recovery/operator action rather than
  fed back as a code-edit prompt.
- Updated the architecture directory map for the new configuration contract
  module.

## Validation evidence

All commands ran from `worktrees/recovery-stabilization` with no live server,
live database mutation, activation, paid model execution, or commit.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run pytest -q \
  tests/unit/test_failure_diagnostics.py \
  tests/unit/test_cli_agent_commit_retry.py \
  tests/unit/test_codex_server_transport.py \
  tests/unit/test_pydantic_events.py \
  tests/integration/test_codex_server_callbacks.py \
  tests/integration/test_graph_sequential_product_path.py::test_api_environment_blockage_restores_rejected_candidate_and_continues
# 184 passed in 50.12s

uv run pytest -q \
  tests/integration/test_graph_sequential_product_path.py::test_api_environment_blockage_restores_rejected_candidate_and_continues \
  tests/integration/test_graph_decision_runtime.py -k 'submission or runtime_check or correction' \
  --maxfail=1
# 9 passed in 31.84s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run ruff check .
# All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run python scripts/check_graph_projection_boundaries.py
# passed
```

The first lint attempt used the default uv cache and was blocked by the
workstation’s permissions on `/Users/peter/.cache/uv`; the same checks passed
with the disposable cache path shown above.

## Merge-blocker correction pass

- Non-correctable `SubmissionRejectedError` now enters deterministic managed
  recovery instead of escaping with a running node/lease.
- Claude CLI's rejection-stop hook terminates the exact owned process without
  manufacturing a success witness.
- Focused correction suite: `50 passed in 22.25s`; focused Ruff and Pyright
  checks passed. No full-repository gate was run in this builder pass.
- Current key hashes: `dispatch.py` `1b51542b20f843a29066c197839e565f4d325161082936b534f0ecccb1b67ee5`;
  `claude_cli/agent.py` `4f7cd26da9518444213eff2cfc8339d158549dfe83bde3e9f440414ed69ea976`;
  `test_decision_recovery_crash_matrix.py` `c6a172368cc8aea1ef80bfa073b9d4d3685cb7d6d6ebfaafe5b92abc2a7db85b`.

## Source hashes at completion

```text
4913ca6469973deabc1cf3d361bbf4a7a7594e8bd80c486191e5451273201123  src/orchestrator/config/failures.py
5c47d4472f202beef6acd5841888a69f11173799a0b3e8878756b7689ce56757  src/orchestrator/graph_runtime/errors.py
4f20cf28bf7b4809d40d876a62e93d068193c811b8834444cc8378d09d7765f9  src/orchestrator/graph_runtime/dispatch.py
0b2009c0f4a44c0bbd3a6093b975d5136086639b59d4718b7c28feea0d0c5d64  src/orchestrator/runners/__init__.py
775fea71e0e1a68d0850414e167810dc4398309bcb33c40f93dea097484a8473  src/orchestrator/runners/types.py
80ee390fcef8d25e710e487865ee6ca6a526363c35012f3782cdd6625d358b77  src/orchestrator/runners/agents/claude_cli/agent.py
f6eadb701ea7656966704cff3c8527c1f7c4b5ffd042de91c2a2838c20485e12  src/orchestrator/runners/agents/codex/agent.py
a9f136cbbe3f14d80455b2a064c361960de700ae70ead9df2c45efd0ce989eda  src/orchestrator/workflow/events/types.py
3680620111e491a7483867f6c1deda5b7eaea23209e243f5dae30ea3a40c7ba0  tests/unit/test_failure_diagnostics.py
7e51d4ced2598d203324877edbef70311b89eb04aeb11f8c0fc5bd8ff6f364cd  tests/unit/test_cli_agent_commit_retry.py
```

## Builder correction pass 2

- A real post-stage authority race now raises the typed
  `DecisionBindingConflictError`; its public diagnostic is
  `stale_binding` / `refresh_binding` with correction disabled, and it never
  consumes a decision-answer rejection.
- Candidate-check failures are countable only when the typed submission-gate
  report names `candidate_check_failure`. Validation-environment blockage is
  non-countable. Product assertions cover the candidate's protected receipt
  and the public next actions for stale, candidate, environment, runner and
  budget failures.
- `SubmissionRepairExhaustedError` now reports an explicit attempt limit, with
  legacy callers retaining the default of three and decision adapters passing
  two.

Correction-focused behavior and static checks passed as recorded in the Slice
5E pass-2 validation manifest. Current pass-2 hashes:

```text
31e78849f62c7a58812bf8f0100c575826d6ad504d8c7c6a3befd6e4b8ed8bf0  src/orchestrator/graph_runtime/errors.py
ddd67d41a084a0097080405cc20476a8097a03d9b2d8fdef31f27ab3ae350fdd  src/orchestrator/graph_runtime/dispatch.py
3a0a2e03337a07e8a663f1635bcf9efd027d3d326e6547fac413009645522fb7  src/orchestrator/config/__init__.py
1124e85c496a1662822a33893c5836e577ae77c1892bd7b04f27e4a651c3a20b  src/orchestrator/runners/__init__.py
30bdac42d9c265be044ae060ecca1c4534c859acfcb053f227491fc24dd243f5  src/orchestrator/runners/errors.py
01305832e5816dd76366db03b2da494b85e1ec34b3878b854bbe157aba62f63c  src/orchestrator/runners/agents/codex/agent.py
f31ec891f99de22ea4b93ff1c31ee033988e8e59b04eea83f544bdc669e3ba1f  tests/unit/test_failure_diagnostics.py
f1ed77d86477dddacbdb2cac8cc85f59ac0e08d5daf6a0b45a374ba1d72754da  tests/integration/test_graph_decision_runtime.py
70a81833eaf728c4a8154494859dbfe9b3d45c66cdae76fb29c437946a4b57a9  tests/integration/test_decision_recovery_crash_matrix.py
```
