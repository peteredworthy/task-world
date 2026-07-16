# W5 - Typed Payloads End-to-End

Status: **closed 2026-07-16**.

Addresses weakness **W5** (medium) and improvement **#6** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Historical Origin

W5 began as an incremental proposal to type one read-side payload family at a
time while preserving historical event-shape tolerance. That proposal is not an
operative requirement. The database and durable event history were reset before
the residual completion work, so the final architecture deliberately removes
the compatibility aliases, permissive payload `extra` maps, normalization
adapters, mapping facades, and generic record fallbacks described by the early
proposal.

## Scope

W5 covers the complete current graph payload boundary:

- 46 canonical event names, their exact payload models, producer ownership, and
  per-event compact-read retention specifications.
- Validation and canonical JSON serialization at every current event producer.
- Strict parsing of canonical events during replay and reduction, without
  retired event aliases or historical payload normalization.
- The 22-discriminator typed output-record registry, strict file-state records,
  strict gatekeeper verdict/cost rows, and typed projection values.
- 23 strict command payloads, exact typed handlers, separate runtime context,
  and shared command/API schemas.
- Strict `GradeRow` values in verification reports.

Durable check-output artifact storage and recovery of truncated stdout/stderr
belong to W5.5 and are explicitly outside W5.

## Architecture

### Canonical Events

`CANONICAL_EVENT_TYPES` is derived from immutable internal producer ownership
plus the sole external-ingress event, `lease_suspended`. It contains exactly 46
names. `EVENT_PAYLOAD_MODELS` and `EVENT_PAYLOAD_SPECS` have exactly the same
keys, and every spec references the exact registered model.

Current producers call their ownership guard, validate through the registered
payload model, and serialize with `model_dump(mode="json")` before constructing
or persisting an `EventEnvelope`. The envelope remains JSON-shaped at the
storage boundary; typed models own its canonical shape on both emission and
consumption. No modeled event returns the caller's original dictionary after
validation. Explicit `exclude_none`/`exclude_unset` policies exist only for
documented sparse wire contracts; all other events use the complete JSON dump.
Unknown top-level fields are rejected. Flat output-record and
file-state `RootModel` envelopes delegate this strictness to their canonical
record roots.

Replay and reducers consume canonical names only. Removed proposal,
environment-failure, requirement/support, authority-resolution, and suspect
resolution aliases are not producer-owned or reducer-consumed. Malformed or
obsolete shapes are rejected rather than normalized through compatibility
helpers.

### Retention

Every canonical event owns explicit `projection`, `light`, `summary`, and
`node_detail` field sets in its `EventPayloadSpec`. A retained field must be
serialized by that event's model; no global field-name inference or compatibility
exception exists. The specs generate four sorted unique global tuples:

- `GRAPH_PROJECTION_PAYLOAD_FIELDS`: 105 fields.
- `LIGHT_GRAPH_PAYLOAD_FIELDS`: 144 fields.
- `SUMMARY_REBUILD_PAYLOAD_FIELDS`: 160 fields.
- `NODE_DETAIL_PAYLOAD_FIELDS`: 92 fields.

Complete nested check-result `value` retention intentionally remains until the
atomic W5.5 artifact cutover.

### Records And Projections

`OUTPUT_RECORD_MODELS_BY_TYPE` contains 22 explicit discriminators. Missing and
unknown discriminators are rejected; no generic or legacy output-record model
survives. File-state accepted/rejected envelopes use strict canonical roots.
Gatekeeper verdict and cost models reject unknown or wrongly typed fields.

Structured projection values use Pydantic models and attribute access where
their schema is owned by the graph domain. Dynamic identifier indexes remain
maps, and explicitly documented external/public JSON or provider metadata stays
JSON-shaped. Compatibility mapping facades are absent.

### Commands And API

`COMMAND_SPECS` contains exactly 23 names. Each maps one
`StrictCommandPayload` subclass (`extra="forbid"`, strict scalar validation) to
a handler whose payload annotation is that exact model. `apply_command` is the
single raw command-ingress validator. Runtime identity, actor, graph position,
and patch provenance are supplied separately through `GraphCommandContext` or
`PatchCommandContext`, never accepted as command payload fields.

Command, record, node, lease, execution, idempotency, requirement, support,
cleanup, and evaluation identifiers use a shared strict nonempty contract that
rejects whitespace. Validation failures are rendered from bounded
`errors(include_input=False)` details, so rejection events retain location and
error type without copying submitted values or unbounded provider text.

Decision API requests reuse `RecordDecisionCommand`; patch API and command
models share `PatchCommandFields`. HTTP-only length, pattern, nonnegative
position, and required-operation constraints remain at the HTTP boundary.

### Verification Grades

