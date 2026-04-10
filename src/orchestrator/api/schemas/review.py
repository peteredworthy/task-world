"""Review API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class TestRunRequest(BaseModel):
    """Request to start a test run."""

    profile: str | None = None  # Reserved for future use; v1 uses routine's auto_verify commands


class TestRunResponse(BaseModel):
    """Response when a test run is started."""

    test_run_id: str
    status: str  # "running"


class TestSummary(BaseModel):
    """Summary counts from a test run."""

    total: int
    passed: int
    failed: int
    skipped: int


class TestRunResult(BaseModel):
    """Full result of a completed (or in-progress) test run."""

    test_run_id: str
    status: str  # "running" | "passed" | "failed" | "error"
    summary: TestSummary | None = None
    log_output: str
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None


class DiffResponse(BaseModel):
    """Response containing diff text for a branch or file."""

    diff: str
    scope: str
    file_path: str | None = None


class DiffFileEntry(BaseModel):
    """A single file entry in a diff file listing."""

    path: str
    status: str
    additions: int
    deletions: int


class CommitEntry(BaseModel):
    """A single commit entry in a commit history listing."""

    sha: str
    short_sha: str
    message: str
    author: str
    timestamp: datetime


class LineRange(BaseModel):
    """A range of line numbers (inclusive)."""

    start: int
    end: int


class FilePrune(BaseModel):
    """Prune selection for a single file."""

    path: str
    mode: Literal["file", "hunk", "line"]
    hunks: list[int] | None = None
    lines: list[LineRange] | None = None


class PruneSelection(BaseModel):
    """A set of prune selections across files."""

    files: list[FilePrune]
    scope: Literal["aggregate", "commit", "task"]


class PrunePreviewResponse(BaseModel):
    """Preview of what a prune operation would produce."""

    resulting_diff: str
    files_affected: int
    hunks_removed: int
    lines_removed: int


class PruneApplyResponse(BaseModel):
    """Result of applying a prune operation."""

    commit_sha: str
    files_affected: int
    hunks_removed: int
    lines_removed: int
    event_id: str


class ConflictBlock(BaseModel):
    """A single conflict block within a file."""

    index: int
    ours_content: str
    theirs_content: str
    base_content: str | None = None


class ConflictFile(BaseModel):
    """A file with unresolved merge conflicts."""

    path: str
    status: str  # "unresolved" | "resolved"
    block_count: int
    blocks: list[ConflictBlock]


class BlockResolution(BaseModel):
    """Resolution for a single conflict block."""

    block_index: int
    choice: str  # "ours" | "theirs" | "manual"
    manual_content: str | None = None


class ConflictResolutionRequest(BaseModel):
    """Request to resolve conflicts in a file."""

    resolutions: list[BlockResolution]


class ConflictResolutionResponse(BaseModel):
    """Response after resolving conflicts in a file."""

    path: str
    status: str  # "resolved"
    remaining_conflicts: int


class BackMergeResponse(BaseModel):
    """Response from a back merge operation."""

    status: str  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_files: list[str] = []
    conflict_count: int = 0


class Gate(BaseModel):
    """A single readiness gate with pass/fail/pending status."""

    name: str
    status: str  # "pass" | "fail" | "pending"
    description: str


class MergeReadiness(BaseModel):
    """Aggregate merge readiness computed from all gates."""

    ready: bool
    gates: list[Gate]


class RevertFileRequest(BaseModel):
    """Request to revert a single file to base-branch state."""

    file_path: str


class AgentResolveConflictsRequest(BaseModel):
    """Request for agent-based conflict resolution."""

    agent_type: str | None = None
    agent_config: dict[str, Any] | None = None
