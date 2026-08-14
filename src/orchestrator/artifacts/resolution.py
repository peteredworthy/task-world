"""Run-scoped composition of artifact stores and garbage collection."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.artifacts.gc import ArtifactGarbageCollectionError, ArtifactGarbageCollector
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
        main_worktree = None
        run_worktree: Path | None = None
        if run.worktree_path is not None:
            run_worktree = Path(run.worktree_path)
            if run_worktree.exists():
                main_worktree = await asyncio.to_thread(resolve_main_worktree, run_worktree)
        if main_worktree is None:
            main_worktree = await asyncio.to_thread(resolve_main_worktree, self._repo_path_for(run))
        if main_worktree is None:
            raise ArtifactRootResolutionError(
                f"cannot resolve artifact project root for run {run.id}"
            )
        if run_worktree is not None and run_worktree.resolve() == main_worktree.resolve():
            # A normal graph run uses a linked worktree, so the project CAS in
            # the main checkout is outside the runner boundary.  Local/operator
            # and test runs may execute in the main checkout itself.  Keep the
            # same project-owned CAS semantics there without letting controller
            # callback artifacts appear as runner-authored untracked files.
            return main_worktree / ".git" / ".orchestrator" / "artifacts"
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
        graph_store: Any,
        now: datetime,
    ) -> frozenset[str]:
        try:
            root = await self._roots.root_for(deleted_run)
        except ArtifactRootResolutionError as exc:
            if deleted_run.worktree_path is None:
                return frozenset()
            raise ArtifactGarbageCollectionError(
                f"cannot resolve artifact root for deleted run {deleted_run.id}"
            ) from exc
        return await ArtifactGarbageCollector(root, self._grace_seconds).collect_after_delete(
            deleted_run,
            graph_store,
            now,
        )
