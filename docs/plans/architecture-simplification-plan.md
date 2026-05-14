# Architecture Simplification Plan

## Goal

Resolve the branch review findings by removing low-value pass-through layers and making the parent oversight state machine easier to reason about.

The target shape is:

```text
ParentOversightService
  - owns parent/child coordination, evidence collection, persistence, and projection hydration
  - exposes one decision surface for parent next actions

Oversight reducer/projection
  - owns durable fact key definitions
  - computes terminal guard, attention queues, merge queue, and next parent action

Delegation state
  - owns command fencing, idempotency, and audit records
  - is recorded through one shared helper, not duplicated service shims

RunRepository
  - persists already-sanitized oversight fact patches
  - does not define parent oversight schema contracts
```

## Non-Goals

- Do not redesign child evidence schema or generated child routines.
- Do not change user-facing parent/child run behavior.
- Do not remove `DelegatedWork` entirely in this pass.
- Do not move fan-out execution out of `WorkflowService` unless required to remove duplicated delegation recording.
- Do not weaken row-locking around oversight fact writes.

## Findings Covered

1. Consolidate parent action reducers.
2. Remove duplicated delegation shims.
3. Share oversight fact key ownership.
4. Drop unused repository pass-through methods.

## Phase 1: Establish Behavior Locks

Run the focused tests before editing:

```bash
uv run pytest \
  tests/unit/test_delegation_models.py \
  tests/unit/test_delegation_fan_out.py \
  tests/unit/test_super_parent_oversight.py \
  tests/unit/test_super_parent_service_mechanics.py \
  tests/unit/test_merge_readiness.py \
  tests/unit/test_delegation_boundaries.py \
  tests/integration/test_fan_out.py \
  tests/integration/test_workflow_smoke.py
```

Add or adjust tests before refactoring if any expected behavior is not already covered:

- terminal parent with unresolved child pauses and records the correct blocker
- completed child with acceptance evidence maps to `accept_child`
- completed child with revision evidence maps to `review_child_evidence`
- max child run limit maps to `ask_user`
- duplicate child creation remains idempotent
- stale delegation commands remain ignored

## Phase 2: Make Oversight Projection the Parent Action Source

Current issue:

- `ParentOversightService.apply_oversight_terminal_guard()` computes `project_parent_oversight()`.
- It then rebuilds `SuperParentFacts` and `DelegatedWork` from the same child runs.
- It calls `SuperParentDelegationPolicy.reduce()` to decide what to record.
- `oversight.py` already computed `terminal_guard`, `merge_queue`, `attention_items`, and `next_parent_action`.

Plan:

1. Add a small pure mapper in the oversight layer:

```python
def delegation_decision_from_parent_snapshot(snapshot: Mapping[str, Any]) -> DelegationDecision:
    ...
```

2. Map projected `next_parent_action` to delegation decisions:

| `next_parent_action` | Delegation decision |
| --- | --- |
| `wait_for_child` | `wait`, `WaitingOnDelegate` |
| `accept_child` | `integrate` for the first `merge_queue` child |
| `review_child_evidence` | `review`, `ReviewDelegateResult` |
| `ask_user` | `ask_user`, `ReviewDelegateResult` |
| `complete_parent` | `complete` |
| `launch_child` | `launch` unless terminal guard is blocking, then `review`, `AwaitingGate` |

3. Update `apply_oversight_terminal_guard()` to record the mapped decision from the projected snapshot instead of invoking `SuperParentDelegationPolicy.reduce()`.
4. Keep `SuperParentDelegationPolicy.decision_for_create_child()` temporarily if it is still useful for create-child command validation.
5. Reassess `SuperParentDelegationPolicy.reduce()` after call sites are removed. Delete it if only tests use it.

Verification:

```bash
uv run pytest tests/unit/test_super_parent_oversight.py tests/unit/test_super_parent_service_mechanics.py
uv run pyright
```

## Phase 3: Centralize Delegation Recording

Current issue:

- `WorkflowService` and `ParentOversightService` both define wrappers around:
  - `DelegationState.from_oversight_state(...)`
  - `with_decision(...)`
  - `with_result(...)`
  - `apply_command(...)`
  - `merge_into(...)`

Plan:

1. Introduce a shared helper, likely `src/orchestrator/workflow/delegation/recorder.py`.
2. Keep it small and pure except for injected clock use:

```python
class DelegationRecorder:
    def __init__(self, clock: Clock) -> None: ...
    def apply_command(...) -> tuple[dict[str, Any], DelegatedWork | None, DelegationDecision]: ...
    def record_decision(...) -> dict[str, Any]: ...
    def record_result(...) -> dict[str, Any]: ...
    def record_review_state(...) -> dict[str, Any]: ...
    def record_work(...) -> dict[str, Any]: ...
```

