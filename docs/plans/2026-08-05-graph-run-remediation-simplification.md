# Graph Run Remediation Simplification

## Decision

The graph read remediation keeps the public bounded-read contract while
removing the durable digest/indexing subsystem introduced during R2.

Exact final blockers are queries over global current graph state. Avoiding
both a current-state projection in memory and a normalized event-targeted
projector is not possible. R2 therefore accepts one explicit bound: archival
maintenance may hold one current `GraphProjection` in memory, but it must read
authority history in fixed keyset batches and must never retain the complete
event history.

The accepted current-state bound includes transient ordering keys, deduplication
maps, and other scalar/index structures needed to produce deterministic rows.
It does not include complete derived topology, blocker, region, bound-record,
or support-ID payload collections: those must be yielded incrementally and
nested public prefixes must be capped before their response dictionaries are
constructed.

## Required behavior

- A graph append only marks archival owners dirty at the new target position.
  It does not traverse or replace topology, blocker, or region rows.
- Explicit background maintenance folds authority events in fixed keyset
  batches, builds all three archival owners as one generation, and publishes
  their shared position last in the same transaction.
- Public GET routes never rebuild or replay authority. They return the existing
  retryable 503 while a generation is missing or dirty.
- `expected_position` remains a structured retryable 409 contract.
- Archival pages retain count and byte caps, SQL size guards before JSON decode,
  and truthful partial metadata for bounded nested values.
- Node-detail collections retain normalized bounded facts. Summary prefixes are
  selected with capped keyset reads and SQL scalar counts.
- Truncated node-detail collections report `total_known`, `truncated`, and a
  stable continuation. Exact whole-collection `original_bytes` and `sha256`
  are not part of the contract for arbitrarily large collections.
- Artifact garbage-collection reachability must use bounded/keyset iteration,
  not one materialized set of every referenced hash.

## Removed design

- Archival staging generations, phase cursors, and region digest accumulators.
- Node-detail canonical-byte chunks, dirty collection state, resumable SHA-256
  state, and node collection publication work in the application lifecycle
  worker.
- Hand-written serializable SHA-256 implementation used only by those owners.

## Schema policy

There is no database schema-upgrade contract. Fresh file-backed and in-memory
databases are created directly from current SQLAlchemy ORM metadata. The
The former schema-upgrade runtime, revision chain, downgrade recreations, and
upgrade-only tests were removed rather than preserving the abandoned maintenance designs as
historical executable code. Existing database files are never altered or
deleted implicitly.

## Validation gate

R2 was independently validated on 2026-08-05 after product-real ASGI proofs for
all three archival routes, live/rebuild page parity, byte and nested caps,
atomic shared publication, retryable 409/503 responses, node-detail parity,
bounded artifact GC, and the absence of request-time replay or unbounded event
history materialization. The concrete evidence is recorded in the remediation
ledger; R8 is the active aggregate validation phase.
