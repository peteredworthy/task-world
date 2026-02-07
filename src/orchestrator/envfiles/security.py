"""Security validation for environment files."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath

from orchestrator.envfiles.errors import EnvFileError

MAX_ENV_FILE_SIZE = 1 * 1024 * 1024  # 1MB default


def validate_env_file_path(relative_path: str) -> None:
    """Reject paths that could escape the worktree.

    Raises EnvFileError if the path is absolute, contains '..' traversal,
    or includes control characters.
    """
    # No absolute paths
    if PurePosixPath(relative_path).is_absolute():
        raise EnvFileError(f"Absolute paths not allowed: {relative_path}")

    # Also check Windows-style absolute paths
    if len(relative_path) >= 2 and relative_path[1] == ":":
        raise EnvFileError(f"Absolute paths not allowed: {relative_path}")

    # No parent traversal
    if ".." in PurePosixPath(relative_path).parts:
        raise EnvFileError(f"Path traversal not allowed: {relative_path}")

    # No null bytes or control characters
    if re.search(r"[\x00-\x1f]", relative_path):
        raise EnvFileError(f"Control characters not allowed in path: {relative_path!r}")


def validate_env_file_size(file_path: Path, max_size: int = MAX_ENV_FILE_SIZE) -> None:
    """Reject files that exceed the size limit.

    Raises EnvFileError if the file exceeds max_size bytes.
    """
    if not file_path.exists():
        return
    size = file_path.stat().st_size
    if size > max_size:
        raise EnvFileError(
            f"File {file_path.name} is {size} bytes, exceeds limit of {max_size} bytes"
        )


def set_restricted_permissions(path: Path) -> None:
    """Set user-only permissions on a file or directory.

    On Unix: 0o700 for dirs, 0o600 for files.
    On Windows: relies on user-profile directory ACLs.
    """
    if sys.platform == "win32":
        return
    if path.is_dir():
        os.chmod(path, 0o700)
    else:
        os.chmod(path, 0o600)
