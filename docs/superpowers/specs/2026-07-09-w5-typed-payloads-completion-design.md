# W5 Typed Payloads Completion Design

> **Superseded 2026-07-15:** The database and durable event history were reset.
> Do not preserve historical payload compatibility from this document. Follow
> `docs/superpowers/plans/2026-07-15-w5-residual-completion.md` instead.

## Objective

Complete the remaining W5 typed-payload migration from commit `7ec4af0ba` while
preserving historical event replay, projection behavior, API compatibility, and
the repository's existing quality gates. The work finishes only when every item
in `docs/dynamic-graph/w5-completion-agent-prompt.md` is complete and recorded in
the durable progress ledger.

The work runs in the isolated worktree
`worktrees/w5-typed-payloads-completion` on branch
`codex/w5-typed-payloads-completion`. The seed is current `main` at
`7ec4af0ba`, which already contains the patch event-family slice. The clean
baseline is `4492 passed, 4 skipped` from `uv run pytest tests/ -q`.

## Execution Strategy

Use a strict slice loop for all edits to shared graph-kernel files:

1. Prepare a brief from the event inventory.
2. Add focused failing tests before implementation.
3. Implement models, producers, reducers, compatibility normalization, and
   public exports as one coherent slice.
4. Send the completed diff to a fresh verifier with no builder context.
5. Fix every failure and repeat independent verification until the slice passes.
6. Commit the passing slice and update the progress ledger with exact evidence.

Parallel work is permitted only when it cannot weaken this loop. Read-only
surveys, brief preparation, and independent validation may run concurrently.
Two implementation agents may run concurrently only after a dependency check
shows that their write sets are disjoint. Because event-family slices normally
share `models.py`, `_commands.py`, and `projections.py`, their implementation is
serial by default. The orchestrator owns integration quality regardless of which
agent produced a change.

## Scope and Order

Resume at the first incomplete ledger item:

1. Decisions.
2. Requirements and evidence.
3. Lifecycle and command rejection.
4. Node lifecycle.
5. Records.
6. File state and gatekeeper.
7. Projection/store allowlist derivation or exhaustive model-field guards.
8. Command payload models for all 23 registered handlers, grouped by lifecycle,
   callback/patch, scheduling, and decisions/records.
9. `GradeRow` for `VerificationReportValue.grades`.
10. Closeout documentation, metrics, and full verification.

The already-completed cleanup, lease, planner/session, and patch slices are not
reimplemented. Existing ledger entries remain historical evidence; closeout may
correct their stale status wording without changing recorded test results.

## Payload Architecture

Event payload models live in `src/orchestrator/graph/models.py` and are exported
through `src/orchestrator/graph/__init__.py`. Current producers construct and
JSON-dump those models before appending events. Reducers parse historical event
payloads through the same models before consuming fields.

Each payload has fixed typed fields and at most one free-form
`extra: dict[str, Any]`. A `mode="before"` validator moves unknown or incompatible
legacy top-level values into `extra`. Reducer-read values must never be silently
dropped. Replay-only aliases are parsed even when no current producer emits them.
The event log remains unchanged and is never rewritten.

Command payload models follow the same boundary-first principle. FastAPI request
validation must flow through typed schemas for all registered handlers, while
domain command dispatch continues to use validated Pydantic values. Constrained
fields use Pydantic enums, literals, validators, or patterns so invalid requests
return actionable 422 responses.

The allowlist phase either derives the four persistence field sets directly from
typed models or adds exhaustive equality guards between the tuples and the union
of model fields. Generation is preferred only if it stays readable and does not
introduce runtime import cycles; exhaustive tests are the safe fallback.

## Compatibility and Error Handling

Historical malformed or partial payloads retain the reducer's current observable
behavior: skip, default, or preserve according to the existing event-family
semantics. Validation must be deterministic and may not introduce clocks, random
identifiers, or I/O. Projection schema version changes occur only when reducer
semantics or the stored `GraphProjection` shape changes.

Out-of-scope dynamic structures remain untyped: patch operations and macro
invocations, command definitions, diagnostics and read-set diffs, edge metadata
and policy fields, decision scope and decider data, and
`TypedRecordBase.payload`/`provenance`.

## Quality Gates

Every slice starts with a named RED test and ends with evidence for:

- Its targeted payload test file.
- Corpus replay parity.
- The full graph-focused test selection.
- Ruff across the repository.
- Pyright across the graph package and relevant tests.
- A fresh diff review for dropped reducer keys, multiple free-form maps,
  event-log rewrites, and accidental out-of-scope typing.

A builder's own report is not acceptance evidence. A fresh verifier must return
PASS with exact command results. If a slice fails, the failure goes to a builder
for correction and then to another clean verification pass. After three repeated
failures, split the slice into smaller independently verifiable units rather than
waiving a requirement.

The final gate runs `uv run pytest tests/ -q`, `uv run ruff check .`, and Pyright
on the graph packages. It also confirms all 23 command handlers have typed
payloads, all ledger items are complete, and the requested metric deltas are
reproducible.

## Durable State and Commits

The progress ledger is the source of resumable execution state. Each accepted
slice records its scope, commit SHA, RED evidence, exact GREEN commands and
counts, legacy keys moved under `extra`, and any intentionally dropped
write-only keys. Commits are small enough to review and bisect and are made only
after independent verification.

At closeout, refresh the graph projection-map inventory, mark the W5 specification
closed, move it into `docs/dynamic-graph/complete/`, and report the deltas from
the documented baselines of 603 `isinstance` guards across `_commands.py` and
`projections.py`, and 174 `dict[str, Any]` occurrences in `projections.py`.

## Completion Criteria

W5 is complete only when every remaining event family, the allowlist phase, all
command payload groups, and `GradeRow` have independently verified ledger
entries; the full backend, lint, and type-check gates pass; and closeout documents
and metrics are committed. Context pressure or elapsed time does not relax these
criteria: the ledger must always make the next incomplete item unambiguous.
