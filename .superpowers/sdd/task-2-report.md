# Task 2 Report: Lifecycle, Callback, Retry, and Dispatch Intent

## Outcome

Implemented ten strict lifecycle/callback/retry/dispatch event specifications and eleven
strict command specifications. Catalog command execution now receives the exact typed command,
the current graph projection, historical events, and universal execution context explicitly.
Converted Task 2 outcomes are `HydratedEvent`; effects awaiting Tasks 3/4/6 specifications use
one named mixed-result compatibility bridge scheduled for deletion in Task 9.

## TDD evidence

- Strict payload RED covered valid samples plus forbidden extras and mistyped required scalars
  for all ten event payloads; reducer RED required concrete payload classes and neutral audit
  participation. GREEN is included in the 276-test focused slice.
- Codemod RED covered the complete 10-event/11-command route inventory, direct envelope
  conversion, bridge registry removal, duplicate import prevention, repeated relocation, and
  second-apply idempotency. GREEN: `31 passed`.
- Final placeholder/ownership RED ran three tests: acknowledgement returned no event, callback
  rejected the context-owned `run_id` before reaching its placeholder, and converted bodies
  remained under their `_apply_*` legacy names. All three failed for those expected reasons.
- GREEN implemented projection/history-aware handlers. The five focused framework/behavior/
  ownership tests passed, followed by `276 passed in 2.79s` for the required slice plus codemod.
- Full-unit RED exposed compact projection loss of callback `idempotency_key` and `payload`;
  adding both projection-required fields made the direct regression `4 passed` and the full
  unit suite `3350 passed`.
- Integration RED exposed cancellation losing legacy lease/node side effects on typed dispatch.
  Routing lifecycle outcomes through the narrow mixed bridge restored those effects; the exact
  integration regression passed.
- Serial integration then exposed strict agent-death retry fields omitted from its command and
  compact node-detail lifecycle events missing required `to_state`. The seven failing tests
  passed after adding producer-owned retry fields and the compact allowlist entry.

## Automation sequence and evidence

The inherited automation sequence was preserved: inventory/preview, one structural apply,
manual semantics, assert-clean, domain check, and repeated apply. The recovery run repeated
`--assert-clean`, `--check-domain lifecycle`, and two consecutive `--apply` invocations; all
exited 0 and neither apply produced a further change. This confirms single-apply convergence,
repeat idempotency, and no reversal/race between manual semantics and the mechanical pass.

The mixed inventory surface remains exactly 44 events and 23 commands: 34/13 future-domain raw
sites plus 10/10 converted lifecycle sites. Heartbeat remains visible at the temporary lease
renewal bridge, accounting for the eleventh typed command without hiding its Task 4 raw effect.
The legacy-only `--check-baseline` intentionally reports converted names absent; its inventory
contract suite passed `20 passed`, and `--check-domain lifecycle` is the authoritative cutover
check for this slice. Dynamic future-domain emissions remain exposed in inventory output.

## Interface and compatibility decisions

- Projection and historical events are explicit handler inputs and never command payload data.
  Run ID, position, clock, ID generation, and actor stay on `CommandExecutionContext`.
- `CommandResult` is a temporary internal `HydratedEvent | EventEnvelope` bridge. The union is
  confined to specification/dispatcher and named conversion adapters.
- Strict callback and lifecycle outcomes hydrate through named specifications. Node, lease,
  output, file-state, and session effects remain envelopes until Tasks 3/4/6 provide specs.
- Controller payloads no longer inject universal `run_id` into strict command models.
- Callback validation preserves stale/conflict/duplicate idempotency behavior, nullable business
  payloads, acknowledgement identity checks, completion effects, and cancellation side effects.
- Comments at both bridge boundaries identify the Task 3/4/6 dependencies and Task 9 deletion.

## Verification

- Lifecycle codemod `--assert-clean`: exit 0.
- Inventory `--check-domain lifecycle`: exit 0.
- Second codemod apply: zero changes.
- Focused lifecycle/callback/framework/outbox/codemod suite: `276 passed`.
- Codemod suite: `31 passed`; inventory suite: `20 passed`.
- Full unit suite: `3350 passed`, with three existing SQLite datetime-adapter warnings.
- Full serial integration suite: `1283 passed, 5 skipped in 360.02s`.
- `tests/e2e` and `tests/slow` contain no collected tests (pytest exit 5: no tests ran).
- Pyright: 0 errors, 0 warnings.
- Ruff check/format: clean before final commit; commit hooks provide the final complete check.

