# Immutable Graph Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat mutable `GraphProjection` with a deeply immutable, entity-grouped Pydantic projection through an automation-first migration that edits broad consumers once.

**Architecture:** First freeze an executable inventory and public-behavior oracle, then codemod all non-core consumers onto a permanent pure query boundary. Build `FrozenMap`, grouped models, strict checkpoint codec, and integrity validation behind green tests before one atomic core cutover replaces clone-before-mutate reduction. Old projection checkpoints are disposable and rebuild from canonical events.

**Tech Stack:** Python 3.12+, Pydantic v2, `immutables>=0.21,<1`, LibCST, Hypothesis, pytest, SQLAlchemy/SQLite, Ruff, Pyright, pre-commit

## Global Constraints

- Execute this plan in an isolated worktree created with the `using-git-worktrees` skill.
- Use `uv run` for every Python command and `uv add` for dependencies; never use bare `python` or `pip`.
- Use test-driven development: add a failing test, run it and observe the expected failure, implement, then rerun.
- Do not use mocks, monkeypatching, `patch`, or `MagicMock`; use real Pydantic values, SQLite, files, and git repositories.
- Do not edit broad generated call sites by hand. Fix the LibCST rule and regenerate from the recorded baseline.
- Do not dual-write old and new production projection representations.
- Do not preserve old projection checkpoint formats; schema mismatch or checkpoint validation failure causes event replay.
- Keep event and transport models in `src/orchestrator/graph/models.py`; reducers convert them to immutable projection-specific values.
- All models reachable from `GraphProjection` use `ConfigDict(frozen=True, extra="forbid")` and contain no mutable child.
- Full accepted record payloads have one owner: `RecordStore.by_id`. Secondary indexes contain IDs only.
- Only the five core files named in the design may inspect grouped storage.
- External modules import projection APIs from `orchestrator.graph`, never graph submodules.
- Run full repository gates before declaring the cutover complete; never bypass pre-commit.
- The approved design is `docs/superpowers/specs/2026-07-26-immutable-graph-projection-design.md`.

---

## File Structure

### New Production Files

- `src/orchestrator/graph/projection_collections.py`: `FrozenMap`, immutable JSON validation, freeze/thaw, and persistent update primitives.
- `src/orchestrator/graph/projection_models.py`: passive frozen grouped projection models and projection-specific record union.
- `src/orchestrator/graph/projection_queries.py`: permanent pure read API over projection storage.
- `src/orchestrator/graph/projection_codec.py`: strict checkpoint conversion, codec errors, and referential integrity.

### New Migration And Guard Files

- `scripts/graph_projection_inventory.py`: bounded LibCST inventory and baseline report generator.
- `scripts/check_graph_projection_boundaries.py`: exact storage-access and deep-immutability guard.
- `scripts/generate_graph_projection_goldens.py`: deterministic replay and public-view oracle generator.
- `scripts/benchmark_graph_projection.py`: current/target replay, memory, checkpoint, and scaling gate runner.
- `scripts/codemods/graph_projection_manifest.yaml`: strict 73-field ownership and occurrence transformation manifest.
- `scripts/codemods/migrate_graph_projection_queries.py`: atomic, fail-closed, idempotent query/fixture codemod.

### New Test Files

- `tests/unit/test_graph_projection_inventory.py`
- `tests/unit/test_graph_projection_boundaries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `tests/unit/test_graph_projection_goldens.py`
- `tests/unit/test_graph_projection_collections.py`
- `tests/unit/test_graph_projection_models.py`
- `tests/unit/test_graph_projected_records.py`
- `tests/unit/test_graph_projection_codec.py`
- `tests/unit/test_graph_projection_integrity.py`
- `tests/unit/test_graph_projection_queries.py`
- `tests/unit/test_graph_projection_duplicate_ids.py`
- `tests/unit/test_graph_projection_immutability.py`
- `tests/unit/test_graph_projection_replay_equivalence.py`
- `tests/unit/test_benchmark_graph_projection.py`
- `tests/integration/test_graph_projection_checkpoint_recovery.py`
- `tests/integration/test_graph_projection_public_parity.py`

### Generated Fixtures

- `tests/fixtures/graph_projection_migration/access_inventory.json`
- `tests/fixtures/graph_projection_migration/query_migration_report.json`
- `tests/fixtures/graph_projection_migration/public_view_goldens.json`
- `tests/fixtures/graph_projection_migration/replay_goldens.json`
- `tests/fixtures/graph_projection_performance/scenarios.json`
- `tests/fixtures/graph_projection_performance/baseline.json`

### Existing Core Files Modified

- `pyproject.toml`, `uv.lock`
- `src/orchestrator/graph/__init__.py`
- `src/orchestrator/graph/projections.py`
- `src/orchestrator/graph/patch_validator.py`
- `src/orchestrator/graph/_commands.py`
- `src/orchestrator/graph/callbacks.py`
- `src/orchestrator/graph/scenario.py`
- `src/orchestrator/graph_runtime/prompts.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- `src/orchestrator/graph_runtime/recovery.py`
- `src/orchestrator/graph_runtime/store.py`
- `src/orchestrator/workflow/graph_driver.py`
- `.pre-commit-config.yaml`
- `docs/ARCHITECTURE.md`, `AGENTS.md`, `docs/dynamic-graph/graph-projection-map-inventory.md`

---

## Execution Revision After Task 1c

