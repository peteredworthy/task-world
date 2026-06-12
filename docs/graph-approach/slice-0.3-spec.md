# Slice 0.3 — Snapshot Plumbing (loop mode)

Phase 0 foundation slice from the kernel-sequencing plan. Git-native snapshot
utility that captures full working state (tracked + untracked) without firing
hooks or touching HEAD/index/worktree. Used downstream by residue classification
(slice 2.4) and anywhere the orchestrator needs a point-in-time state capture.

## Scope

1. **`snapshot()`**: Create a git snapshot of the current worktree state.
   - Stage all files (tracked and untracked) into a **temporary index** (via
     `GIT_INDEX_FILE=<tmpfile>`) — never touches the real index.
   - Call `git write-tree` with the temp index → tree SHA.
   - Call `git commit-tree <tree>` (no `-n`/`--no-verify` needed; `commit-tree`
     never runs hooks by design) with a supplied message → commit SHA.
   - Write `git update-ref refs/orchestrator/snapshots/<id> <commit-sha>`.
   - Clean up temp index file.
   - Returns a `SnapshotResult(id, tree_sha, commit_sha, ref)`.

2. **`restore()`**: Write snapshot files back to the worktree.
   - Accept a snapshot id (or commit SHA).
   - Use `git archive <commit-sha> | tar -x -C <worktree>` (or equivalent) to
     materialise the tree onto disk. Must NOT run `git checkout` (would touch
     index) or `git reset` (would move HEAD).
   - Only writes files present in the snapshot tree; does not delete extras.

3. **Dedup check**: before creating a new commit, compute the tree SHA. If
   `refs/orchestrator/snapshots/*` already has a commit pointing to the same
   tree, return the existing commit SHA instead of creating a duplicate.

4. **Module location**: `src/orchestrator/git/snapshot.py`. Public API:
   `snapshot(worktree_path, message)` and `restore(worktree_path, snapshot_id)`.

5. **Tests** in `tests/unit/test_git_snapshot.py` (property-style, real tmp
   repos, no mocks, no monkeypatching):
   - Round-trip tracked files: snapshot+restore reproduces all tracked files byte-for-byte.
   - Round-trip untracked files: snapshot+restore reproduces untracked files too.
   - Porcelain state untouched: `git status --porcelain` output is identical
     before and after calling `snapshot()`.
   - HEAD untouched: `git rev-parse HEAD` unchanged after `snapshot()`.
   - Real index untouched: `git diff --cached` empty after `snapshot()`.
   - Identical-tree dedup: two snapshots of identical state share the same tree
     SHA; the dedup path returns the existing commit without creating a new one.
   - Restore does not modify HEAD or index.
   - Hooks never fire: install a pre-commit hook that touches a sentinel file;
     assert sentinel absent after `snapshot()`.

## Done when (acceptance)

All 8 property tests pass. No regressions in existing git utility tests
(`tests/unit/test_git_*.py`). `snapshot()` and `restore()` importable from
`src/orchestrator/git/snapshot.py`.

## Ground truth

- `docs/graph-approach/kernel-sequencing-presentation.html` — slide "Phase 0",
  slice 0.3 row
- Existing git utility patterns: `src/orchestrator/git/utils.py`,
  `src/orchestrator/git/ops/`
- `GIT_INDEX_FILE` technique: standard git environment variable; lets you stage
  files into a temporary index without touching `$GIT_DIR/index`.
- `git commit-tree`: low-level plumbing, never runs hooks.

## Standards (non-negotiable)

- NO mocks, NO monkeypatching in tests. Real tmp repos with real git operations.
  Follow existing test conventions in `tests/unit/test_git_autocommit_hook_retry.py`.
- Small, regular commits on the feature branch (`loop/0.3-snapshot-plumbing`),
  each leaving tests green.
- Do NOT touch `.orchestrator/state/history.jsonl`, `orchestrator.db`, or
  anything outside this worktree. Do not run git commands against the main checkout.
- Do not merge to main — the slice ends with a frontier audit pass on this branch.