3. Replace the duplicated helper methods in `ParentOversightService`.
4. Replace the duplicated helper methods in `WorkflowService` fan-out code.
5. Keep fan-out-specific helpers in `WorkflowService` only where they add domain behavior, such as choosing command keys or translating task state to delegated work.

Verification:

```bash
uv run pytest tests/unit/test_delegation_models.py tests/unit/test_delegation_fan_out.py tests/integration/test_fan_out.py
uv run ruff check src/orchestrator/workflow tests/unit/test_delegation_models.py tests/unit/test_delegation_fan_out.py
```

## Phase 4: Move Oversight Fact Key Ownership Out of Repository

Current issue:

- `DURABLE_PARENT_OVERSIGHT_FACT_KEYS` is defined in `workflow/oversight_projection.py`.
- A duplicate `_DURABLE_PARENT_OVERSIGHT_FACT_KEYS` exists in `db/access/repositories.py`.
- The repository now knows detailed parent oversight field names.

Plan:

1. Keep the canonical key set in `workflow/oversight_projection.py` or a new pure module such as `workflow/oversight_facts.py`.
2. Export a single sanitizing function:

```python
def durable_parent_oversight_patch(state: Mapping[str, Any]) -> dict[str, Any]:
    ...
```

3. Update `ParentOversightService.persist_parent_oversight_state()` and related callers to sanitize before calling the repository.
4. Change `RunRepository.update_parent_oversight_facts()` to merge the provided patch without maintaining its own key whitelist.
5. Keep repository merge semantics for append-only lists, set-union lists, and `delegated_work`, but move those key classifications to the same canonical workflow module if they are oversight-specific.

Preferred end state:

```text
workflow/oversight_facts.py
  - DURABLE_PARENT_OVERSIGHT_FACT_KEYS
  - APPEND_ONLY_OVERSIGHT_LIST_KEYS
  - SET_UNION_OVERSIGHT_LIST_KEYS
  - extract_parent_oversight_facts()

db/access/repositories.py
  - receives sanitized patches
  - performs locked JSON merge mechanics
```

Verification:

```bash
uv run pytest tests/unit/test_super_parent_oversight.py tests/unit/test_repositories.py
uv run pytest tests/integration/test_api_runs.py tests/integration/test_fan_out.py
uv run pyright
```

## Phase 5: Delete Unused Repository Pass-Through Methods

Current issue:

- `append_delegation_decisions()`
- `append_delegation_results()`
- `replace_delegated_work()`

These currently have no production call sites and only forward into `_merge_oversight_patch_locked()`.

Plan:

1. Confirm call sites:

```bash
rg -n "append_delegation_decisions|append_delegation_results|replace_delegated_work" src tests
```

2. Delete the unused methods.
3. Keep `_merge_oversight_patch_locked()` private if it remains the shared locked merge implementation.
4. Remove tests that only exercise deleted pass-through methods, or retarget them to `update_parent_oversight_facts()` if they cover meaningful merge behavior.

Verification:

```bash
uv run pytest tests/unit/test_repositories.py
uv run ruff check src/orchestrator/db/access/repositories.py tests/unit/test_repositories.py
```

## Phase 6: Clean Up Public Exports and Boundary Checks

Plan:

1. Update `src/orchestrator/workflow/delegation/__init__.py` after any deleted reducer or new recorder module.
2. Update `src/orchestrator/workflow/__init__.py` only for symbols that remain part of the public module API.
3. Update `scripts/check_delegation_boundaries.py` if the ownership rules change.
4. Update `docs/ARCHITECTURE.md` if the parent oversight or repository responsibilities described there change.

Verification:

```bash
uv run pytest tests/unit/test_delegation_boundaries.py
uv run ruff check .
uv run pyright
```

## Suggested Commit Order

1. Add/adjust behavior-lock tests.
2. Make projected oversight the source for terminal guard delegation decisions.
3. Add `DelegationRecorder` and replace duplicate service shims.
4. Move oversight fact key ownership into one workflow module.
5. Delete unused repository methods.
6. Update architecture docs and boundary checks.

## Final Validation

Run the focused suite:

```bash
uv run pytest \
  tests/unit/test_delegation_models.py \
  tests/unit/test_delegation_fan_out.py \
  tests/unit/test_super_parent_oversight.py \
  tests/unit/test_super_parent_service_mechanics.py \
  tests/unit/test_repositories.py \
  tests/unit/test_delegation_boundaries.py \
  tests/integration/test_fan_out.py \
  tests/integration/test_workflow_smoke.py
```

Then run the project checks:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

## Success Criteria

- Parent next-action logic has one authoritative reducer source.
- `WorkflowService` no longer contains duplicated delegation state recording wrappers.
- Durable parent oversight key definitions exist in one workflow-owned location.
- Repository oversight writes are locked merge mechanics, not schema ownership.
- Unused repository forwarding methods are gone.
- Existing parent oversight, child run, fan-out, and delegation behavior remains unchanged.
