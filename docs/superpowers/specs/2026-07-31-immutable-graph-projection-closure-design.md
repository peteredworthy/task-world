# Immutable Graph Projection Closure Design

## Objective

Finish the immutable `GraphProjection` cutover by proving and fixing observable
event-handling behavior. Retire the compromised migration bookkeeping and
historical performance comparisons instead of repairing evidence about how the
migration happened.

The release contract is pure data in and data out:

```text
events -> reduce_event -> immutable GraphProjection -> queries/checkpoint data
```

SQL, HTTP, startup recovery, and other I/O paths are not acceptance requirements
for this work. Existing repository integration tests remain part of the normal
suite, but this closure adds no database-backed proof obligation.

## Completion Contract

The cutover is complete only when all of the following are executable and pass:

1. Every canonical graph event family is reduced with asserted state changes or
   is explicitly declared projection-neutral.
2. Full replay, incremental replay at every split, and checkpoint-plus-tail
   replay produce equal immutable projections.
3. Every projection field accepting flexible JSON round-trips nested objects,
   arrays, scalars, and `null` through the pure checkpoint codec.
4. Invalid events, conflicting duplicate IDs, malformed checkpoints, and broken
   references fail with the expected typed error. They are not repaired or
   silently ignored.
5. Reducing an event leaves earlier projection generations unchanged. Unchanged
   immutable values may retain identity; changed entities and groups are
   replaced.
6. Public projection queries return the expected values and do not expose
   mutable internal storage.
7. The old mutable root, clone machinery, compatibility checkpoint parsing,
   duplicate full-record storage, and one-time migration machinery are absent.
8. Deterministic general, edge-heavy, and record-heavy 10,000-event streams each
   reduce in a median of less than one second after one warmup.
9. The focused behavior suite, full repository suite, static checks, permanent
   projection boundary guard, and pre-commit hooks all pass.

Passing ordinary repository tests is necessary but not sufficient. A known
behavioral defect or a failed closure check blocks completion even when broad
tests are green.

## Behavior-First Test Architecture

### Canonical Event Matrix

Create a compact, deterministic in-memory matrix that covers every canonical
event family. Each case contains:

- a valid prefix projection or event prefix;
- the event being exercised;
- direct assertions for the state and public-query changes it owns;
- assertions for values that must remain unchanged;
- the expected error for invalid variants, where applicable.

Coverage is derived from the canonical event registry and reducer dispatch so a
new event cannot be added without either a behavior case or an explicit
projection-neutral declaration. The matrix tests domain outcomes, not reducer
branch structure or generated occurrence counts.

### Replay Equivalence

Use representative valid event streams assembled from the event matrix. For
each stream, assert:

- one-pass full replay;
- reduction of every suffix from its corresponding prefix projection;
- checkpoint encode/decode at every split followed by tail reduction;
- equality of final projections and selected public-query outputs.

The checkpoint codec is a pure serialization boundary. These tests do not use a
database or projection snapshot repository.

### Flexible JSON Round Trips

Inventory flexible JSON fields from the immutable model graph, not from the old
projection migration manifest. Exercise those fields through the events that
populate them whenever an event path exists. Use direct immutable model fixtures
only for passive model values with no producing event.

Each field receives canonical cases for nested object/array combinations,
scalars, and `null` where allowed. The encoded checkpoint must contain ordinary
JSON dictionaries and arrays; decoding must reconstruct an equal deeply
immutable value. This coverage includes the reproduced approval-scope and
oversight-decider failures.

### Immutability And Ownership

Retain a permanent, fast boundary check that enforces:

- the grouped root is frozen and has no reachable mutable child;
- `_clone_projection` and the old flat `TypedDict` root do not exist;
- only approved graph-core modules inspect physical grouped storage;
- external consumers import projection APIs through `orchestrator.graph`;
- `RecordStore.by_id` is the sole owner of complete projected records;
- every canonical event is handled or explicitly projection-neutral.

Do not retain migration occurrence IDs, historical source revisions, codemod
reproduction, or old-field ownership checks in the permanent guard.

## Correctness Fixing Loop

Work proceeds by demonstrated failures:

1. Add the smallest failing pure test for a real contract gap.
2. Run it and confirm the expected failure.
3. Fix the model, reducer, codec, integrity validator, or query at the narrowest
   correct boundary.
4. Run the focused domain tests.
5. Run the broader pure projection suite.
6. Continue until the canonical matrix, replay equivalence, and flexible JSON
   coverage expose no unresolved behavior.

Do not add reports, ledgers, or generated counts as substitutes for a failing or
passing executable behavior check.

## One-Time Migration Retirement

Delete the one-time migration system after replacement behavior tests and the
permanent guard are green:

- graph projection inventory and query codemod scripts;
- migration manifests and generated migration reports;
- pre-cutover replay/public-view goldens and their generator;
- migration-only fixtures and tests;
- the explicit migration Make target;
- dependencies used only by deleted migration tooling.

Historical design and implementation documents may remain as history, but no
active command, hook, or acceptance criterion depends on reconstructing the old
mutable source tree.

## Performance Contract

Replace ratio-based comparison against the mutable baseline with a direct
service-level bound. Generate deterministic general, edge-heavy, and
record-heavy streams of exactly 10,000 events. For each scenario:

1. perform one unmeasured warmup replay;
2. perform three measured full replays from `initial_projection()`;
3. assert the median duration is strictly less than one second;
4. assert the replay result is behaviorally valid so timing cannot benchmark a
   no-op or incomplete reducer.

The performance check measures pure event reduction only. Checkpoint encoding,
decoding, SQL, HTTP, memory ratios, historical baselines, hardware metadata, and
cross-version protocol hashes are not release gates.

## Scope Boundaries

This closure does not:

- redesign graph event schemas;
- split the reducer into a handler registry;
- change public REST, MCP, or CLI response contracts;
- add database-backed acceptance tests;
- reconstruct compromised migration provenance;
- preserve one-time codemod or inventory tooling;
- optimize beyond the direct 10,000-event, one-second requirement.

If a pure behavior test reveals a production defect outside the initially known
codec failures, fixing that defect is in scope. Discovering a problem is not a
reason to narrow the test or defer completion.

## Verification

The implementation plan must end with fresh execution of:

```bash
uv run pytest <focused pure projection behavior tests>
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python scripts/check_graph_projection_boundaries.py
uv run pre-commit run --all-files
```

The final review also verifies that retired migration files and commands are
absent and the worktree is clean. Completion is reported from command output and
direct contract review, not from a progress ledger.
