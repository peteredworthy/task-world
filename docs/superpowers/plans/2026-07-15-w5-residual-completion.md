# W5 Residual Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish W5 with strict canonical event and command payloads, remove obsolete compatibility layers after the database reset, and close the specification with reproducible evidence.

**Architecture:** Execute one optimization preflight followed by two implementation batches and closeout. Batch 1 canonicalizes the event corpus, removes historical shims across landed W5 slices, types the remaining event families, and generates compact-read retention allowlists. Batch 2 introduces strict command payloads plus explicit command context, reuses them at API boundaries, and adds `GradeRow`; expensive verification runs once at each batch boundary.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, pytest 9, pytest-xdist, Ruff, Pyright, SQLite compact event reads.

## Global Constraints

- Always run Python commands through `uv run`.
- The database and durable event history have been reset; historical payload compatibility is out of scope.
- Event payloads and typed records use `ConfigDict(extra="forbid")`; command payloads use `ConfigDict(extra="forbid", strict=True)`. Event enum strings remain valid canonical JSON, while numeric and boolean event fields use strict field types where coercion would hide malformed input.
- Do not add top-level `extra: dict[str, Any]`, malformed-value quarantine, replay-only aliases, or generic record fallbacks.
- Dynamic patch operations, macro arguments, command definitions, diagnostics/read-set diffs, edge policy metadata, decision scope/decider data, and typed-record payload/provenance remain dynamic only inside named fields.
- W5 Task 5 defines `StoredArtifactRef` but does not alter check-output fields or persist artifacts; the atomic tail/reference cutover belongs to the separate W5.5 plan.
- Every retained event type must have a current producer or an explicit current external-ingress designation.
- `lease_suspended` is the only designated external event because current stale-callback and worker scenarios consume it; suspect resolution/clearing and proposal-opening aliases are deleted.
- Builders run focused tests and corpus replay while iterating. A fresh verifier alone runs the expensive graph, Ruff, and Pyright gates at each batch boundary.
- On a failed batch verification, fix with implicated focused tests and use a new fresh verifier for the complete rerun.
- No mocks, monkeypatching, event-log rewriting, database deletion, global state, or compatibility suppressions.
- Import graph symbols through `orchestrator.graph` outside the graph module.
- Work in an isolated worktree when executing this plan; do not run git operations from the main checkout.

---

## File Map

- `src/orchestrator/graph/models.py`: strict event payloads, strict projection models, remaining event envelopes, and `GradeRow`.
- `src/orchestrator/graph/event_registry.py`: canonical event ownership and payload-model registry.
- `src/orchestrator/graph/payload_registry.py`: explicit compact-read retention sets and generated tuples.
- `src/orchestrator/graph/command_models.py`: strict command payloads, command context, and shared validators.
- `src/orchestrator/graph/commands/__init__.py`: `CommandSpec` registry and validation-before-dispatch.
- `src/orchestrator/graph/_commands.py`: canonical producer serialization and deletion of payload/coercion shims.
- `src/orchestrator/graph/projections.py`: parse-once reducers, attribute reads, and removal of replay/fallback branches.
- `src/orchestrator/graph_runtime/store.py`: consume generated allowlists and retain canonical JSON boolean/nested-value extraction.
- `src/orchestrator/graph_runtime/controller.py`: construct explicit command context instead of injecting private payload keys.
- `src/orchestrator/graph_runtime/dispatch.py`: stop adding unused patch fields and pass provenance as context.
- `src/orchestrator/workflow/graph_driver.py`: canonical cancel/resume calls and explicit actor context.
- `src/orchestrator/api/routers/graph.py`: compose command schemas for patch and decision requests.
- `tests/fixtures/graph/*.yaml`: canonical event fixtures only.
- `tests/unit/test_graph_event_registry.py`: event ownership and fixture-name guards.
- `tests/unit/test_w5_compatibility_removal.py`: static absence checks for deleted layers.
- `tests/unit/test_output_record_event_payloads.py`: strict record envelopes and producer/reducer behavior.
- `tests/unit/test_record_routing_event_payloads.py`: strict input binding and revision payloads.
- `tests/unit/test_file_state_gatekeeper_event_payloads.py`: strict file-state/gatekeeper payloads and cost retention.
- `tests/unit/test_graph_payload_field_allowlists.py`: all-four registry equality guards.
- `tests/unit/test_*_command_payloads.py`: strict command groups and exact registry coverage.
- `docs/dynamic-graph/w5-progress-ledger.md`: timings, RED/GREEN evidence, deletions, and final metrics.

---

## Batch 0: Optimize And Supersede

### Task 1: Establish The Fast Verification Loop

**Files:**
- Modify: `docs/dynamic-graph/w5-completion-agent-prompt.md`
- Modify: `docs/superpowers/plans/2026-07-09-w5-typed-payloads-completion.md`
- Modify: `docs/superpowers/specs/2026-07-09-w5-typed-payloads-completion-design.md`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Consumes: installed `pytest-xdist` and the repository pre-commit configuration.
- Produces: an authoritative gate matrix and clear supersession markers for compatibility-first documents.

- [ ] **Step 1: Mark stale documents as superseded**

Add this block immediately below each old document title:

```markdown
> **Superseded 2026-07-15:** The database and durable event history were reset.
> Do not preserve historical payload compatibility from this document. Follow
> `docs/superpowers/plans/2026-07-15-w5-residual-completion.md` instead.
```

- [ ] **Step 2: Benchmark representative focused and expensive gates**

Run each command once and record `/usr/bin/time -p` output in the ledger:

```bash
/usr/bin/time -p uv run pytest tests/unit/test_node_lifecycle_event_payloads.py -q
/usr/bin/time -p uv run pytest tests/unit/test_fixture_corpus.py -q
/usr/bin/time -p uv run pytest tests/ -k graph -q
/usr/bin/time -p uv run pytest tests/ -k graph -q -n auto --dist worksteal
/usr/bin/time -p uv run pytest tests/ -q -n auto --dist worksteal
/usr/bin/time -p uv run ruff check .
/usr/bin/time -p uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
```

Expected: every command exits 0; the ledger records pass count and real/user/sys time for each. If serial and parallel graph selections collect different counts or only one passes, retain the passing invocation and record why.

- [ ] **Step 3: Record the gate matrix**

Append this matrix after the benchmark rows and retain the exact measured durations from Step 2 above it:

