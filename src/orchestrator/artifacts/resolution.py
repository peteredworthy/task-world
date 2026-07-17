"""Run-scoped composition of artifact stores and garbage collection."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.artifacts.gc import ArtifactGarbageCollector
from orchestrator.artifacts.store import FilesystemArtifactStore
from orchestrator.git import resolve_main_worktree
from orchestrator.state import Run


class ArtifactRootResolutionError(ValueError):
    """Raised when a run cannot be mapped to its owning project checkout."""


class ArtifactRootResolver:
    """Resolve a run worktree to its main-checkout CAS root."""

    def __init__(self, repos_root: Path | None = None) -> None:
        self._repos_root = repos_root

    async def root_for(self, run: Run) -> Path:
        project_path = (
            Path(run.worktree_path) if run.worktree_path is not None else self._repo_path_for(run)
        )
        main_worktree = await asyncio.to_thread(resolve_main_worktree, project_path)
        if main_worktree is None:
            raise ArtifactRootResolutionError(
                f"cannot resolve artifact project root for run {run.id}"
            )
        return main_worktree / ".orchestrator" / "artifacts"

    def _repo_path_for(self, run: Run) -> Path:
        if self._repos_root is None:
            raise ArtifactRootResolutionError(
                f"run {run.id} has no worktree path for artifact storage"
            )
        return self._repos_root / run.repo_name


class ArtifactStoreResolver:
    """Construct run-scoped stores without exposing filesystem paths to routers."""

    def __init__(self, roots: ArtifactRootResolver) -> None:
        self._roots = roots

    async def for_run(self, run: Run) -> FilesystemArtifactStore:
        return FilesystemArtifactStore(await self._roots.root_for(run))


class ProjectArtifactGarbageCollector:
    """Sweep only the CAS owned by a deleted run's project."""

    def __init__(self, roots: ArtifactRootResolver, grace_seconds: int = 86400) -> None:
        self._roots = roots
        self._grace_seconds = grace_seconds

    async def collect_after_delete(
        self,
        deleted_run: Run,
        surviving_runs: list[Run],
        graph_store: Any,
        now: datetime,
    ) -> frozenset[str]:
        try:
            root = await self._roots.root_for(deleted_run)
        except ArtifactRootResolutionError:
            # A run deleted before worktree preparation has never had a project
            # CAS target, so there is no root whose lifecycle can be swept.
            return frozenset()
        same_project_runs = [
            run for run in surviving_runs if await self._roots.root_for(run) == root
        ]

        async def load_events() -> list[Any]:
            retained_events: list[Any] = []
            for run in same_project_runs:
                retained_events.extend(await graph_store.read_run(run.id))
            return retained_events

        return await ArtifactGarbageCollector(root, self._grace_seconds).collect_after_mark(
            load_events, now
        )
