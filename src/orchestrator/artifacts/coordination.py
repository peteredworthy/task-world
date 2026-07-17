"""Cross-process filesystem coordination for one artifact CAS root."""

import asyncio
import fcntl
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator


class ArtifactRootLock:
    """Serialize publication and sweeping for one filesystem artifact root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @asynccontextmanager
    async def publish(self) -> AsyncIterator[None]:
        """Hold the root lock from blob creation through event persistence."""
        fd = await asyncio.to_thread(self._acquire)
        try:
            yield
        finally:
            await asyncio.to_thread(self._release, fd)

    @asynccontextmanager
    async def sweep(self) -> AsyncIterator[None]:
        """Hold the same root lock while determining and deleting orphans."""
        async with self.publish():
            yield

    def _acquire(self) -> int:
        ancestor = self._root
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise ValueError("artifact coordination root has no safe parent directory")
        identifier = hashlib.sha256(str(self._root.resolve()).encode()).hexdigest()
        fd = os.open(
            ancestor / f".artifact-coordination-{identifier}.lock",
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    @staticmethod
    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
