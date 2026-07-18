# Task 10 Report: Move Pure Driver Policy Into The Graph Kernel

## RED

- Added public `orchestrator.graph` policy imports and policy tests before implementation.
- `uv run pytest tests/unit/test_graph_projections.py -q` failed during collection as expected: `ImportError: cannot import name 'GraphProjectionSnapshot' from 'orchestrator.graph'`.

## Baseline

- `uv run pytest tests/unit/test_graph_driver_logic.py tests/unit/test_graph_projections.py -q`
- Result before relocation: existing suite passed.

## GREEN

- Added graph-owned `GraphRunOutcome`, `GraphProjectionSnapshot`, and `ActiveLeaseWaitPlan`.
- Added public pure projection APIs: `project_graph_projection_snapshot`, `project_graph_outcome`, `project_graph_completion_eligible`, `project_graph_blocked_reason`, `project_active_lease_wait_plan`, and `project_node_max_attempts`.
- Driver now consumes graph-owned policy APIs for projection reads, quiescence classification, completion eligibility, and lease wait planning; effectful scheduling, dispatch, retries, lease renewal, recovery, lifecycle bridges, contamination protection, and event ordering remain in the driver.
- Preserved `orchestrator.workflow.GraphRunOutcome` as the graph-owned public type.

## Verification

- Focused parity suite: 191 passed in 30.94s.
- `uv run ruff check .`: passed.
- `uv run pyright`: 0 errors, 0 warnings.
- `git diff --check`: passed.
- Full suite: 4845 passed, 3 skipped, 3 pre-existing dependency deprecation warnings in 131.59s.

## Concerns

- The worktree contained pre-existing modifications to other `.superpowers/sdd` reports and progress tracking. They were not included in this task's commit.

## Follow-up: Remove Duplicate Driver Policy

- Removed the remaining duplicate snapshot, retry-limit, completion, outcome, blocker, and nonterminal-node policy implementations from `workflow/graph_driver.py`.
- Removed the unused driver terminal-state constant, policy-only imports, and `_legacy_policy_references` tuple. Repository search found no concrete private-import callers requiring compatibility aliases.
- The graph kernel remains the sole implementation authority for these policies.
- Follow-up verification: focused Task 10 and brief-named graph-driver suites passed (`191 passed in 30.45s`); `uv run ruff check .`, `uv run pyright` (0 errors, 0 warnings), and `git diff --check` passed.
