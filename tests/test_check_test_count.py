"""Tests for scripts/check_test_count.sh

Tests cover:
- Snapshot mode captures test names correctly
- Compare with no changes -> exit 0
- Compare after adding a test -> exit 0
- Compare after removing a test -> exit non-zero with removed test listed
- Handle project with no tests gracefully
"""

import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_test_count.sh"


def run_script(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def test_project(tmp_path: Path) -> Path:
    """Create a minimal pytest project with two tests."""
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        textwrap.dedent("""\
            def test_alpha():
                pass

            def test_beta():
                pass
        """)
    )
    return tmp_path


def test_snapshot_captures_test_names(test_project: Path, tmp_path: Path):
    snapshot = tmp_path / "snap.txt"
    result = run_script(["--snapshot", str(snapshot)], cwd=test_project)

    assert result.returncode == 0, result.stderr
    assert snapshot.exists()
    lines = snapshot.read_text().splitlines()
    assert any("test_alpha" in line for line in lines)
    assert any("test_beta" in line for line in lines)


def test_compare_no_changes_exits_zero(test_project: Path, tmp_path: Path):
    snapshot = tmp_path / "snap.txt"
    result = run_script(["--snapshot", str(snapshot)], cwd=test_project)
    assert result.returncode == 0

    result = run_script(["--compare", str(snapshot)], cwd=test_project)
    assert result.returncode == 0
    assert "No tests removed" in result.stderr


def test_compare_after_adding_test_exits_zero(test_project: Path, tmp_path: Path):
    snapshot = tmp_path / "snap.txt"
    result = run_script(["--snapshot", str(snapshot)], cwd=test_project)
    assert result.returncode == 0

    # Add a new test
    (test_project / "test_extra.py").write_text("def test_gamma():\n    pass\n")

    result = run_script(["--compare", str(snapshot)], cwd=test_project)
    assert result.returncode == 0, result.stderr
    assert "Tests added" in result.stderr
    assert "No tests removed" in result.stderr


def test_compare_after_removing_test_exits_nonzero(test_project: Path, tmp_path: Path):
    snapshot = tmp_path / "snap.txt"
    result = run_script(["--snapshot", str(snapshot)], cwd=test_project)
    assert result.returncode == 0

    # Remove test_beta by rewriting the file with only test_alpha
    (test_project / "test_sample.py").write_text("def test_alpha():\n    pass\n")

    result = run_script(["--compare", str(snapshot)], cwd=test_project)
    assert result.returncode == 1
    assert "test_beta" in result.stderr
    assert "ERROR" in result.stderr


def test_no_tests_snapshot_graceful(tmp_path: Path):
    """A project with no tests exits 2 (pytest collection failure), not 1.

    pytest --collect-only exits non-zero when no tests are found, so the
    script propagates this as exit code 2 (collection error) rather than
    silently producing an empty snapshot.  This is the "graceful" behaviour:
    the caller is told that collection failed rather than being given a
    misleading empty snapshot.
    """
    project = tmp_path / "empty_project"
    project.mkdir()

    snapshot = tmp_path / "snap.txt"
    result = run_script(["--snapshot", str(snapshot)], cwd=project)

    # pytest exits 5 when no tests are collected -> script exits 2
    assert result.returncode == 2
    assert "failed" in result.stderr.lower()


def test_no_tests_compare_graceful(tmp_path: Path):
    """Comparing against a project with no tests returns exit 2 (not 1)."""
    project = tmp_path / "empty_project"
    project.mkdir()

    # Manually write an empty snapshot so the compare step can start
    snapshot = tmp_path / "snap.txt"
    snapshot.write_text("")

    result = run_script(["--compare", str(snapshot)], cwd=project)
    # Collection fails (no tests), so exit code is 2, not the removal exit code 1
    assert result.returncode == 2
    assert "failed" in result.stderr.lower()


def test_missing_snapshot_file_exits_with_error(test_project: Path, tmp_path: Path):
    missing = tmp_path / "does_not_exist.txt"
    result = run_script(["--compare", str(missing)], cwd=test_project)
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_snapshot_lists_removed_test_name_in_stderr(test_project: Path, tmp_path: Path):
    """The removed test name must appear in stderr output."""
    snapshot = tmp_path / "snap.txt"
    run_script(["--snapshot", str(snapshot)], cwd=test_project)

    # Remove test_alpha
    (test_project / "test_sample.py").write_text("def test_beta():\n    pass\n")

    result = run_script(["--compare", str(snapshot)], cwd=test_project)
    assert result.returncode == 1
    assert "test_alpha" in result.stderr
