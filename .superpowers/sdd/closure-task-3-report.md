# Task 3 Closure Report: Every-Split Replay, Generation Identity, Query Isolation, and Typed Failures

## Scope

Implemented the Task 3 closure requirements from `task-3-brief.md`. The work
reuses Task 1's `ProjectionBehaviorCase` matrix and adds no public production
API beyond the specified `replay_streams()` test helper.

## RED Evidence

1. Added the every-split replay contract importing the intentionally missing
   `replay_streams` helper.
2. Ran `uv run pytest tests/unit/test_graph_projection_replay_equivalence.py -q`.
3. Observed the required collection failure:

   ```text
   ImportError: cannot import name 'replay_streams'
   ```

4. Added the exact matrix-derived `replay_streams()` helper and reran the
   replay suite. The new contract exposed a reproducible failure for
   `gatekeeper_verdict_recorded` at checkpoint split 3.
5. Isolated the failure with
   `test_gatekeeper_verdict_replay_after_checkpoint_preserves_projected_file_entry_type`.
   Evidence showed the direct path retained `FileEntry`, while the restored
   checkpoint path contained `ProjectedFileEntry`; their checkpoints matched,
   but projection equality did not.
6. Added the representative duplicate node-ID typed-failure assertion. Its RED
   result confirmed the right exception type but revealed that its message did
   not contain the required `conflicts during replay` wording.

## GREEN Changes

- Added `replay_streams() -> tuple[tuple[str, tuple[EventEnvelope, ...]], ...]`
  directly from `behavior_cases()`.
- Added every-split full, incremental, and checkpoint-tail replay coverage;
  retained the existing retired-callback and bounded Hypothesis tests.
- Added matrix-driven prior-generation, root-group identity, entity
  replacement/sharing, and saved-generation checkpoint assertions.
- Corrected Task 1 matrix `changed_groups` data for legitimate derived updates:
  node retirement changes tasks; generic accepted output records change tasks;
  lease transitions change tasks; cleanup events change records. No reducer
  repair logic was added for test data.
- Added public matrix query mutation-isolation coverage using the existing
  matrix mutation probes and checkpoint preservation checks.
- Added representative typed failures for duplicate node IDs, malformed
  checkpoint root keys, and a checkpoint edge target with a missing node.
- Narrow production fixes:
  - Gatekeeper verdict replay now reconstructs the same projected file-entry
    subtype it receives, preserving equality across checkpoint-tail replay.
  - Duplicate stable node creation conflicts now consistently say `conflicts
    during replay` while retaining the prior type and field/event detail.

## Verification Evidence

Focused suite run:

```text
uv run pytest tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py -q

795 passed in 5.14s
```

`git diff --check` completed without whitespace diagnostics. Targeted Ruff
initially reported one unused matrix-helper import; it was removed before the
final verification and commit hooks.

## Self-Review

- Confirmed all replay streams are derived solely from Task 1 matrix cases.
- Confirmed no new reducer-time reference-existence policy was added; broken
  references remain checkpoint integrity failures.
- Confirmed the production changes are limited to the demonstrated projected
  subtype preservation and conflict-message contract.
- Confirmed existing exhaustive test suites remain in place.
- Confirmed `.superpowers/sdd/progress.md` remains uncommitted.

## Review-Fix Evidence (2026-07-31)

### RED Against `58c1002c5`

- Added a canonical gatekeeper subtype contract before changing the matrix
  fixture and ran `uv run pytest tests/unit/test_graph_projection_replay_equivalence.py -q`.
  It failed as expected with `IndexError: tuple index out of range` for
  `direct_record.external[0]`: the prior canonical stream had no external
  entry and therefore did not exercise the external subtype branch.
- Strengthened query mutation probing to require an existing nested target.
  The first run identified rows whose public outputs contained only scalars,
  empty mappings, or frozen projection models; their probe attempts failed
  with `matrix query has no truthful nested mutable target`. These rows are now
  explicitly represented by `has_mutable_query_target=False`, rather than
  receiving synthetic-key mutation probes.
- The existing matrix generation test was corrected to snapshot before
  reduction, and the duplicate-ID test now exposed the required stable-field,
  node, and event diagnostics.

### GREEN Changes

- `test_matrix_reduction_preserves_prior_generation...` takes a deep checkpoint
  before `reduce_event`; stream-level generation coverage saves the initial
  projection immediately before its first reduction, every subsequent current
  generation before reduction, and the final generation. This protects
  one-event stream initial identity.
- Query isolation captures a deep copy of the public response before mutation,
  mutates an existing nested list/dict/model value only, verifies the projection
  checkpoint, and verifies a fresh query is equal to the pre-mutation response.
  The explicit `has_mutable_query_target` matrix metadata distinguishes scalar,
  empty, and frozen-only responses from mutable public views.
- Every split now remains associated with its `ProjectionBehaviorCase` and
  compares that case's query result for full, incremental, and checkpoint-tail
  projections. The public `replay_streams()` helper is preserved.
- The canonical gatekeeper fixture now contains ordinary `untracked` and
  manifest-backed `external` entries, each with a verdict. Direct and
  checkpoint-tail tests assert `ProjectedFileEntry` and
  `ProjectedExternalFileEntry` respectively. The existing production subtype
  preservation implementation covers both branches; no additional production
  change was required.
- The duplicate node-ID representative checks the exception type and replay
  phrase plus node (`worker-1`), stable field (`role`), and event (`event-2`)
  diagnostics.

### Files

- `tests/unit/graph_projection_behavior_cases.py`
- `tests/unit/test_graph_projection_behavior.py`
- `tests/unit/test_graph_projection_duplicate_ids.py`
- `tests/unit/test_graph_projection_immutability.py`
- `tests/unit/test_graph_projection_queries.py`
- `tests/unit/test_graph_projection_replay_equivalence.py`

### Commit

Review-fix implementation commit: `64b4a5941 test(graph): strengthen projection closure coverage`.

### Final Verification

```text
uv run pytest tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py -q

772 passed in 6.91s
```

Normal hooks passed for the review-fix implementation commit: Ruff, Ruff
format, secret detection, Pyright, graph-projection boundaries, pytest,
module-import checks, signal routing, UI lint, and UI typecheck.
