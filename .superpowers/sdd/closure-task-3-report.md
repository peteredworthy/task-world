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
