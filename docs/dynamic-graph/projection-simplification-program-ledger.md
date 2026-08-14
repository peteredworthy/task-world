# Projection simplification program ledger

This ledger records the Stage 3 integration slice against the 2026-08-05
projection simplification report. It is intentionally a delivery ledger, not
a replacement for the report or a decision record for the unresolved product
questions below.

## Baseline and operating contract

| Field | Contract |
| --- | --- |
| Baseline | Clean worktree at `63bfc69e4db5746168418da82c627339d4099911` (current main). |
| Routine | Terminal Stage 3 integration run; one implementation worker, one fresh read-only verifier, and one final invariant check. |
| Config | Worker lease generation `1`; exact repository allowlist from the run specification; no discovery, corrective, speculative, or Stage 4 node. |
| Ownership | Canonical accepted/output records own full record values in `RecordStore.by_id`; secondary indexes contain IDs or summaries only; grouped projection remains the immutable boundary. |
| Dependencies | Authoritative typed events, canonical producer validation, reducer/index invariants, checksum/schema validation, and existing graph query consumers. Stage 4 mutable-builder work is not a dependency of this slice. |
| Evidence | Focused projection tests, boundary and signal checks, configured acceptance, hidden oracle, Ruff, Pyright, and the full test suite. |

## Mind-the-gap ledger

| ID | Surface / gap | Baseline | Intended disposition | Owner | Dependency / exit evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Stage 3 | Canonical projection records and disposable checkpoint | Shadow projected record/value hierarchy, conversion dispatch, and policy-heavy checkpoint validation | Reuse canonical accepted/output record models; preserve deep immutability at the ownership boundary; retain strict reducer/index checks; checkpoint is schema, position, serialized grouped state, checksum plus direct validation | Stage 3 implementation worker | Canonical model validation, every-split replay/checkpoint parity, focused and full tests | complete |
| Stage 4 | Mutable builder and FrozenMap removal | Persistent immutable updates throughout the reducer | Defer; do not alter mutable-builder or FrozenMap architecture in Stage 3 | Future Stage 4 owner | Stage 3 canonical ownership and checkpoint evidence | deferred |
| AR-A | External REST/Python consumer confirmation, telemetry, and deprecation-window owner | Consumer inventory is incomplete in this slice | Preserve as unresolved decision; no answer here | Unassigned | External consumer confirmation and product decision | unresolved |
| AR-B | Supported aggregate edge/binding diagnostic | Aggregate diagnostic need is not established | Preserve as unresolved decision; no answer here | Unassigned | Product/read-contract decision | unresolved |
| AR-C | Failed outbox rows as lifecycle veto or operator-health signal | Existing health/completion behavior must remain covered | Preserve as unresolved decision; no answer here | Unassigned | Operational policy decision and acceptance evidence | unresolved |
| AR-D | Failed-outbox requeue restoration | Requeue behavior exists in adjacent recovery work | Preserve as unresolved decision; no answer here | Unassigned | Recovery/operator workflow decision | unresolved |
| AR-E | Archived diagnostic materialization | Coupled archival views are a separate product choice | Inherit prior-run disposition: keep current behavior in this slice; no archival removal | Existing graph/runtime owner | Consumer audit and API contract | deferred |
| AR-F | Public query/export pruning and boundary retirement | Projection imports and immutable boundary are still live contracts | Inherit prior-run disposition: defer until after Stage 3 and Stage 4 | Graph API owner | Query consumer inventory and boundary review | deferred |

## Inherited-run dispositions

The paused run `r393` is not resumed. Its durable cleanup and recovery evidence
(resume positions `59645`–`59657`) is accepted as product-real evidence. The two
subsequent submissions are treated as lease-authority failures only; they do
not create a discovery or corrective obligation for this run. No unresolved
decision above is answered by that evidence.

## Stage boundaries

Stage 3 removes duplicate projected record/value schemas, conversion dispatch,
and obsolete relation-policy discovery/compiler/artifact machinery while
preserving producer, duplicate-ID, relationship, flexible-JSON, checksum,
schema/cache, secret, symlink, lease, byte-cap, and payload validation. Stage 4
owns the later mutable-builder and `FrozenMap` removal and is explicitly out of
scope.

