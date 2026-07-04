# W1b — Finish the single read path: residual raw-event scans

Follow-up to `w1-single-read-path-spec.md` (completed in `c95793889`). Addresses the
residual portion of weakness **W1** in `dynamic-graph-implementation-review.html`
(re-assessed 2026-07-03).

## Problem

The named high-risk helpers now read the folded `GraphProjection`, but six small
helpers in `src/orchestrator/graph/commands.py` still scan the raw event list, and
command-handler signatures still accept `events` alongside the projection — so
nothing structurally prevents the raw-scan idiom from returning.

## Scope (bounded)

Migrate these helpers to projection-derived fields (confirm names against current code;
find them via `grep -n "for event in events" src/orchestrator/graph/commands.py`):

- `_has_passed_completion_decision`
- `_current_passed_verification_results`
- `_retry_backoff_deferred_reason`
- `_cleanup_requested_event` / `_cleanup_applied_exists`
- `_node_creation_position`

Explicitly **out of scope** (legitimate raw-event uses — leave them):
- `_current_position` (max position — trivially event-derived)
- the patch-staleness scan over `events_since_base` in the patch command path (it
  genuinely needs the event tail after a base position)

## Requirements

**R1 — Projection carries the derived fields.** Add folded fields to `GraphProjection`
covering each helper's answer (e.g. completion-decision flag, passed verification
results, per-node retry/backoff state, cleanup request/applied index, node creation
positions). Fold incrementally in `reduce_event`, never by rescan. *Critical.*

**R2 — Helpers read the projection.** Each targeted helper loses its raw scan; return
shape, ordering, and tie-breaking preserved exactly. *Critical.*

**R3 — Signature cleanup.** After R2, every command handler that no longer needs the
raw `events` parameter drops it. `apply_command` may keep `events` for the legitimate
uses above, but private helpers must not accept it unless they are on the out-of-scope
list. *Critical — this is the enforcement mechanism.*

**R4 — Regression guard.** Add a test that greps/inspects `commands.py` and asserts the
count of `for event in events` occurrences is at or below the post-migration number, so
new raw scans fail CI. *Expected.*

**R5 — Parity tests.** For at least two migrated helpers, a test builds a real event
stream through the kernel (no `mock`/`patch` per AGENTS.md) and asserts the
projection-derived value matches the value the old scan produced. *Critical.*

## Constraints

- Pure-kernel discipline: no I/O in `commands.py`/`projections.py`; clock/id injected.
- No event schema or external API changes.
- No test weakened, skipped, or deleted.

## Acceptance

```
uv run pytest tests/unit/test_command_handlers.py tests/unit/test_graph_commands.py \
  tests/unit/test_graph_projections.py tests/unit/test_projectors.py \
  tests/integration/test_graph_dynamic_e2e.py -q
```

All pass, plus the new R4 and R5 tests.
