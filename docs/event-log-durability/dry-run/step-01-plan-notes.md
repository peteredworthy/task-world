# Step 01 Dry-Run Notes

Input simulated: `routines/event-log-durability/steps/step-01-plan.yaml`

## Overall Assessment

The step is directionally correct for an incremental oversight slice: it names the assumption under test, constrains the proof to one real workflow path, requires real SQLite/journal/projection surfaces, and has explicit stop/replan conditions for missing proof, masked verification, and scope creep.

The main planning gaps are:

- `events_v2` currently has `position`, `aggregate_id`, `event_type`, `payload`, `timestamp`, and `version`, plus `UNIQUE(aggregate_id, version)`, but no separate stable event identity/import identity column. Several auto-verify checks only assert the baseline columns and would pass without the idempotency metadata required by the slice contract.
- The plan asks for "create vs update" behavior around `tests/integration/test_event_log_durability.py`, but several auto_verify commands run that file unconditionally before it exists. This is fine after T-02 creates it, but T-03 onward depend on T-02 succeeding.
- The JSONL outbox is queued post-commit, but `commit_with_event_outbox()` currently propagates secondary sink failures after a successful DB commit. That may be acceptable if "accepted event" means DB committed, but the step must require evidence that callers do not treat the post-commit exception as a rolled-back event.
- The rebuild drill says to clear/drop projection rows but does not explicitly require clearing `projection_checkpoints`, nor does `ProjectionRegistry.rebuild_all()` set checkpoints to the final replayed position. That can leave stale recovery evidence unless tested.
- Some auto_verify items are existence/grep-only and would pass for stubs. The final pytest commands are the real contract surface, but the earlier checks should be hardened where they are the strongest proof for a task.

## T-01: Confirm References And Define Proof Boundaries

Assumptions:

- The graph references exist and support the same authority model: accepted events are authoritative and projections are disposable.
- `docs/event-log-durability/step-01-plan.md` exists and is the current executable plan boundary.
- No later executable plan file should exist in `docs/event-log-durability/`.
- Importing `EventV2Model` and `SqliteEventStore` proves the active DB event-store surface is present.

Expected outputs:

- Handoff/evidence notes state whether the graph references conflict with implementation evidence.
- Scope remains one workflow path plus rebuild/crash drills.
- No `step-02-plan.md` or later executable plan is created.

Blockers and mitigation:

- If a reference is missing, stop before implementation. Mitigation: keep the current `references_exist` check.
- If implementation evidence contradicts the references, stop and record the contradiction. Mitigation: require the evidence note to name the conflicting implementation detail.

Failure modes and hardening:

- File references are mostly correct. `docs/event-log-durability/step-01-plan.md` exists, but `auto_verify.references_exist` does not check it. Add it to the command.
- `event_store_contract_imports` is import/existence-only. It would pass if the active workflow path still bypassed `SqliteEventStore`. Add a wiring check that imports `get_event_emitter`/`WorkflowService` or runs an existing event-store wiring test.
- Incremental oversight quality is good: the plan names the assumption, missing proof, real surface, stop conditions, and evidence artifacts.
- Masked verification is explicitly forbidden in task text, but not mechanically checked. Add a grep/static check for fallback/shim language in the new durability test or rely on final review.

## T-02: Add Canonical Projection-State Comparison Helper

Assumptions:

- A new `tests/integration/test_event_log_durability.py` is the right home unless `test_projection_recovery.py` is extended.
- Canonical state can be read directly from `RunModel`, `StepModel`, `TaskModel`, and `AttemptModel`.
- Volatile timestamp exclusions can be justified from projector/domain behavior.

Expected outputs:

- A helper that snapshots run, step, task, and attempt read-model rows before and after rebuild.
- Assertion output or evidence includes serialized before/after state on mismatch.

Blockers and mitigation:

- Attempt rows may not exist in the smallest workflow path. Mitigation: either choose activity that creates at least one attempt or assert the empty attempt set explicitly.
- Broad JSON fields can be order-sensitive. Mitigation: normalize JSON values with deterministic sorting before comparison.

