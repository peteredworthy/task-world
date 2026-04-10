"""Unit tests for env-files API request schema field validators."""

import pytest
from pydantic import ValidationError

from orchestrator.api.schemas.envfiles import CopyBackRequest, RevertEnvFileRequest


# ---------------------------------------------------------------------------
# RevertEnvFileRequest.revert_to  (Literal constraint)
# ---------------------------------------------------------------------------


def test_revert_invalid_revert_to_rejected() -> None:
    """Invalid revert_to value raises ValidationError."""
    with pytest.raises(ValidationError):
        RevertEnvFileRequest(
            revert_to="invalid_point",
            task_id="T-01",
            worktree_path="/tmp/wt",
        )


def test_revert_task_start_accepted() -> None:
    """'task_start' revert_to is accepted."""
    req = RevertEnvFileRequest(
        revert_to="task_start",
        task_id="T-01",
        worktree_path="/tmp/wt",
    )
    assert req.revert_to == "task_start"


def test_revert_run_start_accepted() -> None:
    """'run_start' revert_to is accepted."""
    req = RevertEnvFileRequest(
        revert_to="run_start",
        task_id="T-01",
        worktree_path="/tmp/wt",
    )
    assert req.revert_to == "run_start"


# ---------------------------------------------------------------------------
# CopyBackRequest.snapshot_id  (pattern=r"^[a-zA-Z0-9_-]+$")
# ---------------------------------------------------------------------------


def test_copy_back_path_traversal_rejected() -> None:
    """Snapshot ID with path traversal characters raises ValidationError."""
    with pytest.raises(ValidationError):
        CopyBackRequest(
            target_dir="/tmp/target",
            snapshot_id="../../../etc/passwd",
        )


def test_copy_back_slash_in_snapshot_id_rejected() -> None:
    """Snapshot ID containing a slash raises ValidationError."""
    with pytest.raises(ValidationError):
        CopyBackRequest(
            target_dir="/tmp/target",
            snapshot_id="snap/subdir",
        )


def test_copy_back_valid_snapshot_ids_accepted() -> None:
    """Valid snapshot_id formats are accepted."""
    for snapshot_id in ["run_end", "run_start", "snap-123", "abc_DEF_012"]:
        req = CopyBackRequest(target_dir="/tmp/target", snapshot_id=snapshot_id)
        assert req.snapshot_id == snapshot_id


def test_copy_back_default_snapshot_id() -> None:
    """Default snapshot_id is 'run_end'."""
    req = CopyBackRequest(target_dir="/tmp/target")
    assert req.snapshot_id == "run_end"
