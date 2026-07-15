# W5 Strict Payload Architecture Cutover

**Status:** Implemented, documented, and independently verified

**Date:** 2026-07-10

## Outcome

W5 implemented one strict architecture across exactly 44 event specifications
and 23 command specifications. Payloads inherit the frozen, strict,
`extra="forbid"` `StrictPayload` base; immutable domain-owned specification
tuples compose into a duplicate-checked catalog injected from the API and CLI
composition roots. Commands validate once before typed dispatch, events are
created through their specifications, stored as generation-2 envelopes,
hydrated once, and reduced with concrete payload models. Projection-neutral
events use the same create/store/hydrate/catalog path.

All full, light, summary-rebuild, projection/checkpoint, and node-detail reads
retain complete hydrated payloads. The four mirrored field allowlists and
partial reconstruction paths were deleted. Deferred Compatibility Cleanup
Register rows D1-D6 and hidden compatibility adapters were deleted in Task 13;
the retired-name grep returned status 1 with no output. The architecture
checker, deterministic metrics, change-spread contracts, codemod idempotency
tests, and pre-commit hook enforce the result.

Final source repairs are `b63146d9b`, which removed the legacy graph effects
adapter; `0289de70c`, which enforced typed graph payload consumers and removed
production adapter use; and `185f31abc`, which completed typed graph command and
read-model ownership. Schedule, patch, callback, lifecycle, and source-repair
logic now live in their owning command modules, and `_commands.py` is a retired
five-line marker with no handlers. Patch operations are a strict discriminated
`PatchOp` union. Store projectors consume concrete payloads, node references are
declared by payload type, and forward references within atomic event batches
are preserved.

Latest independent evidence is 1,063 graph tests and 5,151 full-suite tests
passing (5 skipped, 3 warnings), with the 44/23 catalog and every expanded
architecture, retired-compatibility, and deferred-compatibility count at zero.
The zero gates include raw future command-effects contracts, command-model
dumps to raw helpers, raw event creators, internal JSON payload adapters, and
raw read-model event dispatch.

Task 14 and the final source repair generated the final baseline: every
strict/current architecture, retired-compatibility, deferred-compatibility,
remaining-eligible, second-run-change, and unclassified-dynamic-site metric is
zero. The historical two-file `isinstance` count fell from 603 to 260 (-343), and
`projections.py` `dict[str, Any]` occurrences fell from 174 to 102 (-72).
Task 14 documentation commits are `1b03d5a05` and `938b87ff7`; final source
repair is `185f31abc`. This later bookkeeping reconciliation is pending a final
documentation commit and does not assert a future SHA.

**Supersedes:** The compatibility-first migration strategy in
`2026-07-09-w5-typed-payloads-completion-design.md` and the remaining queue in
`docs/dynamic-graph/w5-completion-agent-prompt.md`

## Objective

Complete W5 with one architectural pattern for every graph event and command,
including audit-only events. The design must remove entire defect categories,
not merely make the existing distributed maintenance process faster.

After the cutover:

- payload shape has one authoritative definition;
- producers cannot emit unvalidated dictionaries;
- reducers and command handlers receive typed payloads;
- unknown or misspelled fields fail at the boundary;
- compact and checkpoint reads do not reconstruct partial event payloads from
  hand-maintained field lists;
- adding a normal field does not require edits across storage, API, reducer
  parsing, exports, and bespoke test scaffolding.

The system currently runs on one machine. Existing runs and the database are
disposable, so historical replay compatibility is not a constraint.

## Non-goals

- Preserve or convert events from the current database.
- Accept malformed, sparse, or unknown historical payload shapes.
- Promote shared JSON payload fields into relational columns during W5. That
  follow-up is recorded in
  `docs/dynamic-graph/post-w5-event-column-promotion.md`.
- Introduce YAML, JSON Schema, or another external schema language that would
  duplicate the Pydantic model definitions.
- Normalize intentionally opaque nested business values. Such values must
  still be named, explicit fields with a deliberate JSON-value type; they are
  not a catch-all for unknown top-level keys.

## Architectural principles

### One schema artifact

Strict Pydantic payload models are the only payload schema definitions. Models
use strict validation and `extra="forbid"`. They do not contain a general
`extra` field or legacy `mode="before"` compatibility normalizers.

The same model drives validation, serialization, deserialization, API schema,
catalog contract tests, and typed dispatch. Storage and read paths must not
copy its field list.

### Domain ownership

