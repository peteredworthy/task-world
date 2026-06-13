# Slice 4.2 — Retire the parent/child oversight layer

Size: L. The convergence payoff: with parent/child re-expressed as a planner
chain (3.8) and human decisions/appeals/review surfaced in the graph UI (3.6),
the legacy super-parent oversight subsystem is redundant and is deleted. This
removes a whole multi-source-of-truth surface (~3.2k lines) that the
event-driven-intent memory traces bugs to.

## Prerequisites

- 3.8 (parent/child re-expressed as planner chain) merged — the capability must
  exist in the graph before its legacy implementation is deleted.
- 3.6 (decisions/appeals/review UI) merged — the operator-facing surface for
  oversight must exist in the graph UI.
- 4.1 (graph default carrier) merged — no live routine still depends on the
  legacy oversight path.

## Ground truth

- execution-graph-evaluation.md §6.1 "Parent/child maps directly … no second run
  lifecycle, no child worktree, no merge step."
- execution-graph-prd-plus.md §15.4/§15.5/§15.7 (gate/appeal/oversight/review as
  graph nodes), §22 human interaction/appeals/oversight.
- Legacy subsystem to retire: `workflow/parent_oversight.py` (~1507),
  `workflow/oversight.py` (~907), `oversight_facts.py`, `oversight_projection.py`,
  `child_templates.py`, `workflow/delegation/` super-parent paths, the related
  signals in `workflow/signals/runtime.py`, and the oversight/super-parent UI
  (`RunDetail`, `RunCard`, `CreateRunModal`, oversight panels, related types).

## Scope — what to build (mostly delete)

### 1. Inventory + dependency map (do first, commit as part of the slice)

- Enumerate every import of the oversight/super-parent modules across `src/` and
  `ui/`, and every route/signal/event type they own. Produce the deletion order
  (leaves first) so the suite stays green at each step.

### 2. Delete the legacy oversight subsystem

- Remove `parent_oversight.py`, `oversight.py`, `oversight_facts.py`,
  `oversight_projection.py`, `child_templates.py`, the super-parent `delegation/`
  paths, their API routes, and their signals — replacing call sites with the
  graph planner-chain path (3.8) where a caller remains, or deleting the caller
  if it was oversight-only.
- Remove the super-parent/oversight UI components and their types; the graph
  Decisions panel (3.6) is the replacement surface.
- Keep event *types* that are part of the immutable event-log history if removing
  them would break replay of historical runs — quarantine them as
  read-only/legacy rather than deleting the enum members. (Event-log durability
  is sacred; deletion is for live code paths, not recorded history.)

### 3. Migration / compatibility

- Existing legacy runs in the DB must still load read-only (their history
  replays). Add a test that an archived super-parent run still renders its
  recorded facts after the code is gone. No DB destruction; no Alembic down-rev
  surprises (single linear head).

## Tests

- `tests/integration/test_oversight_retired.py` (new): the oversight/super-parent
  API routes are gone (404); creating what used to be a super-parent routine now
  produces a planner-chain graph run (delegates to 3.8 behaviour); a previously
  recorded super-parent run still replays read-only.
- Delete/port the existing oversight test suites: tests that asserted legacy
  oversight behaviour are removed or rewritten against the planner-chain path. No
  test may import a deleted module.
- Frontend: oversight UI tests removed; the Decisions panel (3.6) covers the
  surface.

## Done when

1. The legacy oversight/super-parent code paths and UI are deleted; no live
   `src/` or `ui/` code imports the removed modules.
2. The parent/child capability is served entirely by the planner-chain (3.8) +
   graph Decisions UI (3.6).
3. Historical super-parent runs still replay read-only (event-log history intact;
   quarantined legacy event types, not deleted history).
4. Full suites green (unit/integration/vitest); ruff/pyright clean; kernel purity
   + `graph_runtime` boundary unchanged; no dead imports.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; real SQLite tmp; never touch `orchestrator.db` / main
  repo git; never destroy the event log or rewrite recorded history.
- Deletion order keeps the suite green at every committed step.
- §28 rule 1 unchanged; kernel purity + `graph_runtime` boundary unchanged.