## Self-review

- Confirmed all ten event and eleven command specifications are catalog-owned and strict.
- Confirmed converted outcomes reject wrong payload classes and do not leak raw dictionaries.
- Confirmed typed callback and acknowledgement paths execute real behavior with projection/history.
- Confirmed lifecycle cancellation retains lease revocation and node cancellation effects.
- Confirmed compact replay retains callback idempotency inputs.
- Confirmed future-domain raw emissions remain inventoried rather than silently cast away.
- Confirmed `.superpowers/sdd/progress.md` remains controller scratch and will not be staged.

## Concern

The deliberately narrow mixed-result adapter remains until Tasks 3/4/6 define the remaining
effect specifications and Task 9 deletes the compatibility union. No converted Task 2 outcome
uses the raw result path.

## Fix Review History

The review repair replaced delegation back into `_commands.py` with physical domain ownership,
moved converted reducers behind typed specifications, and made every Task-2 rejection hydrate
through the named catalog. The compatibility bridge now accepts only the explicit 34-name
Tasks 3/4/6 effect allowlist and fails closed for unknown or Task-2-owned names.

Dependency inversion is enforced at both pure and effectful boundaries. Converted commands have
no raw `apply_command` bypass. `GraphController` requires an explicit `GraphCatalog` and
`FutureCommandEffects`; it has no implicit default. The lifecycle codemod now discovers real
controller construction sites, injects `build_graph_catalog()` and `future_command_effects()`,
and adds their public imports. Two consecutive final apply passes produced no edits.

Reviewer follow-up exposed legacy test harnesses that bypassed typed dispatch. One shared real
test utility now builds the catalog and execution context, injects a real fake clock, sequential
ID generator, controller actor, projection, history, and future effects, and converts hydrated
results to store envelopes. Compiler, planner, planner-session, parent/child, projection, direct
callback, scenario-corpus, and signal-consumer paths use the same dependency-injected boundary.

Compact replay now retains `idempotency_key` and required nullable callback `payload` for typed
callback events in light, summary, and node-detail reads, while non-callback heavy payload bodies
remain excluded. Strict controller dispatch removes universal `run_id` and `actor_role` before
payload validation and places actor role on `CommandExecutionContext.actor`.

Final evidence after all reviewer fixes:

- Focused migrated harness suite: `208 passed`.
- Codemod and inventory contract suites: `54 passed`.
- Full unit suite: `3360 passed`, with three SQLite datetime-adapter warnings.
- Full serial integration suite: `1283 passed, 5 skipped in 356.71s`.
- Lifecycle `--assert-clean` and inventory `--check-domain lifecycle`: exit 0.
- Two consecutive lifecycle codemod `--apply` runs: zero changes.
- Final future-domain inventory: 34 event names and 13 command names; together with the ten
  converted event and ten converted command routes this preserves the reviewed 44/23 surface,
  with heartbeat represented at its temporary Task-4 renewal bridge.
- Ruff format/check: clean. Pyright: 0 errors after the final context-role narrowing.

## Re-review wave 2 repair

Removed strict-command serialization and all `temporary_unconverted_*` Task-2 policy seams.
Lifecycle, callback, acknowledgement, heartbeat, and agent-death handlers now consume concrete
command attributes. Task-2 rejection and outcome events are constructed by their owning domain
specifications and hydrated before leaving catalog dispatch; acknowledgement identity failures
now follow the same `COMMAND_REJECTED` path.

The mixed projection boundary now resolves catalog-owned event types, JSON-normalizes the stored
payload once, hydrates once, and invokes `EventSpecification.reduce`. Central `reduce_event` no
longer contains converted-name branches, revalidation, or historical default mutation. Compact
readers retain every required callback/retry/heartbeat field. A boundary regression proves
heartbeat remains a native `datetime` in `HydratedEvent` and becomes an ISO string only when
serialized for storage.

`FutureCommandEffects` no longer exposes Task-2 event constructors, rejection policy, callback
payload normalization, lifecycle policy, retry classification, or scalar normalization. The
remaining capabilities emit or validate precomputed Tasks 3/4/6 effects. Dispatch intent remains
hydrated through controller planning and is converted only in the `append_events` argument.

Wave-two verification: focused Task-2/automation slice `307 passed`; full unit suite `3362
passed` with three existing SQLite datetime-adapter warnings; lifecycle assert-clean and domain
inventory passed with the explicit 34 future-event / 13 future-command inventory (44/23 combined
surface); Ruff format/check clean; Pyright 0 errors. Serial integration was started in foreground
and reached the initial segment without a failure, but the execution transport returned before a
pytest completion summary, so no complete integration count is claimed here.

## Direct Event Fix (re-review wave 3, slice A)

Task-2 command outcomes now construct each concrete strict payload once and pass it directly to
the named `EventSpecification` through `TypedEventCreator`. The creator uses the injected clock,
ID generator, actor, run identity, and current position and returns `HydratedEvent` immediately.
Mixed handlers leave typed events unpositioned for the store only when interleaved with
allowlisted Tasks 3/4/6 raw effects, preserving emission order; typed-only handlers allocate
ordered positions directly. Event IDs remain unique and ordered in both cases.

Lifecycle, callback, acknowledgement, heartbeat rejection, agent-death, and retry paths no
longer contain `_strict_event`, `StoredEventEnvelope.model_validate`, or specification hydration
round trips. Raw effects are checked by the explicit future-domain allowlist. The legacy
`_apply_agent_died` alias/export was removed and migration ownership now names
`build_agent_died_effects`.

Defect-specific TDD evidence: the architecture test first failed on `_strict_event` and
stored-envelope hydration, while the creator behavior test failed because no direct creator
existed. GREEN passed the 252-test lifecycle/callback/framework/graph-command slice and the
56-test codemod/inventory architecture slice. Full unit passed 3364 tests after a fixture
regression exposed mixed typed/raw position ordering and the explicit mixed-position policy
fixed it. Lifecycle `--assert-clean`, lifecycle inventory `--check-domain`, Ruff, formatting,
and Pyright also passed.

## Explicit Replay Catalog (re-review wave 3, slice B)

Mixed projection replay now requires the caller's `GraphCatalog` at every folding boundary.
`reduce_event(catalog, projection, event)` asks that catalog to hydrate catalog-owned events
exactly once and routes only unresolved future-domain events through the isolated legacy raw
reducer. `build_projection`, all projectors capable of folding an event stream,
`rebuild_projection`, and `GraphEventStore` snapshot/tail/read-model rebuild paths likewise have
no optional or implicit catalog. `GraphController` reuses its existing injected catalog for
reads, command projection, persistence, and public projection reads.

Defect-specific RED first proved that the projection module constructed a default catalog and
that the desired three-argument reducer API did not exist. GREEN proves an empty custom catalog
is honored (the Task-2 lifecycle event follows the raw unknown-event path), while the composed
catalog applies its typed reducer. A separate legacy reducer remains for the narrow
future-effect repair path, so no hidden default was introduced there.

Repeated call-site changes were performed by the LibCST replay-catalog codemod. Its first
dry-run identified 65 test modules; the expanded projector pass identified eleven production
modules plus the remaining projector-focused tests. Golden tests cover reducer injection,
store-constructor argument order, import insertion, and idempotency. The final assert-clean pass
exited zero after a second apply, and ambiguous dependency-bearing controller/store sites were
threaded manually with their existing catalog rather than rewritten to construct one.

Final slice-B evidence:

- Projection and custom-catalog architecture/behavior focus: `129 passed`.
- Store/API projection focus: `33 passed`.
- Callback/command/mixed replay regression focus: `207 passed`.
- Codemod/snapshot-helper focus: `6 passed`.
- Full unit suite: `3368 passed`, with the same three SQLite datetime-adapter warnings.
- Full serial integration suite: `1283 passed, 5 skipped in 419.57s`.
- Lifecycle codemod `--assert-clean`, lifecycle inventory `--check-domain`, and replay-catalog
  codemod `--assert-clean`: exit 0.
- Ruff format/check clean; Pyright: 0 errors, 0 warnings.

The reviewed mixed inventory remains 44 events and 23 commands. This slice deliberately does
not change the public future-effects export; that remains the separate wave-three finding.