Payload models, their specifications, and domain handlers are grouped into
focused modules such as `graph/events/leases.py` and
`graph/commands/callbacks.py`. W5 must not continue growing a single
`graph/models.py` or a central event-type conditional.

Each module exposes immutable specifications through its public module API.
The application composition root constructs and injects the complete catalog.
There is no mutable global registry.

### Parse once

Raw JSON exists only at the database and external API boundaries. An event is
hydrated through the catalog once after loading. Reducer dispatch then passes
the concrete payload model to its typed handler. Reducers do not call
`model_validate`, inspect raw dictionaries, or repeat tolerance logic.

Commands follow the same rule: validate once at the API/controller boundary,
then dispatch a typed command payload to a typed handler.

### Complete payloads on read paths

Compact, summary, checkpoint, and node-detail paths carry the complete strict
event payload. W5 deletes the four field allowlists instead of generating
partial copies of event payloads.

Strict payloads bound accidental size by rejecting unknown fields. If a later
benchmark proves that complete payload reads are too expensive, a generated
physical optimization may be introduced from the models. A hand-maintained
allowlist is never an acceptable fallback.

## Components

### Strict payload base

A small payload base establishes strict Pydantic configuration and JSON-safe
serialization. Domain models inherit it and define every accepted top-level
field. Legitimately opaque data uses an explicit named field and a bounded JSON
value type.

### Event specification

An immutable generic event specification binds:

- the durable event name;
- the concrete payload model;
- the typed reducer handler;
- projection participation needed for catalog checks.

The specification exposes typed construction and hydration operations. Event
producers use the specification or a typed event factory; `make_event` no
longer accepts `dict[str, Any]`.

### Command specification

An immutable generic command specification binds:

- the command name;
- the concrete request/payload model;
- the typed command handler.

The existing 23-name command dispatch table becomes a composed catalog of
typed specifications. Commands with no data use an explicit empty strict model
rather than an untyped or optional dictionary.

### Injected catalog

The composition root combines domain specifications into one immutable
catalog, rejects duplicate names, and verifies complete event and command
coverage at startup. The catalog is injected into the controller, compiler,
event loader, command dispatcher, and API dependencies.

Catalog construction is deterministic and side-effect free. Domain logic can
be tested with only the relevant specifications.

### Stored and hydrated envelopes

The stored envelope retains universal relational columns such as run ID,
position, event ID, event type, timestamp, causation/correlation identity, and
payload schema generation. Its type-specific payload remains validated JSON.

Loading produces a hydrated domain event whose payload is the model declared
by the event specification. Invalid persisted JSON is a corruption error, not
a tolerated legacy variant.

## Data flow

### Command to event

1. The API or controller resolves the command specification by name.
2. The specification validates the request into its strict payload model.
3. The typed command handler applies domain rules to a typed projection.
4. The handler emits events through typed event specifications.
5. The event store serializes the validated model into the stored envelope.

### Event to projection

1. The event store loads the universal envelope and complete JSON payload.
2. The injected catalog resolves the event specification by durable name.
3. The specification hydrates the strict payload model exactly once.
4. The catalog invokes the specification's typed reducer handler.
5. Projection and snapshot serializers write their own typed models.

Audit events use the same construction, persistence, hydration, and catalog
coverage even when their reducer handler is explicitly projection-neutral.

## Failure behavior

- Unknown event or command name: explicit catalog-resolution error.
- Missing, incorrectly typed, or extra payload field: boundary validation
  error before domain execution or event append.
- Invalid payload found in storage: explicit event-corruption error with run,
  position, event name, and validation detail.
- Duplicate specification name: application startup failure.
- Catalog coverage gap: test and startup failure.

Errors are domain-specific and do not fall back to permissive dictionary
handling.

## Database cutover

No automatic destructive startup behavior is added. The operational cutover
is explicit:

1. Stop the server.
2. If `orchestrator.db` exists, back it up and verify the backup before removal.
3. If it does not exist, record that no backup/reset is necessary before
   compatibility cleanup.
4. Start the application and let Alembic/create-on-empty establish the current
   schema.
5. Seed required factory data and run a typed graph smoke test.

Task 13 took the absence branch. Its exact contemporaneous record is:
`No worktree orchestrator.db existed; per Task 13, no backup or reset was
necessary.` Normal startup then initialized the current strict schema, after
which Task 13 deleted D1-D6 compatibility. No old database was converted or
destroyed.

