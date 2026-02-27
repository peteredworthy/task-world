"""Caching layer for git diff operations."""

from pathlib import Path
from typing import Any, Protocol

from orchestrator.cache.lru_cache import Cache
from orchestrator.git.diff_ops import (
    CommitInfo,
    ModifiedFile,
    get_branch_diff,
    get_commit_diff,
    get_commit_log,
    get_modified_files,
    get_task_diff,
)


class DiffOps(Protocol):
    async def get_branch_diff(self, worktree_path: Path, base_sha: str, head_sha: str) -> str: ...
    async def get_commit_diff(self, worktree_path: Path, commit_sha: str) -> str: ...
    async def get_task_diff(self, worktree_path: Path, start_sha: str, end_sha: str) -> str: ...
    async def get_modified_files(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[ModifiedFile]: ...
    async def get_commit_log(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[CommitInfo]: ...


class GitDiffOps:
    async def get_branch_diff(self, worktree_path: Path, base_sha: str, head_sha: str) -> str:
        return await get_branch_diff(worktree_path, base_sha, head_sha)

    async def get_commit_diff(self, worktree_path: Path, commit_sha: str) -> str:
        return await get_commit_diff(worktree_path, commit_sha)

    async def get_task_diff(self, worktree_path: Path, start_sha: str, end_sha: str) -> str:
        return await get_task_diff(worktree_path, start_sha, end_sha)

    async def get_modified_files(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[ModifiedFile]:
        return await get_modified_files(worktree_path, base_sha, head_sha)

    async def get_commit_log(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[CommitInfo]:
        return await get_commit_log(worktree_path, base_sha, head_sha)


class CachedDiffOps:
    def __init__(self, next_layer: DiffOps, cache: Cache[tuple[str, ...], Any]) -> None:
        self._next_layer = next_layer
        self._cache = cache

    async def get_branch_diff(self, worktree_path: Path, base_sha: str, head_sha: str) -> str:
        key = (base_sha, head_sha)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._next_layer.get_branch_diff(worktree_path, base_sha, head_sha)
        await self._cache.set(key, result)
        return result

    async def get_commit_diff(self, worktree_path: Path, commit_sha: str) -> str:
        key = (commit_sha,)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._next_layer.get_commit_diff(worktree_path, commit_sha)
        await self._cache.set(key, result)
        return result

    async def get_task_diff(self, worktree_path: Path, start_sha: str, end_sha: str) -> str:
        key = (start_sha, end_sha, "task")
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._next_layer.get_task_diff(worktree_path, start_sha, end_sha)
        await self._cache.set(key, result)
        return result

    async def get_modified_files(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[ModifiedFile]:
        key = (base_sha, head_sha, "files")
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._next_layer.get_modified_files(worktree_path, base_sha, head_sha)
        await self._cache.set(key, result)
        return result

    async def get_commit_log(
        self, worktree_path: Path, base_sha: str, head_sha: str
    ) -> list[CommitInfo]:
        key = (base_sha, head_sha, "log")
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._next_layer.get_commit_log(worktree_path, base_sha, head_sha)
        await self._cache.set(key, result)
        return result
