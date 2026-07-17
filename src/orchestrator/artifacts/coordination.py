"""Cross-process filesystem coordination for one artifact CAS root."""

import asyncio
import fcntl
import hashlib
import os
import errno
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
        if self._root.parent.name != ".orchestrator":
            parent_fd = _open_absolute_directory_no_follow(self._root.parent)
            try:
                identifier = hashlib.sha256(str(self._root.resolve()).encode()).hexdigest()
                fd = os.open(
                    f".artifact-coordination-{identifier}.lock",
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                return fd
            finally:
                os.close(parent_fd)
        metadata_parent = self._root.parent
        project = metadata_parent.parent
        project_fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(metadata_parent.name, 0o700, dir_fd=project_fd)
            except FileExistsError:
                pass
            try:
                metadata_fd = os.open(
                    metadata_parent.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=project_fd,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError(
                        "artifact coordination root has no safe metadata directory"
                    ) from exc
                raise
        finally:
            os.close(project_fd)
        try:
            os.fchmod(metadata_fd, 0o700)
            identifier = hashlib.sha256(str(self._root.resolve()).encode()).hexdigest()
            fd = os.open(
                f".artifact-coordination-{identifier}.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=metadata_fd,
            )
        finally:
            os.close(metadata_fd)
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    @staticmethod
    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _open_absolute_directory_no_follow(path: Path) -> int:
    """Open every absolute directory component without resolving symlinks."""
    absolute = path.absolute()
    if absolute.parts[:2] == ("/", "tmp"):
        try:
            trusted_target = os.readlink("/tmp")
        except OSError as exc:
            raise ValueError("generic artifact lock parent is not a safe directory") from exc
        if trusted_target != "private/tmp":
            raise ValueError("generic artifact lock parent is not a safe directory")
        absolute = Path("/private/tmp").joinpath(*absolute.parts[2:])
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            try:
                next_fd = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
            except OSError as exc:
                raise ValueError("generic artifact lock parent is not a safe directory") from exc
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise
