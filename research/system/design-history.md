# Design History, Intent, and Divergences

> Provenance: docs inspection at HEAD `23746c228` (2026-07-07), cross-checked
> against git log and source.

## The two coexisting architectures

1. **Original workflow system** (`docs/intent/01-ARCHITECTURE.md`):
   `Project → Run → Routine → Step → Task → Attempt` hierarchy. Non-negotiables:
   fresh LLM context per phase (Builder→Verifier→Revision), user chooses agent,
   git-versioned routines, pessimistic locking, event sourcing for recovery.
2. **Typed work graph** (`docs/graph-approach/execution-graph-prd-plus.md` +
   `docs/dynamic-graph/typed-work-graph-requirements.md`): *"Agents are
   effectful workers. The graph controller is the deterministic authority."*
   Now the default carrier; legacy is opt-out.

The pivotal design statement between them is
`docs/intent/30-EVENT-DRIVEN-MIGRATION.md`: make events the *sole* driver of
state — one pure `apply(state, event)` used identically at runtime and replay;
DB rows become derived caches. It diagnoses the legacy system's fragility as a
**multi-source-of-truth coordination problem** (SQLite row + in-memory
projection + JSON `oversight_state` blob + four hand-synced `pause_reason`
allowlists). The graph kernel *implements* this philosophy; the legacy carrier
never finished the migration (phases 3–5 undone: ~20 mutable columns without
event coverage, 8 direct `oversight_state` mutation sites, four `pause_reason`
allowlists still uncollapsed).

## Chronology

1. **Routine/Run workflow** — `docs/intent/01–21`, slice phases 1–10.
2. **Event-driven migration plan** — discovered Phase-3 event sourcing was
   specified but never wired as the runtime read path; "events = observability"
   won by accident.
3. **Execution graph clean-sheet** — PRD+ and slices DG-0.1…DG-5.2d (all in
   `graph-approach/complete/`). Dry-run modeling concluded graph *primitives
   were sufficient; the missing pieces were deterministic policies* (routing,
   proposal authority, evidence trust, final acceptance).
4. **Typed dynamic work graph** — `typed-work-graph-requirements.md`
   supersedes DG-5.1. FR-01–18 validated 2026-06-26 (FR-19 comparison-oracle
   admission explicitly out of scope). Validation standard: product-path proof
   through real runs, not tests ("tests are regression evidence only").
5. **W-spec hardening** (current) — from `dynamic-graph-implementation-review.html`.

## W-spec status (verified against git log at 23746c228)

| Spec | Intent | Status |
|---|---|---|
| W1 / W1b | Single read path (`GraphProjection`); kill raw event rescans | Merged (`c95793889`, `4073a0d4b`) |
| W2 | Recovery at source; `reconcile` escape hatch | Merged (`23768b98e`) |
| W3 | Incremental projection snapshots; deferral dedupe | Merged (`0a5e1b0ba`) |
| W4 | Split `commands.py` monolith into handler-registry package | Merged (`0a092e22d`) |
| W5 | Typed payloads (one family per slice) | **First slice only** (`884306176`, `5bd440506`); later families pending |
| W6 | Outbox hardening (backoff, failed-row surfacing, requeue) | Merged (HEAD `23746c228`) |
| W7 | Replace 3-probe glob-overlap heuristic with segment comparator (safety bug) | **Implemented on main** (`018483a3b` + tests `cea6282c9`; `_segments_may_overlap` at `scheduler.py:339`). The W-spec doc still reads as open — **docs stale, not code** |
| W8 | Drive-loop cleanup; remove `recovery.py` no-op | **Partially addressed**: `redispatched` now performs real dispatch (`recovery.py:35`), not the spec's `[]` no-op; broader loop cleanup unverified, no W8-tagged commit |

## Top documented open gaps (deduplicated, ranked)

1. **Final-gate poison / stale-identity pinning** (systemic; `incident-2026-07-04`):
   checks pass-gated on a fixed verifier node id are poisoned when that
   verifier fails; region acceptance pins "my latest candidate" rather than
   "lineage repaired". Partially addressed (P1 ledger items 3/5/6;
   failed→resuming + sweep supersession). The incident doc's "still-open
   kernel gap" (`_derive_task_states` ignoring cross-region supersession)
   **appears since addressed**: `_apply_accepted_region_supersessions`
   (`projections.py:4407`) flips superseded regions, and recovery-supersession
   helpers exist (`:4609`, `:4627`) — likely via `4f2cb0f58`/`7d60173c0`.
   Whether the *full* incident topology replays clean is unproven; see R01.
2. **SQLite write-path contention** (`BUSY_SNAPSHOT`) — hardened via
   `BEGIN IMMEDIATE`, locked-retry, W3 snapshot+tail; residual risk remains.
3. **Runtime-failed nodes reopen path** — partly wired (`5be3550cb`, `6f21bcf50`).
4. **`claude_sdk` cannot submit graph callbacks** — gated off; `codex_server`
   is the only reliable graph runner (P1 item 9).
5. **Event-loop starvation expiring live leases** — root cause was full-log
   JSON parse per command; W3/W5 targets; TTL widened 300→3600s as mitigation.
6. Light-vs-full projection divergence (parity fixed for task state in
   `4f2cb0f58`; needs standing parity tests).
7. Redundant work to satisfy invariants: duplicate acceptance-suite runs,
   gap-planners firing on success, dead branches needing agent retirement.
8. Legacy migration Phases 3–5 unfinished (see above).
9. Tech debt: TD-06 `InMemoryLockManager` never raises `LockTimeoutError`
   (pessimistic-locking contract unenforced); TD-09 `EventBroadcaster` opens a
   DB session per output line.
10. `docs/issues/001` — exhausted `max_attempts` marks task failed and
    proceeds silently; proposed pause/diagnose/fix flow unimplemented.

## Divergences (docs vs reality)

- `01-ARCHITECTURE.md` presents event sourcing as settled; `30-…` documents it
  was never the legacy runtime read path.
- W-spec/status docs describe W7 as an open safety bug; the fix is actually
  merged on main (`018483a3b`) — a divergence in the *stale-docs* direction.
  (An earlier draft of this wiki repeated the doc claim; corrected after
  source verification.)
- FR closure (2026-06-26) was contradicted the same day by dogfood run
  `784d9e7d` (`graph_blocked` on control regions); held only after the
  contract-driven task-region fix. Lesson: closure claims require product
  proof, and even then decay.
- `status.md` repeatedly disclaims green tests as validation ("regression
  evidence only") — an unusual and healthy epistemic stance worth preserving.
- Merge-back convention exists because graph runs were twice seeded from a
  stale base; now guarded by `intended_seed_sha` refusal (`65e36f370`).

## Design principles worth preserving (explicit in docs)

1. Event log authoritative; projections/rows are disposable derived caches.
2. Single mutation point: one pure `apply(state, event)`; replay same stream →
   byte-identical projection.
3. Controller is the only graph writer; agents propose, controller
   accepts/rejects. **Permissions are data, not prompt text** (PRD+ §21).
4. Kernel purity: no clock/random/IO in reducers; `now` and IDs injected.
5. Completion is a deterministic invariant over typed records, never
   prompt-only convention. No silent quiescence — every stopped non-complete
   graph exposes a typed blocker set.
6. Historical facts immutable — supersede, never edit.
7. Fresh context per phase; user chooses agent; git-versioned routines.
8. Closure rule: nothing is "done" without a named regression test re-run
   green **on main** — worktree-local green is not evidence.

See also: [graph-kernel](graph-kernel.md) · [overview](overview.md) ·
[../open-questions.md](../open-questions.md)
