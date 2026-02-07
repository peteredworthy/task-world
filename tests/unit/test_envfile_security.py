"""Unit tests for env file security validation."""

import pytest
from pathlib import Path
from orchestrator.envfiles.security import (
    validate_env_file_path,
    validate_env_file_size,
    set_restricted_permissions,
    MAX_ENV_FILE_SIZE,
)
from orchestrator.envfiles.errors import EnvFileError
import sys


def test_rejects_path_traversal() -> None:
    with pytest.raises(EnvFileError, match="traversal"):
        validate_env_file_path("../../etc/passwd")


def test_rejects_single_dotdot() -> None:
    with pytest.raises(EnvFileError, match="traversal"):
        validate_env_file_path("../secret")


def test_rejects_absolute_path_unix() -> None:
    with pytest.raises(EnvFileError, match="Absolute"):
        validate_env_file_path("/etc/passwd")


def test_rejects_absolute_path_windows() -> None:
    with pytest.raises(EnvFileError, match="Absolute"):
        validate_env_file_path("C:\\Users\\secret")


def test_rejects_control_characters() -> None:
    with pytest.raises(EnvFileError, match="Control characters"):
        validate_env_file_path(".env\x00.bak")


def test_accepts_valid_relative_path() -> None:
    validate_env_file_path(".env")
    validate_env_file_path("config/local.yaml")
    validate_env_file_path(".credentials/service-account.json")


def test_accepts_dotfile() -> None:
    validate_env_file_path(".env.local")


def test_rejects_oversized_file(tmp_path: Path) -> None:
    big_file = tmp_path / "huge.bin"
    big_file.write_bytes(b"x" * (MAX_ENV_FILE_SIZE + 1))
    with pytest.raises(EnvFileError, match="exceeds limit"):
        validate_env_file_size(big_file)


def test_accepts_small_file(tmp_path: Path) -> None:
    small_file = tmp_path / "small.env"
    small_file.write_text("KEY=value")
    validate_env_file_size(small_file)  # Should not raise


def test_accepts_nonexistent_file(tmp_path: Path) -> None:
    validate_env_file_size(tmp_path / "missing.env")  # Should not raise


def test_custom_max_size(tmp_path: Path) -> None:
    file = tmp_path / "medium.bin"
    file.write_bytes(b"x" * 500)
    with pytest.raises(EnvFileError, match="exceeds limit"):
        validate_env_file_size(file, max_size=100)


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")
def test_set_restricted_permissions_dir(tmp_path: Path) -> None:
    d = tmp_path / "secure_dir"
    d.mkdir()
    set_restricted_permissions(d)

    mode = d.stat().st_mode & 0o777
    assert mode == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")
def test_set_restricted_permissions_file(tmp_path: Path) -> None:
    f = tmp_path / "secure_file"
    f.write_text("secret")
    set_restricted_permissions(f)

    mode = f.stat().st_mode & 0o777
    assert mode == 0o600
