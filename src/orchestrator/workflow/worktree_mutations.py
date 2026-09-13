"""Cancellation-safe ownership for legacy run-worktree mutations."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar


_T = TypeVar("_T")


class WorktreeMutationCoordinator:
    """Serialize and drain mutations through a process-external file lock.

    Each checkout maps to a deterministic advisory-lock file in the system temp
    directory. Independent request, executor, and worker service instances can
    therefore coordinate without sharing process-local locks or registries.

    Once an operation owns a worktree, cancellation is delayed until its exact
    async task finishes.  Blocking Git work can therefore run in a worker
    thread without allowing the ownership lock to escape while that thread is
    still mutating the checkout.  Event persistence stays in the async task on
    the event-loop thread.
    """

    async def run(
        self,
        worktree_path: str | Path,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run ``operation`` with exclusive, cancellation-safe checkout ownership."""
        lock_path = self._lock_path(worktree_path)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            await self._acquire(descriptor)
            worker = asyncio.ensure_future(operation())
            return await self._await_drained(worker)
        finally:
            os.close(descriptor)

    @staticmethod
    async def _acquire(descriptor: int) -> None:
        """Wait asynchronously without occupying the shared worker pool."""
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                await asyncio.sleep(0.01)

    @staticmethod
    async def _await_drained(task: asyncio.Future[_T]) -> _T:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            if task.done() and not task.cancelled():
                try:
                    task.result()
                except BaseException:
                    pass
            raise

    @staticmethod
    def _lock_path(worktree_path: str | Path) -> str:
        canonical_path = os.path.realpath(worktree_path)
        digest = hashlib.sha256(os.fsencode(canonical_path)).hexdigest()
        return str(Path(tempfile.gettempdir()) / f"orchestrator-worktree-{digest}.lock")