```markdown
## W5 Residual Verification Matrix

| Stage | Builder gate | Fresh verifier gate |
|---|---|---|
| Batch 1 iteration | Changed focused files + fixture corpus | none |
| Batch 1 candidate | none | focused aggregate, fixture corpus, graph selection with xdist, Ruff, scoped Pyright |
| Batch 2 iteration | Changed command/API/model files | none |
| Batch 2 candidate | none | command aggregate, API integration, graph selection with xdist, Ruff, scoped Pyright |
| Closeout | none | full backend with xdist, Ruff, final Pyright |
```

- [ ] **Step 4: Verify documentation formatting and commit**

Run: `git diff --check`

Expected: exit 0.

Commit:

```bash
git add docs/dynamic-graph/w5-completion-agent-prompt.md \
  docs/dynamic-graph/w5-progress-ledger.md \
  docs/superpowers/plans/2026-07-09-w5-typed-payloads-completion.md \
  docs/superpowers/specs/2026-07-09-w5-typed-payloads-completion-design.md
git commit -m "Optimize W5 residual verification loop"
```

---

## Batch 1: Canonical Events, Shim Removal, And Retention

### Task 2: Own Canonical Event Names And Fixtures

**Files:**
- Create: `src/orchestrator/graph/event_registry.py`
- Create: `tests/unit/test_graph_event_registry.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph/patch_validator.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph_runtime/prompts.py`
- Modify: `src/orchestrator/api/presenters/evidence_digest.py`
- Modify: `tests/fixtures/graph/node_lifecycle_check.yaml`
- Modify: `tests/fixtures/graph/task_projection.yaml`
- Modify: `tests/fixtures/graph/patch_validator.yaml`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `CANONICAL_EVENT_TYPES: frozenset[str]`, `EXTERNAL_EVENT_TYPES: frozenset[str]`, and `EVENT_PAYLOAD_MODELS: Mapping[str, type[BaseModel]]`.
- Preserves: `lease_suspended` as an explicitly external canonical event until a runtime producer replaces it.
- Deletes: unproduced proposal-opening, proposal-status, requirement alias, support alias, environment-failure alias, and suspect-resolution alias paths.

- [ ] **Step 1: Write the event ownership RED tests**

Create `tests/unit/test_graph_event_registry.py` with these assertions:

```python
from pathlib import Path

import yaml

from orchestrator.graph import CANONICAL_EVENT_TYPES, EXTERNAL_EVENT_TYPES


REMOVED_EVENT_TYPES = {
    "environment_failure_accepted",
    "check_result_classified",
    "graph_patch_proposed",
    "planner_proposal_opened",
    "proposal_opened",
    "proposal_recorded",
    "proposal_accepted",
    "proposal_rejected",
    "proposal_resolved",
    "proposal_closed",
    "requirement_amended",
    "requirement_revision_proposed",
    "support_edge_recorded",
    "authority_resolution_recorded",
    "authority_resolved",
    "requirement_revision_authorized",
    "node_marked_suspect",
    "plan_region_suspect_resolved",
    "node_suspect_resolved",
    "plan_region_suspect_cleared",
    "node_suspect_cleared",
}


def test_replay_only_event_types_are_not_canonical() -> None:
    assert not REMOVED_EVENT_TYPES & CANONICAL_EVENT_TYPES
    assert EXTERNAL_EVENT_TYPES == frozenset({"lease_suspended"})


def test_graph_fixtures_only_use_canonical_events() -> None:
    fixture_types: set[str] = set()
    for path in Path("tests/fixtures/graph").glob("*.yaml"):
        scenarios = yaml.safe_load(path.read_text())
        for scenario in scenarios:
            for section in ("given_events", "then_events"):
                for event in scenario.get(section, []):
                    fixture_types.update(event)
    assert fixture_types <= CANONICAL_EVENT_TYPES
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_graph_event_registry.py -q`

Expected: collection fails because `CANONICAL_EVENT_TYPES` is not exported.

- [ ] **Step 3: Add the canonical registry**

Create `event_registry.py` with immutable ownership and model lookup:

```python
from types import MappingProxyType

from pydantic import BaseModel


EXTERNAL_EVENT_TYPES = frozenset({"lease_suspended"})

EVENT_PAYLOAD_MODELS: MappingProxyType[str, type[BaseModel]] = MappingProxyType({})


def canonical_event_types(produced_event_types: set[str]) -> frozenset[str]:
    return frozenset(produced_event_types) | EXTERNAL_EVENT_TYPES
```

Populate `EVENT_PAYLOAD_MODELS` as payload classes become strict in Tasks 3-5. Export `CANONICAL_EVENT_TYPES` as the exact frozen set of current producer names plus `EXTERNAL_EVENT_TYPES`; derive producer names from a single producer registry rather than maintaining a second handwritten list.

- [ ] **Step 4: Canonicalize fixtures and delete alias consumers**

Make these exact migrations:

- Remove `check_result_classified` and `environment_failure_accepted` entries from `node_lifecycle_check.yaml`.
- Replace `task_projection.yaml` environment-failure events with a valid `output_record_accepted` check record whose `record_kind` is `check_result` and whose `value.classification` carries the current environment/tool-failure classification.
- Replace `requirement_amended` with `requirement_revision_recorded` in `patch_validator.yaml` and `INVALIDATING_EVENT_TYPES`.
- Delete proposal-alias branches from `projections.py` and `graph_runtime/prompts.py`.
- Delete environment-failure alias branches and derive failures only from typed check records.
- Delete requirement/support/authority aliases and `_legacy_requirement_evidence_blockers`.
- Delete suspect-resolution/clearing aliases and `node_marked_suspect`; retain only produced `plan_region_marked_suspect`.
- Keep `lease_suspended` in projection/store/presenter consumers and document it in `EXTERNAL_EVENT_TYPES`.

- [ ] **Step 5: Run focused fixture and ownership tests**

Run:

```bash
uv run pytest tests/unit/test_graph_event_registry.py \
  tests/unit/test_fixture_corpus.py \
  tests/unit/test_graph_projections.py \
  tests/unit/test_patch_validator.py -q
```

Expected: all pass and no removed event name appears in graph fixtures.

- [ ] **Step 6: Commit the canonical event set**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime/prompts.py \
  src/orchestrator/api/presenters/evidence_digest.py tests/fixtures/graph \
  tests/unit/test_graph_event_registry.py docs/dynamic-graph/w5-progress-ledger.md
