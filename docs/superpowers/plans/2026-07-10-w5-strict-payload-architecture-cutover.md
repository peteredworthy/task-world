# W5 Strict Payload Architecture Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every live graph event and command payload path with one strict, model-driven, injected catalog architecture and close W5 without historical payload compatibility.

**Architecture:** Strict frozen Pydantic payload models live beside their domain event or command specifications. An immutable catalog validates at boundaries, constructs typed events, hydrates stored JSON exactly once, and dispatches concrete payload models to typed handlers; storage, compact reads, checkpoints, summaries, and API serialization consume the complete validated payload without copied field lists. The current compatibility adapters remain only as temporary scaffolding while domain slices move, then are deleted before the catalog-wide gates are enabled.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2.0, FastAPI, Alembic, pytest/pytest-asyncio, Ruff, Pyright.

## Global Constraints

- Existing graph history is disposable; do not preserve, normalize, convert, or replay legacy payload variants.
- If `orchestrator.db` exists, verify a backup before the explicit final reset;
  if absent, record Branch B and fresh initialize with no backup/reset. Never
  add destructive startup behavior.
- Strict payload models use `ConfigDict(strict=True, extra="forbid", frozen=True)` and contain no catch-all top-level `extra` field.
- Raw JSON exists only at external API and database boundaries; reducers and command handlers receive concrete Pydantic payload types.
- Parse once: hydration occurs in the injected catalog immediately after storage loading, never inside reducers or view helpers.
- The immutable catalog is constructed at composition roots and injected; no mutable registry or module-global default catalog is permitted.
- Cover all 44 currently produced graph event names and all 23 registered command names, including audit-only and projection-neutral events.
- Delete the four hand-maintained payload field allowlists; compact, summary-rebuild, checkpoint, and node-detail paths carry complete strict payloads.
- Do not promote shared payload fields to relational columns in W5; only the envelope-level payload schema generation is added.
- Use real objects and dependency injection in tests; do not use `patch`, `MagicMock`, or monkeypatching.
- Run every Python command through `uv run` and keep unit tests free of FastAPI/TestClient imports.
- Preserve top-level module public APIs: external modules import from `orchestrator.graph` or `orchestrator.graph_runtime`, not their private submodules.
- Keep the event journal append-first and preserve existing pessimistic/optimistic concurrency and outbox transaction guarantees.
- Use AST/CST automation for structural discovery and every mechanically recognizable migration edit; do not manually bulk-move classes, repair imports/exports, rewrite event-emission calls, replace registry entries, thread repeated constructor arguments, or delete allowlist/extraction blocks.
- Use Python `ast` for read-only inventory/enforcement and LibCST for formatting-preserving source modification. Regex or text-replacement codemods are not acceptable for Python source.
- Pydantic models remain the only schema source. Automation may emit ephemeral inventories and class skeletons for review, but may not introduce a checked-in field/type manifest or generate runtime models from a second schema language.

---

## Reconciliation with the Compatibility-First W5 Queue

### Retain as verified behavior or source material

| Merged work | Treatment in the strict cutover |
|---|---|
| Corpus full/checkpoint/compact parity fixture | Keep and strengthen it so every read path hydrates complete strict payloads. |
| `w5-event-payload-inventory.md` | Use as the initial field inventory for the 44 live produced events; refresh it from the final catalog. |
| Existing event payload class field lists | Move the valid current-producer fields into domain modules; keep useful nested typed records. |
| Existing focused event-family tests | Rewrite assertions around strict rejection and typed dispatch while preserving domain semantic regressions. |
| Existing typed projection records (`LeaseProjection`, decision projections, requirement/support projections, file-state records, and related types) | Retain where already concrete; relocate only when domain cohesion improves. |
| Command module split under `graph/commands/` | Retain the domain files, move real handler logic into them, and remove wrapper calls back into `_commands.py`. |
| Exact GREEN evidence in `w5-progress-ledger.md` | Preserve as historical evidence and add a strict-cutover section explaining which implementation was superseded. |

### Replace or delete

| Compatibility-first artifact | Strict replacement |
|---|---|
| `GraphEventPayloadBase`, `LeaseEventPayloadBase`, and `LifecycleEventPayloadBase` with `extra="ignore"` | One `StrictPayload` base with strict validation and `extra="forbid"`. |
| `mode="before"` legacy normalizers and catch-all `extra` maps | Exact current schemas; malformed, sparse, aliased, or unknown shapes fail. |
| Replay-only event aliases such as `lease_suspended`, proposal aliases, suspect-cleared aliases, requirement/support aliases, and environment aliases | Delete unless a current producer is found during the catalog source scan; produced names are the authoritative surface. |
| `_typed_*_event_payload` lookup helpers and producer `model_validate(...).model_dump(...)` chains | `EventSpecification.create(payload_model, metadata)` and typed event factories. |
| Raw `EventEnvelope.payload: dict[str, Any]` | `StoredEventEnvelope` at persistence boundaries and `HydratedEvent` with `StrictPayload` in the kernel. |
| `COMMAND_HANDLERS: dict[str, ApplyCommandHandler]` and raw command dictionaries | Immutable `CommandSpecification` catalog and concrete command payload models. |
| The `reduce_event` event-name conditional and per-event parse wrappers | Catalog resolution followed by the specification's typed reducer handler. |
| `GRAPH_PROJECTION_PAYLOAD_FIELDS`, `LIGHT_GRAPH_PAYLOAD_FIELDS`, `SUMMARY_REBUILD_PAYLOAD_FIELDS`, `NODE_DETAIL_PAYLOAD_FIELDS` and their AST exclusion test | Complete stored payload reads plus parity and architecture enforcement tests. |
| Old `GradeRow` proposal with `extra="allow"` | Strict `GradeRow` with explicit fields and `extra="forbid"`. |
| Compatibility-first completion queue order | The dependency-ordered slices below: framework, domain specifications, full cutover, persistence/read paths, enforcement, operational reset, closeout. |

## Deferred Compatibility Cleanup Register (added 2026-07-12)

Domain tasks (1–8) deleted an alias's **catalog specification and strict-path support** while retaining registered compatibility branches needed by durable replay. Task 13 closed D1-D6 after Branch B fresh initialization established the current strict schema; no backup/reset was necessary, and the register grep returned status 1 with no output.

Rules:
- Domain tasks marked aliases "strict-path deleted, legacy-replay deferred" and did not delete legacy reducer branches.
- Task 13 alone closed the register after the required database precondition.
- Branch B applied: `No worktree orchestrator.db existed; per Task 13, no backup or reset was necessary.` Normal startup then initialized the current strict schema before D1-D6 deletion.

| # | Deferred item (code sites) | Deferred by | Deleted in |
|---|---|---|---|
| D1 | `lease_suspended` reducer/planner branches and enum member | Task 4 (done) | Task 13 (`e63fb41ec`), deleted |
| D2 | `graph_patch_proposed` / proposal-status alias bookkeeping and proposal port checks | Task 6 (done) | Task 13 (`e63fb41ec`), deleted |
| D3 | Legacy output-record parsing, sparse verification fallbacks, raw selectors, and full-history compatibility reads | Task 5 (done) | Task 13 (`e63fb41ec`), deleted |
| D4 | Requirement/authority aliases, authority-resolution helper, and full-history blocker scans | Task 7 (done) | Task 13 (`e63fb41ec`), deleted |
| D5 | `environment_failure_accepted` / `check_result_classified` branches and classification scan | Task 8 (done) | Task 13 (`e63fb41ec`), deleted |
| D6 | `reduce_legacy_event`, callers/delegates, generation-1 paths, and hidden compatibility adapters | Tasks 1–8 (structural) | Task 13 (`e63fb41ec`), deleted |

Final source reconciliation: `b63146d9b` removed the remaining legacy graph
effects adapter after Task 13, and `0289de70c` enforced typed graph payload
consumers without a production payload adapter. The catalog is 44/23, every
measured strict/current, retired, and deferred compatibility metric is zero,
and the latest independently verified suites are 1,083 graph tests and 5,101
passed / 5 skipped / 3 warnings in the full suite.

Task 13 grep gate (run after the Branch B absence record; docs and Alembic migrations exempt):

```bash
grep -rn "lease_suspended\|graph_patch_proposed\|requirement_revision_proposed\|authority_resolution_recorded\|environment_failure_accepted\|check_result_classified\|reduce_legacy_event" \
  src/orchestrator/graph src/orchestrator/graph_runtime
```

Observed: no matches; grep exited 1 with no output.

## Live Catalog Baseline

The completion gate starts from 44 currently produced event names:

```text
agent_died, agent_dispatch_requested, appeal_opened,
approval_decision_recorded, authority_decision_recorded,
callback_accepted, callback_duplicate_returned,
callback_rejected_conflict, callback_rejected_stale,
cleanup_applied, cleanup_requested, command_rejected,
dead_input_detected, edge_created, file_state_accepted,
file_state_rejected, gatekeeper_cost_recorded,
gatekeeper_verdict_recorded, graph_patch_accepted,
graph_patch_rejected, heartbeat_recorded, input_bound,
lease_expired, lease_granted, lease_released, lease_renewed,
lease_revoked, node_authority_changed, node_created,
node_deferred, node_ready, node_retired, node_state_changed,
output_record_accepted, oversight_decision_recorded,
plan_region_marked_suspect, requirement_revision_recorded,
revision_created, run_lifecycle_changed, runtime_retry_scheduled,
session_state_changed, support_evidence_recorded,
verification_failed, verification_passed
```

The command gate starts from the 23 current names in `graph/commands/__init__.py`:

```text
accept_run, start, pause, resume, cancel, complete, fail,
seed_compiled_events, submit_callback, submit_patch, schedule_tick,
reconcile, acknowledge_start, agent_died, record_heartbeat,
raise_appeal, record_decision, record_gatekeeper_verdicts,
record_requirement_revision, record_support_evidence, evaluate_join,
evaluate_final_gate, record_cleanup_applied
```

These lists are migration baselines, not new runtime registries. Once raw event creation and raw command dispatch are forbidden, the injected catalog itself is authoritative.

## Automation-First Migration Protocol