Tasks 1a-1c completed the ownership manifest, single-source collector, and
repository provenance closure. The reviewed inventory intentionally reports
explicit unresolved flows. The original order incorrectly required a zero-
diagnostic baseline before the query codemod that resolves those diagnostics.

The binding execution order is now:

1. Keep Tasks 1a-1c and their diagnostic artifact unchanged as the migration
   input ledger.
2. Execute Task 2 to freeze replay and public-view behavior before source
   transformation.
3. Execute revised Task 3 against both classified occurrences and unresolved
   diagnostics. Every input receives exactly one transformed or allowlisted
   disposition.
4. Require zero unresolved diagnostics after applying Task 3, then write and
   verify `access_inventory.json` at the transformed source revision.
5. Continue Tasks 4-9 unchanged.

The original Task 1 Steps 7-9 are superseded by revised Task 3 Steps 8-10.
This is an execution dependency correction, not an architecture change.

---

### Task 1: Freeze The Ownership Manifest And Access Baseline

**Files:**
- Create: `scripts/codemods/graph_projection_manifest.yaml`
- Create: `scripts/graph_projection_inventory.py`
- Create: `tests/unit/test_graph_projection_inventory.py`
- Create: `tests/fixtures/graph_projection_migration/access_inventory.json`
- Create: `src/orchestrator/graph/projection_queries.py`
- Modify: `src/orchestrator/graph/patch_validator.py:838-858`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `load_manifest(path: Path) -> ProjectionMigrationManifest`
- Produces: `inventory_repository(root: Path, manifest: ProjectionMigrationManifest) -> AccessInventory`
- Produces: `resource_claims_for_node(projection: GraphProjection, node_id: str) -> tuple[ResourceClaimProjection, ...]`
- Produces: CLI `uv run python scripts/graph_projection_inventory.py --write-baseline|--check`
- Consumes: the 73-row normative table in the approved design and `GraphProjection` at `projections.py:175-248`

- [ ] **Step 1: Add failing manifest coverage tests**

```python
def test_manifest_covers_every_projection_field_exactly_once() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    old_fields = set(GraphProjection.__annotations__)

    assert len(old_fields) == 73
    assert {field.old_name for field in manifest.fields} == old_fields
    assert len({field.old_name for field in manifest.fields}) == 73


def test_manifest_assigns_node_creation_payload_fields() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    assigned = set(manifest.node_creation_fields)

    assert assigned == set(NodeCreationProjection.model_fields)
```

- [ ] **Step 2: Run the tests and observe the missing-manifest failure**

Run: `uv run pytest tests/unit/test_graph_projection_inventory.py -v`

Expected: FAIL because `graph_projection_manifest.yaml` and `load_manifest` do not exist.

- [ ] **Step 3: Add strict Pydantic manifest models and all normative entries**

Implement these script-local models in `scripts/graph_projection_inventory.py`:

```python
class FieldOwnership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    old_name: str
    new_path: str | None
    group: str | None
    disposition: Literal["canonical", "index", "derived", "removed"]
    value_type: str
    default_policy: str
    merge_policy: str
    ordering: Literal["not_applicable", "insensitive", "sorted", "explicit_index"]
    checkpoint_policy: Literal["canonical", "id_only", "derived", "omitted"]
    public_output_keys: tuple[str, ...] = ()


class ProjectionMigrationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_revision: str
    fields: tuple[FieldOwnership, ...]
    node_creation_fields: frozenset[str]
```

Set `baseline_revision` to the current worktree `HEAD` before any generated source transformation. Populate the YAML with all 73 rows from the design. Add every `NodeCreationProjection` field to `node_creation_fields`; assign it to `NodeSpecProjection`, `NodeRuntimeProjection`, `NodeSchedulingProjection`, another grouped store, or explicit removal with a reason. Do not retain `node_creation_payloads` as a catch-all destination.

- [ ] **Step 4: Remove the untyped patch-validator escape once**

Add `resource_claims_for_node()` over the current shape in `projection_queries.py`, export it from `orchestrator.graph`, and replace the `cast(dict[str, Any], projection)` compatibility probe in `patch_validator.py` with that query. Do not add a legacy `resource_claims` key path.

- [ ] **Step 5: Add failing inventory classification tests**

```python
def test_inventory_rejects_computed_projection_keys(tmp_path: Path) -> None:
    source = tmp_path / "dynamic.py"
    source.write_text(
        "def read(projection: GraphProjection, field: str):\n"
        "    return projection[field]\n"
    )

    with pytest.raises(UnclassifiedProjectionAccessError):
        inventory_paths((source,), manifest=load_manifest(MANIFEST_PATH))


def test_occurrence_id_ignores_line_number_changes() -> None:
    first = occurrence_id("a.py", "read", 'projection["node_states"]', 0)
    second = occurrence_id("a.py", "read", 'projection["node_states"]', 0)
    assert first == second
```

- [ ] **Step 6: Implement bounded LibCST inventory**

Seed projection values from annotations, known projection-returning functions, local assignments, and `GraphDispatchContext.graph_projection`. Classify subscript, `.get`, membership, key/value/item iteration, assignment, nested assignment, `setdefault`, append, delete, unpack, cast, fixture construction, and untyped escape. Use IDs composed from baseline revision, relative path, qualified function, normalized-expression hash, and same-expression ordinal. Abort on unsupported aliasing or dynamic access.