git commit -m "Canonicalize W5 event names"
```

### Task 3: Remove Landed W5 Compatibility Layers

**Files:**
- Create: `tests/unit/test_w5_compatibility_removal.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `tests/unit/test_lease_event_payloads.py`
- Modify: `tests/unit/test_lifecycle_event_payloads.py`
- Modify: `tests/unit/test_decision_event_payloads.py`
- Modify: `tests/unit/test_cleanup_event_payloads.py`
- Modify: `tests/unit/test_planner_session_event_payloads.py`
- Modify: `tests/unit/test_patch_event_payloads.py`
- Modify: `tests/unit/test_requirement_evidence_event_payloads.py`
- Modify: `tests/unit/test_node_created_event_payloads.py`
- Modify: `tests/unit/test_node_lifecycle_event_payloads.py`
- Modify: `tests/fixtures/graph/task_projection.yaml`
- Modify: `tests/fixtures/graph/node_lifecycle_worker.yaml`

**Interfaces:**
- Produces: `StrictEventPayload`, strict canonical event models, and attribute-only `EdgeProjection`, `InputBindingProjection`, and `LeaseProjection`.
- Deletes: `GraphEventPayloadBase.extra`, `LeaseEventPayloadBase`, `LifecycleEventPayloadBase`, `LegacyOutputRecord`, `_DictCompatibleProjection`, replay status models, malformed normalizers, and fallback extractors.

- [ ] **Step 1: Write static absence and strictness RED tests**

Create `tests/unit/test_w5_compatibility_removal.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.graph import GraphPatchAcceptedPayload, NodeStateChangedPayload


SOURCE = Path("src/orchestrator/graph")


def test_event_payloads_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate(
            {
                "patch_id": "patch-1",
                "base_graph_position": 0,
                "future_field": True,
            }
        )
    with pytest.raises(ValidationError):
        NodeStateChangedPayload.model_validate(
            {"node_id": "node-1", "new_state": "ready", "attempt_number": "1"}
        )


def test_historical_compatibility_symbols_are_absent() -> None:
    source = "\n".join(path.read_text() for path in SOURCE.glob("*.py"))
    for symbol in (
        "LegacyOutputRecord",
        "GraphPatchStatusPayload",
        "RequirementAuthorityResolutionPayload",
        "_legacy_output_record_payload",
        "_generic_output_record_payload",
        "_legacy_requirement_evidence_blockers",
        "_DictCompatibleProjection",
    ):
        assert symbol not in source
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_w5_compatibility_removal.py -q`

Expected: failures because unknown fields are quarantined and compatibility symbols remain.

- [ ] **Step 3: Replace compatibility bases with one strict base**

Use this base in `models.py`:

```python
class StrictEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
```

Change every W5 event payload class to inherit it directly or through a semantic base that adds fields only. Set `TypedRecordBase.model_config` to `ConfigDict(extra="forbid", populate_by_name=True)` so root event models cannot admit unknown record keys. Delete custom `model_dump` methods that merge `extra`, all empty-extra factories, and historical `mode="before"` validators. Retain only validators that enforce a current cross-field invariant. Use `StrictInt`, `StrictFloat`, `StrictBool`, or `Field(strict=True, ...)` on event scalars that must not coerce; do not use global strict mode because canonical JSON enum values arrive as strings.

- [ ] **Step 4: Canonicalize current producers before deleting normalizers**

Update compiler and command producers to emit one shape:

- Keep nested `authority` as the canonical `NodeCreatedPayload.authority` shape and make reducers read it directly.
- Emit direct canonical membership fields for decision and node-state events; do not read them from alternate nesting.
- Emit `verification_report`, `accepted_file_state`, and other current port names consistently; migrate current selectors before deleting their aliases.
- Preserve explicit callback `payload=None` using `model_fields_set`, not `payload.extra`.
- Add real `task_region_id` and `kind` fields where `LeaseGrantedPayload` currently recovers them from `extra`.

- [ ] **Step 5: Delete generic record and mapping facades**

Canonicalize sparse output fixtures into complete typed records, remove `LegacyOutputRecord` from `OutputRecordPayload`, and make `_parse_output_record_payload` dispatch only through the exact record discriminator. Convert `.get()` and `[...]` calls on `EdgeProjection`, `InputBindingProjection`, and `LeaseProjection` to attributes, then delete TYPE_CHECKING dict subclasses, `_DictCompatibleProjection`, `.get`, and `__getitem__` implementations.

- [ ] **Step 6: Rewrite compatibility tests as canonical contract tests**

For each existing W5 payload test file:

- Delete tests asserting unknown keys move to `extra`, malformed rows are filtered, or replay-only aliases parse.
- Keep producer validation and projection behavior tests.
- Add one unknown-field and one wrong-type `ValidationError` assertion per family.
- Assert `model_dump(mode="json")` equals the exact current producer payload.

- [ ] **Step 7: Run the focused cleanup gate**

Run:

```bash
uv run pytest tests/unit/test_w5_compatibility_removal.py \
  tests/unit/test_lease_event_payloads.py \
  tests/unit/test_lifecycle_event_payloads.py \
  tests/unit/test_decision_event_payloads.py \
  tests/unit/test_cleanup_event_payloads.py \
  tests/unit/test_planner_session_event_payloads.py \
  tests/unit/test_patch_event_payloads.py \
  tests/unit/test_requirement_evidence_event_payloads.py \
  tests/unit/test_node_created_event_payloads.py \
  tests/unit/test_node_lifecycle_event_payloads.py \
  tests/unit/test_fixture_corpus.py -q
```

Expected: all pass; no test asserts historical quarantine or alias behavior.

- [ ] **Step 8: Commit compatibility removal**

```bash
git add src/orchestrator/graph tests/unit/test_*event_payloads.py \
  tests/unit/test_w5_compatibility_removal.py tests/fixtures/graph
git commit -m "Remove obsolete W5 payload compatibility"
```

### Task 4: Type Remaining Record And Gatekeeper Events

