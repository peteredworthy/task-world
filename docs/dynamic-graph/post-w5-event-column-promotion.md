# Deferred: Promote Shared Graph Payload Fields to Relational Columns

**Status:** Deferred — precondition (100% strict payload catalog) is met on
main, but no representative measurement pass has been run against main's
actual implementation yet.

**Recorded:** 2026-07-22 (ported from `backup/origin-main-2026-07-21`, an
abandoned parallel W5 implementation attempt dated 2026-07-10; the idea and
preconditions outlived that branch even though its code did not).

**Current target:** `src/orchestrator/graph/payload_registry.py` and
`docs/dynamic-graph/re-evaluation-2026-07-18.md` (§8, deferred items).

## State on main

W5 shipped on main 2026-07-16 (ff-merged, 939 graph tests + ruff + pyright
green) via a different module decomposition than the abandoned branch. Per
`re-evaluation-2026-07-18.md` §8: the four payload allowlists are now
*generated* from typed models, and the `isinstance`/`dict[str, Any]` guard
count across the two kernel files is down from 526 to 401 post-W5.

The benchmark table below is carried over from the abandoned branch's own
instrumentation (a differently-shaped codebase) and does **not** describe
main. Before starting this work, re-run equivalent complete-read baselines
against main and replace this table.

### Original (abandoned-branch) baseline, for reference only

| Workload | Rows | Complete payload bytes per reader | Median allocated peak range |
|---|---:|---:|---:|
| Fixture scale | 300 | 19,731,738 | 60,304,850-60,309,546 bytes |
| Generated scale | 1,000 | 131,308,839 | 397,651,584-397,744,576 bytes |

All five readers had payload parity on that branch. These figures motivated
investigation but did not approve relational promotion there either — the
same caution applies on main until re-measured.

## Reminder

Now that every graph event and command uses the strict model-driven catalog,
evaluate moving frequently queried fields from the event payload JSON column
into real relational columns, generated columns, indexes, or purpose-built
projection tables.

This was intentionally not part of W5. Strong payload types had to land first
so column choices are based on stable semantics and measured access patterns
rather than defensive dictionary handling.

## Why defer it

Combining strict payload conversion with relational normalization would have
coupled two independent migrations:

1. Establishing the canonical event and command schemas.
2. Choosing and maintaining a physical query/storage representation.

Deferral kept W5 focused on eliminating shape drift and reducing change
spread. The completed type catalog makes this follow-up safer and more
mechanical.

## Preconditions

- W5 covers 100% of events and commands with strict models — **met on main**.
- Complete typed payload reads have replaced the four hand-maintained field
  allowlists — **met on main** (`payload_registry.py`).
- Representative graph runs produce query and payload-size measurements
  *against main* — **not yet done**; the table above is stale/foreign.
- Event, checkpoint, summary, and node-detail access patterns are stable.
- The database is on the current strict payload schema generation (main is,
  via the shipped W5 migrations).

## Questions to answer with measurements

- Which fields are filtered, joined, sorted, or grouped in SQL frequently
  enough to justify physical columns?
- Which common-looking names have genuinely identical semantics across event
  families?
- Would a universal envelope column, generated column, index, or projection
  table best serve each access pattern?
- How much CPU and I/O does complete JSON payload loading consume after
  strict models remove unknown and redundant fields?
- Can promoted-column definitions or migrations be derived from catalog model
  metadata without creating another hand-maintained mirror?

## Likely candidates for evaluation

Investigation candidates, not approved schema changes:

- node, lease, execution, session, patch, record, and requirement identifiers;
- task-region identity;
- lifecycle state, outcome, verdict, and decision fields;
- attempt and generation numbers;
- retry and expiry timestamps;
- correlation and causation identifiers not already in the universal envelope.

Fields belong in the universal event envelope only when their meaning is
truly universal. Otherwise prefer event-family columns, generated columns,
indexes, or projection tables over nullable columns whose semantics vary by
event type.

## Architectural constraints for the follow-up

- Pydantic/catalog schemas remain the semantic source of truth.
- Do not reintroduce manually synchronized payload-field lists.
- Promoted values must be written or derived automatically from validated
  payload models.
- Full event replay remains behaviorally equivalent to checkpoint and compact
  reads.
- Physical schema optimization must not force domain producers and reducers
  to know storage layout.

## Completion evidence for the follow-up

- Before/after query, storage, and replay benchmarks, measured on main.
- A documented field-promotion decision for each measured hot path.
- Migrations and indexes derived from or checked against the typed catalog.
- Parity tests across full replay, checkpoints, summaries, and node detail.
- A demonstrated reduction in JSON extraction or payload-loading cost without
  increasing ordinary domain change spread.