- [x] **Steps 7-9: Superseded after Task 1c**

Tasks 1a-1c committed and reviewed the manifest, collector, provenance closure,
and complete diagnostic artifact. Baseline generation is deferred until the
revised Task 3 codemod resolves the inventoried migration sites.

---

### Task 2: Capture Replay And Public-View Oracles

**Files:**
- Create: `scripts/generate_graph_projection_goldens.py`
- Create: `tests/unit/test_graph_projection_goldens.py`
- Create: `tests/integration/test_graph_projection_public_parity.py`
- Create: `tests/fixtures/graph_projection_migration/public_view_goldens.json`
- Create: `tests/fixtures/graph_projection_migration/replay_goldens.json`
- Modify: `tests/fixtures/graph/COVERAGE.md`

**Interfaces:**
- Produces: `build_replay_goldens() -> dict[str, JsonValue]`
- Produces: `build_public_view_goldens() -> dict[str, JsonValue]`
- Produces: CLI `uv run python scripts/generate_graph_projection_goldens.py --write|--check`
- Consumes: existing YAML graph corpus, FR17 event fixture, real SQLite integration fixtures, and current public projectors

- [ ] **Step 1: Add a failing deterministic-golden test**

```python
def test_replay_goldens_match_current_projection() -> None:
    expected = json.loads(REPLAY_GOLDENS.read_text())
    assert build_replay_goldens() == expected


def test_public_view_goldens_match_current_presenters() -> None:
    expected = json.loads(PUBLIC_VIEW_GOLDENS.read_text())
    assert build_public_view_goldens() == expected
```

- [ ] **Step 2: Run and observe missing generator/fixture failures**

Run: `uv run pytest tests/unit/test_graph_projection_goldens.py -v`

Expected: FAIL because the generator and golden JSON do not exist.

- [ ] **Step 3: Implement deterministic golden generation**

Reuse `tests/unit/graph_test_utils.py`, `tests/unit/test_fixture_corpus.py`, and the representative event setup from `tests/integration/test_graph_fr17_acceptance.py`. Serialize sorted scenario names and canonical JSON. Capture full replay, incremental replay, checkpoint round trip, topology, scheduler, node detail, planner, verification, governance, recovery, records, and API response bodies. Do not include object identities or unordered backend iteration.

- [ ] **Step 4: Generate checked-in oracles**

Run: `uv run python scripts/generate_graph_projection_goldens.py --write`

Expected: writes both sorted JSON fixtures.

Run: `uv run python scripts/generate_graph_projection_goldens.py --check`

Expected: exit 0 with no diff.

- [ ] **Step 5: Add real integration parity coverage**

Use an in-memory SQLite database and the actual graph routers/presenters. Assert the seeded FR17 surfaces equal `public_view_goldens.json`; do not start a unit-test HTTP client or mock the store.

- [ ] **Step 6: Run replay and public-view suites**

Run: `uv run pytest tests/unit/test_graph_projection_goldens.py tests/unit/test_fixture_corpus.py tests/integration/test_graph_projection_public_parity.py tests/integration/test_graph_fr17_acceptance.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the oracles**

```bash
git add scripts/generate_graph_projection_goldens.py tests/unit/test_graph_projection_goldens.py \
  tests/integration/test_graph_projection_public_parity.py \
  tests/fixtures/graph_projection_migration tests/fixtures/graph/COVERAGE.md
git commit -m "test: capture graph projection behavior"
```

---

### Task 3: Resolve Inventory And Move Consumers Onto The Query Boundary

**Files:**
- Modify: `src/orchestrator/graph/projection_queries.py`
- Create: `scripts/codemods/migrate_graph_projection_queries.py`
- Create: `scripts/check_graph_projection_boundaries.py`
- Create: `tests/unit/test_graph_projection_queries.py`
- Create: `tests/unit/test_migrate_graph_projection_queries.py`
- Create: `tests/unit/test_graph_projection_boundaries.py`
- Create: `tests/fixtures/graph_projection_migration/query_migration_report.json`
- Modify mechanically: all non-core source and test consumers listed by `access_inventory.json`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: pure query functions for every manifest read pattern
- Produces: `transform_repository(root: Path, inventory: AccessInventory) -> MigrationResult`
- Produces: CLI `--check`, `--apply`, and `--assert-clean`
- Produces: boundary-check CLI with an exact five-file physical-storage allowlist
- Produces: clean `access_inventory.json` only after transformed source has zero unresolved diagnostics
- Consumes: Task 1c occurrences plus every site in `docs/graph-projection-inventory-diagnostics.md`

- [ ] **Step 1: Add failing query behavior tests over the old shape**

```python
def test_node_queries_preserve_missing_value_semantics() -> None:
    projection = initial_projection()
    assert node_exists(projection, "missing") is False
    assert node_kind(projection, "missing") is None
    assert node_state(projection, "missing") is None


def test_records_for_node_port_preserves_order() -> None:
    projection = build_projection(record_events("r1", "r2"))
    assert tuple(record.record_id for record in records_for_node_port(
        projection, "worker", "output"
    )) == ("r1", "r2")