`GradeRow` is exported, inherits the strict nested-model policy, requires
`requirement_id` and `grade`, permits an optional `reason`, and rejects unknown
fields. `VerificationReportValue.grades` is a typed list of `GradeRow` values.

## Requirements

- [x] **R1 - Exact canonical event coverage.** All 46 canonical events have one
  exact strict payload model and one explicit retention spec.
- [x] **R2 - Producer validation.** Every current producer validates ownership,
  validates the payload, and emits canonical JSON.
- [x] **R3 - Strict replay.** Reducers parse canonical typed envelopes; obsolete
  aliases and historical normalization paths are removed.
- [x] **R4 - Explicit generated retention.** Per-event specs generate all four
  global retention tuples, and retained keys are model-owned.
- [x] **R5 - Typed records and projections.** All 22 output-record
  discriminators, file-state/gatekeeper envelopes, and schema-owned projection
  values are strict and typed.
- [x] **R6 - Typed commands and API reuse.** All 23 commands have strict exact
  models and handlers, runtime context is separate, and API schemas reuse domain
  contracts without losing HTTP-only constraints.
- [x] **R7 - Typed grades.** Verification grade rows use strict `GradeRow`
  values.
- [x] **R8 - Compatibility deletion.** Retired aliases, permissive payload
  `extra`, generic record fallback, selector normalization, mapping facades, and
  graph `mode="before"` validators are absent.
- [x] **R9 - Verification and documentation.** Focused batches, full backend,
  Ruff, Pyright, diff checks, metrics, inventories, and the progress ledger are
  complete.
- [x] **R10 - Identity and error safety.** Semantic scalars and identities reject
  coercion/blank values, command validation errors are bounded and redacted,
  and `StoredArtifactRef.storage_uri` carries the same SHA-256 digest as
  `content_hash`.

## Constraints

- Pydantic validation and reduction remain deterministic and side-effect free.
- JSON event storage and public read-model shapes remain stable where explicitly
  documented; strictness is enforced by registered domain models rather than
  compatibility adapters.
- Dynamic identifier maps and intentionally flexible external/public metadata
  are not converted merely to reduce `dict[str, Any]` counts.
- W5 does not add artifact-store I/O, stdout/stderr reference fields, hydration,
  garbage collection, artifact-aware SQL, or truncation recovery.
- Tests use real objects and dependency injection; no mocks, patches, type
  suppressions, or weakened assertions are introduced.

## Acceptance

The final accepted source implementation head is
`29c5264d9` (`Redact durable graph rejection reasons`). The documentation
closeout is the commit containing this update; it intentionally does not
self-reference its own hash.

- Registry audit: 46 canonical names, 46 models, 46 exact specs, all strict.
- Command audit: 23 strict payloads and 23 exact typed handlers.
- Output-record audit: 22 explicit discriminators.
- Generated retention at final-review correction head: 105/144/160/92 fields.
- Durable rejection reasons use one graph-internal safe renderer. Pydantic
  validation retains at most eight location/type entries and 1,000 characters
  without rejected input or user-derived messages; arbitrary `TypeError` and
  `ValueError` paths emit fixed safe codes/messages.
- `SubmitCallbackCommand.payload_hash` and string decision deciders are strict,
  nonblank domain-ingress values.
- Focused callback/patch/command/gatekeeper/macro/API audit: 305 passed.
- Full backend: 4,779 passed, 3 skipped, 3 existing `aiosqlite` warnings.
- Ruff: all checks passed.
- Format: 702 files already formatted.
- Full Pyright: 0 errors, 0 warnings, 0 informations.
- `git diff --check`: passed.
- Pre-commit hooks: Ruff, format, secret detection, Pyright, pytest, module
  imports, signal routing, UI lint, and UI typecheck passed; enum drift skipped
  because no relevant files changed.
- Metrics: `isinstance(` 603 to 465 (-138); `dict[str, Any]` 174 to
  136 (-38); direct `event.payload.get(` 28; total `payload.get(` 89; graph
  before validators 0.

Historical evidence: `bafeb650d27884ae5584f1fb4b4378780b4f587f`
(`Correct event payload implementation docs`), the 145-test focused audit, and
the 4,756-test backend run were the earlier W5 closeout baseline. They are
superseded by the final-review evidence above, not current-head results.

Exact commands and timings are retained in `../w5-progress-ledger.md`.

## W5.5 Deferral

W5 closure does not claim durable stdout/stderr artifact persistence,
reference-field cutover, bounded hydration, garbage collection, event-aware
artifact SQL, or recovery of content beyond the current 20,000-character
truncation. Those remain pending in:

- `docs/superpowers/specs/2026-07-15-w5-artifact-output-design.md`
- `docs/superpowers/plans/2026-07-15-w5-artifact-output.md`