**Files:**
- Create: `tests/unit/test_output_record_event_payloads.py`
- Create: `tests/unit/test_record_routing_event_payloads.py`
- Create: `tests/unit/test_file_state_gatekeeper_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/event_registry.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `OutputRecordAcceptedPayload`, `VerificationOutcomePayload`, `InputBoundPayload`, `RevisionCreatedPayload`, `FileStateAcceptedPayload`, `FileStateRejectedPayload`, `GatekeeperVerdictRow`, `GatekeeperVerdictRecordedPayload`, and `GatekeeperCostRecordedPayload`.
- Consumes: strict current record unions and canonical event registry from Tasks 2-3.

- [ ] **Step 1: Write strict RED tests for the three families**

Tests must assert:

```python
def test_output_record_event_uses_a_typed_record() -> None:
    payload = OutputRecordAcceptedPayload.model_validate(CANONICAL_RECORD)
    assert payload.root.record_id == CANONICAL_RECORD["record_id"]


def test_input_bound_requires_canonical_routing_fields() -> None:
    with pytest.raises(ValidationError):
        InputBoundPayload.model_validate({"input": "candidate", "record_ids": ["r-1"]})


def test_gatekeeper_cost_rejects_unknown_and_negative_values() -> None:
    with pytest.raises(ValidationError):
        GatekeeperCostRecordedPayload.model_validate(
            {"execution_id": "e-1", "input_tokens": -1, "legacy_cost": 1}
        )
```

In the real test file, define `CANONICAL_RECORD` as a complete current `CandidateRecord` dump and assert all record union variants already emitted by `_commands.py` validate.

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_record_routing_event_payloads.py \
  tests/unit/test_file_state_gatekeeper_event_payloads.py -q
```

Expected: collection fails on missing exports.

- [ ] **Step 3: Implement strict envelope models**

Use root models for events whose wire payload is already a complete typed record, preserving the canonical flat JSON event shape:

```python
class OutputRecordAcceptedPayload(RootModel[OutputRecordPayload]):
    pass


class VerificationOutcomePayload(StrictEventPayload):
    node_id: str
    verifier_node_id: str
    candidate_id: str
    task_region_id: str | None = None
    record_id: str
    outcome: Literal["passed", "failed"]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    value: VerificationReportValue


class InputBoundPayload(StrictEventPayload):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str] = Field(min_length=1)
    bound_at_position: int = Field(ge=0)
    binding_policy: str | None = None
    supersedes_record_id: str | None = None
    record_bound_positions: dict[str, int] = Field(default_factory=dict)


class RevisionCreatedPayload(StrictEventPayload):
    node: NodeModel
    worker_node: NodeModel
    verifier_node: NodeModel


class CanonicalFileStateRecord(FileStateRecord):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FileStateAcceptedPayload(RootModel[CanonicalFileStateRecord]):
    pass


class FileStateRejectedPayload(CanonicalFileStateRecord):
    reason: str | None = None


class GatekeeperVerdictRow(StrictEventPayload):
    path: str
    classification: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    model_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_ms: int = Field(default=0, ge=0)


class GatekeeperVerdictRecordedPayload(StrictEventPayload):
    file_state_record_id: str
    execution_id: str
    producer_node_id: str
    verdicts: list[GatekeeperVerdictRow] = Field(min_length=1)
    resolved_count: int = Field(ge=0)


class GatekeeperCostRecordedPayload(StrictEventPayload):
    execution_id: str
    file_state_record_id: str
    consult_id: str
    model_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    item_count: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_ms: int = Field(default=0, ge=0)
```

Change current producers to supply every required identifier above. Keep `classification` as a string because the current classifier registry is extensible; reject missing classifications rather than adding an alias/default.

- [ ] **Step 4: Route producers and reducers through models**

Change producer flow to:

```python
typed = EVENT_PAYLOAD_MODELS[event_type].model_validate(payload)
return make_event(event_type, typed.model_dump(mode="json"))
```

Change reducer branches to parse once and pass models to helpers. Delete `_payload_string_list`, `_input_bound_payload_for_record` aliases, scalar-value record fallbacks, and any event-family helper whose only purpose was defensive dictionary extraction.

- [ ] **Step 5: Run focused tests and corpus**

Run:

```bash
uv run pytest tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_record_routing_event_payloads.py \
  tests/unit/test_file_state_gatekeeper_event_payloads.py \
  tests/unit/test_graph_models.py \
  tests/unit/test_graph_projections.py \
  tests/unit/test_fixture_corpus.py -q
```

Expected: all pass; gatekeeper cost summary assertions preserve every token/cache/count/cost/time field.

- [ ] **Step 6: Commit the remaining event models**

```bash
git add src/orchestrator/graph tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_record_routing_event_payloads.py \
  tests/unit/test_file_state_gatekeeper_event_payloads.py
git commit -m "Type remaining canonical graph events"
```

### Task 5: Define Durable Artifact Identity And Generate Retention Allowlists

**Files:**
- Create: `src/orchestrator/graph/payload_registry.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/event_registry.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `tests/unit/test_graph_models.py`
- Modify: `tests/unit/test_graph_payload_field_allowlists.py`

**Interfaces:**
- Produces: `GRAPH_PROJECTION_PAYLOAD_FIELDS`, `LIGHT_GRAPH_PAYLOAD_FIELDS`, `SUMMARY_REBUILD_PAYLOAD_FIELDS`, and `NODE_DETAIL_PAYLOAD_FIELDS` generated from immutable specs.
- Produces: strict `StoredArtifactRef` durable blob identity for the separate W5.5 producer/storage cutover.
- Consumes: complete `EVENT_PAYLOAD_MODELS` from Tasks 2-4.

- [ ] **Step 1: Add `StoredArtifactRef` RED tests**

Add to `tests/unit/test_graph_models.py`:

```python
def test_stored_artifact_ref_is_strict_and_portable() -> None:
    ref = StoredArtifactRef.model_validate(
        {
            "artifact_id": "check-output-1",
            "content_hash": f"sha256:{'a' * 64}",
            "size_bytes": 1_048_576,
            "media_type": "text/plain",
            "encoding": "utf-8",
            "storage_uri": f"artifact://sha256/{'a' * 64}",
        }
    )
    assert ref.size_bytes == 1_048_576
    assert ref.storage_uri.startswith("artifact://sha256/")


@pytest.mark.parametrize(
    "update",
    [
        {"content_hash": "sha256:../escape"},
        {"content_hash": "md5:" + "a" * 32},
        {"size_bytes": -1},
        {"size_bytes": "12"},
        {"storage_uri": "file:///tmp/output"},
        {"unknown": True},
    ],
)
def test_stored_artifact_ref_rejects_noncanonical_identity(update: dict[str, Any]) -> None:
    payload = {
        "artifact_id": "check-output-1",
        "content_hash": f"sha256:{'a' * 64}",
        "size_bytes": 12,
        "media_type": "text/plain",
        "encoding": "utf-8",
        "storage_uri": f"artifact://sha256/{'a' * 64}",
    }
    payload.update(update)
    with pytest.raises(ValidationError):
        StoredArtifactRef.model_validate(payload)