```

- [ ] **Step 2: Implement the complete pure query surface over the old representation**

Group functions by lifecycle, nodes, tasks, topology, records, scheduling, planning, verification, governance, requirements, execution, and usage. Query signatures use scalars, tuples, existing stable public read models, or query-owned `Protocol` types structurally satisfied by both the old event models and final projected models. They must not expose a concrete old or final storage class. Move every `isinstance` decision that depends on a concrete storage model behind a semantic query. Queries never return an internal mutable list/dict. Export every externally consumed function through `orchestrator.graph`.

- [ ] **Step 3: Add codemod failure, preservation, and idempotence tests**

```python
def test_codemod_rewrites_typed_projection_read() -> None:
    result = transform_source(
        'def f(p: GraphProjection):\n    return p["node_states"].get("n")\n'
    )
    assert "node_state(p, \"n\")" in result.code


def test_codemod_refuses_dynamic_key() -> None:
    with pytest.raises(AmbiguousProjectionAccessError):
        transform_source('def f(p: GraphProjection, key: str):\n    return p[key]\n')


def test_codemod_is_idempotent() -> None:
    once = transform_source(SOURCE).code
    assert transform_source(once).code == once
```

- [ ] **Step 4: Implement atomic LibCST transformation and diagnostic dispositions**

Follow `scripts/codemods/r04_otel_vocab.py`: collect and diagnose the complete repository in memory, transform reads to query calls, move non-core production mutations to graph update functions, and convert direct test construction/mutation to event-driven fixture factories. The migration report maps every Task 1c occurrence and diagnostic to exactly one `transformed`, `approved_core`, `projection_neutral`, or `rejected` disposition. A `projection_neutral` disposition requires an exact source-pattern rule and reason; no path-wide suppression is allowed. Write no files unless every input site has one disposition and an in-memory re-inventory of the transformed tree has zero unresolved diagnostics outside the exact five core files.

- [ ] **Step 5: Dry-run and inspect the generated report**

Run: `uv run python -m scripts.codemods.migrate_graph_projection_queries --check`

Expected: exit 0 with every baseline occurrence accounted for and no files changed.

- [ ] **Step 6: Apply the codemod once**

Run: `uv run python -m scripts.codemods.migrate_graph_projection_queries --apply`

Expected: writes all transformed consumers and `query_migration_report.json`.

Run: `uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean`

Expected: exit 0 and no second-run changes.

- [ ] **Step 7: Prove diagnostic closure before freezing the baseline**

Run: `uv run python scripts/graph_projection_inventory.py --diagnose`

Expected: exit 0 with zero unresolved diagnostics after the codemod. The command
must not rewrite the historical Task 1c diagnostic artifact.

- [ ] **Step 8: Write and verify the transformed-source baseline**

Update the manifest baseline revision to the pre-apply migration base retained
in `query_migration_report.json`, then run:

```bash
uv run python scripts/graph_projection_inventory.py --write-baseline
uv run python scripts/graph_projection_inventory.py --check
```

Expected: a sorted `access_inventory.json`, zero source drift, zero unresolved
diagnostics, and a one-to-one link from every original occurrence/diagnostic to
the migration report.

- [ ] **Step 9: Implement the exact boundary guard**

Allow direct grouped storage access only in:

```python
ALLOWED_STORAGE_READERS = frozenset({
    "src/orchestrator/graph/projection_models.py",
    "src/orchestrator/graph/projection_collections.py",
    "src/orchestrator/graph/projection_queries.py",
    "src/orchestrator/graph/projection_codec.py",
    "src/orchestrator/graph/projections.py",
})
```

Reject old literal projection subscripts, dynamic projection access, mutable projection operations, and imports from graph submodules outside `orchestrator.graph`.

- [ ] **Step 10: Run generated-change verification**

Run: `uv run python scripts/graph_projection_inventory.py --check`

Expected: all original occurrence IDs have one report disposition.

Run: `uv run python scripts/check_graph_projection_boundaries.py`

Expected: exit 0.

Run: `uv run pytest tests/unit/test_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py tests/unit/test_graph_projection_boundaries.py tests/unit/test_callbacks.py tests/unit/test_patch_validator.py -q`

Expected: PASS.

- [ ] **Step 11: Run broad graph tests before committing generated changes**

Run: `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/integration/test_graph_fr17_acceptance.py -q`

Expected: PASS with unchanged golden output.

- [ ] **Step 12: Commit the one-time consumer migration**

```bash
git add src tests scripts/check_graph_projection_boundaries.py \
  scripts/codemods/migrate_graph_projection_queries.py \
  tests/fixtures/graph_projection_migration/query_migration_report.json \
  tests/fixtures/graph_projection_migration/access_inventory.json \
  scripts/codemods/graph_projection_manifest.yaml
git commit -m "refactor: isolate graph projection storage"
```

---

### Task 4: Add Persistent Collections And Frozen JSON

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `src/orchestrator/graph/projection_collections.py`
- Create: `tests/unit/test_graph_projection_collections.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `FrozenMap[K, V]`
- Produces: `FrozenJsonValue`, `JsonValue`
- Produces: `empty_frozen_map`, `map_set`, `map_delete`, `map_update`, `freeze_json`, `thaw_json`

- [ ] **Step 1: Add the production dependency**

Run: `uv add 'immutables>=0.21,<1'`

Expected: updates `pyproject.toml` and `uv.lock` with a direct runtime dependency.

- [ ] **Step 2: Write failing persistent-map and frozen-JSON tests**

