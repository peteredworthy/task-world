# W5 Residual Completion Design

## Objective

Complete the unfinished W5 typed-payload work from the current repository state
without repeating the eight event-family slices already recorded as complete.
Completion requires the remaining event envelopes, generated retention
allowlists, all 23 command payloads, `GradeRow`, full verification, metric
reporting, and documentation closeout. The database and durable event history
have been reset, so historical payload compatibility is explicitly out of
scope. W5 must remove obsolete compatibility layers rather than preserve them.
This design supersedes the historical-replay requirements in the July 9 W5
completion design, plan, and completion-agent prompt. The residual
implementation plan is the authoritative queue.

## Verified Residual Scope

The external review is materially correct. The remaining work is:

1. Record event envelopes for `output_record_accepted`,
   `verification_passed`, `verification_failed`, `input_bound`, and
   `revision_created`. Existing typed output-record value models are reused.
2. File-state and gatekeeper envelopes for `file_state_accepted`,
   `file_state_rejected`, `gatekeeper_verdict_recorded`, and
   `gatekeeper_cost_recorded`. The unproduced replay aliases
   `environment_failure_accepted` and `check_result_classified` are deleted.
3. Removal of historical compatibility code added or retained by all W5 event
   slices: unknown-field `extra` quarantine, malformed-value normalizers,
   replay-only event aliases, generic record fallbacks, and dict-compatible
   model facades.
4. A declarative typed-model registry that generates the projection, light,
   summary, and node-detail payload retention allowlists.
5. Typed payloads for exactly the 23 handlers registered in
   `orchestrator.graph.commands`.
6. A strict `GradeRow` model for
   `VerificationReportValue.grades`.
7. W5 ledger, inventory, metrics, final verification, and spec closeout.

The raw-access review count is not a fixed acceptance target. At review time,
`projections.py` contains 180 total `payload.get(` occurrences, including 72
direct `event.payload.get(` occurrences. These include intentional generic and
dynamic-domain paths. Final closeout reports these counts diagnostically while
using the specification's required baselines for formal metric deltas.

## Execution Structure

Work is organized into one optimization preflight and three large, serial
batches. Focused tests remain separated by family or command group so failures
are localizable, but expensive acceptance gates and fresh-verifier review occur
once per large batch.

### Batch 0: Optimize The Execution Loop

Before implementation:

1. Benchmark representative completed W5 payload tests, corpus replay, the
   existing graph selection, full backend suite, Ruff, and Pyright targets,
   recording commands and wall times. Record new focused-file timings as those
   files are introduced without rerunning the baseline benchmark.
2. Confirm graph and backend tests are safe under the repository's installed
   `pytest-xdist` configuration: `-n auto --dist worksteal`. Retain serial
   execution only for a selection shown to be order-sensitive.
3. Build a change-to-test gate matrix for Batches 1 and 2.
4. Mark the older compatibility-first W5 completion documents as superseded so
   agents cannot follow their stale replay requirements.
5. Assign builders only focused tests and corpus replay during iteration.
6. Assign one fresh verifier the expensive graph, lint, and type gates when a
   batch is a complete candidate.
7. After a failed verification, run only implicated focused tests while fixing;
   send the repaired candidate through the complete batch gate once with a new
   fresh verifier.

This keeps independent verification but removes duplicated full-suite runs
after every small family. The current ledger's 112-second serial graph result
also indicates that repeated agent and gate cycles, rather than one test run,
were the main source of the previous multi-day completion time.

### Batch 1: Canonical Events, Shim Removal, And Retention

First inventory every current event producer, reducer consumer, fixture event,
and external event ingress. Establish one canonical event-name and payload-shape
registry. Every retained reducer event must either have a current producer or
be explicitly designated as a current externally seeded domain event. Delete
all other reducer-only names and add a guard that rejects fixture-only event
types.

Canonicalize the fixture corpus before tightening validation. Replace sparse
`output_record_accepted` fixtures with valid typed records, replace historical
environment-failure aliases with canonical typed check records, and replace
`requirement_amended` with `requirement_revision_recorded`. Fixtures must no
longer be used to justify production compatibility branches.

Add record and file-state/gatekeeper event payload models to
`orchestrator.graph.models` and export them through the graph module's public
API. Producers validate and JSON-dump models before `make_event`; reducers parse
canonical payloads once and then consume model attributes.

Remove compatibility machinery across both new and already-landed W5 families:

- Replace event payload bases that preserve unknown values under `extra` with a
  strict canonical base using `ConfigDict(extra="forbid")`.
- Delete historical `mode="before"` alias, malformed-value, and partial-row
  normalizers after current producers emit the canonical shape.
- Delete replay-only patch, requirement/evidence, environment-failure, and
  suspect aliases unless the event audit designates one as a current domain
  event and adds or identifies its canonical producer.
- Delete `LegacyOutputRecord` and generic output-record fallback paths after
  canonicalizing fixtures.
- Convert consumers of dict-compatible projection models to attributes, then
  delete fake mapping methods and dual runtime/type-checking definitions.
- Replace reducer reads from `payload.extra` with canonical named fields or
  Pydantic field-set semantics where explicit null remains meaningful.

Three currently ambiguous reducer-only concepts require explicit resolution in
the event audit: `lease_suspended`, suspect resolution/clearing, and proposal
opening. For each, either establish one canonical producer and event model or
delete every consumer, prompt branch, fixture, and test. They may not remain as
undocumented compatibility paths.

After every remaining event has a typed model, add a declarative event payload
registry. Each event specification names its model and explicit projection,
light, summary, and node-detail retention sets. Generate sorted, deduplicated
allowlist tuples from those sets. Do not retain every model field in every read
mode. Named legacy exceptions remain possible, but tests must prove each
exception is necessary and reject stale exceptions.

Focused test files cover output/verification records, input binding/revision
routing, file-state/gatekeeper behavior, canonical fixture replay, strict
malformed-input rejection, cost-field retention, event producer/consumer name
equality, removal of compatibility symbols, and exact equality for all four
generated allowlists.

### Batch 2: Commands And Grade Rows

Introduce `orchestrator.graph.command_models` and a `CommandSpec` registry that
pairs every registered command handler with one Pydantic payload model. The
registry is the single source of truth for exactly these 23 command names:

- Lifecycle: `accept_run`, `start`, `pause`, `resume`, `cancel`, `complete`,
  `fail`, and `record_heartbeat`.
- Scheduling: `seed_compiled_events`, `schedule_tick`, and `reconcile`.
- Callback and patch: `submit_callback`, `submit_patch`, and
  `acknowledge_start`.
- Decisions and records: `agent_died`, `raise_appeal`, `record_decision`,
  `record_gatekeeper_verdicts`, `record_requirement_revision`,
  `record_support_evidence`, `evaluate_join`, `evaluate_final_gate`, and
  `record_cleanup_applied`.

Command dispatch validates through the selected `CommandSpec` before invoking
the handler. Unknown commands and invalid internal commands preserve the
existing deterministic `command_rejected` behavior. Runtime-injected context,
including `run_id` and current graph position, remains separate from public
command fields.

FastAPI patch and decision requests compose or reuse their command payload
schemas so malformed constrained values return 422 at the API boundary without
duplicating domain validation. Intentionally dynamic nested patch operations,
macros, decision scope, and decider structures remain flexible.

Add `GradeRow` with `requirement_id`, `grade`, and optional `reason` fields under
the strict canonical model policy. Change `VerificationReportValue.grades` to
`list[GradeRow]`. Keep grade values open as strings for current and future grade
labels, but reject unknown row fields and partial rows missing required identity
or grade values.

Focused tests are split into lifecycle, scheduling, callback/patch, and
decision/record command files, plus existing command and API integration tests.
They assert exact registry equality, strict outer types, canonical
constrained-field values, defaults, public 422 behavior, and unchanged valid
dispatch.

### Batch 3: Closeout

Audit the W5 queue and ensure the ledger contains named evidence for both
remaining event groups, all four allowlists, all four command groups,
`GradeRow`, and final verification. One large-batch ledger entry may contain
separate evidence subsections for the original checklist items.

Refresh `docs/dynamic-graph/graph-projection-map-inventory.md`, mark W5 closed,
and move `docs/dynamic-graph/w5-typed-payloads-spec.md` to
`docs/dynamic-graph/complete/w5-typed-payloads-spec.md`.

## Canonical Contracts And Error Handling

The reset event store is not a backward-compatibility surface. Event and command
payloads accept only canonical current shapes and reject unknown or malformed
fields at their boundary. Reducers do not recover values from old aliases,
arbitrary dictionaries, `extra` maps, or alternate nesting locations.

Dynamic structures that are part of the current domain remain deliberately
untyped only at their named boundary: patch operations and macros, command
definitions, diagnostics/read-set diffs, edge metadata and policy data,
decision scope and decider data, and typed-record payload and provenance fields.
Their enclosing event or command model is still strict. This flexibility must
not be implemented through catch-all top-level compatibility maps.

`gatekeeper_cost_recorded` must retain every identifier, token/cache count,
item count, `cost_usd`, and `wall_time_ms` field consumed by run-summary logic.
Compact reads must produce the same projection result as full event replay.
Projection schema version changes occur only if stored projection shape or
reducer semantics change.

## Verification Strategy

Batch 1 acceptance includes:

- Focused event-family tests and canonical corpus replay parity.
- Producer/reducer/fixture event-name equality, with documented current external
  events as the only permitted exception.
- Negative tests proving obsolete aliases, unknown fields, malformed values,
  sparse legacy records, and partial grade-like rows are rejected.
- Static assertions that removed compatibility bases, replay models, fallback
  helpers, and dict-compatible facades no longer exist.
- Projection and all-four-allowlist equality tests.
- Relevant graph read-model and event-store integration tests.
- One parallelized full graph selection.
- Ruff and scoped Pyright across graph and graph runtime.
- Fresh review for surviving compatibility layers, unowned reducer event names,
  dropped canonical fields, cost loss, and accidental out-of-scope typing.

Batch 2 acceptance includes:

- Four focused command payload files and `test_graph_commands.py`.
- Patch and decision API integration tests.
- `GradeRow` model, command, and corpus tests.
- Exact equality between the registry and all 23 required names.
- One parallelized full graph selection.
- Ruff and scoped Pyright across graph, graph runtime, and API.
- Fresh review for API/domain validation drift and changed rejection behavior.

Batch 3 acceptance runs:

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime \
  src/orchestrator/api tests/unit tests/integration
```

If Batch 0 finds an order-sensitive test selection, the affected final pytest
command runs serially and the reason is recorded. A fresh final verifier reviews
the complete residual diff and reports exact command results.

## Metrics

Closeout records final values and deltas for:

- `isinstance(` across `_commands.py` and `projections.py`, baseline 603.
- `dict[str, Any]` in `projections.py`, baseline 174.

It also records direct `event.payload.get(` and total `payload.get(` counts as
diagnostics. These diagnostic counts demonstrate migration progress but are not
forced to zero because intentionally dynamic domain structures remain in scope.
Closeout also records deleted compatibility models/helpers and any remaining
`mode="before"` validators or dict-compatible model methods, each with a current
non-history justification.

## Completion Criteria

W5 is complete only when:

- All remaining currently produced event envelopes are typed and verified.
- Historical replay aliases and malformed-payload compatibility paths are
  removed rather than typed.
- Every retained event type has a current producer or an explicit current
  external-ingress designation.
- W5 payload models use strict canonical fields without top-level `extra`
  quarantine, generic record fallback, or fake dict/model duality.
- All four retention allowlists are registry-generated and equality-guarded.
- Exactly 23 command payloads validate at domain and applicable API boundaries.
- `GradeRow` is used by `VerificationReportValue.grades`.
- Corpus, graph, backend, Ruff, and Pyright gates pass.
- The ledger and projection inventory are current.
- Required and diagnostic metric counts are reported reproducibly.
- The W5 specification is closed and moved into `complete/`.

## Task 3 Review Closure Addendum

The approved Task 3 review closure uses targeted W5 strictness rather than
changing `GraphBaseModel` globally. An immutable output-record discriminator
map explicitly owns every supported `record_type`, including named generic
types mapped to `OutputRecord`; missing and unknown discriminators are invalid.
Nested models reachable from W5 event payloads and typed records inherit a
small extra-forbid base, while named dynamic dictionaries and `Any` fields
remain intentionally open.

Decision events accept only canonical literal values emitted by current
producers. Cleanup superseding records retain `cleanup_excluded_paths` as typed
metadata. Current producers are exercised directly in all nine payload-family
suites, and compact-read tests retain runtime retry timing, hidden-oracle
commands, and full/compact node-created parity. Projection models remain
attribute-only. Current graph patch producers emit integer positions, so W5
event fields use strict integers rather than integer/string unions.

Acceptance runs the exact Task 3 aggregate, directly affected producer and
compact-read tests, Ruff, Pyright, and one full suite before the fix commit.
