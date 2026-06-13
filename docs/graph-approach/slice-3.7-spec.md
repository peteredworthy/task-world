# Slice 3.7 — Retained planner session

Size: M. §6.1 promotes the retained session from "deferred" to **required for the
planner role**: the planner chain is one logical planning context, so resuming it
per generation (a new lease generation each time, per §19) must keep accumulated
understanding cheap to re-enter, with compression between generations. 3.1 built
the recursive horizon planner (region + successor planner, generation budget,
termination invariant) but treats each generation's lease as unrelated to the
previous one. This slice threads a shared planner **session** through the chain.

## Ground truth

- execution-graph-evaluation.md §6.1 — "Planner should be a retained session …
  resuming it per generation (new lease generation each time, per §19) keeps
  accumulated understanding of the run cheap to re-enter, with compression
  between generations. This promotes the retained-session decision from
  'deferred' to 'required for the planner role'."
- execution-graph-prd-plus.md §19 Lease and Callback Semantics — "Agent sessions:
  attached / suspended / detached / dead; session state may be retained for
  efficiency; **session state never grants permission**; resuming a session
  always requires a new active lease generation."
- §15.6 Planner lifecycle; the 3.1 kernel: `commands.py` planner lease/patch
  handling, `projections.py` `project_planner_chain`, `models.py` `LeaseModel`
  (`session_id`, `generation`), `NodeKind.SESSION`, session states.

## Scope — what to build

### 1. Planner session identity in the kernel (`commands.py`, `models.py`)

- A planner chain shares one logical `session_id`. The chain head planner (seeded
  by the compiler, 3.1) is assigned a `session_id` at lease grant; every successor
  planner created in a horizon patch **inherits the same `session_id`** (carried on
  the planner node / propagated when its lease is granted).
- Each generation gets a **new lease generation** (and/or new lease id) per §19 —
  resume never reactivates a suspended generation. The shared `session_id` is the
  only thing that persists across generations.
- Session lifecycle events (attached → suspended → detached/dead) recorded as
  accepted events through the controller path only (§28 rule 1). A generation
  ending (planner node completed / region handed to successor) suspends or
  detaches the session; the successor's lease re-attaches the **same** session_id
  under a fresh generation.
- **Session state never grants authority**: every mutating callback is still
  validated against the live lease generation, not the session. A callback bearing
  a valid `session_id` but a stale `lease_generation` is rejected stale exactly as
  in 3.1 (regression guard test required).

### 2. Compression carryover between generations (`commands.py`, `models.py`)

- The horizon patch may carry a `carryover_summary` record id (a planner-produced
  artifact record) that the successor planner's session re-enters with — a pointer
  to the compressed accumulated context, NOT new authority. Bind it as an
  optional successor input port (`session_carryover`, empty-allowed), alongside the
  3.1 milestone ports. No new bind authority; selector-bound like the others.
- The carryover is advisory context only; absence of it must not block readiness.

### 3. Projection (`projections.py`)

- `project_planner_session(events)` → `{session_id, state, generations:
  [{node_id, lease_generation, state}], current_node_id, carryover_record_id |
  None}` for UI/audit — one entry per planner chain (v1: single chain).
- Extend `project_planner_chain` entries with `session_id` and `lease_generation`
  so the chain view shows session continuity. Existing chain fields preserved.

### 4. Compiler (`compiler.py`)

- The seeded chain-head planner declares the chain's session intent so the first
  lease grant opens the session. Non-planner routines compile **unchanged**
  (minimal-graph guarantee from 2.2 must keep holding; existing compiler tests
  untouched).

## Tests

### Unit — `tests/unit/test_graph_planner_session.py` (new)

Pure / `GraphController`-free where possible; hand-built events:
- `test_successor_inherits_session_id` — successor planner created by a horizon
  patch carries the chain head's `session_id`; a new generation is assigned.
- `test_resume_emits_new_generation_same_session` — suspending a planner
  generation and re-leasing the chain emits a new lease generation under the same
  `session_id`; the suspended generation is never reactivated (§19).
- `test_session_does_not_grant_authority` — a callback with a valid `session_id`
  but stale `lease_generation` is rejected stale (no node outcome change).
- `test_carryover_binds_as_optional_input` — a horizon patch naming a
  `carryover_summary` record binds the successor's `session_carryover` port;
  absence binds empty and does NOT block readiness.
- `test_project_planner_session` — session projection reports id, state, ordered
  generations, current node, carryover record id.

### Integration — `tests/integration/test_graph_planner_session_flow.py` (new)

Real SQLite tmp DB, `GraphController` only (no HTTP, no runner):
- `test_two_horizon_chain_retains_one_session` — drive a two-generation planner
  chain (reuse 3.1 flow seeding); assert both generations share one `session_id`
  with distinct lease generations, the session suspends/re-attaches across the
  boundary, and event replay reproduces identical session + chain projections.
- `test_session_retained_but_authority_per_generation` — generation-2 callback
  under generation-1's lease is rejected stale; run still completes via the live
  generation.

## Done when

1. A planner chain shares one `session_id` across all generations; each generation
   is a new lease generation per §19 (resume never reactivates a suspended
   generation). All recorded via the controller append path only.
2. Session state never grants authority: callback validation remains
   lease-generation–scoped (stale-generation callbacks rejected even with a valid
   session_id) — regression-tested.
3. Optional `session_carryover` port binds a compression-carryover record between
   generations without affecting readiness when absent.
4. `project_planner_session` reports session id/state/generations/carryover;
   `project_planner_chain` shows session continuity. 3.1 chain semantics intact.
5. Compiler seeds the chain-head session; non-planner routines compile unchanged.
6. Full unit + integration suites green; kernel-only graph tests still fast.
7. Kernel purity unchanged; §28 rule 1 unchanged.

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written fake/recording classes only.
- Real SQLite tmp dirs only. Never touch `orchestrator.db` / main repo git.
- Kernel purity: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- `graph_runtime` imports no FastAPI / workflow-service internals.
- §28 rule 1: only `GraphController.handle_command()` appends graph events;
  session lifecycle events are appended ONLY through that path.
- v1 keeps §6.1's smallness: a single planner chain / single session; the one
  optional carryover binding above only. No parallel sessions.
