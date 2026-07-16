# Task 11 Canonical Event Payloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add strict canonical payload contracts, serialization, retention, and replay coverage for `agent_dispatch_requested` and `command_recorded`.

**Architecture:** Reuse the graph event model registry as the validation source and expose its existing serialization policy as a public `orchestrator.graph` API. Runtime and scenario producers serialize typed payloads before envelope construction; compact reads derive explicit retained fields from each new event specification.

**Tech Stack:** Python 3.12, Pydantic v2, pytest/pytest-asyncio, SQLAlchemy async SQLite, Ruff, Pyright, pre-commit.

## Global Constraints

- Do not mark either event external or add compatibility aliases/defaults for sparse historical fixtures.
- `command_recorded` is exactly `{"command_type": str, "command_payload": dict[str, Any]}`.
- Unknown fields and scalar coercion must fail; dynamic content is allowed only in `command_payload`.
- Use `uv run` for every Python command, no mocks, suppressions, database deletion, or hook bypasses.
- Preserve the unrelated existing `.superpowers/sdd/progress.md` change.

---

### Task 1: Complete Canonical Event Typing

**Files:**
- Modify: `tests/unit/test_graph_event_registry.py`
- Create: `tests/unit/test_runtime_event_payloads.py`
- Modify: `tests/unit/test_scenario_harness.py`
- Modify: `tests/integration/test_graph_outbox_crash_points.py`
- Modify: `tests/unit/test_fixture_corpus.py`
- Modify: `tests/fixtures/graph/invariants.yaml`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/event_registry.py`
- Modify: `src/orchestrator/graph/payload_registry.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph/scenario.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Create: `.superpowers/sdd/task-11-event-fix-report.md`

**Interfaces:**
- Consumes: `EVENT_PAYLOAD_MODELS`, `EventPayloadSpec`, `ResourceClaimProjection`, and the existing event serialization policy.
- Produces: `AgentDispatchRequestedPayload`, `CommandRecordedPayload`, and `serialize_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]`, exported from `orchestrator.graph`.

- [ ] **Step 1: Add registry and strict-model tests**

Add equality coverage and focused model cases:

```python
assert CANONICAL_EVENT_TYPES == EVENT_PAYLOAD_MODELS.keys()
assert CommandRecordedPayload.model_validate({
    "command_type": "schedule_tick",
    "command_payload": {"base_snapshot_id": "S0"},
}).model_dump(mode="json") == {
    "command_type": "schedule_tick",
    "command_payload": {"base_snapshot_id": "S0"},
}
```

Parametrize unknown fields, flattened command fields, wrong scalar types, and invalid nested resource claims under `pytest.raises(ValidationError)`.

- [ ] **Step 2: Run RED model/registry tests**

Run: `uv run pytest tests/unit/test_graph_event_registry.py tests/unit/test_runtime_event_payloads.py -q`

Expected: FAIL because the two models and registry entries do not exist and canonical/model keys differ.

- [ ] **Step 3: Add producer and compact/full parity tests**

Assert the scenario event uses nested `command_payload`, the controller payload equals its typed JSON dump, and persisted reads retain complete canonical payloads through projection/light/summary/node-detail readers for both event types.

- [ ] **Step 4: Run RED producer tests**

Run: `uv run pytest tests/unit/test_scenario_harness.py tests/integration/test_graph_outbox_crash_points.py tests/unit/test_fixture_corpus.py -q`

Expected: FAIL on the old flattened scenario payload and missing typed serialization/retention.

- [ ] **Step 5: Implement strict models and complete registries**

Add required fields without defaults:

```python
class AgentDispatchRequestedPayload(StrictEventPayload):
    lease_granted_event_id: str
    lease_id: str
    node_id: str
    generation: StrictInt
    execution_id: str
    base_snapshot_id: str
    resource_claims: list[ResourceClaimProjection]


class CommandRecordedPayload(StrictEventPayload):
    command_type: str
    command_payload: dict[str, Any]
```

Register/export both, assert canonical keys equal model keys at module load, and add explicit four-mode retention specs containing all producer fields.

- [ ] **Step 6: Route producers through the shared policy**

Rename `_serialize_event_payload` to public `serialize_event_payload`, export it through commands and `orchestrator.graph`, retain the policy completeness check, and add both new names to the raw JSON policy because all fields are required and already canonical. Build `command_recorded` with nested `command_payload`; validate and serialize both producers before `EventEnvelope` construction.

- [ ] **Step 7: Canonicalize fixtures and make focused tests GREEN**

Update `command_recorded` expectations to:

```yaml
- command_recorded:
    command_type: schedule_tick
    command_payload: {base_snapshot_id: S0}
```

Run the focused registry/model/scenario/controller/corpus/allowlist/read tests and fix only contract-related failures.

- [ ] **Step 8: Verify the repository**

Run, in order:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pre-commit run --all-files
```

Expected: all commands pass.

- [ ] **Step 9: Self-review and report**

Inspect `git diff --check`, `git diff`, registry equality, strict boundaries, producer serialization, retention parity, and fixture canonicalization. Write `.superpowers/sdd/task-11-event-fix-report.md` with status, commits, test evidence, concerns, and files changed.

- [ ] **Step 10: Commit**

Stage only Task 11 implementation, tests, fixtures, plan, and report, leaving the pre-existing progress-file modification unstaged. Commit with hooks enabled using a concise repository-style message.
