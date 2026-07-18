# R01 — Pin the Assumed-Closed Gaps; Fix the Real Cost-Rate Hole

**Priority: P0 (do first). Effort: small.**

> Note: an earlier draft of this recommendation asserted two open bugs (W7
> glob overlap; cross-region supersession) based on the project's own status
> docs and incident memory. Source verification showed both are at least
> partially fixed already — the docs are stale, not the code. The
> recommendation is restated accordingly; the P0 work is now mostly
> *pinning closure* rather than fixing.

## (a) Prove the final-gate supersession fix with an incident-replay regression

- Repo evidence: `docs/dynamic-graph/incident-2026-07-04-*.md` names
  "`_derive_task_states` ignores cross-region supersession" as the still-open
  kernel gap. Verification shows handling now exists:
  `_apply_accepted_region_supersessions` (`graph/projections.py:4407`) plus
  recovery-supersession helpers (`:4609`, `:4627`), likely landed via
  `4f2cb0f58` / `7d60173c0`. What does **not** exist is a regression that
  replays the *full incident topology* (verifier fails → sibling region
  repairs cite the applied fix → task states, final blockers, and final gate
  all read clean).
- Closure: the named regression now reconstructs the incident's event shape
  through the real SQLite-backed `GraphEventStore` and proves the same outcome
  from full events, compact projection events, the incremental checkpoint, and
  a rebuilt checkpoint. It is a faithful minimal reconstruction, not a
  byte-identical production export or runtime-journal replay.
- Why P0: this incident family is the worst in the project's history, and
  the difference between "we think it's fixed" and "a named test pins it" is
  exactly the repo's own closure rule.

## (b) Make unmatched-model cost machine-visible; reconcile the rate table

- Repo evidence: `runners/costs.py:73-95` + `model_costs.yaml` fall back to
  an explicit zero-rate `unknown_model` entry. The *UI* shows "cost unknown",
  but run totals and any future budget/rollup count the usage as **$0 with no
  machine-readable flag**. The claude_sdk default model string
  `claude-sonnet-4-5` (`agents/claude_sdk/agent.py:446`) matches nothing in
  the YAML (nearest key: `claude-sonnet-4-6`) → the SDK default bills as
  free in aggregates today.
- Change: (1) set `rate_missing=true` on the usage record and emit a warning
  event when the fallback fires; (2) reconcile the YAML with every default
  model string the runners can emit; (3) unit test: every runner default
  resolves to a nonzero rate.
- Why P0: silently-$0 rows corrupt the cost data that R03/R04/R07 all
  depend on. Cheap to fix now, expensive to backfill later.

## (c) Correct the stale ledgers

- Repo evidence: W7 is merged (`018483a3b`, tests `cea6282c9` —
  `_segments_may_overlap`, `scheduler.py:339`) but
  `w7-glob-overlap-spec.md` and the implementation review still describe it
  as an open safety bug; W8's headline no-op is gone (`recovery.py:35` does
  real dispatch) with the broader cleanup unverified.
- Change: update the W-spec status entries to match main (W7 done with
  commit refs; W8 partial with what remains); this wiki's
  [design-history](../system/design-history.md) table is the corrected
  reference.
- Why P0-adjacent: stale "open safety bug" docs actively misdirect future
  agents — this research itself initially repeated them. Fifteen minutes of
  doc hygiene prevents repeated re-investigation.

## Risks

- (a) touches nothing — it is a test plus doc updates unless it fails; if it
  fails, the fix lands in `projections.py` (~4900 lines) — mitigate with
  pure-replay before/after comparison.

## Validation

- (a) the named regression green on main; (b) unit test + one live run per
  runner showing nonzero recorded cost; (c) doc diff reviewed against git log.

## Dependencies

None. Everything else benefits from these landing first.

## Backlog closeout triage — 2026-07-17

Fresh-main review confirms these four findings remain **OPEN**. This note
records current implementation evidence without changing the historical
recommendation or diagnosis:

- **Scheduler-view snapshot drift — OPEN.** `graph_runtime/store.py::_scheduler_view_from_projection` duplicates canonical scheduler policy and does not exclude ready `max_grants_reached` nodes.
- **Graph human-gate approval path — OPEN.** `GraphPanel` only renders pending gates; `runs approve` only posts to the legacy step endpoint.
- **Codex cli_subprocess model routing — OPEN.** `CLIAgent` constructs `codex --model MODEL exec ...` instead of `codex exec --model MODEL ...`.
- **R01(a) July 4 supersession replay — CLOSED.**
  `tests/integration/test_graph_read_models.py::test_july_4_incident_replay_preserves_supersession_and_completion_parity`
  jointly proves task acceptance, projection parity, empty final blockers, and
  completion through the real SQLite-backed store on all four projection paths.