Automation is the default for migration mechanics; manual edits are reserved for decisions a syntax tree cannot safely infer, chiefly required-versus-optional fields, domain invariants, reducer behavior, and command semantics.

### Read-only AST inventory

`scripts/w5_payload_ast_inventory.py` parses the production tree and emits a deterministic report containing:

- literal and dynamic event construction sites, including factory calls and direct `EventEnvelope` construction;
- event-name branches and raw payload reads reachable from reducer/view/runtime entry points;
- current W5 payload classes, their declared fields/configuration, and before validators;
- command registry names, handlers, handler annotations, and controller call sites;
- the four allowlist definitions and every consumer of partial-event extraction;
- catalog coverage and remaining migration patterns after each slice.

The report is written to stdout or `/tmp`; it is evidence and a migration input, not a checked-in schema. `--check-baseline` asserts the initial 44 event/23 command surface before edits. `--check-domain <name>` asserts that a completed domain has no raw producer, raw handler boundary, compatibility model, or central reducer branch remaining.

### Formatting-preserving LibCST codemod

`scripts/codemods/w5_strict_payload_cutover.py` owns repetitive source modification. Its `DomainMigration` table contains only mechanical symbol/name routing—event name, old class name, specification constant, command name, and target module. It contains no payload fields or types.

For each domain it can:

- relocate selected class/function definitions while preserving comments and formatting;
- update imports and `__all__` exports from the moved symbol graph;
- replace recognized `make_event("name", model_validate(...).model_dump(...))` and raw factory calls with the named specification constructor;
- replace command registry entries with specification tuple entries;
- change repeated handler annotations from raw dictionaries to the selected strict model;
- add an injected `catalog` argument at structurally matched compiler/controller/store construction sites;
- remove the four allowlist constants and replace their known read-method bodies with the complete hydration call;
- delete recognized compatibility adapters only when their references reach zero.

Every transformation supports `--dry-run`, `--apply`, and `--assert-clean`. `--dry-run` emits a unified diff without writing. `--assert-clean` reruns the matcher after application and fails if another mechanical edit remains, making every transformation idempotent.

### Mandatory slice loop

Tasks 2–11 follow this order, even when a task's detailed steps abbreviate it:

1. Run the AST inventory for the domain and save the report under `/tmp`.
2. Write/execute focused RED semantic tests.
3. Run the LibCST codemod with `--dry-run`; inspect the complete proposed diff.
4. Run the same transform with `--apply` before making manual production edits.
5. Manually implement only strict field semantics, domain rules, and cases explicitly reported as unsafe to automate.
6. Run `--assert-clean` and the domain AST check; zero eligible mechanical sites may remain.
7. Run focused GREEN tests and inspect `git diff --stat` plus the automation report's transformed/manual-site counts.

If the codemod cannot safely transform a repeated construct, extend the codemod and its golden tests first, then rerun it. Do not work around a missing transform with repeated hand edits.

### Automation acceptance metrics

Closeout records, per domain and in total:

```text
discovered_mechanical_sites
transformed_by_libcst
reported_unsafe_for_manual_semantics
eligible_sites_left_after_assert_clean = 0
codemod_second_run_changes = 0
inventory_unclassified_dynamic_event_sites = 0
```

There is no line-count percentage target because domain handlers and strict schemas require judgment. The measurable gate is that every site classified as mechanical is transformed by the codemod and no eligible site is edited manually.

## Target File Map

### New framework and enforcement files

- `src/orchestrator/graph/payloads.py` — recursive JSON value type and strict payload base.
- `src/orchestrator/graph/specifications.py` — stored/hydrated envelopes, metadata/context types, generic event/command specifications, projection participation enum.
- `src/orchestrator/graph/catalog.py` — immutable duplicate-checking event/command catalog and deterministic `build_graph_catalog()` composition.
- `src/orchestrator/graph/events/__init__.py` — public domain specification groups only.
- `src/orchestrator/graph/events/lifecycle.py` — lifecycle, callback, retry, dispatch-intent, heartbeat, and agent-death event payloads/handlers/specifications.
- `src/orchestrator/graph/events/topology.py` — node, edge, input-binding, session, dead-input, and revision event payloads/handlers/specifications.
- `src/orchestrator/graph/events/leases.py` — five live lease event payloads/handlers/specifications.
- `src/orchestrator/graph/events/records.py` — output-record and verification event payloads/handlers/specifications.
- `src/orchestrator/graph/events/patches.py` — accepted/rejected patch event payloads/handlers/specifications.
- `src/orchestrator/graph/events/decisions.py` — appeal and three decision event families.
- `src/orchestrator/graph/events/requirements.py` — requirement revision and support evidence events.
- `src/orchestrator/graph/events/file_state.py` — file-state, gatekeeper, and cleanup events.
- `scripts/check_graph_payload_architecture.py` — static guard against raw payload boundaries, central dispatch, legacy normalizers, and allowlists.
- `scripts/measure_graph_payload_architecture.py` — reproducible catalog counts and before/after change-spread metrics.
- `scripts/w5_payload_ast_inventory.py` — deterministic AST inventory and per-domain migration completeness checks.
- `scripts/codemods/w5_strict_payload_cutover.py` — idempotent LibCST migration tool for structural W5 edits.
- `tests/unit/test_w5_payload_ast_inventory.py` — AST inventory fixtures, baseline detection, and dynamic-site diagnostics.
- `tests/unit/test_w5_strict_payload_codemod.py` — LibCST golden transformations and second-run idempotency.
- `tests/unit/test_graph_payload_framework.py` — strict base, envelope, specification, catalog, and vertical-slice tests.
- `tests/unit/test_graph_catalog_contracts.py` — parameterized contracts over every event and command.
- `tests/unit/test_graph_payload_architecture.py` — executes the static guard and its self-test fixtures.
- `tests/unit/test_graph_change_spread.py` — generic field/event/command maintenance exercises.
- `src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_add_graph_payload_schema_generation.py` — nullable envelope generation column for `events_v2`; graph rows require the current generation.

### Existing files changed across slices

- `src/orchestrator/graph/models.py` — remove event payload classes/normalizers; keep shared graph records and projection values; add strict `GradeRow` and replace remaining payload-shaped maps in W5 scope.
- `src/orchestrator/graph/_commands.py` — shrink as domain logic moves, then delete.
- `src/orchestrator/graph/commands/{__init__,lifecycle,callbacks,patches,records,schedule}.py` — define strict command models/specifications and own typed handlers.
- `src/orchestrator/graph/compiler.py` — inject catalog/event factory and construct typed topology events.
- `src/orchestrator/graph/projections.py` — remove payload parsing and central event dispatch; retain projection state/checkpoint/view functions.
- `src/orchestrator/graph/callbacks.py`, `command_bindings.py`, `patch_validator.py`, `scenario.py` — consume hydrated typed payloads or catalog interfaces instead of raw event dictionaries.
- `src/orchestrator/graph/__init__.py` — export only public strict/catalog/domain types and remove compatibility exports.
- `src/orchestrator/graph_runtime/{controller,store,dispatch,recovery,seeding,outbox,errors,__init__}.py` — inject catalog, validate commands once, hydrate stored events once, serialize strict models, and preserve complete payloads.
- `src/orchestrator/db/orm/models.py` — add `payload_schema_generation` to `EventV2Model`.
- `src/orchestrator/api/{app,deps}.py`, `src/orchestrator/api/routers/graph.py` — build/inject the catalog and use command payload schemas at HTTP boundaries.
- `src/orchestrator/workflow/{service,graph_driver}.py` — receive and forward the catalog to graph store/controller construction.
- `.pre-commit-config.yaml` — run the payload architecture guard.
- `pyproject.toml`, `uv.lock` — declare LibCST directly in the dev dependency group rather than relying on its current transitive installation.
- Existing W5 event-family tests — replace legacy-normalization assertions with strict rejection, round-trip, and typed-handler assertions.
- `tests/unit/test_graph_payload_field_allowlists.py` — delete after the four constants and extraction code disappear.
- Graph integration/acceptance tests — pass the injected catalog through real stores/controllers and assert corruption/generation failures.
- `docs/ARCHITECTURE.md`, `docs/dynamic-graph/{w5-progress-ledger,w5-event-payload-inventory,graph-projection-map-inventory,w5-typed-payloads-spec}.md`, and the approved design — record final architecture, metrics, and closure.

---

### Task 0: AST Inventory and LibCST Migration Harness