Failure modes and hardening:

- The auto_verify `durability_test_file_exists` allows a grep fallback into `test_projection_recovery.py`; that is acceptable only if the helper is actually reused by the durability drill. Harden by requiring the final rebuild test to call the helper by name.
- `canonical_helper_present` is grep-only and would pass for a comment or unused helper. Add a pytest test name requirement or a command that imports the helper and asserts it returns keys for `runs`, `steps`, `tasks`, and `attempts`.
- The task should explicitly list fields to include or define "all columns except justified volatile fields"; otherwise omissions can mask projection loss.

## T-03: Confirm events_v2 Schema And Migration Contract

Assumptions:

- Existing `EventV2Model` and Alembic migration may already satisfy most ordering requirements.
- Additive metadata can be added safely if stable idempotency identity is missing.

Expected outputs:

- Confirmed or extended SQLAlchemy model and migration.
- Evidence notes include the migration revision and SQL shape if a revision is added.

Blockers and mitigation:

- Current schema lacks a stable event identity column beyond autoincrement `position` and aggregate/version. Mitigation: require either a new unique identity column or an explicit decision that `(aggregate_id, version)` is the stable retry/import identity, with tests proving it is sufficient for import retry.
- Migration of existing live-like data requires backups if a real cutover/import command is touched. Mitigation: keep migration tests on temp DBs and require backup behavior only for operational import tooling.

Failure modes and hardening:

- `events_v2_metadata_imports` only checks baseline columns, not idempotency or duplicate-detection metadata. Harden it to assert the relevant unique constraints and any new column/index, e.g. an `event_id`/`source_position`/`import_key` unique constraint if added.
- The task mentions payload/timestamp metadata but not source/import/schema/correlation metadata from the architecture context. Decide whether that metadata is in scope for this proof or explicitly defer it in evidence.
- Existing tests can pass while stable import identity is missing because aggregate/version uniqueness prevents one class of duplicate only. Add an import retry test using legacy/outbox JSONL records with repeated positions and repeated aggregate/version attempts.

## T-04: Verify Event-Store Append And Ordered Reads

Assumptions:

- `SqliteEventStore.append()` remains compatible with both single events and sequences.
- `get_stream()` and `get_all()` ordered by `position` are sufficient for deterministic rebuild.
- Projection listeners run after flush and before commit in the same session.

Expected outputs:

- Existing event-store tests still pass.
- Durability tests prove ordered stream and global reads.

Blockers and mitigation:

- Concurrent append tests may be hard against SQLite transaction behavior. Mitigation: use the existing `ConcurrencyStrategy` injection pattern from unit tests for conflict behavior, and real SQLite constraints for integration proof.

Failure modes and hardening:

- Component wiring risk: tests can instantiate `SqliteEventStore` directly while active services still use an old path. Existing `WorkflowService` and API dependencies appear wired to `create_wired_event_store_v2`, but the step should require one service/API path assertion, not only repository tests.
- The task says duplicate prevention belongs to T-05, but append ordering and version assignment interact with duplicate behavior. Make sure T-04 does not accidentally accept duplicate rows as part of retry.
- Add assertions that `StoredEvent.position` is monotonic globally and versions are monotonic per aggregate after mixed-aggregate appends.

## T-05: Add Duplicate-Prevention Durability Tests

Assumptions:

- Duplicate prevention can be proven through real SQLite constraints or idempotent import behavior.
- Duplicate stable event identity is a separate concern from duplicate aggregate sequence.

Expected outputs:

- Tests prove duplicate aggregate/version does not create a second accepted row.
- Tests prove duplicate stable event/import identity does not create a second accepted row or fails explicitly.

Blockers and mitigation:

- No separate stable event identity exists today. Mitigation: add one, or harden the YAML to say aggregate/version is the chosen identity for this slice and test import/retry semantics around it.

Failure modes and hardening:

