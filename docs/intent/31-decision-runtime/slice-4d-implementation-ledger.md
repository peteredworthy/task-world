# Slice 4D implementation ledger

Status: implementation complete and independently validated. The existing
recovery-stabilization changes and prior slice ledgers remain untouched. No live
server, live database/history operation, paid execution, activation, or commit
was performed.

## Requirements and evidence

| ID | Required behavior | Product-real / regression evidence | Status |
|---|---|---|---|
| S4D-1 | Appeal, oversight, and recovery advisory outputs use the shared typed submit contract while retaining the existing `RecoveryPlan` schema and record. | `_submission_contract` exposes the generated `RecoveryPlanValue` schema; typed submit builds the existing `RecoveryPlanRecord` with trusted runtime identity and provenance. | validated |
| S4D-2 | Advisory output preserves exact provenance and cannot author trusted identity or lifecycle fields. | `test_advisory_submission_is_validated_and_runtime_owns_record_identity` and the unknown-field negative validate the runtime-owned record envelope and strict nested value. | validated |
| S4D-3 | Advisory authors receive no graph-mutation or lifecycle callback tools. | Connected FastMCP catalog test exposes only `submit`; Codex dynamic catalog and both runner prompts omit graph, checklist, recovery, and grading tools. | validated |
| S4D-4 | Typed advisory answers use the same terminal-answer closure and invocation plumbing; legacy no-argument callbacks remain compatible. | Runtime dispatch now enables the trusted invocation factory and terminal closure for typed advisory answers, while an empty legacy callback still uses the prior synthesized recovery plan. Existing oversight/recovery integration suite remains green. | validated |

## Implementation

- `graph_runtime/dispatch.py` derives an advisory `SubmissionContract` from the
  declared `recovery_plan` port, validates authored `RecoveryPlanValue`, and
  emits the existing `RecoveryPlanRecord` with runtime-owned identity and
  provenance.
- `runners/submission.py` owns the advisory-contract predicate.
- Codex dynamic tools, Claude prompts, and the connected Claude FastMCP server
  use the shared typed schema and suppress unauthorized graph/lifecycle tools.
- No new record type, graph command, event, lifecycle path, or advisory schema
  was introduced. Empty legacy advisory submit remains on the old output-record
  builder.

## Source identity

Starting hashes are the preceding slice's final hashes where recorded, or the
unchanged inherited hash from the Slice 3A ledger. The new test had no prior
source hash.

| File | Starting SHA-256 | Final SHA-256 |
|---|---|---|
| `src/orchestrator/graph_runtime/dispatch.py` | `c740ea3e70f5413a12094c639e1ca5cde148d598e88b79b7c5c683008beb8b54` | `fa01a141b6340183db801384d668d0a1149033c99dcbe3c7b3310da953b1d0dc` |
| `src/orchestrator/graph_runtime/graph_mcp_tools.py` | `c9e11f681eaee83eabd969978206e816f5c4d808bad4f34657e6d4f87fb491b5` | `8f45f5df42eaec886615d438a632064941de08853d8c2f1928565b1d3b048a60` |
| `src/orchestrator/runners/submission.py` | `d76b6cf3957c70a2168754cc3021c213cd472ba7dd83b779ed49a69e78abae08` | `f3b7925c6aa75cf5869ac5d3a4f9b7f4dc15fb6ae56ce5e13b81c76d52e11332` |
| `src/orchestrator/runners/__init__.py` | `0d7f6e96d7b0eacf7480ac76ce281a4a5588e2184879dc1a583c5f9072817b18` | `f6cdaf572ccf1719eabf2431273e7978f80019b3a3d41969f38f7426aeb6933a` |
| `src/orchestrator/runners/agents/codex/common.py` | `f04cfdde5623a24c2338e9043f974918b47d46ca143e74395b5e61fe7373f98e` | `f94fd10794136fa4d23773237d11b5e8086ac00ea20e43d6167a01bd83ca4ae8` |
| `src/orchestrator/runners/agents/claude_cli/agent.py` | `de6ce0f55720859b95690a30cc7fd070ef212cecbdbbe8638a23683c15bb4ece` | `57ec55f33c0ee0be878e0addd6001d7ac59a61e0db15e1153541848a8ac62855` |
| `tests/unit/test_advisory_submission.py` | `new` | `4da1aa0007628fc6dcaf05bdcd9727b620a0cc2dc49227f179ee95f02eaf5aa5` |

## Validation record

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_advisory_submission.py tests/unit/test_graph_dispatch_on_output.py \
  tests/unit/test_decision_schema_consumers.py tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_codex_server_common.py tests/unit/test_cli_agent.py \
  --override-ini='addopts='
# 307 passed, 9 warnings in 3.52s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_oversight_retired.py tests/integration/test_graph_runner_recovery_dispatch.py \
  tests/integration/test_graph_startup_recovery.py tests/integration/test_graph_fr02_acceptance.py \
  tests/integration/test_graph_fr03_acceptance.py tests/integration/test_graph_fr08_acceptance.py \
  tests/integration/test_codex_server_callbacks.py tests/integration/test_graph_decisions_api.py \
  tests/integration/test_recovery_deterministic_lifecycle.py --override-ini='addopts='
# 42 passed, 25 skipped in 27.67s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py tests/unit/test_graph_decisions.py \
  tests/unit/test_initial_planning_decision.py tests/unit/test_gap_correction_decision.py \
  tests/unit/test_successor_amendment_decision.py tests/integration/test_recovery_successor_replay.py \
  tests/integration/test_recovery_successor_planner_probe.py --override-ini='addopts='
# 242 passed, 9 warnings in 308.31s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright \
  src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/graph_mcp_tools.py \
  src/orchestrator/runners/submission.py src/orchestrator/runners/agents/codex/common.py \
  src/orchestrator/runners/agents/claude_cli/agent.py src/orchestrator/runners/__init__.py
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check <changed files>
# All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check <changed files>
# All files already formatted

git diff --check
# clean
```

The graph boundary checker ran on the focused pytest invocations and passed for
the tracked source set. The new test uses only public graph/runtime boundaries;
the worktree remains uncommitted as required by the slice instructions.

## Remaining concerns

The advisory path is intentionally compatibility-scoped: `RecoveryPlan` remains
an advisory output and is not interpreted as a lifecycle command or graph patch.
The tests use disposable/in-memory or connected local transport boundaries and
do not claim provider reliability. The complete repository gate remains
deferred to the final recovery slice as required by the implementation prompt.
