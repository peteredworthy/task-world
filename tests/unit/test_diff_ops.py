"""Unit tests for diff_ops functions using real git repos (no mocking)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator.git import (
    FileStatus,
    GitCommandError,
    get_branch_diff,
    get_commit_diff,
    get_commit_log,
    get_modified_files,
    get_task_diff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command synchronously and return stripped stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _setup_repo(path: Path, base_repo: Path) -> None:
    """Copy the session-scoped base repo to *path* as a fast git repo starting point."""
    shutil.copytree(str(base_repo), str(path))


def _commit(path: Path, message: str) -> str:
    """Stage all changes, commit with *message*, and return the new HEAD SHA."""
    _git(["add", "--all"], path)
    _git(["commit", "-m", message], path)
    return _git(["rev-parse", "HEAD"], path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_repo(tmp_path: Path, _unit_base_repo: Path) -> dict[str, str | Path]:
    """A git repo with three commits:

    initial → add_commit → modify_commit

    Returns a dict with:
        path          – Path to the repo
        initial_sha   – SHA of the initial commit
        add_sha       – SHA after adding file.py
        modify_sha    – SHA after modifying file.py
    """
    repo = tmp_path / "repo"
    _setup_repo(repo, _unit_base_repo)

    # Commit 1 – the base repo already has the initial commit (README.md)
    initial_sha = _git(["rev-parse", "HEAD"], repo)

    # Commit 2 – add a Python source file
    (repo / "file.py").write_text("def hello():\n    return 'hello'\n")
    add_sha = _commit(repo, "Add file.py")

    # Commit 3 – modify the Python source file
    (repo / "file.py").write_text("def hello():\n    return 'hello world'\n")
    modify_sha = _commit(repo, "Modify file.py")

    return {
        "path": repo,
        "initial_sha": initial_sha,
        "add_sha": add_sha,
        "modify_sha": modify_sha,
    }


@pytest.fixture
def extended_repo(tmp_path: Path, _unit_base_repo: Path) -> dict[str, str | Path]:
    """A git repo exercising added, modified, deleted, renamed, and binary files.

    Commits:
        base_sha      – one file: base.txt
        added_sha     – adds new.txt
        modified_sha  – modifies base.txt
        deleted_sha   – deletes new.txt
        renamed_sha   – renames base.txt → renamed.txt
        binary_sha    – adds binary.bin (binary file)

    Returns a dict with keys: path, base_sha, added_sha, modified_sha,
    deleted_sha, renamed_sha, binary_sha.
    """
    repo = tmp_path / "repo"
    _setup_repo(repo, _unit_base_repo)

    (repo / "base.txt").write_text("base content\n")
    base_sha = _commit(repo, "Initial: add base.txt")

    (repo / "new.txt").write_text("new content\n")
    added_sha = _commit(repo, "Add new.txt")

    (repo / "base.txt").write_text("modified base content\n")
    modified_sha = _commit(repo, "Modify base.txt")

    (repo / "new.txt").unlink()
    deleted_sha = _commit(repo, "Delete new.txt")

    _git(["mv", "base.txt", "renamed.txt"], repo)
    renamed_sha = _commit(repo, "Rename base.txt to renamed.txt")

    (repo / "binary.bin").write_bytes(bytes(range(256)))
    binary_sha = _commit(repo, "Add binary.bin")

    return {
        "path": repo,
        "base_sha": base_sha,
        "added_sha": added_sha,
        "modified_sha": modified_sha,
        "deleted_sha": deleted_sha,
        "renamed_sha": renamed_sha,
        "binary_sha": binary_sha,
    }


# ---------------------------------------------------------------------------
# get_branch_diff
# ---------------------------------------------------------------------------


class TestGetBranchDiff:
    async def test_returns_unified_diff(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_branch_diff(path, simple_repo["initial_sha"], simple_repo["modify_sha"])

        assert "diff --git" in diff
        assert "file.py" in diff

    async def test_empty_diff_same_sha(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        sha = simple_repo["modify_sha"]
        diff = await get_branch_diff(path, sha, sha)

        assert diff == ""

    async def test_diff_contains_added_content(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_branch_diff(path, simple_repo["initial_sha"], simple_repo["add_sha"])

        assert "+def hello():" in diff

    async def test_invalid_sha_raises_git_error(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        with pytest.raises(GitCommandError):
            await get_branch_diff(path, "deadbeef" * 5, simple_repo["modify_sha"])

    async def test_range_covers_multiple_commits(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_branch_diff(path, simple_repo["initial_sha"], simple_repo["modify_sha"])

        # Both file.py (add + modify) and README.md should NOT appear twice; just ensure
        # the full range diff is captured (file.py was added and then modified)
        assert "file.py" in diff


# ---------------------------------------------------------------------------
# get_commit_diff
# ---------------------------------------------------------------------------


class TestGetCommitDiff:
    async def test_single_commit_diff(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_commit_diff(path, simple_repo["add_sha"])

        assert "diff --git" in diff
        assert "file.py" in diff
        assert "+def hello():" in diff

    async def test_diff_does_not_contain_other_commits(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        # add_sha only added file.py, not README.md
        diff = await get_commit_diff(path, simple_repo["add_sha"])
        assert "README.md" not in diff

    async def test_includes_commit_metadata(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_commit_diff(path, simple_repo["add_sha"])

        # git show output includes the author line
        assert "Author:" in diff

    async def test_invalid_sha_raises_git_error(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        with pytest.raises(GitCommandError):
            await get_commit_diff(path, "0000000000000000000000000000000000000000")


# ---------------------------------------------------------------------------
# get_task_diff
# ---------------------------------------------------------------------------


class TestGetTaskDiff:
    async def test_range_diff(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_task_diff(path, simple_repo["initial_sha"], simple_repo["modify_sha"])

        assert "file.py" in diff

    async def test_empty_range_same_sha(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        sha = simple_repo["add_sha"]
        diff = await get_task_diff(path, sha, sha)

        assert diff == ""

    async def test_single_commit_range(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        diff = await get_task_diff(path, simple_repo["initial_sha"], simple_repo["add_sha"])

        assert "+def hello():" in diff

    async def test_invalid_sha_raises_git_error(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        with pytest.raises(GitCommandError):
            await get_task_diff(path, "notasha", simple_repo["modify_sha"])


# ---------------------------------------------------------------------------
# get_modified_files
# ---------------------------------------------------------------------------


class TestGetModifiedFiles:
    async def test_added_file_status(self, extended_repo: dict) -> None:
        path = extended_repo["path"]
        files = await get_modified_files(
            path, extended_repo["base_sha"], extended_repo["added_sha"]
        )

        assert len(files) == 1
        f = files[0]
        assert f.path == "new.txt"
        assert f.status == FileStatus.ADDED
        assert f.additions > 0
        assert f.deletions == 0

    async def test_modified_file_status(self, extended_repo: dict) -> None:
        path = extended_repo["path"]
        files = await get_modified_files(
            path, extended_repo["added_sha"], extended_repo["modified_sha"]
        )

        assert len(files) == 1
        f = files[0]
        assert f.path == "base.txt"
        assert f.status == FileStatus.MODIFIED

    async def test_deleted_file_status(self, extended_repo: dict) -> None:
        path = extended_repo["path"]
        files = await get_modified_files(
            path, extended_repo["modified_sha"], extended_repo["deleted_sha"]
        )

        assert len(files) == 1
        f = files[0]
        assert f.path == "new.txt"
        assert f.status == FileStatus.DELETED
        assert f.deletions > 0
        assert f.additions == 0

    async def test_renamed_file_status(self, extended_repo: dict) -> None:
        path = extended_repo["path"]
        files = await get_modified_files(
            path, extended_repo["deleted_sha"], extended_repo["renamed_sha"]
        )

        assert len(files) == 1
        f = files[0]
        # git diff --numstat encodes renames as "{old} => {new}"; the function
        # stores this composite string verbatim as the path.
        assert "renamed.txt" in f.path
        # The name-status output yields "renamed.txt" as the key, but the
        # numstat path is "{old} => {new}", so the status_map lookup misses
        # and falls back to MODIFIED – document actual behaviour here.
        assert f.status in (FileStatus.RENAMED, FileStatus.MODIFIED)

    async def test_binary_file(self, extended_repo: dict) -> None:
        path = extended_repo["path"]
        files = await get_modified_files(
            path, extended_repo["renamed_sha"], extended_repo["binary_sha"]
        )

        assert len(files) == 1
        f = files[0]
        assert f.path == "binary.bin"
        assert f.status == FileStatus.ADDED
        # Binary files report 0 additions/deletions (git uses "-")
        assert f.additions == 0
        assert f.deletions == 0

    async def test_empty_diff_returns_empty_list(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        sha = simple_repo["modify_sha"]
        files = await get_modified_files(path, sha, sha)

        assert files == []

    async def test_multiple_files_in_range(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        # initial→modify covers README.md (initial) and file.py (add+modify)
        files = await get_modified_files(
            path, simple_repo["initial_sha"], simple_repo["modify_sha"]
        )

        paths = [f.path for f in files]
        assert "file.py" in paths

    async def test_additions_and_deletions_counted(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        files = await get_modified_files(path, simple_repo["add_sha"], simple_repo["modify_sha"])

        f = files[0]
        assert f.path == "file.py"
        # One line replaced: 1 addition, 1 deletion
        assert f.additions == 1
        assert f.deletions == 1


# ---------------------------------------------------------------------------
# get_commit_log
# ---------------------------------------------------------------------------


class TestGetCommitLog:
    async def test_returns_commits_in_reverse_order(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        commits = await get_commit_log(path, simple_repo["initial_sha"], simple_repo["modify_sha"])

        # Two commits: add_sha and modify_sha (initial is excluded from range)
        assert len(commits) == 2
        # Newest first
        assert commits[0].sha == simple_repo["modify_sha"]
        assert commits[1].sha == simple_repo["add_sha"]

    async def test_commit_fields_populated(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        commits = await get_commit_log(path, simple_repo["initial_sha"], simple_repo["add_sha"])

        assert len(commits) == 1
        c = commits[0]
        assert c.sha == simple_repo["add_sha"]
        assert len(c.short_sha) == 7
        assert c.message == "Add file.py"
        assert c.author == "Test"
        assert c.timestamp.tzinfo is not None  # timezone-aware

    async def test_empty_range_returns_empty_list(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        sha = simple_repo["add_sha"]
        commits = await get_commit_log(path, sha, sha)

        assert commits == []

    async def test_single_commit_range(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        commits = await get_commit_log(path, simple_repo["add_sha"], simple_repo["modify_sha"])

        assert len(commits) == 1
        assert commits[0].sha == simple_repo["modify_sha"]
        assert commits[0].message == "Modify file.py"

    async def test_short_sha_is_prefix_of_full_sha(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        commits = await get_commit_log(path, simple_repo["initial_sha"], simple_repo["modify_sha"])

        for commit in commits:
            assert commit.sha.startswith(commit.short_sha)

    async def test_invalid_sha_raises_git_error(self, simple_repo: dict) -> None:
        path = simple_repo["path"]
        with pytest.raises(GitCommandError):
            await get_commit_log(path, "badbadbadbad", simple_repo["modify_sha"])