- `-k 'constraint or duplicate'` will pass if any loosely named test passes and a stronger duplicate identity test is missing. Harden by naming required tests explicitly or using separate `-k` expressions for aggregate sequence and stable identity.
- A test that only catches `IntegrityError` without checking row count can miss partial duplicate insert behavior. Require post-failure row-count and ordered stream assertions.
- If idempotent import uses `INSERT OR IGNORE` on `position`, duplicate aggregate/version with a new position can still fail differently. Require tests for duplicate position, duplicate aggregate/version, and duplicate import identity if that differs.

## T-06: Prove DB Append Authority And Secondary Journal Behavior

Assumptions:

- At least one real workflow/service/API path can create observable run/task lifecycle events without unrelated engine rewrites.
- Temporary file SQLite and temporary JSONL journal paths can exercise the same store wiring as production.
- Journal failure can be produced with real filesystem behavior or a concrete injected observer.

Expected outputs:

- A real path creates run/task events in `events_v2`.
- Projections are updated only after DB append in the same transaction boundary.
- JSONL exists as a secondary sink and rebuild does not depend on it.
- Journal failure evidence shows the DB event row remains authoritative.

Blockers and mitigation:

- Filesystem permissions can behave differently on macOS temp dirs and under sandboxing. Mitigation: prefer a concrete observer object that raises through the existing listener interface, avoiding mocks while still using real session/DB behavior.
- `commit_with_event_outbox()` currently propagates outbox failure after commit. Mitigation: define the expected caller-visible semantics: either change it to log/suppress secondary failures, or assert that the DB row remains and record that caller may see a secondary failure after acceptance.

Failure modes and hardening:

- Critical component wiring risk: a direct `SqliteEventStore` test does not prove a workflow path uses it. Require a `WorkflowService` or API test that constructs the standard dependency path and observes `events_v2` rows.
- "Before projection updates are committed" is subtle because projections are listeners in the same session before commit. Harden by injecting a concrete failing projector/listener and asserting event rows are rolled back when projection fails, while outbox failure after commit does not remove rows.
- Auto_verify `workflow_authority_tests` relies on test names containing workflow/authority/journal. Require exact test names or final full durability test command to avoid name-filter masking.

## T-07: Add Projection Rebuild Durability Drill

Assumptions:

- Projection rows are disposable read models and can be cleared in a temp DB.
- Ordered `events_v2` rows can be deserialized to `WorkflowEvent` objects and replayed through `ProjectionRegistry`.
- The smallest workflow path emits enough event types for run, step, task, and attempt comparison.

Expected outputs:

- Test creates real activity, snapshots canonical state, clears projection rows, rebuilds from `events_v2`, and asserts equality.
- Event counts and aggregate version ranges are recorded before/after rebuild.

Blockers and mitigation:

- Foreign-key cascades can make deletion order important. Mitigation: clear `attempts`, `tasks`, `steps`, `runs`, and `projection_checkpoints` in dependency order or use SQLAlchemy table deletes respecting constraints.
- `ProjectionRegistry.rebuild_all()` resets checkpoints to zero but does not obviously advance them to the final position. Mitigation: either assert read-model equivalence only and defer checkpoint correctness, or require checkpoint position evidence.

Failure modes and hardening:

- The drill could accidentally rebuild from in-memory events captured before clearing rather than from `events_v2`. Require the test to call `store.get_all()` or query `EventV2Model` after clearing projections and deserialize that stream.
- If `RunCreated.run_snapshot` expansion creates steps/tasks, fabricated event fixtures may mask missing real task events. Require the activity path and event stream evidence to list event types and counts.
- Auto_verify `rebuild_drill` is contract-level if the test is real, but the YAML should explicitly forbid marking the test with skip/xfail.

## T-08: Add Crash/Retry Durability Drill

Assumptions:

- Crash/retry can be simulated around real DB transaction boundaries without process-killing the test runner.
- "Accepted event" means an event whose `events_v2` transaction committed.
- Retry behavior can be proven without monkeypatching by using real constraints, sessions, and concrete injected strategies/observers.

Expected outputs:

- Test shows pre-commit interruption does not create an accepted event.
- Test shows retry after a committed append does not duplicate an accepted event.
- Event counts and aggregate version ranges are recorded before crash, after retry, and after rebuild.

