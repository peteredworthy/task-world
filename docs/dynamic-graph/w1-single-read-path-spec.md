# W1 — Make `GraphProjection` the single read path

Addresses weakness **W1** (dual source of truth) and recommended improvement **#1**
from `docs/dynamic-graph/dynamic-graph-implementation-review.html` (reviewed at
commit `f526cd70a`).

## Problem

Command handlers in `src/orchestrator/graph/commands.py` receive **both** the folded
`GraphProjection` and the raw event list, and dozens of private helpers answer state
questions ("which output records were accepted?", "which verifications failed?",
"which recovery nodes exist?") by re-deriving state from the raw event log with ad-hoc
payload parsing (`for event in events` scans). Each such helper is a second,
independently-written reducer that can silently disagree with the projection. This is
the multi-source-of-truth failure class the project's own architecture notes trace to
the Phase-3 event-driven intent never becoming the single read path.

The fix is to make `GraphProjection` (folded in `reduce_event`) the single source of
truth: add the missing derived fields to the projection, fold them in `reduce_event`,
and migrate the raw-event-scan helpers to read from the projection.

## Scope (bounded)

Migrate the following concrete raw-event-scan helpers in `commands.py` (and their
`projections.py` twins) to projection-derived fields. Do **not** attempt to eliminate
every scan in one pass; migrate exactly the named helpers below and any helpers they
call that also scan raw events.

Target helpers (starting set, confirm against current code):
- `_accepted_output_record_events` / accepted-output-record lookups by port
- `_current_failed_verification_results` / failed-verification lookups
- `_recovery_nodes_by_record_id` / recovery-node index

## Requirements Ledger

**R1 — Projection carries the derived fields.**
`GraphProjection` gains typed, folded fields covering: accepted output records keyed by
`(node_id, port)` (or equivalent), current failed verification results, and the
recovery-node-by-record-id index. These fields are populated incrementally in
`reduce_event` as the relevant events are folded — never by a post-hoc rescan.
*Priority: critical.*

**R2 — Named helpers read the projection, not raw events.**
Each targeted helper is reimplemented to derive its answer from the new projection
fields. The `for event in events` raw scan inside each targeted helper is removed. Any
public behavior (return shape, ordering, tie-breaking) is preserved exactly.
*Priority: critical.*

**R3 — Behavior parity, no regressions.**
The full graph command/projection test surface passes unchanged. No existing test is
weakened, skipped, or deleted to make this pass. Scheduling, recovery, and
terminalization decisions produce identical events before and after for the covered
scenarios.
*Priority: critical.*

**R4 — Parity test for at least one migrated helper.**
Add a focused test asserting that the new projection-derived value equals the value the
old raw-scan produced, over a representative event stream (e.g. a run that accepts an
output record, fails a verification, and arms a recovery node). Do NOT use
`mock`/`patch`/`MagicMock` (per AGENTS.md) — build the event stream through the real
kernel.
*Priority: critical.*

**R5 — No signature regression toward raw scans.**
Do not add new `for event in events` scans. Where a migrated handler no longer needs the
raw `events` argument, prefer dropping it from that helper's signature so the projection
is the enforced read path. (Full handler-signature cleanup across the module is out of
scope for this slice.)
*Priority: expected.*

## Constraints

- Pure-kernel discipline: `commands.py`/`projections.py` stay I/O-free; time and identity
  stay injected. Determinism and replayability must be preserved.
- Do not change the external API contract or event schema semantics; only *where* state
  is read from.
- Do not modify `docs/dynamic-graph` closure/status docs unless this work exposes a real
  contradiction. Do not touch `orchestrator.db` directly.

## Acceptance

`uv run pytest tests/unit/test_command_handlers.py tests/unit/test_projectors.py tests/integration/test_graph_dynamic_e2e.py -q`
must pass, plus the new R4 parity test.
