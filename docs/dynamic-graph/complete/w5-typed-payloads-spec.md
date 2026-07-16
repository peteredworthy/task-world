# W5 — Typed event payloads end-to-end (incremental)

Status: **closed 2026-07-16**.

Addresses weakness **W5** (medium) and improvement **#6** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Problem

Records and node payloads have Pydantic models in `graph/models.py` but are validated
at the boundary and handled as `dict[str, Any]` everywhere else — `GraphProjection`
(a TypedDict of `dict[str, Any]` maps), the reducers, and command helpers all use
defensive extraction shims (`_payload_string_list`, `_is_*_record_payload`,
`_*_payload_for_validation`, …). Shape drift is caught at runtime, not by mypy.

The typed-edge-selectors commit (`478055890`) already proved the incremental path:
type one family, delete its shims, repeat.

## Scope (bounded — one slice)

Convert **one payload family per slice**. First slice: **output records** (they already
have Pydantic models and the densest shim usage). Later slices repeat the recipe for
verification results, check results, and node payloads. Do not attempt all families
at once.

## Architecture

1. Define a discriminated union for the family's event payloads (discriminator:
   `event_type` or the existing record `kind` field — inspect which is already
   reliable), reusing the existing models in `models.py`.
2. Parse once at the fold: `reduce_event` converts the raw payload into the typed
   model and stores the *typed* object in the projection field (change that
   `GraphProjection` field's annotation from `dict[str, Any]` to the model type).
   Malformed payloads must behave exactly as today (inspect current shim behavior:
   skip vs. default), not raise — the log may contain historical events.
3. Migrate readers of that projection field to attribute access; delete each
   `_is_*_record_payload` / extraction shim that no longer has callers.
4. Serialization boundary: events on disk stay JSON dicts — typing lives from
   fold onward. Snapshot persistence (if W3 landed) must round-trip the typed field.

## Requirements

**R1 — Typed at the fold.** The chosen family is parsed once in `reduce_event`; the
projection field carries model instances, not dicts. *Critical.*

**R2 — Shim deletion.** Every extraction shim exclusive to the family is deleted; grep
proves no `_is_<family>_record_payload`-style helper survives. *Critical.*

**R3 — Tolerance parity.** A test feeds a malformed/legacy-shaped payload through the
kernel and asserts identical observable behavior to before (same events, same
projection semantics). No `mock`/`patch` (AGENTS.md). *Critical.*

**R4 — mypy gate.** `uv run mypy src/orchestrator/graph` (or the project's configured
type-check command — check `pyproject.toml`/CI config) passes, and a deliberate typo
on a model attribute in a scratch check fails it. *Expected.*

**R5 — No behavior change.** Full graph suite green, no test weakened. *Critical.*

## Constraints

- Event schema on disk unchanged — this is a read-side typing change only.
- Kernel purity preserved; Pydantic validation in `reduce_event` must stay
  deterministic (no now()/uuid defaults firing in models).
- Keep the slice small enough to review; stop after one family.

## Acceptance

```
uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py \
  tests/unit/test_projectors.py tests/unit/test_command_handlers.py \
  tests/integration/test_graph_dynamic_e2e.py tests/integration/test_graph_event_store.py -q
```

All pass, plus R3 tolerance test and the R4 type-check gate.

## Closure

The incremental slices expanded through the complete current graph boundary.
All 46 canonical events now have exact strict payload models and explicit
four-mode retention specs; all current producers validate and JSON-dump their
envelopes. The command boundary has exactly 23 strict typed payloads and exact
typed handlers. Record, file-state, gatekeeper, API-schema, projection, and
verification-grade requirements are complete, and obsolete compatibility
models, aliases, adapters, and graph before validators are deleted.

Final verification at source head `bafeb650d27884ae5584f1fb4b4378780b4f587f`
passed 4,756 backend tests with 3 skipped, Ruff, final scoped Pyright with zero
errors, and `git diff --check`. Detailed evidence and metrics are recorded in
`../w5-progress-ledger.md`.

This closure is limited to W5 strict typing. W5.5 durable check-output artifacts
remain pending: stdout/stderr storage, reference-field cutover, bounded
hydration, garbage collection, and replacement/recovery of the current
20,000-character truncation are not implemented or claimed here. Their design
and implementation plan remain in `docs/superpowers/`.