```python
def test_map_set_returns_a_new_map_without_changing_old_map() -> None:
    old = FrozenMap({"a": 1})
    new = map_set(old, "b", 2)
    assert dict(old) == {"a": 1}
    assert dict(new) == {"a": 1, "b": 2}


def test_frozen_json_rejects_cycles_and_non_string_keys() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(FrozenJsonValueError, match="cycle"):
        freeze_json(cyclic)
    with pytest.raises(FrozenJsonValueError, match="string keys"):
        freeze_json({1: "bad"})


def test_frozen_json_round_trips_normal_json() -> None:
    value = {"nested": [1, True, None, {"name": "x"}]}
    assert thaw_json(freeze_json(value)) == value
```

- [ ] **Step 3: Implement `FrozenMap` as a private `immutables.Map` wrapper**

Implement `collections.abc.Mapping`, generic typing, equality, repr, and Pydantic core-schema validation/serialization. Validate through the declared key/value schema, accept canonical input dictionaries, and serialize to a dictionary. Do not expose the wrapped `immutables.Map` or mutating transient object.

- [ ] **Step 4: Implement recursive immutable JSON**

Accept only `None`, exact booleans, finite exact integers/floats, strings, lists/tuples, and string-keyed dictionaries. Detect cycles by active object ID, reject depth greater than 100, convert sequences to tuples and objects to `FrozenMap`, and reverse the conversion in `thaw_json`.

- [ ] **Step 5: Run focused tests and type checking**

Run: `uv run pytest tests/unit/test_graph_projection_collections.py -q`

Expected: PASS.

Run: `uv run pyright src/orchestrator/graph/projection_collections.py`

Expected: 0 errors.

- [ ] **Step 6: Commit immutable primitives**

```bash
git add pyproject.toml uv.lock src/orchestrator/graph/projection_collections.py \
  src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_projection_collections.py
git commit -m "feat: add persistent projection collections"
```

---

### Task 5: Add The Final Grouped Models And Projected Records

**Files:**
- Create: `src/orchestrator/graph/projection_models.py`
- Create: `tests/unit/test_graph_projection_models.py`
- Create: `tests/unit/test_graph_projected_records.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `ProjectionModel`, all grouped projection models, and temporary scaffold name `ImmutableGraphProjection`
- Produces: discriminated `ProjectedRecord` union and `project_record(record: AcceptedOutputRecordPayload) -> ProjectedRecord`
- Consumes: `FrozenMap`, `FrozenJsonValue`, and the approved manifest

- [ ] **Step 1: Write failing model-graph immutability tests**

```python
def test_projection_model_graph_has_no_mutable_annotation_or_open_extra() -> None:
    violations = inspect_projection_model_graph(ImmutableGraphProjection)
    assert violations == []


def test_graph_projection_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ImmutableGraphProjection.model_validate({"unknown": True})


def test_empty_projection_uses_persistent_defaults() -> None:
    projection = ImmutableGraphProjection()
    assert isinstance(projection.nodes, FrozenMap)
    assert projection.scheduling.ready_node_ids == ()
```

- [ ] **Step 2: Implement the grouped model tree**

Implement the root scaffold as `ImmutableGraphProjection` and the groups exactly as approved: lifecycle, nodes, tasks, topology, records, scheduling, planning, verification, governance, requirements, execution, and usage. Use strict scalar fields, tuples, `FrozenMap`, and `FrozenJsonValue`. Include every retained `NodeCreationProjection` fact assigned by the manifest. Replace `GraphRecordSummary` and `FinalInvariantBlocker` TypedDict storage with frozen projection models. Export the temporary scaffold name through `orchestrator.graph`; do not replace the production `GraphProjection` export until Task 8.

- [ ] **Step 3: Write the failing 22-tag projected-record matrix**

```python
@pytest.mark.parametrize(("record_type", "expected_type"), PROJECTED_RECORD_CASES)
def test_project_record_converts_each_accepted_tag(
    record_type: str,
    expected_type: type[ProjectionModel],
) -> None:
    event_record = accepted_record_for_type(record_type)
    projected = project_record(event_record)
    assert type(projected) is expected_type
    assert projected.record_type == record_type
```

Include all 22 tags from `OUTPUT_RECORD_MODELS_BY_TYPE`; missing, unknown, and contradictory discriminator/port/schema cases must fail.

- [ ] **Step 4: Implement projection-specific record models**

Create frozen counterparts for all 20 accepted concrete record classes. Replace inherited payload/provenance dictionaries, record-specific lists/dicts, nested decision actors, git/file entries, evidence, and `Any` values with frozen models, tuples, or `FrozenJsonValue`. Define `ProjectedRecord` as an annotated discriminated union on required `record_type` literals; the gap classification model accepts its three literal tags.

- [ ] **Step 5: Add JSON round-trip and deep-mutation tests**

For every projected record case, dump in JSON mode, validate back, compare equality, and recursively attempt list/map/model mutation. Assert event-record mutation after conversion cannot affect the projected record.

- [ ] **Step 6: Run model and record suites**

Run: `uv run pytest tests/unit/test_graph_projection_models.py tests/unit/test_graph_projected_records.py tests/unit/test_output_record_event_payloads.py -q`

Expected: PASS.

Run: `uv run pyright src/orchestrator/graph/projection_models.py`

Expected: 0 errors.

- [ ] **Step 7: Commit destination models**

```bash
git add src/orchestrator/graph/projection_models.py src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_projection_models.py tests/unit/test_graph_projected_records.py
git commit -m "feat: define immutable graph projection models"
```

---

### Task 6: Add Strict Codec And Referential Integrity

**Files:**
- Create: `src/orchestrator/graph/projection_codec.py`
- Create: `tests/unit/test_graph_projection_codec.py`
- Create: `tests/unit/test_graph_projection_integrity.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `ProjectionCheckpointCodecError`, `ProjectionCheckpointIntegrityError`
- Produces: temporary `immutable_projection_to_checkpoint`, `immutable_projection_from_checkpoint`, and `validate_projection_integrity`
- Consumes: grouped `ImmutableGraphProjection`

