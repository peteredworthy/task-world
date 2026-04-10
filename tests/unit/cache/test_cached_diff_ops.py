"""Unit tests for CachedDiffOps.

Uses a real StubDiffOps (no MagicMock) together with a real LRUCache instance.
"""

from pathlib import Path


from orchestrator.git import LRUCache, CachedDiffOps


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------


class StubDiffOps:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_branch_diff(self, worktree_path: Path, base_sha: str, head_sha: str) -> str:
        self.calls.append(("branch_diff", base_sha, head_sha))
        return f"diff:{base_sha}..{head_sha}"

    async def get_commit_diff(self, worktree_path: Path, commit_sha: str) -> str:
        self.calls.append(("commit_diff", commit_sha))
        return f"commit:{commit_sha}"

    async def get_task_diff(self, worktree_path: Path, start_sha: str, end_sha: str) -> str:
        self.calls.append(("task_diff", start_sha, end_sha))
        return f"task:{start_sha}..{end_sha}"

    async def get_modified_files(self, worktree_path: Path, base_sha: str, head_sha: str):
        self.calls.append(("modified_files", base_sha, head_sha))
        return []

    async def get_commit_log(self, worktree_path: Path, base_sha: str, head_sha: str):
        self.calls.append(("commit_log", base_sha, head_sha))
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKTREE = Path("/fake/worktree")


def _make_cached(stub: StubDiffOps) -> CachedDiffOps:
    cache: LRUCache[tuple, object] = LRUCache(maxsize=64)
    return CachedDiffOps(next_layer=stub, cache=cache)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCachedDiffOpsBranchDiff:
    async def test_cache_miss_calls_next_layer(self) -> None:
        """First call delegates to next_layer and returns the result."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        result = await ops.get_branch_diff(WORKTREE, "aaa", "bbb")

        assert result == "diff:aaa..bbb"
        assert len(stub.calls) == 1
        assert stub.calls[0] == ("branch_diff", "aaa", "bbb")

    async def test_cache_hit_skips_next_layer(self) -> None:
        """Second call with the same SHAs is served from cache without calling next_layer."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        first = await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        second = await ops.get_branch_diff(WORKTREE, "aaa", "bbb")

        assert first == second
        assert len(stub.calls) == 1  # next_layer called only once

    async def test_different_sha_pairs_are_independent(self) -> None:
        """Different (base_sha, head_sha) pairs are separate cache entries."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        r1 = await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        r2 = await ops.get_branch_diff(WORKTREE, "ccc", "ddd")

        assert r1 == "diff:aaa..bbb"
        assert r2 == "diff:ccc..ddd"
        assert len(stub.calls) == 2


class TestCachedDiffOpsKeyDisambiguation:
    async def test_files_and_diff_keys_are_independent(self) -> None:
        """get_modified_files and get_branch_diff with the same SHAs use different cache keys."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        await ops.get_modified_files(WORKTREE, "aaa", "bbb")

        # Both calls must have reached the stub (different keys → two cache misses)
        branch_diff_calls = [c for c in stub.calls if c[0] == "branch_diff"]
        modified_files_calls = [c for c in stub.calls if c[0] == "modified_files"]
        assert len(branch_diff_calls) == 1
        assert len(modified_files_calls) == 1

        # A second call to each should now be cached independently
        stub.calls.clear()
        await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        await ops.get_modified_files(WORKTREE, "aaa", "bbb")
        assert stub.calls == []  # both served from cache

    async def test_log_and_diff_keys_are_independent(self) -> None:
        """get_commit_log and get_branch_diff with the same SHAs use different cache entries."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        await ops.get_commit_log(WORKTREE, "aaa", "bbb")

        branch_diff_calls = [c for c in stub.calls if c[0] == "branch_diff"]
        commit_log_calls = [c for c in stub.calls if c[0] == "commit_log"]
        assert len(branch_diff_calls) == 1
        assert len(commit_log_calls) == 1

        # Second round — both should hit cache
        stub.calls.clear()
        await ops.get_branch_diff(WORKTREE, "aaa", "bbb")
        await ops.get_commit_log(WORKTREE, "aaa", "bbb")
        assert stub.calls == []


class TestCachedDiffOpsCommitDiff:
    async def test_commit_diff_cached(self) -> None:
        """get_commit_diff caches on a single-SHA key; second call hits cache."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        first = await ops.get_commit_diff(WORKTREE, "sha1")
        assert first == "commit:sha1"
        assert len(stub.calls) == 1

        second = await ops.get_commit_diff(WORKTREE, "sha1")
        assert second == "commit:sha1"
        assert len(stub.calls) == 1  # no additional call

    async def test_commit_diff_different_shas_are_independent(self) -> None:
        stub = StubDiffOps()
        ops = _make_cached(stub)

        r1 = await ops.get_commit_diff(WORKTREE, "sha1")
        r2 = await ops.get_commit_diff(WORKTREE, "sha2")

        assert r1 == "commit:sha1"
        assert r2 == "commit:sha2"
        assert len(stub.calls) == 2


class TestCachedDiffOpsTaskDiff:
    async def test_task_diff_cached(self) -> None:
        """get_task_diff caches on (start_sha, end_sha, 'task'); second call hits cache."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        first = await ops.get_task_diff(WORKTREE, "s1", "e1")
        assert first == "task:s1..e1"
        assert len(stub.calls) == 1

        second = await ops.get_task_diff(WORKTREE, "s1", "e1")
        assert second == "task:s1..e1"
        assert len(stub.calls) == 1  # served from cache

    async def test_task_diff_key_does_not_collide_with_branch_diff(self) -> None:
        """get_task_diff and get_branch_diff with the same SHA pair use different keys."""
        stub = StubDiffOps()
        ops = _make_cached(stub)

        branch = await ops.get_branch_diff(WORKTREE, "s1", "e1")
        task = await ops.get_task_diff(WORKTREE, "s1", "e1")

        # The underlying stub returns different strings per method type
        assert branch == "diff:s1..e1"
        assert task == "task:s1..e1"

        # Both should have hit the stub exactly once
        branch_calls = [c for c in stub.calls if c[0] == "branch_diff"]
        task_calls = [c for c in stub.calls if c[0] == "task_diff"]
        assert len(branch_calls) == 1
        assert len(task_calls) == 1
