# R08 — Consolidate Sources of Truth; Shrink the Legacy Surface

**Priority: P2 (deliberately after the P0/P1 items). Effort: medium-large,
incremental.**

## Problem

The system's own diagnosis (docs/intent/30) is that multi-source-of-truth
coordination causes its recurring bug classes. The graph stack fixed this for
graph state; three copies of the disease remain:

1. **Prompt triplication**: builder/verifier system prompts exist as
   hardcoded strings (`workflow/agent/prompts.py`), a second hardcoded SDK
   variant (`build_claude_sdk_prompt`), and editable DB rows
   (`agent_configs`) — drift is unguarded (the exact risk
   `token-cost-improvements/04` flagged).
2. **Legacy engine liabilities**: `SessionStateManager` whole-state JSON
   snapshots coexist with the event store; migration phases 3-5 (20 mutable
   columns, 8 `oversight_state` mutation sites, 4 `pause_reason` allowlists)
   were never finished; TD-06 (locks never time out) and TD-09 remain.
3. **Graph runtime still lives partly inside the legacy module**:
   `workflow/graph_driver.py` hosts the drive loop and deliberately
   duplicates dispatch helpers; W8's headline no-op is already fixed
   (`recovery.py:35` does real dispatch) but the broader loop cleanup and
   relocation remain.

## Proposed change (in order)

1. **Single prompt source**: make DB `agent_configs` (seeded from files in
   `src/orchestrator/agents/prompts/`) the only source; the SDK builder and
   workflow strings consume it. One drift test: seeded defaults ==
   file contents.
2. **W8 remainder**: finish the spec's loop simplification (the `recovery.py`
   no-op is already fixed) and, as part of it, **move `graph_driver.py` out
   of `workflow/` into `graph_runtime/`**, importing the shared helpers
   instead of mirroring them (kills fragility F2).
3. **Legacy disposition inventory instead of migration phases 3-5** (OQ-7):
   enumerate what still executes only on the legacy carrier (routine
   approval flows? clarifications? oversight?). For each: port to graph,
   or freeze-and-document. Do **not** invest in completing the legacy
   event-migration for its own sake — the graph carrier already is the
   target architecture; finishing a migration for code that should retire is
   wasted motion. Explicitly decide claude_sdk's fate here too (OQ-5).
4. **TD-06** while touching locks: make `InMemoryLockManager` honor its
   timeout contract (raise `LockTimeoutError`) — the pessimistic-locking
   principle is currently unenforced.

## Expected benefit

- Removes the drift class of bugs at its remaining roots rather than patching
  symptoms.
- Shrinks the surface future agents must understand (the two-architectures
  problem is the single biggest onboarding cost visible in the docs).

## Cost / complexity

Item 1 small; item 2 medium (mechanical but touches the drive loop — do
after R01, with the incident-fix comments preserved as tests, not comments);
item 3 is an investigation then a series of small ports.

## Risks

- The drive loop encodes hard-won incident fixes as subtle interacting
  guards; a move-refactor could silently drop one. Mitigate: before moving,
  convert each dated incident comment into a named regression test (several
  already exist — verify coverage per guard).
- Legacy removal can break UI paths that still read legacy fields; the
  disposition inventory must include UI consumers.

## Validation

- Prompt drift test; full FR + e2e suites; a replayed historical incident
  stream per drive-loop guard.

## Dependencies

After R01 (don't refactor the loop while a known kernel gap is open);
independent of R02-R07 but sequenced last to avoid churn under the P1 work.