- [ ] **Step 1: Write failing strict codec tests**

```python
def final_projection_fixture() -> ImmutableGraphProjection:
    return ImmutableGraphProjection()


def test_checkpoint_round_trip_preserves_projection() -> None:
    projection = final_projection_fixture()
    assert immutable_projection_from_checkpoint(
        immutable_projection_to_checkpoint(projection)
    ) == projection


@pytest.mark.parametrize("bad", ["1", True, float("inf")])
def test_checkpoint_rejects_scalar_coercion(bad: object) -> None:
    raw = immutable_projection_to_checkpoint(final_projection_fixture())
    raw["usage"]["tokens_by_node"] = {"node": bad}
    with pytest.raises(ValidationError):
        immutable_projection_from_checkpoint(raw)
```

- [ ] **Step 2: Implement strict model dump/validate codec**

`immutable_projection_to_checkpoint()` returns `projection.model_dump(mode="json")` and wraps only Pydantic serialization failures as `ProjectionCheckpointCodecError`. `immutable_projection_from_checkpoint()` lets Pydantic `ValidationError` propagate, validates the scaffold root, calls integrity validation, and returns it. Do not salvage siblings or default a malformed current-version root. Export the temporary names through `orchestrator.graph`; Task 8 replaces the old public codec names atomically.

- [ ] **Step 3: Write one failing test per integrity family**

Cover key/entity ID mismatch, dangling record ID, incorrect node/port record index, bad summary derivation, missing edge endpoint, bad adjacency, bad binding reference, invalid ready node, missing task relation, invalid planner session relation, dangling verification relation, and governance/requirement/execution references.

- [ ] **Step 4: Implement pure integrity validation**

Build a tuple of deterministic diagnostics and raise one `ProjectionCheckpointIntegrityError` containing sorted paths and reasons. Do not mutate or repair the projection. Keep helpers in `projection_codec.py` so only an approved core file reads grouped storage.

- [ ] **Step 5: Run codec and integrity tests**

Run: `uv run pytest tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_integrity.py -q`

Expected: PASS.

- [ ] **Step 6: Commit codec scaffolding**

```bash
git add src/orchestrator/graph/projection_codec.py src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_integrity.py
git commit -m "feat: validate graph projection checkpoints"
```

---

### Task 7: Establish Performance Baselines And Gates

**Files:**
- Create: `scripts/benchmark_graph_projection.py`
- Create: `tests/unit/test_benchmark_graph_projection.py`
- Create: `tests/fixtures/graph_projection_performance/scenarios.json`
- Create: `tests/fixtures/graph_projection_performance/baseline.json`
- Modify: `scripts/profile_graph_readback.py`

**Interfaces:**
- Produces: CLI `--sizes`, `--warmups`, `--runs`, `--baseline`, `--write-baseline`, `--check-gates`
- Measures: current reducer, persistent primitive/model operations, checkpoint encode/decode, peak memory, and public views

- [ ] **Step 1: Add benchmark CLI contract tests**

Add subprocess tests in `tests/unit/test_benchmark_graph_projection.py` that run a 100-event corpus, write a baseline, rerun `--check-gates`, and reject a synthetic result exceeding each configured ratio. Store hardware, Python version, dependency versions, corpus hash, warmups, runs, and medians.

- [ ] **Step 2: Implement deterministic corpora**

Generate general, edge-heavy, and record-heavy streams at 100, 1,000, and 10,000 events. Obtain the maximum observed event count through the orchestrator API when available and record only the count, not production payloads. Every requested-size and generated half-size probe uses exactly the configured `--warmups 2 --runs 7`; do not adapt sampling to corpus size, manipulate garbage collection, precondition garbage collection, or rerun until a gate gets a favorable result.

This uniform protocol corrects the prior 7/3/1 schedule, which produced unstable official gate results. Generation-2 scans added 89–93 ms while collecting zero objects. Isolated normal samples remained approximately linear: edge replay increased about 2.1 times from 5,000 to 10,000 events, general replay about 2.0 times, and record-heavy public-view normal samples were about 79 ms with garbage-collection outliers up to about 300 ms. Use uniform 2/7 medians rather than garbage-collection preconditioning or rerunning until lucky.

- [ ] **Step 3: Implement the exact design gates**

Enforce replay `<=1.15x`, doubling scale `<=2.5x`, peak memory `<=1.15x`, checkpoint size `<=1.0x` and smaller for record-heavy, public views and non-edge-heavy checkpoint decode `<=1.25x`, checkpoint encode `<=2.25x`, edge-heavy checkpoint decode `<=9.0x`, and cold rebuild `<=1.15x`. Exit nonzero with metric- and scenario-specific diagnostics. The codec limits are the approved 2026-07-30 evidence-backed design amendment; every non-codec limit remains unchanged.

