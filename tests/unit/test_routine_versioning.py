"""Unit tests for routine git versioning.

Tests use real git repositories in temporary directories.
NO mocks.
"""

import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from orchestrator.config.routines.versioning import (
    RoutineVersion,
    find_git_root,
    get_routine_version,
)


@pytest.fixture
def git_repo() -> Generator[Path, None, None]:
    """Create a temporary git repository with a committed routine file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create and commit a routine file
        routines_dir = repo_path / "routines"
        routines_dir.mkdir()
        routine_file = routines_dir / "test-routine.yaml"
        routine_file.write_text("name: test\nsteps: []\n")

        subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add test routine"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        yield repo_path


def test_find_git_root_from_file(git_repo: Path) -> None:
    """Test finding git root from a file path."""
    routine_file = git_repo / "routines" / "test-routine.yaml"
    root = find_git_root(routine_file)

    assert root is not None
    # Resolve both paths to handle macOS /var -> /private/var symlink
    assert root.resolve() == git_repo.resolve()
    assert (root / ".git").exists()


def test_find_git_root_from_directory(git_repo: Path) -> None:
    """Test finding git root from a directory path."""
    routines_dir = git_repo / "routines"
    root = find_git_root(routines_dir)

    assert root is not None
    assert root.resolve() == git_repo.resolve()


def test_find_git_root_from_repo_root(git_repo: Path) -> None:
    """Test finding git root from the repo root itself."""
    root = find_git_root(git_repo)

    assert root is not None
    assert root.resolve() == git_repo.resolve()


def test_find_git_root_not_in_repo() -> None:
    """Test that find_git_root returns None outside a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_repo_path = Path(tmpdir) / "not-a-repo"
        non_repo_path.mkdir()
        test_file = non_repo_path / "test.txt"
        test_file.write_text("test")

        root = find_git_root(test_file)
        assert root is None


def test_get_routine_version_clean_file(git_repo: Path) -> None:
    """Test getting version for a clean committed file."""
    routine_file = git_repo / "routines" / "test-routine.yaml"

    version = get_routine_version(routine_file)

    assert isinstance(version, RoutineVersion)
    assert len(version.sha) == 40  # Full SHA
    assert version.dirty is False
    assert version.path == routine_file


def test_get_routine_version_dirty_file(git_repo: Path) -> None:
    """Test getting version for a file with uncommitted changes."""
    routine_file = git_repo / "routines" / "test-routine.yaml"

    # Modify the file without committing
    routine_file.write_text("name: test\nsteps: []\ndescription: modified\n")

    version = get_routine_version(routine_file)

    assert isinstance(version, RoutineVersion)
    assert len(version.sha) == 40
    assert version.dirty is True
    assert version.path == routine_file


def test_get_routine_version_new_untracked_file(git_repo: Path) -> None:
    """Test getting version for a new untracked file."""
    routine_file = git_repo / "routines" / "new-routine.yaml"
    routine_file.write_text("name: new\nsteps: []\n")

    with pytest.raises(ValueError, match="has no git history"):
        get_routine_version(routine_file)


def test_get_routine_version_not_in_repo() -> None:
    """Test getting version for a file outside a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        routine_file = Path(tmpdir) / "routine.yaml"
        routine_file.write_text("name: test\nsteps: []\n")

        with pytest.raises(ValueError, match="not in a git repository"):
            get_routine_version(routine_file)


def test_get_routine_version_staged_but_uncommitted(git_repo: Path) -> None:
    """Test getting version for a staged but uncommitted file."""
    routine_file = git_repo / "routines" / "staged-routine.yaml"
    routine_file.write_text("name: staged\nsteps: []\n")

    subprocess.run(
        ["git", "add", str(routine_file)],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="has no git history"):
        get_routine_version(routine_file)


def test_get_routine_version_multiple_commits(git_repo: Path) -> None:
    """Test that version reflects the last commit that touched the file."""
    routine_file = git_repo / "routines" / "test-routine.yaml"

    # Get initial version
    version1 = get_routine_version(routine_file)
    initial_sha = version1.sha

    # Commit another file (should not change routine's version)
    other_file = git_repo / "other.txt"
    other_file.write_text("other")
    subprocess.run(
        ["git", "add", str(other_file)],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add other file"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    version2 = get_routine_version(routine_file)
    assert version2.sha == initial_sha

    # Modify and commit the routine file
    routine_file.write_text("name: test\nsteps: []\ndescription: updated\n")
    subprocess.run(
        ["git", "add", str(routine_file)],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Update routine"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    version3 = get_routine_version(routine_file)
    assert version3.sha != initial_sha
    assert len(version3.sha) == 40


def test_get_routine_version_nested_directory(git_repo: Path) -> None:
    """Test getting version for a routine in a deeply nested directory."""
    nested_dir = git_repo / "routines" / "category" / "subcategory"
    nested_dir.mkdir(parents=True)
    routine_file = nested_dir / "nested-routine.yaml"
    routine_file.write_text("name: nested\nsteps: []\n")

    subprocess.run(
        ["git", "add", str(routine_file)],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add nested routine"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    version = get_routine_version(routine_file)

    assert isinstance(version, RoutineVersion)
    assert len(version.sha) == 40
    assert version.dirty is False
    assert version.path == routine_file


def test_get_routine_version_deleted_file() -> None:
    """Test getting version for a file that was deleted but has git history."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create and commit a file
        routine_file = repo_path / "routine.yaml"
        routine_file.write_text("name: test\nsteps: []\n")
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add routine"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Delete the file (but it still has git history)
        routine_file.unlink()

        # Git can still retrieve history for deleted files
        # The file will show as dirty (deleted) but has valid history
        version = get_routine_version(routine_file)
        assert len(version.sha) == 40
        assert version.dirty is True  # File is deleted, so it's dirty


def test_routine_version_dataclass() -> None:
    """Test RoutineVersion dataclass attributes."""
    sha = "a" * 40
    path = Path("/test/routine.yaml")

    version = RoutineVersion(sha=sha, dirty=True, path=path)

    assert version.sha == sha
    assert version.dirty is True
    assert version.path == path


def test_find_git_root_symlink(git_repo: Path) -> None:
    """Test finding git root when using a symlink to a file."""
    routine_file = git_repo / "routines" / "test-routine.yaml"

    # Create a symlink to the routine file
    symlink_dir = git_repo / "links"
    symlink_dir.mkdir()
    symlink = symlink_dir / "routine-link.yaml"
    symlink.symlink_to(routine_file)

    # Should resolve the symlink and find the git root
    root = find_git_root(symlink)

    assert root is not None
    assert root.resolve() == git_repo.resolve()
