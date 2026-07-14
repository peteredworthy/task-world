# Deferred: Promote Shared Graph Payload Fields to Relational Columns

**Status:** Deferred until after the W5 strict payload architecture cutover

**Recorded:** 2026-07-10

**Current target:**
`docs/superpowers/specs/2026-07-10-w5-strict-payload-architecture-design.md`

## Final W5 Baseline

W5 closed with exactly 44 event specifications and 23 command specifications.
All measured raw-boundary, direct-dictionary construction, legacy normalizer,
top-level payload-extra, central-dispatch, allowlist, remaining migration,
second-run, unclassified dynamic-site, retired-compatibility, and deferred
D1-D6 counts are zero. The historical two-kernel-file `isinstance` count fell
from 603 to 412 (-191); `projections.py` `dict[str, Any]` occurrences fell from
174 to 102 (-72). Remaining dictionaries include dynamic indexes and named
opaque/public JSON, not a license to promote fields without measurements.

Task 11 complete-read baselines provide the starting cost data:

| Workload | Rows | Complete payload bytes per reader | Median allocated peak range |
|---|---:|---:|---:|
| Fixture scale | 300 | 19,731,738 | 60,304,850-60,309,546 bytes |
| Generated scale | 1,000 | 131,308,839 | 397,651,584-397,744,576 bytes |

All five readers had payload parity. These figures motivate investigation but
do not approve relational promotion; this document remains deferred.

## Reminder

Once every graph event and command uses the strict model-driven catalog,
evaluate moving frequently queried fields from the event payload JSON column
into real relational columns, generated columns, indexes, or purpose-built
projection tables.

This is intentionally not part of W5. Strong payload types must land first so
column choices are based on stable semantics and measured access patterns
rather than today's defensive dictionary handling.

## Why defer it

Combining strict payload conversion with relational normalization would couple
two independent migrations:

1. Establishing the canonical event and command schemas.
2. Choosing and maintaining a physical query/storage representation.

Deferral keeps W5 focused on eliminating shape drift and reducing change
spread. The completed type catalog will make later column promotion safer and
more mechanical.

## Preconditions

Begin this follow-up only after:

- W5 covers 100% of events and commands with strict models;
- complete typed payload reads have replaced the four hand-maintained field
  allowlists;
- representative graph runs produce query and payload-size measurements;
- event, checkpoint, summary, and node-detail access patterns are stable;
- the database is on the current strict payload schema generation, whether by
  fresh initialization (the W5 Branch B path) or a verified reset.

## Questions to answer with measurements

- Which fields are filtered, joined, sorted, or grouped in SQL frequently
  enough to justify physical columns?
- Which common-looking names have genuinely identical semantics across event
  families?
- Would a universal envelope column, generated column, index, or projection
  table best serve each access pattern?
- How much CPU and I/O does complete JSON payload loading consume after strict
  models remove unknown and redundant fields?
- Can promoted-column definitions or migrations be derived from catalog model
  metadata without creating another hand-maintained mirror?

## Likely candidates for evaluation

These are investigation candidates, not approved schema changes:

- node, lease, execution, session, patch, record, and requirement identifiers;
- task-region identity;
- lifecycle state, outcome, verdict, and decision fields;
- attempt and generation numbers;
- retry and expiry timestamps;
- correlation and causation identifiers not already in the universal envelope.

Fields belong in the universal event envelope only when their meaning is truly
universal. Otherwise prefer event-family columns, generated columns, indexes,
or projection tables over nullable columns whose semantics vary by event type.

## Architectural constraints for the follow-up

- Pydantic/catalog schemas remain the semantic source of truth.
- Do not reintroduce manually synchronized payload-field lists.
- Promoted values must be written or derived automatically from validated
  payload models.
- Full event replay remains behaviorally equivalent to checkpoint and compact
  reads.
- Physical schema optimization must not force domain producers and reducers to
  know storage layout.

## Completion evidence for the follow-up

- Before/after query, storage, and replay benchmarks.
- A documented field-promotion decision for each measured hot path.
- Migrations and indexes derived from or checked against the typed catalog.
- Parity tests across full replay, checkpoints, summaries, and node detail.
- A demonstrated reduction in JSON extraction or payload-loading cost without
  increasing ordinary domain change spread.