```

Run: `uv run pytest tests/unit/test_graph_models.py -k stored_artifact_ref -q`

Expected: import/name failure for `StoredArtifactRef`.

- [ ] **Step 2: Implement and export durable artifact identity**

Add beside other strict nested record values:

```python
class StoredArtifactRef(StrictNestedModel):
    artifact_id: str
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(ge=0)
    media_type: str
    encoding: str | None = None
    storage_uri: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
```

Export it through `orchestrator.graph`. Do not add it to `CheckResultValue`,
change `stdout`/`stderr`, write artifact files, add hydration, or alter SQL
serialization. Those changes must land atomically under
`docs/superpowers/plans/2026-07-15-w5-artifact-output.md`.

- [ ] **Step 3: Add exact-equality retention RED tests**

Add:

```python
from orchestrator.graph import (
    GRAPH_PROJECTION_PAYLOAD_FIELDS,
    LIGHT_GRAPH_PAYLOAD_FIELDS,
    NODE_DETAIL_PAYLOAD_FIELDS,
    SUMMARY_REBUILD_PAYLOAD_FIELDS,
    generated_payload_fields,
)


def test_all_payload_allowlists_are_generated_exactly() -> None:
    assert GRAPH_PROJECTION_PAYLOAD_FIELDS == generated_payload_fields("projection")
    assert LIGHT_GRAPH_PAYLOAD_FIELDS == generated_payload_fields("light")
    assert SUMMARY_REBUILD_PAYLOAD_FIELDS == generated_payload_fields("summary")
    assert NODE_DETAIL_PAYLOAD_FIELDS == generated_payload_fields("node_detail")


def test_generated_fields_are_sorted_unique_and_strict() -> None:
    for mode in ("projection", "light", "summary", "node_detail"):
        fields = generated_payload_fields(mode)
        assert fields == tuple(sorted(set(fields)))
        assert "extra" not in fields
```

- [ ] **Step 4: Run retention RED**

Run: `uv run pytest tests/unit/test_graph_payload_field_allowlists.py -q`

Expected: import failure for `generated_payload_fields`.

- [ ] **Step 5: Implement declarative retention**

Create:

```python
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

RetentionMode = Literal["projection", "light", "summary", "node_detail"]


@dataclass(frozen=True)
class EventPayloadSpec:
    model: type[BaseModel]
    projection: frozenset[str] = frozenset()
    light: frozenset[str] = frozenset()
    summary: frozenset[str] = frozenset()
    node_detail: frozenset[str] = frozenset()


def generated_payload_fields(mode: RetentionMode) -> tuple[str, ...]:
    fields: set[str] = set()
    for spec in EVENT_PAYLOAD_SPECS.values():
        fields.update(getattr(spec, mode))
    return tuple(sorted(fields))
```

Build `EVENT_PAYLOAD_SPECS` for every canonical event model. Each retained set must be explicit and a subset of the model's serialized fields, except named envelope columns extracted outside payload JSON. Preserve SQLite JSON boolean conversion and nested `value` extraction because they support current canonical payloads.

Generated mode-wide tuples deliberately preserve the current complete `value`
behavior. Record this as a W5.5 operational limitation; do not introduce
event-aware SQL or silently remove large values in this task.

- [ ] **Step 6: Replace handwritten tuples and keep the AST guard**

Import generated constants into `projections.py` and `graph_runtime/store.py`. Keep the AST test as an independent reducer-read guard, but delete stale `_EXCLUDED_KEYS` entries made unreachable by typed attribute access.

- [ ] **Step 7: Run retention and read-model tests**

```bash
uv run pytest tests/unit/test_graph_payload_field_allowlists.py \
  tests/unit/test_graph_models.py \
  tests/unit/test_fixture_corpus.py \
  tests/integration/test_graph_read_models.py \
  tests/integration/test_graph_event_store.py \
  tests/integration/test_graph_node_detail_read_models.py -q
```

Expected: all pass and compact/full projection results are equal.

- [ ] **Step 8: Commit artifact identity and generated retention**

```bash
git add src/orchestrator/graph/payload_registry.py src/orchestrator/graph/event_registry.py \
  src/orchestrator/graph/models.py \
  src/orchestrator/graph/projections.py src/orchestrator/graph/__init__.py \
  src/orchestrator/graph_runtime/store.py tests/unit/test_graph_models.py \
  tests/unit/test_graph_payload_field_allowlists.py
git commit -m "Define artifact identity and generate payload retention"
```

### Task 6: Batch 1 Verification Gate

**Files:**
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces: one independently verified Batch 1 ledger entry with subsections for event ownership, compatibility deletion, records, file-state/gatekeeper, and allowlists.

- [ ] **Step 1: Run the focused aggregate**

```bash
uv run pytest tests/unit/test_graph_event_registry.py \
  tests/unit/test_w5_compatibility_removal.py \
  tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_record_routing_event_payloads.py \
  tests/unit/test_file_state_gatekeeper_event_payloads.py \
  tests/unit/test_graph_payload_field_allowlists.py \
  tests/unit/test_fixture_corpus.py -q -n auto --dist worksteal