**Files:**
- Create: `scripts/w5_payload_ast_inventory.py`
- Create: `scripts/codemods/w5_strict_payload_cutover.py`
- Create: `tests/unit/test_w5_payload_ast_inventory.py`
- Create: `tests/unit/test_w5_strict_payload_codemod.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: `InventoryReport`, `DomainInventory`, `scan_graph_payload_architecture(paths)`, `DomainMigration`, and `StrictPayloadCutoverCodemod`.
- CLI: `w5_payload_ast_inventory.py [--format text|json] [--output PATH] [--check-baseline] [--check-domain DOMAIN]`.
- CLI: `w5_strict_payload_cutover.py --domain DOMAIN (--dry-run|--apply|--assert-clean)`.
- Consumed by every later migration task; neither tool defines payload fields or runtime schemas.

- [ ] **Step 1: Add LibCST as a direct development dependency**

Run: `uv add --group dev "libcst>=1.5"`

Expected: `pyproject.toml` lists LibCST in `[dependency-groups].dev`, and `uv.lock` remains consistent with the already-resolved 1.5+ package.

- [ ] **Step 2: Write failing AST inventory tests**

```python
def test_inventory_finds_literal_dynamic_and_registry_sites(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(SAMPLE_EVENT_AND_COMMAND_SOURCE)
    report = scan_graph_payload_architecture([source])
    assert report.literal_event_names == {"node_created"}
    assert report.dynamic_event_sites[0].expression == "event_type"
    assert report.command_names == ("start",)
    assert report.raw_payload_reads[0].field == "node_id"
```

Run: `uv run pytest tests/unit/test_w5_payload_ast_inventory.py -q`

Expected: collection fails because the inventory module does not exist.

- [ ] **Step 3: Implement the AST inventory with source locations and stable output**

Use `ast.parse`, parent/call-graph indexing, and dataclasses/Pydantic report records. Sort every path/name/site tuple before rendering. Dynamic sites must include `path`, `line`, `column`, and `ast.unparse(expression)`; never silently discard a nonliteral event or command name.

- [ ] **Step 4: Verify the real baseline structurally**

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-baseline --format json --output /tmp/w5-payload-baseline.json`

Expected: exit 0 with 44 produced event names and 23 command names; every dynamic factory site is listed and either resolved to finite outcomes or explicitly classified as the generic factory definition.

- [ ] **Step 5: Write failing LibCST golden/idempotency tests**

```python
def test_domain_codemod_preserves_comments_and_is_idempotent() -> None:
    once = apply_codemod(BEFORE_LIFECYCLE_SOURCE, LIFECYCLE_MIGRATION)
    assert once == AFTER_LIFECYCLE_SOURCE
    assert apply_codemod(once, LIFECYCLE_MIGRATION) == once
```

Cover class relocation, import/export repair, emission replacement, handler annotation replacement, catalog argument insertion, allowlist removal, and refusal diagnostics for ambiguous constructs.

Run: `uv run pytest tests/unit/test_w5_strict_payload_codemod.py -q`

Expected: collection fails because the codemod module does not exist.

- [ ] **Step 6: Implement dry-run/apply/assert-clean modes**

Use LibCST metadata providers (`PositionProvider`, `QualifiedNameProvider`, and `ScopeProvider`) so replacements depend on syntax and resolved symbol shape, not text coincidence. `--dry-run` returns a unified diff, `--apply` writes through `apply_patch`-compatible normal file updates, and `--assert-clean` exits nonzero with every remaining eligible site.

- [ ] **Step 7: Run harness verification**

Run: `uv run pytest tests/unit/test_w5_payload_ast_inventory.py tests/unit/test_w5_strict_payload_codemod.py -q`

Run: `uv run ruff check scripts/w5_payload_ast_inventory.py scripts/codemods/w5_strict_payload_cutover.py tests/unit/test_w5_payload_ast_inventory.py tests/unit/test_w5_strict_payload_codemod.py`

Expected: pass; applying every golden transform twice produces no second diff.

- [ ] **Step 8: Commit the automation harness**

```bash
git add pyproject.toml uv.lock scripts/w5_payload_ast_inventory.py scripts/codemods/w5_strict_payload_cutover.py tests/unit/test_w5_payload_ast_inventory.py tests/unit/test_w5_strict_payload_codemod.py
git commit -m "tooling: add AST-driven W5 payload migration"
```

---

### Task 1: Strict Payload Framework and Heartbeat Vertical Slice

**Files:**
- Create: `src/orchestrator/graph/payloads.py`
- Create: `src/orchestrator/graph/specifications.py`
- Create: `src/orchestrator/graph/catalog.py`
- Create: `src/orchestrator/graph/events/__init__.py`
- Create: `src/orchestrator/graph/events/lifecycle.py`
- Create: `tests/unit/test_graph_payload_framework.py`
- Modify: `src/orchestrator/graph/commands/lifecycle.py`
- Modify: `src/orchestrator/graph/__init__.py`

**Interfaces:**
- Produces: `StrictPayload`, `JsonValue`, `StoredEventEnvelope`, `HydratedEvent`, `EventMetadata`, `EventSpecification[PayloadT]`, `CommandExecutionContext`, `CommandSpecification[CommandT]`, `ProjectionParticipation`, `GraphCatalog`, and `build_graph_catalog()`.
- Proves end to end: `RecordHeartbeatCommand -> HEARTBEAT_RECORDED -> projection-neutral typed dispatch`.

- [ ] **Automation checkpoint A: Preview representative relocation/emission edits**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain vertical_slice --dry-run`

Expected: the preview covers relocation of the heartbeat payload class, import/export repair, heartbeat emission replacement, and the `record_heartbeat` registry/specification substitution; new framework files remain manual because they have no source analogue.

- [ ] **Step 1: Write failing strictness and catalog tests**

```python
class ExamplePayload(StrictPayload):
    node_id: str
    generation: int

def test_strict_payload_rejects_unknown_and_coerced_fields() -> None:
    with pytest.raises(ValidationError):
        ExamplePayload.model_validate({"node_id": "n-1", "generation": "1"})
    with pytest.raises(ValidationError):
        ExamplePayload.model_validate({"node_id": "n-1", "generation": 1, "typo": True})

def test_catalog_rejects_duplicate_names() -> None:
    with pytest.raises(DuplicateGraphSpecificationError, match="heartbeat_recorded"):
        GraphCatalog.compose(
            event_specs=(HEARTBEAT_RECORDED, HEARTBEAT_RECORDED),
            command_specs=(),
        )
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `uv run pytest tests/unit/test_graph_payload_framework.py -q`

Expected: collection fails because `orchestrator.graph.payloads`, specifications, and catalog do not exist.

- [ ] **Automation checkpoint B: Apply representative mechanics before framework wiring**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain vertical_slice --apply`

After Steps 3–5, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain vertical_slice --assert-clean`

Expected: exit 0 and a second codemod pass produces no changes.

- [ ] **Step 3: Implement the strict base and envelope/specification interfaces**

```python
JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

class StrictPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, populate_by_name=True)

    def to_json(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.model_dump(mode="json", by_alias=True))

class StoredEventEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    event_id: str
    run_id: str
    position: int
    event_type: str
    payload_schema_generation: int
    actor: Actor
    causation_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime
    payload: dict[str, JsonValue]

class HydratedEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)
    metadata: EventMetadata
    payload: SerializeAsAny[StrictPayload]
```

Implement `EventSpecification.create()` to require the exact payload class, `hydrate()` to validate stored JSON once, `serialize()` to call `to_json()`, and `reduce()` to invoke its typed handler. Implement `CommandSpecification.validate()` and `handle()` with the same exact-class guarantee. Wrap internal generic casts inside these two specifications so domain handlers contain no casts.

- [ ] **Step 4: Implement an immutable duplicate-checking catalog**

```python
@dataclass(frozen=True)
class GraphCatalog:
    event_specs: Mapping[str, EventSpecification[Any]]
    command_specs: Mapping[str, CommandSpecification[Any]]

    @classmethod
    def compose(cls, event_specs: Iterable[EventSpecification[Any]], command_specs: Iterable[CommandSpecification[Any]]) -> "GraphCatalog":
        return cls(
            event_specs=MappingProxyType(_unique_by_name("event", event_specs)),
            command_specs=MappingProxyType(_unique_by_name("command", command_specs)),
        )

    @property
    def events(self) -> tuple[EventSpecification[Any], ...]:
        return tuple(self.event_specs.values())

    @property
    def commands(self) -> tuple[CommandSpecification[Any], ...]:
        return tuple(self.command_specs.values())
```

Resolution raises `UnknownGraphEventError` or `UnknownGraphCommandError`; duplicate composition raises `DuplicateGraphSpecificationError` during construction.

- [ ] **Step 5: Convert the representative heartbeat event and command**

```python
class HeartbeatRecordedPayload(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)
    observed_at: datetime

class RecordHeartbeatCommand(StrictPayload):
    node_id: str
    lease_id: str
    lease_generation: int = Field(ge=0)

HEARTBEAT_RECORDED = EventSpecification(
    name="heartbeat_recorded",
    payload_type=HeartbeatRecordedPayload,
    reducer=projection_neutral,
    projection_participation=ProjectionParticipation.NEUTRAL,
)
RECORD_HEARTBEAT = CommandSpecification(
    name="record_heartbeat",
    payload_type=RecordHeartbeatCommand,
    handler=handle_record_heartbeat,
)
```

The typed handler receives `RecordHeartbeatCommand`, uses the injected clock from `CommandExecutionContext`, and emits `HEARTBEAT_RECORDED.create(...)`. During migration, a temporary explicit compatibility bridge for unconverted specifications was marked by the architecture test as `_UNCONVERTED_W5_BRIDGE`. The completed cutover removed it in `b63146d9b`; `0289de70c` finalized typed consumers without a production payload adapter. All compatibility metrics are zero.

- [ ] **Step 6: Run focused and existing heartbeat tests**

Run: `uv run pytest tests/unit/test_graph_payload_framework.py tests/unit/test_lifecycle_event_payloads.py tests/unit/test_graph_commands.py -q`

Expected: all selected tests pass; the framework tests prove strict failure, exact-class creation, JSON round-trip, duplicate rejection, unknown-name errors, and projection-neutral dispatch.

- [ ] **Step 7: Commit the vertical slice**

```bash
git add src/orchestrator/graph tests/unit/test_graph_payload_framework.py
git commit -m "feat: add strict graph payload specifications"
```

---

### Task 2: Lifecycle, Callback, Retry, and Dispatch-Intent Domain

**Files:**
- Modify: `src/orchestrator/graph/events/lifecycle.py`
- Modify: `src/orchestrator/graph/commands/lifecycle.py`
- Modify: `src/orchestrator/graph/commands/callbacks.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Modify: `src/orchestrator/graph_runtime/outbox.py`
- Modify: `src/orchestrator/graph/callbacks.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `tests/unit/test_lifecycle_event_payloads.py`
- Modify: `tests/unit/test_callbacks.py`
- Modify: `tests/unit/test_graph_commands.py`

**Interfaces:**
- Produces ten event specs: lifecycle change, command rejection, four callback outcomes, retry scheduled, heartbeat, agent died, and dispatch requested.
- Produces eleven command specs: seven lifecycle commands plus `record_heartbeat`, `agent_died`, `acknowledge_start`, and `submit_callback`.
- Consumes framework types from Task 1.

- [ ] **Automation checkpoint A: Inventory and preview lifecycle/callback mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-lifecycle-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain lifecycle --dry-run`

Expected: the inventory identifies every lifecycle/callback producer, model, registry entry, import/export, and raw handler boundary; the dry-run changes no files and shows only structural edits.

- [ ] **Step 1: Replace compatibility assertions with strict RED tests**

Parameterize all ten payload classes and assert a valid sample passes while an added `unknown_field` and a mistyped required scalar fail. Add behavior tests proving audit events use `ProjectionParticipation.NEUTRAL` and callback/lifecycle reducers receive concrete payload classes.

Run: `uv run pytest tests/unit/test_lifecycle_event_payloads.py tests/unit/test_callbacks.py -q`

Expected: failures show current models still accept/move legacy fields and callback helpers still read dictionaries.

- [ ] **Automation checkpoint B: Apply structural edits before manual semantics**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain lifecycle --apply`

After the domain implementation steps below, run:

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain lifecycle --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain lifecycle`

Expected: both checks exit 0; no eligible lifecycle/callback site was left for a manual bulk edit.

- [ ] **Step 2: Define exact strict event models and specifications**

Use the current producer-written fields from the ledger/inventory, but make required producer invariants required. Explicitly model nullable callback business data as `payload: JsonValue` and `prior_result: JsonValue | None`; do not use these named fields to accept unknown top-level keys. Mark `command_rejected`, rejected/duplicate callbacks, heartbeat, agent death, and dispatch intent projection-neutral.

```python
LIFECYCLE_EVENT_SPECS = (
    RUN_LIFECYCLE_CHANGED,
    COMMAND_REJECTED,
    CALLBACK_ACCEPTED,
    CALLBACK_REJECTED_STALE,
    CALLBACK_REJECTED_CONFLICT,
    CALLBACK_DUPLICATE_RETURNED,
    RUNTIME_RETRY_SCHEDULED,
    HEARTBEAT_RECORDED,
    AGENT_DIED,
    AGENT_DISPATCH_REQUESTED,
)
```

- [ ] **Step 3: Define the eleven strict command models/specifications**

Use separate empty strict models where commands have no data. Put universal `run_id`, current position, clock, ID generation, actor, and historical hydrated events on `CommandExecutionContext`, not in command payloads. Remove `_current_graph_position` and controller-injected `run_id` from payload dictionaries.

```python
class EmptyLifecycleCommand(StrictPayload):
    pass

LIFECYCLE_COMMAND_SPECS = (
    ACCEPT_RUN, START, PAUSE, RESUME, CANCEL, COMPLETE, FAIL,
    RECORD_HEARTBEAT, AGENT_DIED_COMMAND, ACKNOWLEDGE_START, SUBMIT_CALLBACK,
)
```

- [ ] **Step 4: Move handler logic out of `_commands.py`**

Move lifecycle and callback domain functions into `commands/lifecycle.py` and `commands/callbacks.py`. Replace raw factory calls with named event specifications. Update callback idempotency and outbox routing to narrow `HydratedEvent.payload` with specification dispatch, never `event.payload.get(...)`.

- [ ] **Step 5: Run the lifecycle/callback slice**

Run: `uv run pytest tests/unit/test_graph_payload_framework.py tests/unit/test_lifecycle_event_payloads.py tests/unit/test_callbacks.py tests/unit/test_graph_commands.py tests/unit/test_outbox_retry.py -q`

Expected: pass; strict samples reject extra/mistyped fields and all eleven command specs execute typed handlers.

- [ ] **Step 6: Commit the domain slice**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime/controller.py src/orchestrator/graph_runtime/outbox.py tests/unit
git commit -m "refactor: type lifecycle and callback graph domains"
```

---

### Task 3: Topology, Node, Session, Input, and Revision Domain

**Files:**
- Create: `src/orchestrator/graph/events/topology.py`
- Modify: `src/orchestrator/graph/compiler.py`
- Modify: `src/orchestrator/graph/commands/schedule.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/command_bindings.py`
- Modify: `src/orchestrator/graph/patch_validator.py`
- Modify: `tests/unit/test_node_created_event_payloads.py`
- Modify: `tests/unit/test_node_lifecycle_event_payloads.py`
- Modify: `tests/unit/test_planner_session_event_payloads.py`
- Modify: `tests/unit/test_graph_compiler.py`
- Modify: `tests/unit/test_graph_projections.py`

**Interfaces:**
- Produces twelve event specs: seven node lifecycle names plus `edge_created`, `input_bound`, `session_state_changed`, `dead_input_detected`, and `revision_created`.
- Produces `SeedCompiledEventsCommand` and `SEED_COMPILED_EVENTS`.
- Changes `compile_routine(..., catalog: GraphCatalog)` to return `list[HydratedEvent]`.

- [ ] **Automation checkpoint A: Inventory and preview topology mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-topology-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain topology --dry-run`

Expected: all compiler/factory construction sites, topology payload classes, reducer branches, imports, and exports are classified before production edits.

- [ ] **Step 1: Write strict producer and typed reducer RED tests**

Add parameterized samples for all twelve names. Assert `node_created` accepts the complete current compiler/patch producer shape, rejects every historical alias and unknown key, and preserves explicitly typed opaque fields (`command_definition`, policy metadata, and record values) only under their named fields.

Run: `uv run pytest tests/unit/test_node_created_event_payloads.py tests/unit/test_node_lifecycle_event_payloads.py tests/unit/test_planner_session_event_payloads.py tests/unit/test_graph_compiler.py -q`

Expected: legacy normalizers accept cases the strict tests reject, and compiler events still contain raw dictionaries.

- [ ] **Automation checkpoint B: Apply and prove topology codemod idempotency**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain topology --apply`

After semantic implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain topology --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain topology`

Expected: exit 0 with zero eligible topology sites remaining.

- [ ] **Step 2: Move payloads and reducer handlers into `events/topology.py`**

Define `EdgeCreatedPayload`, `InputBoundPayload`, and the strict node/session/revision payloads. Remove `NodeSuspectPayload` aliases for unproduced cleared/resolved names. Move each matching `reduce_event` branch and its private payload parser into a typed handler such as:

```python
def reduce_node_deferred(state: GraphProjection, payload: NodeDeferredPayload, meta: EventMetadata) -> GraphProjection:
    next_state = copy_projection(state)
    next_state["last_node_deferrals"][payload.node_id] = payload.reason
    return next_state
```

Handlers may call projection-state utilities, but may not validate or inspect raw dictionaries.

- [ ] **Step 3: Convert compiler construction and seed command**

Inject the catalog or a typed `EventBuilder` into `compile_routine`; replace `_Compiler._event(event_type, payload)` with named specifications. Define:

```python
class SeedCompiledEventsCommand(StrictPayload):
    events: tuple[HydratedEvent, ...]
```

Validate every nested event is already hydrated and registered before returning it from the seed handler.

- [ ] **Step 4: Convert topology consumers outside the reducer**

Update command bindings, patch invalidation checks, compiler helpers, scenario fixtures, and projection view helpers to use concrete payload classes or typed projection records. Remove replay-only suspect, legacy input-binding, and sparse-node fallback branches.

- [ ] **Step 5: Run topology and corpus parity tests**

Run: `uv run pytest tests/unit/test_node_created_event_payloads.py tests/unit/test_node_lifecycle_event_payloads.py tests/unit/test_planner_session_event_payloads.py tests/unit/test_graph_compiler.py tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py -q`

Expected: pass with no duplicate recovery-node index entry and identical full/checkpoint/compact projections.

- [ ] **Step 6: Commit the domain slice**

```bash
git add src/orchestrator/graph tests/unit/test_node_created_event_payloads.py tests/unit/test_node_lifecycle_event_payloads.py tests/unit/test_planner_session_event_payloads.py tests/unit/test_graph_compiler.py tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py
git commit -m "refactor: type topology and node graph domains"
```

---

### Task 4: Lease and Scheduling Domain

**Files:**
- Create: `src/orchestrator/graph/events/leases.py`
- Modify: `src/orchestrator/graph/commands/schedule.py`
- Modify: `src/orchestrator/graph/scheduler.py`
- Modify: `src/orchestrator/graph/callbacks.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `tests/unit/test_lease_event_payloads.py`
- Modify: `tests/unit/test_scheduler.py`
- Modify: `tests/unit/test_graph_commands.py`

**Interfaces:**
- Produces five event specs: granted, renewed, released, revoked, expired.
- Produces `ScheduleTickCommand`, `ReconcileCommand`, `SCHEDULE_TICK`, and `RECONCILE`.
- Deletes unproduced `lease_suspended` compatibility support.

- [ ] **Automation checkpoint A: Inventory and preview lease mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-leases-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain leases --dry-run`

Expected: all five live lease names and two scheduling commands are classified; `lease_suspended` is reported as compatibility-only.

- [ ] **Step 1: Write strict lease/command RED tests**

Assert required IDs/generation/timestamps/resource claims reject missing or coerced values; assert grant/release/revoke/expire handlers receive the exact model; assert the empty reconcile command rejects any field.

Run: `uv run pytest tests/unit/test_lease_event_payloads.py tests/unit/test_scheduler.py tests/unit/test_graph_commands.py -q`

Expected: current compatibility models accept sparse and extra input.

- [ ] **Automation checkpoint B: Apply and prove lease codemod idempotency**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain leases --apply`

After semantic implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain leases --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain leases`

Expected: exit 0 with no raw lease producer/handler/model relocation left.

- [ ] **Step 2: Implement lease payloads/specifications and typed reducers**

Use `tuple[ResourceClaimProjection, ...]` for resource claims and exact nullable fields for optional session identity. Do not derive legacy `task_region_id` or `kind` from an `extra` map; the current producer must emit every reducer-required fact or the typed handler derives it only from already typed projection state.

- [ ] **Step 3: Implement scheduling command specifications**

`ScheduleTickCommand` explicitly declares lease duration, grant limit, and base snapshot identity. `ReconcileCommand` is empty. Move the scheduling/reconciliation logic from `_commands.py` into `commands/schedule.py` and emit only named specs.

- [ ] **Step 4: Run lease/scheduler regression tests**

Run: `uv run pytest tests/unit/test_lease_event_payloads.py tests/unit/test_scheduler.py tests/unit/test_graph_commands.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py -q`

Expected: pass; there is no `lease_suspended` event specification in the catalog and no strict-path support for it. (Historical amendment 2026-07-12: the `lease_suspended` branches inside `reduce_legacy_event` and `_planner_generation_state`, and the `GraphRecordKind.LEASE_SUSPENDED` enum member were retained through Task 9 for durable replay, then deleted by Task 13 after Branch B fresh initialization. Register entry D1 is closed.)

- [ ] **Step 5: Commit the domain slice**

```bash
git add src/orchestrator/graph tests/unit/test_lease_event_payloads.py tests/unit/test_scheduler.py tests/unit/test_graph_commands.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py
git commit -m "refactor: type lease and scheduling graph domains"
```

---

### Task 5: Records, Verification, Join, Final Gate, and Strict Grades

**Files:**
- Create: `src/orchestrator/graph/events/records.py`
- Modify: `src/orchestrator/graph/commands/records.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/contracts.py`
- Modify: `tests/unit/test_graph_models.py`
- Modify: `tests/unit/test_graph_commands.py`
- Modify: `tests/unit/test_graph_projections.py`
- Modify: `tests/integration/test_graph_fr14_final_gate_acceptance.py`

**Interfaces:**
- Produces `OutputRecordAcceptedPayload`, `VerificationOutcomePayload`, and three event specs.
- Produces strict `EvaluateJoinCommand`, `EvaluateFinalGateCommand`, `EVALUATE_JOIN`, and `EVALUATE_FINAL_GATE`.
- Produces strict `GradeRow`; `VerificationReportValue.grades: list[GradeRow]`.

- [ ] **Automation checkpoint A: Inventory and preview record mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-records-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain records --dry-run`

Expected: output/verification event emissions, record model relocations, command registry entries, and reducer parse sites are classified without interpreting record semantics.

- [ ] **Step 1: Write strict record envelope and grade RED tests**

```python
def test_grade_row_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GradeRow.model_validate({"requirement_id": "r-1", "grade": "pass", "typo": 1})

def test_output_record_event_rejects_unknown_record_shape() -> None:
    with pytest.raises(ValidationError):
        OutputRecordAcceptedPayload.model_validate({"record": {"record_id": "x"}})
```

Use the existing discriminated typed record union as the `record` field; do not duplicate every record's fields at the event top level.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_commands.py -q`

Expected: `grades` is still `list[dict[str, Any]]`, and output event parsing still depends on raw payload discriminators.

- [ ] **Automation checkpoint B: Apply and prove record codemod idempotency**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain records --apply`

After semantic implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain records --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain records`

Expected: exit 0; record union/grade semantics are the only manual portion.

- [ ] **Step 3: Implement strict record/verification event specifications**

Use a discriminated `OutputRecordPayload` union and explicit verification fields. Move record acceptance and verification reducers into `events/records.py`; delete legacy output-record parsing, sparse verification fallbacks, and repeated `value.get(...)` logic **from the strict specification path only**. (Historical amendment 2026-07-12: legacy parsing reachable only through `reduce_legacy_event` or full-history scans was retained through Task 9 so durable history could replay. Task 13 deleted those D3 sites after Branch B fresh initialization; D3 is closed.)

- [ ] **Step 4: Implement join/final-gate command specifications**

Declare candidate, node, task-region, evaluated-record, and decision fields explicitly. Move handlers from `_commands.py`; accept typed record/projection inputs and emit `OUTPUT_RECORD_ACCEPTED`, `VERIFICATION_PASSED`, or `VERIFICATION_FAILED` specifications.

- [ ] **Step 5: Run record, projection, and final-gate tests**

Run: `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_fr14_final_gate_acceptance.py -q`

Expected: pass with strict grade rows and identical final-gate behavior.

- [ ] **Step 6: Commit the domain slice**

```bash
git add src/orchestrator/graph tests/unit/test_graph_models.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_fr14_final_gate_acceptance.py
git commit -m "refactor: type graph record and verification domains"
```

---

### Task 6: Patch Domain

**Files:**
- Create: `src/orchestrator/graph/events/patches.py`
- Modify: `src/orchestrator/graph/commands/patches.py`
- Modify: `src/orchestrator/graph/patch_validator.py`
- Modify: `src/orchestrator/graph/macros.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph_runtime/prompts.py`
- Modify: `tests/unit/test_patch_event_payloads.py`
- Modify: `tests/unit/test_patch_validator.py`
- Modify: `tests/unit/test_graph_commands.py`

**Interfaces:**
- Produces two event specs: accepted and rejected.
- Produces `SubmitPatchCommand` and `SUBMIT_PATCH`.
- Intentionally keeps `ops`, `macro_invocations`, diagnostics, and read-set diff as explicit named `JsonValue`/typed patch fields, never unknown top-level keys.

- [ ] **Automation checkpoint A: Inventory and preview patch mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-patches-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain patches --dry-run`

Expected: the report separates the two live patch events from compatibility-only aliases and classifies every producer/parser/import site.

- [ ] **Step 1: Write strict patch RED tests**

Assert only `graph_patch_accepted` and `graph_patch_rejected` are registered; proposal/status replay aliases are absent. Assert misspelled `base_graph_position`, scalar/list mismatches, and unknown top-level diagnostics fail.

Run: `uv run pytest tests/unit/test_patch_event_payloads.py tests/unit/test_patch_validator.py -q`

Expected: proposal aliases remain accepted and unknown fields move under `extra`.

- [ ] **Automation checkpoint B: Apply and prove patch codemod idempotency**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain patches --apply`

After semantic implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain patches --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain patches`

Expected: exit 0; opaque named patch values remain manual semantic choices, not codemod-generated schema.

- [ ] **Step 2: Implement patch models/specifications and typed reducers**

Move accepted/rejected attempt updates into `events/patches.py`. Keep `PatchEnvelope`/`PatchOp` as the typed business value for operations. Remove open-proposal replay bookkeeping from the strict specification path. (Historical amendment 2026-07-12: the `graph_patch_proposed`/proposal-status bookkeeping inside `reduce_legacy_event` and the blocker/attempt scan helpers was retained through Task 9. Task 13 deleted those D2 sites after Branch B fresh initialization; D2 is closed.)

- [ ] **Step 3: Implement the strict submit command and move its handler**

`SubmitPatchCommand` declares patch ID, base position, actor role, proposer, operations, session/carryover identity, and named diagnostic values. The controller reads `payload.base_graph_position` from the validated model rather than `_patch_base_graph_position(dict)`.

- [ ] **Step 4: Run patch and planner prompt tests**

Run: `uv run pytest tests/unit/test_patch_event_payloads.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_prompt_generation.py tests/unit/test_graph_planner.py -q`

Expected: pass with two patch event specs and one command spec.

- [ ] **Step 5: Commit the domain slice**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime/prompts.py tests/unit/test_patch_event_payloads.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_prompt_generation.py tests/unit/test_graph_planner.py
git commit -m "refactor: type graph patch domain"
```

---

### Task 7: Appeals, Decisions, Requirements, and Evidence Domains

**Files:**
- Create: `src/orchestrator/graph/events/decisions.py`
- Create: `src/orchestrator/graph/events/requirements.py`
- Modify: `src/orchestrator/graph/commands/callbacks.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `tests/unit/test_decision_event_payloads.py`
- Modify: `tests/unit/test_requirement_evidence_event_payloads.py`
- Modify: `tests/integration/test_graph_decisions_api.py`

**Interfaces:**
- Produces six event specs: appeal opened, three decisions, requirement revision, support evidence.
- Produces four command specs: raise appeal, record decision, record requirement revision, record support evidence.
- Keeps `scope`, `decider`, provenance, and evidence as explicitly named JSON/business values.

- [ ] **Automation checkpoint A: Inventory and preview both policy domains**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-policy-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain decisions --dry-run`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain requirements --dry-run`

Expected: live names, compatibility-only aliases, shared wrapper sites, and all model/registry/reducer locations are classified before edits.

- [ ] **Step 1: Write strict decision/requirement RED tests**

Remove assertions for `decision`/`outcome`/`verdict` aliases, boolean decision fallback, nested legacy membership, requirement/support aliases, and sparse history. Add exact valid producer samples and extra/mistyped/missing-field rejection for all six event and four command models.

Run: `uv run pytest tests/unit/test_decision_event_payloads.py tests/unit/test_requirement_evidence_event_payloads.py -q`

Expected: compatibility validators still accept at least one rejected sample.

- [ ] **Automation checkpoint B: Apply and prove both codemods idempotent**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain decisions --apply`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain requirements --apply`

After semantic implementation, run:

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain decisions --assert-clean`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain requirements --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain decisions`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain requirements`

Expected: all four checks exit 0; no shared wrapper was hand-rewritten around the codemod.

- [ ] **Step 2: Implement decision and requirement event modules**

Define separate payload models when semantics differ; do not use one permissive decision base with many optional aliases. Move latest-decision, appeal resolution, authority requirement, revision, and evidence reducers into their owning modules. (Historical amendment 2026-07-12: the `requirement_revision_proposed` and `authority_resolution_recorded` branches, `_requires_authority_resolution(dict)`, and authority blocker/full-history scans were retained as D4 through Task 9. Task 13 deleted them after Branch B fresh initialization; D4 is closed.)

- [ ] **Step 3: Implement four strict command specifications**

Move the matching command logic into `commands/callbacks.py` or split it into `commands/decisions.py` and `commands/requirements.py` if either file would exceed a cohesive review unit. Each handler accepts its concrete command model and emits named specs only.

- [ ] **Step 4: Run domain and API tests**

Run: `uv run pytest tests/unit/test_decision_event_payloads.py tests/unit/test_requirement_evidence_event_payloads.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_decisions_api.py -q`

Expected: pass; invalid constrained API values return 422 from Pydantic and accepted commands preserve decision/revision semantics.

- [ ] **Step 5: Commit the domain slice**

```bash
git add src/orchestrator/graph tests/unit/test_decision_event_payloads.py tests/unit/test_requirement_evidence_event_payloads.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_decisions_api.py
git commit -m "refactor: type graph decision and requirement domains"
```

---

### Task 8: File-State, Gatekeeper, and Cleanup Domain

**Files:**
- Create: `src/orchestrator/graph/events/file_state.py`
- Modify: `src/orchestrator/graph/commands/callbacks.py`
- Modify: `src/orchestrator/graph/file_state.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph_runtime/file_state.py`
- Modify: `src/orchestrator/graph_runtime/gatekeeper.py`
- Modify: `src/orchestrator/graph_runtime/dispatch.py`
- Modify: `tests/unit/test_cleanup_event_payloads.py`
- Modify: `tests/unit/test_graph_gatekeeper.py`
- Modify: `tests/integration/test_graph_file_state_boundary.py`
- Modify: `tests/integration/test_graph_gatekeeper_flow.py`

**Interfaces:**
- Produces six event specs: file accepted/rejected, gatekeeper verdict/cost, cleanup requested/applied.
- Produces `RecordGatekeeperVerdictsCommand`, `RecordCleanupAppliedCommand`, and their specs.
- Uses existing typed `FileStateRecord` and concrete gatekeeper verdict/cost models.

- [ ] **Automation checkpoint A: Inventory and preview file-state mechanics**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-file-state-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain file_state --dry-run`

Expected: all six event producers, two command entries, runtime consumers, payload classes, and compatibility-only environment aliases are classified.

- [ ] **Step 1: Write strict file-state/gatekeeper/cleanup RED tests**

Assert complete current producer shapes round-trip, malformed nested verdict/file entries fail, `resolved_count` and cost fields remain explicit, and audit `file_state_rejected` is registered as projection-neutral. Remove legacy environment/check-result alias tests because neither event is produced. (Historical amendment 2026-07-12: the `environment_failure_accepted`/`check_result_classified` reducer branches and classification scan were retained as D5 through Task 9. Task 13 deleted them after Branch B fresh initialization; D5 is closed.)

Run: `uv run pytest tests/unit/test_cleanup_event_payloads.py tests/unit/test_graph_gatekeeper.py -q`

Expected: cleanup still preserves unknown keys and gatekeeper consumers still parse dictionaries.

- [ ] **Automation checkpoint B: Apply and prove file-state codemod idempotency**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain file_state --apply`

After semantic implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain file_state --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain file_state`

Expected: exit 0; nested file/verdict/cost semantics are reviewed manually after structural conversion.

- [ ] **Step 2: Implement the six event specifications and typed handlers**

Use `FileStateRecord` as the accepted payload business record, explicit rejection evidence, `tuple[GatekeeperVerdict, ...]`, a concrete cost model, and exact cleanup fields. Move projection and cost-summary handlers into `events/file_state.py` or typed view helpers; no handler accepts `dict[str, Any]`.

- [ ] **Step 3: Implement the two strict command specifications**

Move gatekeeper/cleanup command logic from `_commands.py`; update runtime dispatch to construct the models once before controller dispatch and consume typed result events.

- [ ] **Step 4: Run domain and integration tests**

Run: `uv run pytest tests/unit/test_cleanup_event_payloads.py tests/unit/test_graph_gatekeeper.py tests/unit/test_graph_projections.py tests/integration/test_graph_file_state_boundary.py tests/integration/test_graph_gatekeeper_flow.py -q`

Expected: pass with all cost fields retained and cleanup lineage unchanged.

- [ ] **Step 5: Commit the domain slice**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_cleanup_event_payloads.py tests/unit/test_graph_gatekeeper.py tests/unit/test_graph_projections.py tests/integration/test_graph_file_state_boundary.py tests/integration/test_graph_gatekeeper_flow.py
git commit -m "refactor: type file-state and gatekeeper graph domains"
```

---

### Task 9: Complete Catalog Composition and Typed Dispatch Cutover

**Files:**
- Modify: `src/orchestrator/graph/catalog.py`
- Modify: `src/orchestrator/graph/events/__init__.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/projections.py`
- Delete: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Create: `tests/unit/test_graph_catalog_contracts.py`
- Modify: all existing W5 payload test files

**Interfaces:**
- `build_graph_catalog()` returns exactly 44 unique event specs and 23 unique command specs.
- `apply_command(catalog, projection, events, command_name, payload, context)` validates once and dispatches typed.
- `reduce_event(catalog, projection, hydrated_event)` dispatches typed with no event-name branch.

- [ ] **Automation checkpoint A: Inventory the remaining cross-domain cutover**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-catalog-cutover-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_cutover --dry-run`

Expected: the preview covers tuple composition, registry removal, central reducer branch removal, compatibility symbol deletion, imports, and exports; any branch whose semantics cannot be moved automatically is reported with its owning specification.

- [ ] **Step 1: Write catalog-wide RED contracts**

```python
@pytest.mark.parametrize("spec", build_graph_catalog().events, ids=lambda spec: spec.name)
def test_every_event_spec_is_strict_and_round_trips(spec: EventSpecification[Any]) -> None:
    sample = EVENT_SAMPLES[spec.name]
    payload = spec.validate_payload(sample)
    stored = spec.serialize(spec.create(TEST_METADATA, payload))
    assert spec.hydrate(stored).payload == payload
    with pytest.raises(ValidationError):
        spec.validate_payload({**sample, "unknown_field": True})

def test_catalog_has_complete_live_surface() -> None:
    catalog = build_graph_catalog()
    assert len(catalog.events) == 44
    assert len(catalog.commands) == 23
    assert all(spec.reducer is not None for spec in catalog.events)
```

Also parameterize missing/mistyped required-field cases, projection-neutral declarations, command strictness, JSON schema generation, and unique names.

- [ ] **Automation checkpoint B: Apply catalog cutover mechanics before semantic cleanup**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_cutover --apply`

After Steps 2–4, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_cutover --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain catalog_cutover`

Expected: exit 0; no registry/central-dispatch/compatibility site eligible for mechanical conversion remains.

- [ ] **Step 2: Compose the production catalog from domain tuples**

```python
def build_graph_catalog() -> GraphCatalog:
    return GraphCatalog.compose(
        event_specs=(*LIFECYCLE_EVENT_SPECS, *TOPOLOGY_EVENT_SPECS, *LEASE_EVENT_SPECS,
                     *RECORD_EVENT_SPECS, *PATCH_EVENT_SPECS, *DECISION_EVENT_SPECS,
                     *REQUIREMENT_EVENT_SPECS, *FILE_STATE_EVENT_SPECS),
        command_specs=(*LIFECYCLE_COMMAND_SPECS, *CALLBACK_COMMAND_SPECS,
                       *PATCH_COMMAND_SPECS, *RECORD_COMMAND_SPECS, *SCHEDULE_COMMAND_SPECS),
    )
```

The tuple names are public domain APIs; adding a normal event/command to an existing domain edits only its domain tuple, not `catalog.py`.

- [ ] **Step 3: Cut current command and reducer dispatch to catalog-only paths**

Delete `COMMAND_HANDLERS`, current-path per-event parse wrappers, `_typed_*` helpers, and `_UNCONVERTED_W5_BRIDGE` only where they are proven unreachable from durable replay. Current typed dispatch resolves catalog specifications and never falls through to legacy handling; unknown current names raise typed catalog errors, while a deliberately invalid known command may still produce `command_rejected` after its typed handler evaluates domain rules. Task 9 retained `reduce_legacy_event`, all D1–D6 callers, and typed-spec reducers required for durable replay. Task 13 deleted them after Branch B fresh initialization established the current strict schema.

- [ ] **Step 4: Delete compatibility models, validators, aliases, and `_commands.py`**

Remove only obsolete strict-path W5 payload classes, exports, validators, and `_commands.py` content proven non-replay-critical. Keep D1–D6 compatibility helpers, aliases, models, and validators isolated to legacy replay. Delete `_commands.py` in this task only if every replay-critical caller has first been retained in an explicit legacy module without changing replay; otherwise defer file deletion to Task 13.

**Task 9 did not sweep the Deferred Compatibility Cleanup Register.** D1–D6 remained through Task 9 and were deleted in Task 13 after Branch B fresh initialization; no backup/reset was necessary.

- [ ] **Step 5: Run catalog and full unit graph tests**

Run: `uv run pytest tests/unit/test_graph_catalog_contracts.py tests/unit/test_graph_payload_framework.py tests/unit -k 'graph or payload or callback or scheduler' -q`

Expected: pass; catalog counts are exactly 44/23 and no test constructs a live raw payload envelope.

- [ ] **Step 6: Commit the catalog cutover**

```bash
git add src/orchestrator/graph tests/unit
git commit -m "refactor: cut graph kernel to strict catalog dispatch"
```

---

### Task 10: Inject Catalog Through Composition Roots and Persistence

**Files:**
- Modify: `src/orchestrator/api/app.py`
- Modify: `src/orchestrator/api/deps.py`
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `src/orchestrator/graph_runtime/dispatch.py`
- Modify: `src/orchestrator/graph_runtime/recovery.py`
- Modify: `src/orchestrator/graph_runtime/seeding.py`
- Modify: `src/orchestrator/graph_runtime/errors.py`
- Modify: `src/orchestrator/graph_runtime/__init__.py`
- Modify: `src/orchestrator/workflow/service.py`
- Modify: `src/orchestrator/workflow/graph_driver.py`
- Modify: `src/orchestrator/db/orm/models.py`
- Create: `src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_add_graph_payload_schema_generation.py`
- Modify: `tests/integration/test_graph_event_store.py`
- Modify: `tests/integration/test_graph_controller_transactions.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces:**
- `GraphEventStore(session, catalog)`, `GraphController(session_factory, catalog, clock, id_gen, ...)`, `compile_routine(..., catalog=...)`, and graph runtime factories require explicit catalog injection.
- Stored graph rows use `GRAPH_PAYLOAD_SCHEMA_GENERATION = 2` and hydrate before returning from any store read.
- Produces `EventPayloadCorruptionError(run_id, position, event_type, detail)` and `IncompatibleGraphPayloadGenerationError`.

- [ ] **Automation checkpoint A: Inventory constructor/call-site injection**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-injection-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_injection --dry-run`

Expected: every `GraphEventStore`, `GraphController`, compiler, runtime, workflow, and API construction site is resolved by qualified name and included in the preview; ambiguous test factories are reported rather than guessed.

- [ ] **Step 1: Write injection, generation, and corruption RED tests**

Assert constructors fail type checking/call sites without a catalog, duplicate catalog construction fails before app startup, a stored row with generation 1 fails clearly, and invalid JSON payload details include run ID, position, and event name.

Run: `uv run pytest tests/integration/test_graph_event_store.py tests/integration/test_graph_controller_transactions.py tests/integration/test_migrations.py -q`

Expected: current store hydrates `EventEnvelope` with raw dictionaries and has no generation check.

- [ ] **Automation checkpoint B: Apply repeated injection edits before storage semantics**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_injection --apply`

After constructor/composition implementation, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain catalog_injection --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain catalog_injection`

Expected: exit 0; manual work is limited to choosing ownership/lifetime of the injected catalog and implementing persistence errors/generation rules.

- [ ] **Step 2: Add the envelope generation column and migration**

```python
payload_schema_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

The Alembic upgrade adds a nullable column because `events_v2` also stores non-graph workflow events. `GraphEventStore.append_events()` always writes generation 2; graph reads require exactly 2. No data migration or old graph payload conversion is added.

- [ ] **Step 3: Serialize typed events and hydrate exactly once**

`append_events()` converts `HydratedEvent` to `StoredEventEnvelope`, adds durable run/position metadata, and writes JSON. `read_run()` validates the stored envelope then calls `catalog.hydrate_event()` once. Translate stored-envelope/Pydantic failures to `EventPayloadCorruptionError` with structured context.

- [ ] **Step 4: Thread the catalog through every construction site**

Build one immutable catalog in `create_app()` and pass it through API dependencies/service factories. Add `GraphCatalog` constructor parameters to `GraphDriver`/workflow services and graph runtime builders. Tests construct a real catalog via `build_graph_catalog()` or a small real test catalog; no default global is introduced.

- [ ] **Step 5: Make FastAPI command endpoints use the same models**

Alias or directly use `SubmitPatchCommand` and `RecordDecisionCommand` as request schemas, adding only HTTP-owned fields in thin API models when response/documentation concerns require them. Controller resolution validates generic/internal callers. Remove duplicate request-field definitions and dictionary coercion.

- [ ] **Step 6: Run persistence, controller, API, and migration tests**

Run: `uv run pytest tests/integration/test_graph_event_store.py tests/integration/test_graph_controller_transactions.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_migrations.py -q`

Expected: pass; malformed persisted JSON and generation mismatch raise the new domain errors before reducer execution.

- [ ] **Step 7: Commit persistence and injection**

```bash
git add src/orchestrator/api src/orchestrator/graph_runtime src/orchestrator/workflow src/orchestrator/db tests/integration
git commit -m "refactor: inject strict graph catalog through persistence"
```

---

### Task 11: Complete Payload Reads and Typed Projection Records

**Files:**
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `src/orchestrator/db/access/activity_summaries.py`
- Delete: `tests/unit/test_graph_payload_field_allowlists.py`
- Modify: `tests/unit/test_fixture_corpus.py`
- Modify: `tests/unit/test_graph_projections.py`
- Modify: `tests/integration/test_graph_read_models.py`
- Modify: `tests/integration/test_graph_node_detail_read_models.py`

**Interfaces:**
- `read_run_light`, `read_run_summary_rebuild`, `read_run_projection`, and `read_run_node_detail` all return fully hydrated events with complete payloads.
- Checkpoint and summary rows serialize complete strict payloads; API summary mode transforms only after hydration.

- [ ] **Automation checkpoint A: Inventory partial-read definitions and consumers**

Run: `uv run python scripts/w5_payload_ast_inventory.py --format json --output /tmp/w5-read-paths-before.json`

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain complete_reads --dry-run`

Expected: all four constants, `_read_run_extracting_fields`, nested extraction fallbacks, light-event reconstruction, imports, and test references appear in the structural preview.

- [ ] **Step 1: Write complete-payload parity RED tests**

For every catalog sample event, append it once and assert each read method returns the same `payload.to_json()` as `read_run()`. Assert checkpoint replay, summary rebuild, node detail, and full replay yield equal projections and event payloads.

Run: `uv run pytest tests/unit/test_fixture_corpus.py tests/integration/test_graph_read_models.py tests/integration/test_graph_node_detail_read_models.py -q`

Expected: extracted read paths omit fields for at least one complete sample.

- [ ] **Automation checkpoint B: Apply allowlist/read-path mechanics before projection semantics**

Run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain complete_reads --apply`

After complete-payload and typed-projection changes, run: `uv run python scripts/codemods/w5_strict_payload_cutover.py --domain complete_reads --assert-clean`

Run: `uv run python scripts/w5_payload_ast_inventory.py --check-domain complete_reads`

Expected: exit 0 with no partial-event extraction site or allowlist reference remaining.

- [ ] **Step 2: Delete all four allowlists and JSON extraction reconstruction**

Remove `GRAPH_PROJECTION_PAYLOAD_FIELDS`, `LIGHT_GRAPH_PAYLOAD_FIELDS`, `SUMMARY_REBUILD_PAYLOAD_FIELDS`, `NODE_DETAIL_PAYLOAD_FIELDS`, `_read_run_extracting_fields`, nested value fallback extraction, `_node_detail_light_event`, and `_json_extract_payload_value`. Implement the four public methods as named semantic entry points over the complete stored-envelope query/hydration path so callers remain readable without partial events.

- [ ] **Step 3: Store complete payloads in disposable summaries/checkpoints**

Stop compacting payloads before `GraphEventSummaryModel` and node-detail/checkpoint reconstruction. Keep explicit summary presentation logic in `activity_summaries.py` and the API after hydration; it returns a response summary, never a substitute event envelope.

- [ ] **Step 4: Replace remaining payload-shaped projection maps**

Convert W5-owned raw shapes to concrete Pydantic models: topology edge/binding contract records, graph patch attempts, gatekeeper report/cost rows, planner generation/session rows, and accepted record summaries. Leave deliberately opaque named business values typed as `JsonValue`; do not convert unrelated response dictionaries solely to reach a count.

- [ ] **Step 5: Run read-path parity and graph integration tests**

Run: `uv run pytest tests/unit/test_fixture_corpus.py tests/unit/test_graph_projections.py tests/integration/test_graph_event_store.py tests/integration/test_graph_read_models.py tests/integration/test_graph_node_detail_read_models.py -q`

Expected: pass; all read modes return complete payloads and all projection variants agree.

- [ ] **Step 6: Record complete-read measurements**

Run before/after comparisons with `scripts/profile_graph_readback.py` on the fixture corpus and a representative generated run. Record wall time, rows, serialized payload bytes, and peak memory in the ledger. Do not restore field allowlists. If complete reads show a repeatable production-blocking regression, pause for an explicit design amendment backed by measurements; any accepted optimization must be generated from catalog models.

- [ ] **Step 7: Commit complete read paths**

```bash
git add src/orchestrator/graph src/orchestrator/graph_runtime src/orchestrator/api/routers/graph.py src/orchestrator/db/access/activity_summaries.py tests
git commit -m "refactor: carry complete strict graph payloads"
```

---

### Task 12: Architecture Enforcement and Change-Spread Gates

**Files:**
- Create: `scripts/check_graph_payload_architecture.py`
- Create: `scripts/measure_graph_payload_architecture.py`
- Create: `tests/unit/test_graph_payload_architecture.py`
- Create: `tests/unit/test_graph_change_spread.py`
- Modify: `.pre-commit-config.yaml`
- Modify: `tests/unit/test_graph_catalog_contracts.py`

**Interfaces:**
- Static guard exits nonzero with file/line/rule diagnostics.
- Metrics script emits stable JSON and Markdown containing catalog and forbidden-pattern counts.
- `check_graph_payload_architecture.py` imports and evaluates the shared AST facts from `w5_payload_ast_inventory.py`; it does not implement a second scanner.

- [ ] **Step 1: Write failing guard self-tests**

Create temporary source fixtures containing each banned pattern and assert the checker reports it: raw `event.payload.get`/indexing, boundary `payload: dict[str, Any]`, direct event construction with dictionary payload, the four allowlist names, W5 `mode="before"` payload normalization, top-level payload `extra`, `COMMAND_HANDLERS`, and event-name branching in `reduce_event`.

Run: `uv run pytest tests/unit/test_graph_payload_architecture.py -q`

Expected: fails because the checker does not exist.

- [ ] **Step 2: Implement the AST/static checker**

Build rules on `scan_graph_payload_architecture()` from Task 0. Scope checks to `src/orchestrator/graph`, graph-facing runtime/controller/store code, and command/event boundaries. Permit raw JSON only in named storage/API adapter functions. Diagnostics must name the rule and exact location; do not use broad text matches that flag typed projection serialization.

- [ ] **Step 3: Add measurable generic change-spread exercises**

In `test_graph_change_spread.py`, define a test-local event and command domain with strict payloads. Prove that adding a second model field automatically changes JSON schema, serialization, hydration, API-ready dump, round-trip contract coverage, and typed dispatch without editing storage/catalog framework code. Prove a new spec joins a domain tuple and is composed without central dispatch edits.

- [ ] **Step 4: Implement and run the metrics gate**

The metrics output must meet all targets:

```text
registered_event_specs = 44
registered_command_specs = 23
event_payload_raw_reads_in_kernel = 0
raw_event_or_command_boundary_dict_annotations = 0
direct_dictionary_event_construction_sites = 0
hand_maintained_payload_field_allowlists = 0
w5_legacy_payload_before_validators = 0
w5_top_level_payload_extra_fields = 0
central_command_handler_tables = 0
central_reduce_event_name_branches = 0
eligible_ast_cst_migration_sites_remaining = 0
codemod_second_run_changes = 0
unclassified_dynamic_event_or_command_sites = 0
```

Record the current before values in the ledger: 627 `isinstance(` calls across `_commands.py` + `projections.py`, 174 `dict[str, Any]` occurrences in `projections.py`, 86 `event.payload.get(` calls, 6 `event.payload[` calls, 42 relevant before validators in the surveyed W5 files, and 5 top-level payload `extra` declarations.

- [ ] **Step 5: Add the checker to pre-commit and run gates**

Run: `uv run python scripts/check_graph_payload_architecture.py`

Run: `uv run pytest tests/unit/test_graph_payload_architecture.py tests/unit/test_graph_change_spread.py tests/unit/test_graph_catalog_contracts.py -q`

Run: `uv run ruff check scripts/check_graph_payload_architecture.py scripts/measure_graph_payload_architecture.py tests/unit/test_graph_payload_architecture.py tests/unit/test_graph_change_spread.py`

Run: `uv run pyright scripts/check_graph_payload_architecture.py scripts/measure_graph_payload_architecture.py tests/unit/test_graph_payload_architecture.py tests/unit/test_graph_change_spread.py`

Expected: checker exits 0, tests pass, and every target count is satisfied.

- [ ] **Step 6: Commit enforcement**

```bash
git add scripts/check_graph_payload_architecture.py scripts/measure_graph_payload_architecture.py tests/unit/test_graph_payload_architecture.py tests/unit/test_graph_change_spread.py tests/unit/test_graph_catalog_contracts.py .pre-commit-config.yaml
git commit -m "test: enforce strict graph payload architecture"
```

---

### Task 13: Full Verification and Explicit Database Cutover

**Database precondition (choose exactly one branch before D1-D6 deletion):**

- **Branch A, database present:** stop the server, create and size-verify a
  timestamped backup, remove only the disposable working database, and perform
  normal fresh initialization onto the strict schema.
- **Branch B, database absent:** record that no backup/reset is necessary, then
  perform normal fresh initialization onto the strict schema.

Both branches require successful fresh initialization before compatibility
deletion. Task 13 used Branch B. Final source repairs are `b63146d9b` and
`0289de70c`.

**Files:**
- Modify only if a verification failure exposes a real defect in the owning slice.
- Branch A only, create at runtime: timestamped
  `orchestrator.db.w5-strict-backup-YYYYMMDD-HHMMSS` outside git tracking.

**Interfaces:**
- Fresh database must seed factory data and complete a representative typed graph run.
- No old graph database is converted.

- [ ] **Step 1: Run focused architecture and graph gates**

Run: `uv run python scripts/check_graph_payload_architecture.py`

Run: `uv run pytest tests/unit/test_graph_catalog_contracts.py tests/unit/test_graph_change_spread.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_projections.py -q`

Run: `uv run pytest tests/ -k graph -q`

Expected: all pass.

- [ ] **Step 2: Run complete repository gates**

Run: `uv run pytest tests/ -q`

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `uv run pyright`

Run: `git diff --check`

Expected: all commands exit 0; do not classify any failure as unrelated.

- [ ] **Step 3: Stop the server and select Branch A or Branch B**

Confirm no Orchestrator server process is using the database. For Branch A,
run a timestamped copy before removal:

```bash
cp orchestrator.db "orchestrator.db.w5-strict-backup-$(date +%Y%m%d-%H%M%S)"
```

For Branch A, verify the backup exists and has the same byte size as the source.
For Branch B, record exactly that the worktree database is absent and no
backup/reset is necessary.

- [ ] **Step 4: Remove only the disposable working database and initialize fresh schema**

For Branch A, after backup verification, remove `orchestrator.db`. For Branch B,
there is nothing to remove. Start the application through the normal project
command and let Alembic/create-on-empty establish the current strict schema.
Never remove a backup or journal and never add automatic reset code.

- [ ] **Step 5: Delete the deferred compatibility register after fresh initialization**

Only after Branch A backup/reset plus fresh initialization or Branch B absence
record plus fresh initialization, delete every D1-D6 site, including
`reduce_legacy_event`, replay-only aliases, and any retained `_commands.py`
caller. Then run the register grep gate:

```bash
grep -rn "lease_suspended\|graph_patch_proposed\|requirement_revision_proposed\|authority_resolution_recorded\|environment_failure_accepted\|check_result_classified\|reduce_legacy_event" \
  src/orchestrator/graph src/orchestrator/graph_runtime
```

Expected: no matches. Task 13 used Branch B and recorded
`No worktree orchestrator.db existed; per Task 13, no backup or reset was
necessary.` Fresh initialization preceded deletion. Source repairs `b63146d9b`
and `0289de70c` removed the final legacy effects adapter and enforced typed
consumers without a production payload adapter; final metrics are 44/23 with
all strict/current, retired, and deferred compatibility counts zero.

- [ ] **Step 6: Run fresh-schema typed smoke tests through public interfaces**

Seed factory data, create a representative routine/run, execute lifecycle start, scheduling, callback/verification, checkpoint, compact read, node detail, summary, and graph completion. Assert every persisted graph row has generation 2 and can hydrate through the catalog.

- [ ] **Step 7: Re-run integration and architecture gates after the smoke test**

Run: `uv run pytest tests/integration/test_graph_dynamic_e2e.py tests/integration/test_graph_read_models.py tests/integration/test_graph_node_detail_read_models.py tests/integration/test_graph_startup_recovery.py -q`

Run: `uv run python scripts/check_graph_payload_architecture.py`

Expected: pass against the fresh schema.

---

### Task 14: Documentation, Ledger Reconciliation, Metrics, and W5 Closure

**Files:**
- Modify: `docs/superpowers/specs/2026-07-10-w5-strict-payload-architecture-design.md`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`
- Modify: `docs/dynamic-graph/w5-event-payload-inventory.md`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`
- Modify: `docs/dynamic-graph/w5-typed-payloads-spec.md`
- Move: `docs/dynamic-graph/w5-typed-payloads-spec.md` to `docs/dynamic-graph/complete/w5-typed-payloads-spec.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `AGENTS.md` only if new module/API navigation requires it under the repository maintenance rule.

**Interfaces:**
- Ledger names the retained/replaced compatibility work, every strict slice
  commit, exact verification commands/counts, Branch A backup/reset or Branch B
  absence/fresh-initialization evidence, and before/after metrics.
- Architecture docs identify domain module ownership and injected catalog composition.

- [ ] **Step 1: Generate final metrics and catalog inventory**

Run: `uv run python scripts/measure_graph_payload_architecture.py --format markdown`

Capture the 44/23 catalog inventory, zero forbidden-pattern counts, final `isinstance`/`dict[str, Any]` counts, files touched by representative maintenance exercises, and complete-read benchmark results.

Also capture the automation ledger for every slice: discovered mechanical sites, sites transformed by LibCST, unsafe semantic sites, zero remaining eligible sites, zero second-run changes, and zero unclassified dynamic event/command sites.

- [ ] **Step 2: Reconcile the ledger explicitly**

Add a strict-cutover section that marks prior payload field inventories/semantic tests as retained and compatibility validators/aliases/allowlist work as replaced. Close the old queue items as follows: records, file-state, commands, and grades are completed by Tasks 5–8; allowlist generation is superseded by deletion in Task 11; legacy preservation is superseded by the approved explicit Branch A/B cutover.

- [ ] **Step 3: Refresh architecture and projection documentation**

Document the event/command flow, catalog construction/injection points, corruption errors, payload generation, complete read paths, projection typed records, and the post-W5 relational-promotion deferral. Ensure no documentation suggests adding an event to a central conditional or mirroring fields into storage lists.

- [ ] **Step 4: Close W5 documents**

Set the approved design status to implemented, set the W5 typed-payload spec to closed, move the latter to `docs/dynamic-graph/complete/`, and leave `post-w5-event-column-promotion.md` deferred with measured W5 baselines.

- [ ] **Step 5: Verify documentation and final repository state**

Run: `rg -n 'GRAPH_PROJECTION_PAYLOAD_FIELDS|LIGHT_GRAPH_PAYLOAD_FIELDS|SUMMARY_REBUILD_PAYLOAD_FIELDS|NODE_DETAIL_PAYLOAD_FIELDS|COMMAND_HANDLERS' src tests docs/ARCHITECTURE.md docs/dynamic-graph`

Expected: no live-code or current-architecture references; historical ledger/design references clearly say superseded/deleted.

Run: `uv run pytest tests/ -q && uv run ruff check . && uv run pyright && git diff --check`

Expected: all exit 0.

- [ ] **Step 6: Commit W5 closure**

```bash
git add docs AGENTS.md
git commit -m "docs: close W5 strict payload architecture"
```

## Final Acceptance Checklist

Builder reconciliation: complete against Tasks 5-13 evidence and Task 14
generated metrics. Fresh independent Task 14 verification remains pending; no
closure commit SHA exists. Final source commits: `b63146d9b` and `0289de70c`;
latest independent evidence is 1,083 graph tests and 5,101 passed / 5 skipped /
3 warnings in the full suite, with 44/23 and zero metrics.

- [x] Exactly 44 live event specifications and 23 command specifications are cataloged; new raw emissions/dispatches are structurally impossible.
- [x] Every payload is strict/frozen/extra-forbid; no W5 compatibility normalizer or catch-all top-level field remains.
- [x] Every producer emits via an event specification; every reducer and command handler receives a concrete model.
- [x] Audit-only and projection-neutral events use the same create/store/hydrate/catalog path and are explicitly marked neutral.
- [x] The catalog is immutable, duplicate-checked, deterministic, and injected through compiler, controller, store, runtime, workflow, and API composition.
- [x] Stored payload generation mismatch and corrupted JSON fail with contextual domain errors.
- [x] The four allowlists and partial-event reconstruction code are deleted; all read modes preserve complete strict payloads.
- [x] Payload-shaped W5 projection records are concrete models.
- [x] Static architecture targets are all zero and pre-commit enforces them.
- [x] AST inventory classifies the entire migration surface; every mechanically eligible edit was performed by the LibCST codemod, every domain reports zero eligible sites remaining, and every second codemod run is empty.
- [x] The model-field, new-event, and new-command maintenance exercises demonstrate no storage or central-dispatch changes.
- [x] Every Deferred Compatibility Cleanup Register row (D1–D6) is deleted and the register grep gate returns no matches.
- [x] Corpus replay, graph-focused tests, full backend tests, Ruff, formatting, Pyright, and diff checks pass in Task 13 evidence; Task 14 rerun is pending below.
- [x] Branch B recorded that no database existed and no backup/reset was necessary; normal startup initialized the fresh schema and representative typed graph smoke tests passed.
- [x] Documentation records before/after metrics, retained/replaced work, complete-read measurements, and W5 closure.