Fresh-database journal bootstrap deliberately excludes `graph:` aggregates
because their strict generation-2 envelopes cannot be reconstructed by generic
workflow restore. It leaves those records in the journal, skips malformed
records, and continues restoring valid workflow history.

No migration converts old graph events or snapshots. A payload schema
generation on stored envelopes makes accidental use of an incompatible
database fail clearly.

## Migration strategy

### 1. Framework vertical slice

Introduce strict payload bases, generic specifications, the injected catalog,
typed stored/hydrated envelopes, and catalog-wide contract tests. Convert one
representative event and command end to end to prove the interfaces.

### 2. Domain event conversion

Move payload models and reducer handlers into domain modules. Convert every
live produced or consumed event, including audit-only and explicitly
projection-neutral events. Delete aliases and reducer branches that exist only
to replay old event logs. Previously added W5 models provide a field inventory,
but their compatibility validators and `extra` containment behavior are
deliberately removed.

Mechanical edits may be generated or codemodded from the catalog, but the
Pydantic models remain the source rather than generated output from a second
schema language.

### 3. Command conversion

Convert all registered commands, including empty and internal commands, to
strict payload models and typed handlers. API schemas and controller entry
points validate through the same specifications.

### 4. Projection and storage cutover

Delete per-event parse wrappers, raw payload extraction helpers, and the four
payload field allowlists. Compact and checkpoint reads carry complete payloads.
Projection fields that represent domain records become concrete models rather
than `dict[str, Any]` maps.

### 5. Enforcement and cleanup

Add static/catalog checks that prevent unregistered names and raw payload
access. Remove superseded compatibility tests and replace repetitive model
tests with catalog-wide contracts plus focused domain behavior tests.

### 6. Explicit database branch and verification

If the database exists (Branch A), stop the server, create and verify a backup,
reset the disposable database, and fresh initialize the strict schema. If the
database is absent (Branch B), record the absence and fresh initialize the
strict schema with no backup/reset. After either branch initializes
successfully, delete compatibility and verify fresh-run creation, event replay,
checkpoints, compact reads, node detail, summaries, and graph completion.

## Testing and enforcement

Catalog-wide parameterized tests cover every event and command specification:

- strict validation rejects missing, mistyped, and unknown fields;
- model serialization and hydration round-trip;
- event names and command names are unique;
- every emitted or consumed event name is registered;
- every command handler name is registered;
- projection-neutral audit events are explicit rather than omitted;
- stored full replay, checkpoint replay, and compact replay agree.

Static checks fail on new kernel uses of:

- `event.payload.get(...)` or equivalent raw event-payload indexing;
- `payload: dict[str, Any]` at event or command boundaries;
- event creation with a dictionary payload;
- per-read-path payload field allowlists;
- legacy payload normalizers or catch-all top-level `extra` fields.

Focused tests remain for domain semantics, not for repeating generic model
behavior per family.

## Change-spread acceptance criteria

The architecture is not complete merely because all payloads have model names.
Representative maintenance exercises must demonstrate:

- adding an ordinary field changes one payload model and relevant domain
  behavior only;
- adding an event changes one cohesive domain module (payload model,
  specification, and handler) and its domain behavior test, without storage or
  central-dispatch edits;
- adding a command changes one cohesive command module (payload model,
  specification, and handler) and its behavior test, without API schema
  duplication or central-dispatch edits;
- storage serialization, hydration, API schema, round-trip coverage, and
  catalog coverage update automatically from the specification.

Infrastructure files must not participate in ordinary domain-field changes.

## Completion criteria

- One strict typed pattern covers 100% of events and commands, including audit
  and projection-neutral events.
- No catch-all top-level payload fields or historical compatibility validators
  remain.
- No producer emits a raw payload dictionary.
- No reducer or command handler consumes a raw payload dictionary.
- The four hand-maintained payload field allowlists are deleted.
- Typed projection fields replace remaining payload-shaped
  `dict[str, Any]` maps within the W5 scope.
- Catalog completeness and change-spread tests pass.
- Corpus replay, full graph tests, full backend tests, Ruff, and Pyright pass.
- A fresh database completes representative graph runs on the strict schema.
- W5 documentation records before/after complexity metrics and closes the old
  slice queue.

## Deferred persistence optimization

After W5 establishes trustworthy schemas and access patterns, evaluate
promoting frequently queried shared JSON fields into real relational columns.
The reminder and decision criteria live in
`docs/dynamic-graph/post-w5-event-column-promotion.md`. That work is explicitly
outside this design's implementation target.