```

Expected: all pass.

- [ ] **Step 2: Dispatch a fresh verifier for expensive gates**

The fresh verifier runs:

```bash
uv run pytest tests/ -k graph -q -n auto --dist worksteal
uv run ruff check .
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime tests/unit
git diff --check
```

Expected: all exit 0. The verifier must also search for removed event names, `LegacyOutputRecord`, top-level payload `extra`, historical-only `mode="before"` validators, and dict-compatible projection methods.

- [ ] **Step 3: Record evidence and commit**

Append exact commands, counts, timings, verifier verdict, deleted symbols, and the retained justification for `lease_suspended`.

```bash
git add docs/dynamic-graph/w5-progress-ledger.md
git commit -m "Verify canonical W5 event batch"
```

---

## Batch 2: Strict Commands And Grade Rows

### Task 7: Add Explicit Command Context And The 23-Model Registry

**Files:**
- Create: `src/orchestrator/graph/command_models.py`
- Create: `tests/unit/test_lifecycle_command_payloads.py`
- Create: `tests/unit/test_scheduling_command_payloads.py`
- Create: `tests/unit/test_callback_patch_command_payloads.py`
- Create: `tests/unit/test_decision_record_command_payloads.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/commands/lifecycle.py`
- Modify: `src/orchestrator/graph/commands/schedule.py`
- Modify: `src/orchestrator/graph/commands/callbacks.py`
- Modify: `src/orchestrator/graph/commands/patches.py`
- Modify: `src/orchestrator/graph/commands/records.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Modify: `src/orchestrator/graph_runtime/dispatch.py`
- Modify: `src/orchestrator/workflow/graph_driver.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `GraphCommandContext`, `PatchCommandContext`, `StrictCommandPayload`, `CommandSpec`, and exact `COMMAND_SPECS` coverage.
- Removes: payload-injected `run_id`, `_current_graph_position`, actor/proposer provenance, ignored patch runtime fields, handler scalar coercion, and duplicate alias normalization.

- [ ] **Step 1: Write exact registry and strictness RED tests**

Use this exact set in `test_lifecycle_command_payloads.py`:

```python
EXPECTED_COMMANDS = {
    "accept_run", "start", "pause", "resume", "cancel", "complete", "fail",
    "record_heartbeat", "seed_compiled_events", "schedule_tick", "reconcile",
    "submit_callback", "submit_patch", "acknowledge_start", "agent_died",
    "raise_appeal", "record_decision", "record_gatekeeper_verdicts",
    "record_requirement_revision", "record_support_evidence", "evaluate_join",
    "evaluate_final_gate", "record_cleanup_applied",
}


def test_command_registry_has_exactly_23_strict_models() -> None:
    assert set(COMMAND_SPECS) == EXPECTED_COMMANDS
    assert len(COMMAND_SPECS) == 23
    assert all(spec.payload_model.model_config["extra"] == "forbid" for spec in COMMAND_SPECS.values())
```

Add wrong-type tests proving `True` fails integer fields, strings fail integer fields, unknown keys fail, and missing required IDs fail before handlers run.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/unit/test_lifecycle_command_payloads.py \
  tests/unit/test_scheduling_command_payloads.py \
  tests/unit/test_callback_patch_command_payloads.py \
  tests/unit/test_decision_record_command_payloads.py -q
```

Expected: collection fails on missing `COMMAND_SPECS` and command models.

- [ ] **Step 3: Implement strict context and registry primitives**

Create:

```python
class StrictCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GraphCommandContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str
    current_graph_position: int = Field(ge=-1)
    actor: Actor | None = None


class PatchCommandContext(GraphCommandContext):
    proposed_by_node_id: str
    actor_role: str


@dataclass(frozen=True)
class CommandSpec:
    payload_model: type[StrictCommandPayload]
    handler: ApplyCommandHandler
```

Change `apply_command` to accept context separately, resolve `CommandSpec`, validate the payload once, and pass the model to its handler. Unknown command names still emit deterministic `command_rejected`; schema errors at internal command ingress become deterministic `command_rejected` with Pydantic error details, while FastAPI rejects before dispatch.

- [ ] **Step 4: Implement the lifecycle and scheduling models**

Create models with these exact canonical fields:

```python
class TriggerCommand(StrictCommandPayload):
    trigger: str | None = None

class AcceptRunCommand(TriggerCommand): pass
class StartCommand(TriggerCommand): pass
class PauseCommand(TriggerCommand): pass
class ResumeCommand(TriggerCommand): pass
class CancelCommand(TriggerCommand): pass

class CompleteCommand(TriggerCommand):
    completion_decision_record_id: str | None = None
    node_id: str | None = None

class FailCommand(StrictCommandPayload):
    reason: str = "unrecoverable_controller_error"

class RecordHeartbeatCommand(StrictCommandPayload):
    lease_id: str
    node_id: str | None = None
    generation: int | None = Field(default=None, ge=0)
    ttl_seconds: int = Field(default=300, gt=0)

class SeedCompiledEventsCommand(StrictCommandPayload):
    events: list[EventEnvelope] = Field(min_length=1)

class ScheduleTickCommand(StrictCommandPayload):
    base_snapshot_id: str | None = None
    max_grants: int = Field(default=10, ge=0)
    lease_seconds: int = Field(default=300, gt=0)
    lease_ids: dict[str, str] = Field(default_factory=dict)
    priorities: dict[str, int] = Field(default_factory=dict)
    region_order: dict[str, int] = Field(default_factory=dict)

class ReconcileCommand(StrictCommandPayload): pass
```

Move failed-resume actor authorization to `GraphCommandContext.actor`. Stop sending ignored cancel `reason` from `graph_driver.py`.

- [ ] **Step 5: Implement callback, patch, and runtime models**

Use required identity fields and current defaults:

```python
class SubmitCallbackCommand(StrictCommandPayload):
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    base_snapshot_id: str
    observed_graph_position: int = Field(ge=0)
    idempotency_key: str
    payload_hash: str | None = None
    payload: dict[str, Any] | None = None
    is_mutating: bool = True
    complete_node: bool = True
    new_state: Literal["completed", "failed"] = "completed"

class SubmitPatchCommand(StrictCommandPayload):
    patch_id: str
    base_graph_position: int = Field(ge=-1)
    ops: list[dict[str, Any]] = Field(default_factory=list)
    macro_invocations: list[MacroInvocation] = Field(default_factory=list)
    rationale_record_id: str | None = None
    budget_gate_node_id: str | None = None
    carryover_record_id: str | None = None

class AcknowledgeStartCommand(StrictCommandPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    execution_id: str
    prompt_summary: dict[str, Any] | None = None

class AgentDiedCommand(StrictCommandPayload):
    lease_id: str
    execution_id: str | None = None
    reason: str = "runtime_process_died"
    max_attempts: int = Field(default=0, ge=0)
    retry_backoff_seconds: int = Field(default=0, ge=0)
```

Add an `after` validator requiring callback `payload` or `payload_hash`. Canonicalize current callers to `carryover_record_id`; delete `carryover_summary`, macro `name`/`tool`, and arbitrary scalar callback payload conversion. Move patch actor/proposer fields into `PatchCommandContext` and stop injecting six unread runtime identity fields.

- [ ] **Step 6: Implement decision and record models**

Implement strict models for the nine remaining names. Use canonical decision values only:

