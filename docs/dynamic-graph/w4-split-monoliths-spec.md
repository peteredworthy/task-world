# W4 — Split the monoliths along command/role seams

Addresses weakness **W4** (medium) and improvement **#5** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Problem

Four files hold ~65% of the subsystem: `graph/commands.py` (~5,000 lines, 150+
private helpers, if-chain dispatcher in `apply_command`), `graph/projections.py`
(~3,900), `graph_runtime/dispatch.py` (~3,000), `graph_runtime/store.py` (~1,800).
`graph/__init__.py` flat-re-exports ~190 names. A seam already exists:
`graph/callbacks.py` was extracted earlier — follow that pattern.

## Architecture

**Pure moves only. No behavior change, no renames of public symbols.**

1. `graph/commands.py` → package `graph/commands/` with modules along the existing
   if-chain seams in `apply_command`: `lifecycle.py`, `callbacks.py` (merge with the
   existing `graph/callbacks.py` if it is the same concern), `patches.py`,
   `scheduling.py`, `recovery.py`, `records.py`, plus `_shared.py` for helpers used
   across modules. Read the if-chain first and group by command family, not by line
   ranges.
2. Replace the if-chain with a registry: `COMMAND_HANDLERS: dict[str, Handler]`
   populated by each module; `apply_command` becomes a lookup + shared
   rejection/envelope logic. Unknown command behavior must be byte-identical to
   today (same `command_rejected` event).
3. `graph_runtime/dispatch.py`: extract prompt/packet assembly (the pure ~1,200-line
   portion) into `graph_runtime/prompts.py`; keep process/outbox execution in
   `dispatch.py`.
4. Keep `graph/__init__.py` re-exports intact this pass so no consumer changes;
   prune it in a later slice.

Suggested order: 3 first (smallest blast radius), then 1+2 together.

## Requirements

**R1 — No behavior change.** Every moved function is byte-identical apart from imports.
No logic edits ride along, however tempting. *Critical.*

**R2 — Registry dispatcher.** `apply_command` if-chain replaced by the registry;
handler set identical; rejection semantics identical. *Critical.*

**R3 — Import stability.** `from orchestrator.graph import X` keeps working for every
currently-exported name. Test edits limited to import paths of *private* helpers, and
only where a test reached into `commands.py` internals. *Critical.*

**R4 — No cycles.** No circular imports between the new modules; `_shared.py` (and
`models`/`projections`) sit at the bottom of the intra-package import graph. *Critical.*

**R5 — Size outcome.** No module in the new `graph/commands/` package exceeds ~1,200
lines. *Expected.*

## Constraints

- Do this in its own branch/PR with nothing else mixed in — reviewability is the
  entire point.
- If W2 (`w2-recovery-at-source-spec.md`) is in flight, coordinate: land W2 first or
  this split first, never interleave.
- Verify with `git diff --stat` that test files show only import-path churn.

## Acceptance

Full graph test surface, unchanged except import paths:

```
uv run pytest tests -k "graph or command or scheduler or projector or outbox" -q
```

Plus an import smoke check (`python -c "import orchestrator.graph as g; print(len(dir(g)))"`
matches the pre-split count) and `uv run ruff check src/orchestrator/graph src/orchestrator/graph_runtime`.
