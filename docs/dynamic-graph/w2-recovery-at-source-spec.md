# W2 — Move state repair out of `schedule_tick` to the causing command

Addresses weakness **W2** (high) and improvement **#2** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Problem

`_apply_schedule_tick` in `src/orchestrator/graph/commands.py` runs five repair
sweeps before it schedules anything:

- `_failed_check_recovery_events`
- `_failed_verification_recovery_events`
- `_passed_verification_terminalization_events`
- `_passed_check_terminalization_events`
- `_no_successor_recovery_terminal_failure_events`

Each exists because a lifecycle transition was not emitted where its triggering
event was applied (callback acceptance, check result). The graph goes quiescent
with non-accepted tasks, and a new sweep gets bolted onto the tick. The recurring
"graph quiescent" bug class traces here.

## Architecture

Emit follow-up transitions at the **source command**, and demote the sweeps to one
explicit escape hatch:

1. Identify the source command for each sweep. For verification/check results that
   arrive via `_apply_callback_command` (and the check-result path), the acceptance
   of that record must also emit the terminalization or recovery-arming events the
   corresponding sweep would later produce. Reuse the existing sweep functions as
   pure helpers called with a scope narrowed to the just-accepted record — do not
   duplicate their logic.
2. Add one idempotent `reconcile` command (new command type, same
   `apply_command` dispatch) that runs all five passes graph-wide. This is the
   operator/recovery escape hatch, invoked by startup recovery and by the driver
   only when quiescence is detected with unsettled state — never on the normal path.
3. Strip the five sweep invocations out of `_apply_schedule_tick`, leaving it pure
   scheduling (readiness, claims, dispatch, defer).

## Requirements

**R1 — Transitions at source.** For each sweep, the same events it would emit are now
emitted by the command that applies the triggering record. Scoped to that record — no
graph-wide rescan inside callback handling. *Critical.*

**R2 — `schedule_tick` is a scheduler.** No repair passes remain in
`_apply_schedule_tick`. *Critical.*

**R3 — `reconcile` command.** Idempotent (running it twice emits nothing the second
time), reuses the same pure pass functions, rejected cleanly on terminal runs.
Wire it into startup recovery (`graph_runtime/recovery.py`) and the driver's
quiescence-with-blockers path (`workflow/graph_driver.py`). *Critical.*

**R4 — Behavior parity.** Same terminal outcome and same *set* of lifecycle events for
existing scenarios; event *positions/order* may shift (transitions now happen earlier).
Update order-sensitive test assertions only where the earlier emission is the intended
change — never weaken an assertion about which events exist. *Critical.*

**R5 — No-sweep e2e proof.** The dynamic e2e run (worker fails verification → recovery
→ passes → terminal) reaches terminal state without the driver ever issuing
`reconcile`. Assert reconcile was not needed. *Critical.*

## Constraints

- Pure kernel: sweeps stay pure functions; the reconcile command is kernel-side, the
  runtime only issues it.
- No event schema changes; new command type is additive.
- Watch ordering hazards: emitting terminalization inside callback application changes
  the positions later commands see — `expected_position` flows in tests will shift.

## Historical acceptance and current regression command

The original W2 acceptance command named the now-retired
`tests/integration/test_graph_dynamic_e2e.py`. W2 is closed; do not recreate
that fixture. Its current joined and focused coverage is exercised with:

```
uv run pytest tests/unit/test_graph_commands.py tests/unit/test_command_handlers.py \
  tests/unit/test_graph_recovery_selection.py tests/unit/test_scheduler.py \
  tests/unit/test_graph_runner_boundary_commands.py::test_runner_recovery_completes_non_gap_planner_with_accepted_patch \
  tests/unit/test_graph_dispatch_on_output.py::test_gap_planner_submit_emits_classified_gap_after_accepted_nonempty_patch \
  tests/unit/test_graph_dispatch_on_output.py::test_gap_planner_submit_emits_no_gap_after_accepted_no_op_patch \
  tests/integration/test_graph_fr12_acceptance.py \
  tests/integration/test_graph_fr16_acceptance.py \
  tests/integration/test_graph_sequential_product_path.py -q
```

The retained tests establish source-command behavior, accepted-patch recovery,
gap/no-gap output, and joined terminal behavior without depending on the stale
scripted topology. Run the full graph suite (`uv run pytest tests -k graph -q`)
before merging changes to this area.