```python
DECISION_VALUES = {
    "approval": frozenset({"approved", "rejected", "deferred"}),
    "authority": frozenset({"granted", "denied", "deferred"}),
    "oversight": frozenset({"accepted", "rejected", "invalid_test_accepted"}),
}

class RecordDecisionCommand(StrictCommandPayload):
    decision_type: Literal["approval", "authority", "oversight"]
    node_id: str
    decision: str
    decider: Actor | str
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "RecordDecisionCommand":
        if self.decision not in DECISION_VALUES[self.decision_type]:
            options = ", ".join(sorted(DECISION_VALUES[self.decision_type]))
            raise ValueError(f"decision for {self.decision_type} must be one of: {options}")
        return self
```

Add the remaining canonical models exactly as follows:

```python
class RaiseAppealCommand(StrictCommandPayload):
    node_id: str
    appeal_type: Literal["invalid_test"]
    appeal_node_id: str | None = None
    oversight_node_id: str | None = None
    candidate_id: str | None = None
    task_region_id: str | None = None
    lease_id: str | None = None


GatekeeperClassification = Literal[
    "tool_cache", "build_output", "test_artifact", "secret",
    "external_artifact", "unknown_ignored",
]


class GatekeeperVerdictCommandRow(StrictCommandPayload):
    path: str
    classification: GatekeeperClassification
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    model_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_ms: int = Field(default=0, ge=0)


class GatekeeperCostCommandRow(StrictCommandPayload):
    model_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    wall_time_ms: int | None = Field(default=None, ge=0)


class RecordGatekeeperVerdictsCommand(StrictCommandPayload):
    file_state_record_id: str
    execution_id: str
    verdicts: list[GatekeeperVerdictCommandRow] = Field(min_length=1)
    consult_id: str = "gatekeeper-consult"
    model_id: str | None = None
    cost: GatekeeperCostCommandRow | None = None


class RecordRequirementRevisionCommand(StrictCommandPayload):
    requirement_id: str
    version_id: str
    classification: str | None = None
    requires_authority: bool | None = None
    validation_strengthening: bool | None = None
    active: bool = True
    previous_version_id: str | None = None
    revision_index: int | None = Field(default=None, ge=0)
    authority_required_reason: str | None = None
    revision_id: str | None = None
    proposal_id: str | None = None
    patch_id: str | None = None
    node_id: str | None = None
    requirement: dict[str, Any] | None = None


class RecordSupportEvidenceCommand(StrictCommandPayload):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str | None = None
    status: str | None = None
    stale_reason: str | None = None
    confidence: str | None = None


class LeaseScopedEvaluationCommand(StrictCommandPayload):
    node_id: str
    record_id: str | None = None
    lease_id: str | None = None
    lease_generation: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_lease_pair(self) -> "LeaseScopedEvaluationCommand":
        if (self.lease_id is None) != (self.lease_generation is None):
            raise ValueError("lease_id and lease_generation must be provided together")
        return self


class EvaluateJoinCommand(LeaseScopedEvaluationCommand):
    pass


class EvaluateFinalGateCommand(LeaseScopedEvaluationCommand):
    pass


class StrictFileStateRecord(FileStateRecord):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecordCleanupAppliedCommand(StrictCommandPayload):
    cleanup_id: str
    superseding_file_state_record: StrictFileStateRecord
    deleted_snapshot_ref: bool = False
    reason: str | None = None
```

Remove `defer`/`grant`/`deny`, boolean `approved`, `outcome`/`verdict`, requirement/support ID synonyms, and scalar coercions from handlers and tests.

- [ ] **Step 7: Update all current callers and focused tests**

Construct `GraphCommandContext` in controller/API/driver entry points. Remove `run_id` and `_current_graph_position` before strict payload validation. Update direct command tests to pass context separately. Keep projection-dependent command rejection tests; move malformed schema tests to the Pydantic boundary.

- [ ] **Step 8: Run command-focused tests**

```bash
uv run pytest tests/unit/test_lifecycle_command_payloads.py \
  tests/unit/test_scheduling_command_payloads.py \
  tests/unit/test_callback_patch_command_payloads.py \
  tests/unit/test_decision_record_command_payloads.py \
  tests/unit/test_graph_commands.py -q
```

Expected: all pass; exact registry count is 23 and no handler accepts a raw payload dictionary.

- [ ] **Step 9: Commit command infrastructure**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime/controller.py \
  src/orchestrator/graph_runtime/dispatch.py src/orchestrator/workflow/graph_driver.py \
  tests/unit/test_*command_payloads.py tests/unit/test_graph_commands.py
git commit -m "Add strict graph command payloads"
```

### Task 8: Reuse Command Schemas At FastAPI Boundaries

**Files:**
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `tests/integration/test_graph_api.py`
- Modify: `tests/integration/test_graph_decisions_api.py`

**Interfaces:**
- Consumes: `SubmitPatchCommand`, `RecordDecisionCommand`, and command context from Task 7.
- Produces: one validation implementation shared by HTTP and domain dispatch.

- [ ] **Step 1: Add API RED tests for removed aliases and strict fields**

Add parametrized requests proving HTTP 422 for:

```python
INVALID_DECISIONS = [
    ("approval", "defer"),
    ("authority", "grant"),
    ("authority", "deny"),
]

INVALID_PATCHES = [
    {"patch_id": "p", "base_graph_position": "0", "ops": []},
    {"patch_id": "p", "base_graph_position": 0, "carryover_summary": "r"},
    {"patch_id": "p", "base_graph_position": 0, "unknown": True},
]
```

Keep valid requests for canonical decisions and canonical patch fields.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_graph_api.py \
  tests/integration/test_graph_decisions_api.py -q
```

Expected: alias cases currently succeed or fail with a noncanonical response.

- [ ] **Step 3: Compose API request models from command models**

Replace duplicate validators with inheritance or field composition:

```python
class RecordGraphDecisionRequest(RecordDecisionCommand):
    pass


class SubmitGraphPatchRequest(SubmitPatchCommand):
    pass
```

If API response-model configuration requires `ApiModel`, extract shared strict field mixins used by both request and command models; do not copy validators. Build actor/proposer context from authentication/server state, not request payload fields.

- [ ] **Step 4: Run API and command tests**

```bash
uv run pytest tests/integration/test_graph_api.py \
  tests/integration/test_graph_decisions_api.py \
  tests/unit/test_callback_patch_command_payloads.py \
  tests/unit/test_decision_record_command_payloads.py -q
```