- [ ] **Step 4: Record the pre-cutover baseline**

Run: `uv run python scripts/benchmark_graph_projection.py --sizes 100 1000 10000 --warmups 2 --runs 7 --write-baseline`

Expected: writes `baseline.json` with all required metadata and current measurements; every
requested and half-size probe records two warmups and seven measured samples.

- [ ] **Step 5: Commit benchmark tooling and baseline**

```bash
git add scripts/benchmark_graph_projection.py scripts/profile_graph_readback.py \
  tests/unit/test_benchmark_graph_projection.py tests/fixtures/graph_projection_performance
git commit -m "perf: baseline graph projection replay"
```

---

### Task 8: Perform The Atomic Core Semantic Cutover

**Files:**
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/projection_queries.py`
- Modify: `src/orchestrator/graph/projection_models.py`
- Modify: `src/orchestrator/graph_runtime/store.py:669-716,845-893,1250-1331`
- Modify: `src/orchestrator/graph/__init__.py`
- Create: `tests/unit/test_graph_projection_duplicate_ids.py`
- Create: `tests/unit/test_graph_projection_immutability.py`
- Create: `tests/unit/test_graph_projection_replay_equivalence.py`
- Create: `tests/integration/test_graph_projection_checkpoint_recovery.py`
- Modify: `tests/unit/test_graph_projections.py`
- Modify mechanically: remaining projection test fixtures identified by the migration inventory

**Interfaces:**
- Keeps: `initial_projection() -> GraphProjection`
- Keeps: `reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection`
- Adds: `ProjectionReplayConflictError`
- Adds: `merge_node_created(existing, payload, *, position, event_id) -> NodeProjection`
- Adds: `insert_projected_record(store, record, *, event_id) -> RecordStore`
- Switches store reads/writes to strict codec and grouped queries

- [ ] **Step 1: Write failing duplicate node and record tests**

```python
def test_identical_record_id_is_idempotent() -> None:
    event = output_record_event(record_id="r1", value={"x": 1})
    once = reduce_event(initial_projection(), event)
    twice = reduce_event(once, event.model_copy(update={"position": event.position + 1}))
    assert twice == once


def test_conflicting_record_id_fails_replay() -> None:
    first = output_record_event(record_id="r1", value={"x": 1})
    second = output_record_event(record_id="r1", value={"x": 2})
    with pytest.raises(ProjectionReplayConflictError, match="record.*r1"):
        build_projection([first, second])


def test_repeated_node_creation_does_not_reset_runtime_state() -> None:
    projection = build_projection([
        node_created_event("n", state="planned"),
        node_state_event("n", "running"),
        node_created_event("n", state="planned"),
    ])
    assert node_state(projection, "n") == "running"
```

Add the full matrix for absent-field fill, stable-field conflict, first creation position, first non-null `max_attempts`, explicit empty collections, cross-node/port record conflicts, file state, candidate, and side-index idempotency.

- [ ] **Step 2: Write failing deep-immutability and sharing tests**

Recursively walk the final model graph, attempt field assignment, map assignment/delete, tuple item assignment, and nested JSON mutation. For representative events assert the input projection is unchanged, unchanged groups retain identity, and changed groups/entities receive new identity.

- [ ] **Step 3: Write failing replay-equivalence property tests**

For every fixture stream and every split position, assert reducing the suffix from the prefix projection equals full replay. Add Hypothesis-generated valid event sequences and compare incremental, full, and checkpoint-plus-tail results. Replace old checkpoint-salvage expectations with strict invalid-cache behavior.

- [ ] **Step 4: Replace the root and initial state atomically**

Rename the scaffold `ImmutableGraphProjection` to `GraphProjection`, replace the old public export, delete the 73-field `TypedDict`, and return `GraphProjection()` from `initial_projection()`. Rename the temporary codec functions to `projection_to_checkpoint` and `projection_from_checkpoint` while replacing the old exports. Keep public view `TypedDict`s because they are serialized views, not stored state. Remove every temporary scaffold export in the same change.

- [ ] **Step 5: Convert reducer writes to persistent grouped updates**

Remove `_clone_projection`. Convert each event branch and reducer helper using the manifest ownership and typed persistent update helpers. Construct complete validated replacement entities before insertion. Recompute task state and ready IDs into tuples before installing them. Preserve branch order and explicit projection-neutral event behavior.

- [ ] **Step 6: Canonicalize nodes and records**

Implement `merge_node_created` and `insert_projected_record` with the exact collision rules from the design. Delete `node_creation_payloads`, duplicate full record indexes, raw record wrappers, and record-copy helpers. Decision aliases become canonical decision values plus node-to-decision ID indexes so checkpoint payloads are not duplicated.

- [ ] **Step 7: Switch query implementations to grouped storage**

Change only `projection_queries.py`; broad consumers must remain untouched. Preserve query return shapes and explicit ordering. Run the codemod clean check to prove no regeneration occurred.

- [ ] **Step 8: Switch checkpoint store behavior**

Increment `PROJECTION_SCHEMA_VERSION` from 12 to 13. In `read_projection_checkpoint`, catch only Pydantic `ValidationError`, `ProjectionCheckpointCodecError`, and `ProjectionCheckpointIntegrityError`; return an invalid-cache result. `load_projection_with_tail` must then read all canonical events, rebuild, persist v13 transactionally, and continue. Do not catch `ProjectionReplayConflictError`, event validation errors, or programming errors.

- [ ] **Step 9: Delete obsolete checkpoint and copy machinery**

Delete old field-level checkpoint parsers, malformed-sibling salvage, dict-or-model normalizers, `_clone_projection`, and old default/copy tests. Keep no compatibility branch for v12 projection bodies.

- [ ] **Step 10: Run focused cutover tests**

Run:

```bash
uv run pytest \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projections.py \
  tests/integration/test_graph_projection_checkpoint_recovery.py \
  tests/integration/test_graph_event_store.py -q
