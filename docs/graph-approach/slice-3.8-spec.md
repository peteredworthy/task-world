# Slice 3.8 — Parent/child re-expressed as planner chain

Size: M. §6.1: "Parent/child maps directly: the parent becomes the planner chain,
child routines become horizon regions — with no second run lifecycle, no child
worktree, no merge step." This slice closes the dynamic-planning track by making
the legacy super-parent/child oversight pattern expressible as a planner chain in
the kernel — the structural bridge that lets Phase 4 retire the parent/child
oversight layer entirely. Builds on 3.1 (recursive horizon planner) and 3.7
(retained planner session).

## Ground truth

- execution-graph-evaluation.md §6.1 — "Parent/child maps directly: the parent
  becomes the planner chain, child routines become horizon regions — with no
  second run lifecycle, no child worktree, no merge step."
- execution-graph-prd-plus.md §15.6 Planner lifecycle, §16 Graph Patch Model,
  §17 readiness; §22 oversight/appeals (a child's escalation maps onto the chain's
  oversight/appeal nodes, not a separate run).
- The legacy "Super Parent Sequential Oversight" routine (existing routine in the
  catalog) is the reference parent/child shape to translate.
- 3.1 kernel (`compiler.py` planner seeding, `commands.py` horizon patch handling),
  3.7 planner session.

## Scope — what to build

### 1. Parent/child → planner-chain translation (`compiler.py`)

- A routine declaring the legacy parent/child oversight shape (a parent step with
  ordered child routine references) compiles into a **planner chain**: the parent
  becomes the chain-head planner; each child routine becomes a **horizon region**
  the planner is expected to emit (one generation per child), with the successor
  planner threading the prior child's accepted milestone records (§6.1 successor
  bindings + 3.7 session carryover).
- Translation is pure graph seeding: it produces planner + initial-context bindings
  ONLY. It creates **no second run, no child worktree, and no merge step** — the
  child regions execute in the parent run's single graph (assert these absences).
- A `child_routine` reference compiles to the region template the planner emits on
  that generation; ordering (sequential oversight) is expressed as the chain order
  (generation N's region must reach accepted before generation N+1 plans).

### 2. Child completion = region accepted (`commands.py`, `projections.py`)

- "Child finished" is re-expressed as "that generation's horizon region reached its
  accepted boundary" — no child-run status, no merge. The next child plans only
  when the prior region is accepted (3.1 termination/readiness; no new policy).
- `project_planner_chain` / `project_planner_session` (3.7) already expose the
  chain; add a `region_label` (the originating child routine name) per generation
  so the UI/audit can show "this generation == child X" — derived from the seed
  payload, no new mutation.

### 3. Oversight/appeal within the chain (no separate run)

- A child's oversight/appeal (legacy super-parent escalation) maps onto
  oversight/appeal nodes inside the chain's region (existing `create_appeal` /
  oversight ops, §16). No cross-run escalation path is introduced. v1 only needs
  to prove the mapping is expressible and seeded; full appeal UI is 3.6.

## Tests

### Unit — `tests/unit/test_graph_parent_child_translation.py` (new)

Pure; hand-built routine configs / events:
- `test_parent_child_routine_compiles_to_planner_chain` — a parent-with-two-
  children routine compiles to a chain-head planner with the children expressed as
  ordered horizon regions; NO second-run / worktree / merge artifacts are produced
  (assert their absence in the seeded graph).
- `test_child_order_is_chain_order` — child ordering becomes generation ordering;
  generation N+1's planner is not ready until generation N's region is accepted.
- `test_region_label_names_child_routine` — each generation carries the originating
  child routine name as `region_label` in the chain projection.
- `test_non_parent_routine_compiles_unchanged` — routines without the parent/child
  shape compile byte-identically (minimal-graph regression guard).

### Integration — `tests/integration/test_graph_parent_child_flow.py` (new)

Real SQLite tmp DB, `GraphController` only:
- `test_two_child_parent_runs_as_one_graph_run` — drive the translated chain:
  child-1 region planned + driven to accepted, child-2 region then planned and
  driven to accepted, run state `completed`; assert exactly one run lifecycle and
  no child worktree path was ever created; event replay reproduces projections.
- `test_child_oversight_maps_to_in_chain_appeal` — a child generation that routes
  to oversight/appeal resolves through in-chain appeal nodes (no separate run).

## Done when

1. A legacy parent/child oversight routine compiles into a planner chain whose
   generations correspond, in order, to the child routines — no second run, no
   child worktree, no merge step (asserted absent).
2. Child ordering == generation ordering: a generation plans only after the prior
   region is accepted (3.1 readiness/termination; no new scheduler policy).
3. The chain/session projections label each generation with its originating child
   routine, derived from the seed payload (no new mutation).
4. A child's oversight/appeal maps onto in-chain oversight/appeal nodes; no
   cross-run escalation is introduced.
5. Non-parent routines compile unchanged (regression guard green).
6. Full unit + integration suites green; kernel-only graph tests still fast.
7. Kernel purity unchanged; §28 rule 1 unchanged.

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written fake/recording classes only.
- Real SQLite tmp dirs only. Never touch `orchestrator.db` / main repo git.
- Kernel purity: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- `graph_runtime` imports no FastAPI / workflow-service internals.
- §28 rule 1: only `GraphController.handle_command()` appends graph events.
- Translation is pure graph seeding — it must NOT create a run, worktree, or merge
  step; those absences are explicitly tested.