Expected: canonical requests succeed and removed aliases return 422 listing valid values.

- [ ] **Step 5: Commit API schema reuse**

```bash
git add src/orchestrator/api/routers/graph.py \
  tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py
git commit -m "Reuse graph command schemas in API"
```

### Task 9: Add Strict Grade Rows

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `tests/unit/test_graph_models.py`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`

**Interfaces:**
- Produces: `GradeRow` and `VerificationReportValue.grades: list[GradeRow]`.

- [ ] **Step 1: Write GradeRow RED tests**

```python
def test_grade_row_is_strict_and_complete() -> None:
    row = GradeRow.model_validate(
        {"requirement_id": "R1", "grade": "pass", "reason": "covered"}
    )
    assert row.grade == "pass"
    with pytest.raises(ValidationError):
        GradeRow.model_validate({"requirement_id": "R1"})
    with pytest.raises(ValidationError):
        GradeRow.model_validate(
            {"requirement_id": "R1", "grade": "pass", "legacy": True}
        )
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_graph_models.py -k grade_row -q`

Expected: import or name failure for `GradeRow`.

- [ ] **Step 3: Implement strict GradeRow**

```python
class GradeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    grade: str
    reason: str | None = None


class VerificationReportValue(GraphBaseModel):
    outcome: str
    grades: list[GradeRow] = Field(default_factory=list)
```

Remove the inventory statement that grades are intentionally raw. Keep the grade string open rather than introducing a historical/future alias table.

- [ ] **Step 4: Run model, command, and corpus tests**

```bash
uv run pytest tests/unit/test_graph_models.py \
  tests/unit/test_graph_commands.py \
  tests/unit/test_fixture_corpus.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit GradeRow**

```bash
git add src/orchestrator/graph/models.py src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_models.py docs/dynamic-graph/graph-projection-map-inventory.md
git commit -m "Add strict verification grade rows"
```

### Task 10: Batch 2 Verification Gate

**Files:**
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Consumes: Tasks 7-9.
- Produces: independently verified command/API/GradeRow evidence.

- [ ] **Step 1: Run focused aggregate**

```bash
uv run pytest tests/unit/test_lifecycle_command_payloads.py \
  tests/unit/test_scheduling_command_payloads.py \
  tests/unit/test_callback_patch_command_payloads.py \
  tests/unit/test_decision_record_command_payloads.py \
  tests/unit/test_graph_commands.py tests/unit/test_graph_models.py \
  tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py \
  -q -n auto --dist worksteal
```

Expected: all pass.

- [ ] **Step 2: Dispatch fresh verifier**

```bash
uv run pytest tests/ -k graph -q -n auto --dist worksteal
uv run ruff check .
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime \
  src/orchestrator/api src/orchestrator/workflow tests/unit tests/integration
git diff --check
```

Expected: all exit 0. The verifier confirms exactly 23 specs, no raw dictionary handler payloads, no duplicate API/domain validators, no scalar coercion shims, and no payload-injected command context.

- [ ] **Step 3: Record evidence and commit**

```bash
git add docs/dynamic-graph/w5-progress-ledger.md
git commit -m "Verify strict W5 command batch"
```

---

## Batch 3: Closeout

### Task 11: Final Verification, Metrics, And Spec Closure

**Files:**
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`
- Modify: `docs/dynamic-graph/w5-event-payload-inventory.md`
- Move: `docs/dynamic-graph/w5-typed-payloads-spec.md` to `docs/dynamic-graph/complete/w5-typed-payloads-spec.md`

**Interfaces:**
- Produces: closed W5 queue, final metrics, complete ledger evidence, and no stale compatibility mandate.

- [ ] **Step 1: Audit every completion criterion**

Confirm the ledger has named evidence for:

```text
canonical event ownership
compatibility layer removal
record envelopes
file-state/gatekeeper envelopes
four generated allowlists
23 command payloads
API schema reuse
GradeRow
Batch 1 and Batch 2 fresh verification
```

Run static searches and record every remaining match with a current-domain justification:

```bash
rg -n 'mode="before"|mode='"'"'before'"'"'|LegacyOutputRecord|_DictCompatibleProjection|payload\.extra' src/orchestrator/graph
rg -n 'environment_failure_accepted|check_result_classified|proposal_opened|requirement_amended|support_edge_recorded|node_suspect_resolved|node_suspect_cleared' src tests
```

Expected: no obsolete compatibility matches. Any `mode="before"` outside W5 must be listed as a current input canonicalizer rather than silently accepted.

- [ ] **Step 2: Run final verification with one fresh verifier**

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime \
  src/orchestrator/api src/orchestrator/workflow tests/unit tests/integration
git diff --check
```

Expected: all pass. If Batch 0 proved the full suite order-sensitive under xdist, use the recorded serial command instead.

- [ ] **Step 3: Compute required and diagnostic metrics**

```bash
rg -o 'isinstance\(' src/orchestrator/graph/_commands.py \
  src/orchestrator/graph/projections.py | wc -l
rg -o 'dict\[str, Any\]' src/orchestrator/graph/projections.py | wc -l
rg -o 'event\.payload\.get\(' src/orchestrator/graph/projections.py | wc -l
rg -o 'payload\.get\(' src/orchestrator/graph/projections.py | wc -l
rg -o 'mode="before"|mode='"'"'before'"'"'' src/orchestrator/graph | wc -l
```

Record final values and deltas from 603 `isinstance(` and 174 `dict[str, Any]`. Record both payload-get counts and the before-validator count as diagnostics. List the names of deleted compatibility models/helpers and the explicit current justification for any surviving before validator.

- [ ] **Step 4: Refresh and close documentation**

Update the event and projection inventories to canonical event/model names, strictness, generated retention, and deleted aliases. Mark every W5 requirement complete and move the spec into `complete/`.

- [ ] **Step 5: Commit closeout**

```bash
git add docs/dynamic-graph/w5-progress-ledger.md \
  docs/dynamic-graph/graph-projection-map-inventory.md \
  docs/dynamic-graph/w5-event-payload-inventory.md \
  docs/dynamic-graph/complete/w5-typed-payloads-spec.md
git rm docs/dynamic-graph/w5-typed-payloads-spec.md
git commit -m "Close strict W5 payload migration"
```

- [ ] **Step 6: Confirm clean handoff**

```bash
git status --short
git log --oneline --decorate -20
```

Expected: clean worktree and a reviewable sequence ending with `Close strict W5 payload migration`.