Blockers and mitigation:

- Actual process kill tests are expensive and flaky. Mitigation: use two real sessions/transactions and constraint-backed failures to model the transaction boundary, while clearly documenting what is and is not proven.
- Without stable event identity, retry after commit may only be detectable as duplicate aggregate/version conflict, not idempotent retry. Mitigation: add stable identity or specify that explicit constraint failure is the accepted behavior.

Failure modes and hardening:

- The command `-k 'crash or retry'` could run a weak retry test only. Require distinct tests for pre-commit rollback and post-commit duplicate retry.
- A crash drill can be fake if it only appends fabricated events. Require use of the same append path as T-06 or clearly state why the transaction-boundary proof is lower-level.
- Stop/replan condition is good: acceptance before DB commit is an architectural failure for this slice.

## T-09: Record Evidence And Run Targeted Verification

Assumptions:

- Evidence can live in implementation artifacts or a durability evidence document.
- Full targeted durability tests and event-store regression tests are feasible in the environment.

Expected outputs:

- Evidence notes include schema shape, test commands/output, rebuild snapshots, counts/ranges, temp path patterns, reference conflict status, and next-cycle recommendation.
- `uv run pytest tests/integration/test_event_log_durability.py -v --tb=short` passes.
- Existing event-store, JSONL bootstrap, and projection recovery regressions pass.

Blockers and mitigation:

- If the environment cannot run SQLite/Alembic/workflow integration tests, stop rather than substituting grep/static checks. Mitigation: record the blocker and do not claim completion.
- If a test is skipped due to fixture/env constraints, the evidence is insufficient. Mitigation: make the durability proof independent of external credentials/services.

Failure modes and hardening:

- The final command is the strongest real verification surface and is good. Add `-rs` or a no-skips assertion if the project commonly reports skipped tests quietly.
- `no_forbidden_mocking` scans only the durability test file. If helpers are added elsewhere, mocking could be hidden. Harden by scanning any helper module introduced by the step.
- Evidence should explicitly identify whether migration/import backup behavior was touched. If not touched, say "not touched in this slice" so later planners do not infer it was proven.

## Cross-Cutting Hardening Actions

1. Add a stable event identity decision to T-03/T-05. Either introduce a column/unique constraint for retry/import identity, or explicitly define `(aggregate_id, version)` as the retry identity for this slice and prove its limitations.
2. Strengthen schema auto_verify to inspect constraints/indexes, not just columns.
3. Require exact durability test names for schema, ordering, duplicate identity, aggregate sequence, workflow authority, journal failure, rebuild, pre-commit rollback, and post-commit retry.
4. Require the workflow authority test to use an active service/API dependency path, not only a manually instantiated store.
5. Require rebuild tests to read events back from `events_v2` after projection clearing.
6. Require projection clearing to include `projection_checkpoints` or explicitly justify excluding checkpoints from equivalence.
7. Require journal failure semantics to be explicit: DB row remains committed, and either the secondary failure is suppressed/logged or caller-visible as a secondary failure that must not be interpreted as event rejection.
8. Require final evidence to state whether operational backup/import behavior was modified or deferred.
9. Add a no-skip/no-xfail check for `tests/integration/test_event_log_durability.py`.
10. Keep all verification commands `must: true`; no current task relies on a `must: false` command, which is good.

## Existing-Test Impact

Likely affected surfaces:

- `tests/unit/test_event_store_v2.py` for version assignment, ordering, and conflict behavior.
- `tests/integration/test_event_store_wiring.py` for outbox behavior and `commit_with_event_outbox()` semantics.
- `tests/integration/test_jsonl_bootstrap.py` and `scripts/restore_from_journal.py` if import identity or backup behavior is hardened.
- `tests/integration/test_projection_recovery.py` if rebuild/checkpoint behavior changes.
- Service/API tests using `create_wired_event_store_v2()` if outbox failure handling changes.

The plan should expect test updates if stable identity columns or outbox failure semantics are changed. If only tests are added and no runtime behavior changes, T-03/T-05 may still fail the stronger durability contract because current schema does not expose separate stable event identity.
