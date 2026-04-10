"""Unit tests for review API request schema field validators."""

import pytest
from pydantic import ValidationError

from orchestrator.api.schemas.review import FilePrune, PruneSelection, RevertFileRequest


# ---------------------------------------------------------------------------
# FilePrune.mode  (Literal["file", "hunk", "line"])
# ---------------------------------------------------------------------------


def test_prune_invalid_mode_rejected() -> None:
    """Invalid prune mode raises ValidationError."""
    with pytest.raises(ValidationError):
        FilePrune(path="foo.txt", mode="invalid")


def test_prune_file_mode_accepted() -> None:
    """'file' mode is accepted."""
    fp = FilePrune(path="foo.txt", mode="file")
    assert fp.mode == "file"


def test_prune_hunk_mode_accepted() -> None:
    """'hunk' mode is accepted."""
    fp = FilePrune(path="foo.txt", mode="hunk")
    assert fp.mode == "hunk"


def test_prune_line_mode_accepted() -> None:
    """'line' mode is accepted."""
    fp = FilePrune(path="foo.txt", mode="line")
    assert fp.mode == "line"


# ---------------------------------------------------------------------------
# PruneSelection.scope  (Literal["aggregate", "commit", "task"])
# ---------------------------------------------------------------------------


def test_prune_selection_invalid_scope_rejected() -> None:
    """Invalid prune scope raises ValidationError."""
    with pytest.raises(ValidationError):
        PruneSelection(
            scope="invalid_scope",
            files=[{"path": "foo.txt", "mode": "file"}],
        )


def test_prune_selection_aggregate_scope_accepted() -> None:
    """'aggregate' scope is accepted."""
    ps = PruneSelection(scope="aggregate", files=[])
    assert ps.scope == "aggregate"


def test_prune_selection_commit_scope_accepted() -> None:
    """'commit' scope is accepted."""
    ps = PruneSelection(scope="commit", files=[])
    assert ps.scope == "commit"


def test_prune_selection_task_scope_accepted() -> None:
    """'task' scope is accepted."""
    ps = PruneSelection(scope="task", files=[])
    assert ps.scope == "task"


# ---------------------------------------------------------------------------
# RevertFileRequest — required file_path field
# ---------------------------------------------------------------------------


def test_revert_file_missing_path_rejected() -> None:
    """Missing file_path raises ValidationError."""
    with pytest.raises(ValidationError):
        RevertFileRequest()  # type: ignore[call-arg]


def test_revert_file_with_path_accepted() -> None:
    """Valid file_path is accepted."""
    req = RevertFileRequest(file_path="src/foo.py")
    assert req.file_path == "src/foo.py"