```

Expected: PASS.

- [ ] **Step 11: Verify public and generated parity**

Run: `uv run python scripts/generate_graph_projection_goldens.py --check`

Run: `uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean`

Run: `uv run python scripts/check_graph_projection_boundaries.py`

Run: `uv run pytest tests/integration/test_graph_projection_public_parity.py tests/integration/test_graph_fr17_acceptance.py tests/integration/test_graph_node_detail_read_models.py -q`

Expected: all commands exit 0.

- [ ] **Step 12: Run the performance gates**

Run: `uv run python scripts/benchmark_graph_projection.py --baseline tests/fixtures/graph_projection_performance/baseline.json --check-gates`

Expected: every non-scaling gate remains hard: replay, memory, checkpoint, amended codec,
unchanged view, cold rebuild, invalid units/sources, invalid scaling denominators, and all
compatibility failures. A `scaling ... exceeds 2.5` result remains visible in sorted
`diagnostics`, but is non-blocking only if every scenario's 10,000-event
`reducer_full_replay` median is strictly below 1000 ms; if any scenario is `>=1000 ms`, that
ratio result is a hard violation. This is release classification outside measurement protocol
identity: retain the checked-in corpus, exact 2 warmups/7 runs for every probe, unmodified GC,
existing measured baseline, and protocol hash `26808c77121ceb4db824201db6b912cf3bfff3c1325356a41f0741c9705c02b6`.

- [ ] **Step 13: Commit the atomic cutover**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime/store.py tests \
  tests/fixtures/graph_projection_migration scripts/benchmark_graph_projection.py
git commit -m "refactor: make graph projection immutable"
```

---

### Task 9: Install Permanent Guards, Update Documentation, And Run Repository Gates

**Files:**
- Modify: `.pre-commit-config.yaml`
- Modify: `scripts/check_graph_projection_boundaries.py`
- Modify: `tests/unit/test_graph_projection_boundaries.py`
- Modify: `tests/unit/test_graph_public_exports.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `AGENTS.md`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`
- Modify: `docs/superpowers/specs/2026-07-26-immutable-graph-projection-design.md` only if measured implementation facts require an approved amendment

**Interfaces:**
- Produces: permanent pre-commit hook `graph-projection-boundaries`
- Documents: module map, immutable invariant, query boundary, checkpoint policy, and benchmark evidence

- [ ] **Step 1: Add the boundary hook**

```yaml
- id: graph-projection-boundaries
  name: graph-projection-boundaries
  entry: uv run python scripts/check_graph_projection_boundaries.py
  language: system
  pass_filenames: false
```

- [ ] **Step 2: Add permanent regression assertions**

Assert the exact five-file allowlist, no old `GraphProjection` `TypedDict`, no `_clone_projection`, no mutable reachable annotation, no non-frozen reachable Pydantic model, no full record payload outside `RecordStore.by_id`, all external imports through `orchestrator.graph`, and every canonical event handled or explicitly projection-neutral.

- [ ] **Step 3: Update architecture and agent guidance**

Document the four new graph modules, public query API, v13 disposable checkpoint policy, `FrozenMap`/tuple deep-immutability invariant, record ownership, strict integrity validation, and automation guard. Replace the old AGENTS statement that only requires `frozen=True` with the deeper invariant and persistent-update rule.

- [ ] **Step 4: Run static and formatting gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python scripts/graph_projection_inventory.py --check
uv run python scripts/check_graph_projection_boundaries.py
uv run python scripts/check_module_imports.py
```

Expected: all exit 0.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`

Expected: all non-slow, non-e2e tests pass with zero failures.

- [ ] **Step 6: Run the complete pre-commit gate**

Run: `uv run pre-commit run --all-files`

Expected: every hook passes. Do not bypass or suppress any failure.

- [ ] **Step 7: Inspect migration closure**

Run:

```bash
uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean
uv run python scripts/generate_graph_projection_goldens.py --check
uv run python scripts/benchmark_graph_projection.py \
  --baseline tests/fixtures/graph_projection_performance/baseline.json --check-gates
```

Expected: no codemod changes, no golden drift, and all performance gates pass.

- [ ] **Step 8: Commit guards and documentation**

```bash
git add .pre-commit-config.yaml scripts/check_graph_projection_boundaries.py \
  tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_public_exports.py \
  docs/ARCHITECTURE.md AGENTS.md docs/dynamic-graph/graph-projection-map-inventory.md
git commit -m "docs: lock graph projection invariants"
```

---

## Follow-Up Boundary

Do not split `reduce_event` during this plan. Once the immutable cutover has operated under the
permanent guards and parity suite, write a separate handler-registry plan. That follow-up may
move event families into focused modules but must not change projection representation,
checkpoint schema, query outputs, or reducer semantics.
