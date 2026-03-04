"""Review API endpoints: diff, file listing, commit history, prune, and test operations."""

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from orchestrator.agents.executor import AgentExecutor
from orchestrator.api.deps import (
    get_agent_executor,
    get_event_emitter,
    get_global_config,
    get_test_runner,
    get_workflow_service,
)
from orchestrator.api.schemas.review import (
    AgentResolveConflictsRequest,
    CommitEntry,
    ConflictBlock as ConflictBlockSchema,
    ConflictFile,
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    DiffFileEntry,
    DiffResponse,
    Gate,
    MergeReadiness,
    PruneApplyResponse,
    PrunePreviewResponse,
    PruneSelection,
    RevertFileRequest,
    TestRunRequest,
    TestRunResponse,
    TestRunResult as TestRunResultSchema,
    TestSummary as TestSummarySchema,
)
from orchestrator.config.enums import AgentType
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import RoutineConfig
from orchestrator.git.branch_ops import get_branch_status, revert_back_merge
from orchestrator.state.models import Run
from orchestrator.git.conflict_ops import (
    BlockResolution as ConflictBlockResolution,
    get_conflict_blocks,
    get_conflict_files,
    resolve_conflict,
)
from orchestrator.cache.lru_cache import LRUCache
from orchestrator.git.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps
from orchestrator.git.errors import GitCommandError
from orchestrator.git.prune_ops import (
    FileSelectionEntry,
    apply_prune,
    compute_selection_preview,
    prune_hunks,
    prune_lines,
    revert_file,
)
from orchestrator.review.test_runner import TestRunResult, TestRunner
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import (
    AgentFixStarted,
    BackMergeReverted,
    ConflictResolved,
    PruneApplied,
    TestRunCompleted,
    TestRunStarted,
)
from orchestrator.workflow.service import WorkflowService

router = APIRouter(prefix="/api/runs", tags=["review"])

_diff_ops: DiffOps = CachedDiffOps(
    next_layer=GitDiffOps(),
    cache=LRUCache(maxsize=256),
)


def _get_merge_base_sync(worktree_path: Path, source_branch: str) -> str:
    """Return the merge-base SHA between source_branch and HEAD."""
    result = subprocess.run(
        ["git", "merge-base", source_branch, "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    # Fallback: use the first commit (no common ancestor)
    result = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _get_head_sha_sync(worktree_path: Path) -> str:
    """Return the HEAD commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _require_worktree(worktree_path_str: str | None) -> Path:
    """Validate worktree exists and return its Path. Raises HTTPException on failure."""
    if not worktree_path_str:
        raise HTTPException(
            status_code=409,
            detail="Run does not have a worktree configured",
        )
    worktree_path = Path(worktree_path_str)
    if not worktree_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Run worktree path does not exist",
        )
    return worktree_path


@router.get("/{run_id}/review/diff", response_model=DiffResponse)
async def get_diff(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    scope: str = Query(
        default="aggregate",
        description="Diff scope: 'aggregate' (full branch), 'commit' (single commit), or 'task'",
    ),
    ref: str | None = Query(
        default=None,
        description="Commit SHA for 'commit' scope, or end commit SHA for 'task' scope",
    ),
    context_lines: int = Query(default=3, ge=0, description="Number of context lines"),
) -> DiffResponse:
    """Return unified diff for a run branch.

    Scopes:
    - aggregate (default): full diff from source branch merge-base to HEAD
    - commit: diff for a single commit (requires ref=<sha>)
    - task: diff for a commit range from merge-base to ref
    """
    if scope not in ("aggregate", "commit", "task"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scope '{scope}'. Valid options: aggregate, commit, task",
        )

    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    try:
        if scope == "commit":
            if not ref:
                raise HTTPException(
                    status_code=400,
                    detail="'ref' query parameter is required for commit scope",
                )
            diff_text = await _diff_ops.get_commit_diff(worktree_path, ref)
        else:
            if not run.source_branch:
                raise HTTPException(
                    status_code=409,
                    detail="Run does not have a source branch configured",
                )
            base_sha, head_sha = await asyncio.gather(
                asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch),
                asyncio.to_thread(_get_head_sha_sync, worktree_path),
            )
            if scope == "task" and ref:
                # Support explicit "{start}..{end}" range or legacy single-SHA (uses merge-base)
                if ".." in ref:
                    start_sha, end_sha = ref.split("..", 1)
                    diff_text = await _diff_ops.get_task_diff(worktree_path, start_sha, end_sha)
                else:
                    diff_text = await _diff_ops.get_task_diff(worktree_path, base_sha, ref)
            else:
                diff_text = await _diff_ops.get_branch_diff(worktree_path, base_sha, head_sha)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DiffResponse(diff=diff_text, scope=scope)


@router.get("/{run_id}/review/diff/files", response_model=list[DiffFileEntry])
async def get_diff_files(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    scope: str = Query(default="aggregate", description="Diff scope: 'aggregate' or 'task'"),
    ref: str | None = Query(
        default=None,
        description="For 'task' scope: '{start_sha}..{end_sha}' commit range",
    ),
) -> list[DiffFileEntry]:
    """Return list of modified files with change stats for a run branch.

    Scopes:
    - aggregate (default): all files changed from source branch merge-base to HEAD
    - task: files changed in a specific commit range (requires ref='{start}..{end}')
    """
    if scope not in ("aggregate", "task"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scope '{scope}'. Valid options: aggregate, task",
        )

    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    try:
        if scope == "task" and ref:
            # Parse "{start}..{end}" range format
            if ".." not in ref:
                raise HTTPException(
                    status_code=400,
                    detail="'ref' must be in '{start_sha}..{end_sha}' format for task scope",
                )
            start_sha, end_sha = ref.split("..", 1)
            modified_files = await _diff_ops.get_modified_files(worktree_path, start_sha, end_sha)
        else:
            if not run.source_branch:
                raise HTTPException(
                    status_code=409,
                    detail="Run does not have a source branch configured",
                )
            base_sha, head_sha = await asyncio.gather(
                asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch),
                asyncio.to_thread(_get_head_sha_sync, worktree_path),
            )
            modified_files = await _diff_ops.get_modified_files(worktree_path, base_sha, head_sha)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [
        DiffFileEntry(
            path=f.path,
            status=f.status.value,
            additions=f.additions,
            deletions=f.deletions,
        )
        for f in modified_files
    ]


@router.get("/{run_id}/review/commits", response_model=list[CommitEntry])
async def get_commits(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> list[CommitEntry]:
    """Return commit history for a run branch from source branch merge-base to HEAD."""
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    if not run.source_branch:
        raise HTTPException(
            status_code=409,
            detail="Run does not have a source branch configured",
        )

    try:
        base_sha, head_sha = await asyncio.gather(
            asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch),
            asyncio.to_thread(_get_head_sha_sync, worktree_path),
        )
        commits = await _diff_ops.get_commit_log(worktree_path, base_sha, head_sha)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [
        CommitEntry(
            sha=c.sha,
            short_sha=c.short_sha,
            message=c.message,
            author=c.author,
            timestamp=c.timestamp,
        )
        for c in commits
    ]


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/prune/preview
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/prune/preview", response_model=PrunePreviewResponse)
async def prune_preview(
    run_id: str,
    body: PruneSelection,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> PrunePreviewResponse:
    """Preview the result of a prune selection without modifying the worktree."""
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    if not run.source_branch:
        raise HTTPException(
            status_code=409,
            detail="Run does not have a source branch configured",
        )

    try:
        base_sha = await asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch)
        entries = [
            FileSelectionEntry(
                path=fp.path,
                mode=fp.mode,
                hunk_indices=fp.hunks,
                line_ranges=[(lr.start, lr.end) for lr in fp.lines] if fp.lines else None,
            )
            for fp in body.files
        ]
        stats = await compute_selection_preview(worktree_path, entries, base_sha)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PrunePreviewResponse(
        resulting_diff=stats.resulting_diff,
        files_affected=stats.files_affected,
        hunks_removed=stats.hunks_removed,
        lines_removed=stats.lines_removed,
    )


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/prune/apply
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/prune/apply", response_model=PruneApplyResponse)
async def prune_apply(
    run_id: str,
    body: PruneSelection,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    emitter: Annotated[PersistentEventEmitter, Depends(get_event_emitter)],
) -> PruneApplyResponse:
    """Apply prune selections and create a dedicated commit for auditability."""
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    if not run.source_branch:
        raise HTTPException(
            status_code=409,
            detail="Run does not have a source branch configured",
        )

    try:
        base_sha = await asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Separate selections by mode
    file_paths = [fp.path for fp in body.files if fp.mode == "file"]
    hunk_files = [fp for fp in body.files if fp.mode == "hunk" and fp.hunks]
    line_files = [fp for fp in body.files if fp.mode == "line" and fp.lines]

    if not file_paths and not hunk_files and not line_files:
        raise HTTPException(status_code=400, detail="No valid prune selections provided")

    total_files = 0
    total_hunks = 0
    total_lines = 0
    last_commit_sha = ""

    try:
        # File-level: batch into a single commit
        if file_paths:
            commit_sha, stats = await apply_prune(
                worktree_path,
                file_paths,
                base_sha,
                message="prune: remove selected changes",
            )
            last_commit_sha = commit_sha
            total_files += stats.files_affected
            total_hunks += stats.hunks_removed
            total_lines += stats.lines_removed

        # Hunk-level: one commit per file
        for fp in hunk_files:
            commit_sha, stats = await prune_hunks(
                worktree_path,
                fp.path,
                base_sha,
                fp.hunks or [],  # type: ignore[arg-type]
                message="prune: remove selected hunks",
            )
            last_commit_sha = commit_sha
            total_files += stats.files_affected
            total_hunks += stats.hunks_removed
            total_lines += stats.lines_removed

        # Line-level: one commit per file
        for fp in line_files:
            line_ranges = [(lr.start, lr.end) for lr in (fp.lines or [])]
            commit_sha, stats = await prune_lines(
                worktree_path,
                fp.path,
                base_sha,
                line_ranges,
                message="prune: remove selected lines",
            )
            last_commit_sha = commit_sha
            total_files += stats.files_affected
            total_hunks += stats.hunks_removed
            total_lines += stats.lines_removed

    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Log PRUNE_APPLIED event
    await emitter.emit(
        PruneApplied(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="prune_applied",
            commit_sha=last_commit_sha,
            files_affected=total_files,
            hunks_removed=total_hunks,
            lines_removed=total_lines,
        )
    )

    event_id = str(uuid.uuid4())
    return PruneApplyResponse(
        commit_sha=last_commit_sha,
        files_affected=total_files,
        hunks_removed=total_hunks,
        lines_removed=total_lines,
        event_id=event_id,
    )


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/revert-file
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/revert-file")
async def revert_file_endpoint(
    run_id: str,
    body: RevertFileRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, str]:
    """Revert a single file to its base-branch state and create a commit."""
    file_path = body.file_path

    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    if not run.source_branch:
        raise HTTPException(
            status_code=409,
            detail="Run does not have a source branch configured",
        )

    try:
        base_sha = await asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch)
        commit_sha = await revert_file(worktree_path, file_path, base_sha)
    except GitCommandError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "commit_sha": commit_sha,
        "file_path": file_path,
        "reverted_to": base_sha,
    }


# ---------------------------------------------------------------------------
# Helpers for test execution
# ---------------------------------------------------------------------------


def _get_auto_verify_commands(run_embedded: dict[str, Any] | None) -> list[str]:
    """Collect all auto_verify commands from every task in the routine.

    Returns a flat list of shell command strings. Returns an empty list if
    the routine has no auto_verify items configured.
    """
    if run_embedded is None:
        return []
    routine_config = RoutineConfig.model_validate(run_embedded)
    cmds: list[str] = []
    for step in routine_config.steps:
        for task in step.tasks:
            for item in task.auto_verify.items:
                cmds.append(item.cmd)
    return cmds


def _test_result_to_schema(result: TestRunResult) -> TestRunResultSchema:
    """Convert an internal TestRunResult to the API schema model."""
    summary: TestSummarySchema | None = None
    if result.summary is not None:
        summary = TestSummarySchema(
            total=result.summary.total,
            passed=result.summary.passed,
            failed=result.summary.failed,
            skipped=result.summary.skipped,
        )
    return TestRunResultSchema(
        test_run_id=result.test_run_id,
        status=result.status,
        summary=summary,
        log_output=result.log_output,
        duration_ms=result.duration_ms,
        started_at=result.started_at,
        completed_at=result.completed_at,
    )


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/test
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/test", response_model=TestRunResponse, status_code=202)
async def start_test_run(
    run_id: str,
    body: TestRunRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    emitter: Annotated[PersistentEventEmitter, Depends(get_event_emitter)],
    test_runner: Annotated[TestRunner, Depends(get_test_runner)],
) -> TestRunResponse:
    """Start async test execution using the routine's auto_verify commands.

    Returns immediately with a test_run_id. Use GET /review/test/{test_run_id}
    to poll for results.
    """
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    # Validate that auto_verify commands are configured
    commands = _get_auto_verify_commands(run.routine_embedded)
    if not commands:
        raise HTTPException(
            status_code=422,
            detail="No auto_verify commands configured in the routine",
        )

    # Prevent concurrent test runs for the same run
    if test_runner.is_running(run_id):
        raise HTTPException(
            status_code=409,
            detail="A test run is already in progress for this run",
        )

    # Prepare completion callback to emit TEST_RUN_COMPLETED event
    async def _on_complete(result: TestRunResult) -> None:
        await emitter.emit(
            TestRunCompleted(
                timestamp=datetime.now(timezone.utc),
                run_id=run_id,
                event_type="test_run_completed",
                test_run_id=result.test_run_id,
                status=result.status,
                duration_ms=result.duration_ms,
            )
        )

    test_run_id = await test_runner.start_test_run(
        run_id=run_id,
        worktree_path=str(worktree_path),
        commands=commands,
        on_complete=_on_complete,
    )

    # Log TEST_RUN_STARTED event
    await emitter.emit(
        TestRunStarted(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="test_run_started",
            test_run_id=test_run_id,
        )
    )

    return TestRunResponse(test_run_id=test_run_id, status="running")


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/test/{test_run_id}
# ---------------------------------------------------------------------------


@router.get("/{run_id}/review/test/{test_run_id}", response_model=TestRunResultSchema)
async def get_test_run(
    run_id: str,
    test_run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    test_runner: Annotated[TestRunner, Depends(get_test_runner)],
) -> TestRunResultSchema:
    """Return the current status and results of a test run."""
    # Validate run exists (raises 404 if not found)
    await service.get_run(run_id)

    try:
        result = await test_runner.get_test_result(test_run_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Test run {test_run_id!r} not found",
        )

    return _test_result_to_schema(result)


# ---------------------------------------------------------------------------
# Conflict resolution helpers
# ---------------------------------------------------------------------------


def _find_merge_commit_sync(worktree_path: Path) -> str | None:
    """Return HEAD SHA if it is a merge commit (has ≥ 2 parents), else None."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%P", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        parents = result.stdout.strip().split()
        if len(parents) >= 2:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            return sha
    except subprocess.CalledProcessError:
        pass
    return None


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/conflicts
# ---------------------------------------------------------------------------


@router.get("/{run_id}/review/conflicts", response_model=list[ConflictFile])
async def get_conflicts(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> list[ConflictFile]:
    """Return all files with unresolved merge conflicts, including structured block details."""
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    try:
        conflict_file_paths = await get_conflict_files(worktree_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        blocks_list = await asyncio.gather(
            *[get_conflict_blocks(worktree_path, fp) for fp in conflict_file_paths]
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [
        ConflictFile(
            path=file_path,
            status="unresolved",
            block_count=len(blocks),
            blocks=[
                ConflictBlockSchema(
                    index=b.index,
                    ours_content=b.ours_content,
                    theirs_content=b.theirs_content,
                    base_content=b.base_content,
                )
                for b in blocks
            ],
        )
        for file_path, blocks in zip(conflict_file_paths, blocks_list)
    ]


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/conflicts/agent-resolve
# NOTE: This route must be defined before the {file_path:path}/resolve route
#       so the literal segment "agent-resolve" is not captured as a file path.
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/conflicts/agent-resolve")
async def agent_resolve_conflicts(
    run_id: str,
    body: AgentResolveConflictsRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    emitter: Annotated[PersistentEventEmitter, Depends(get_event_emitter)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> dict[str, str]:
    """Dispatch the run's agent to resolve merge conflicts."""
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    conflict_file_paths = await get_conflict_files(worktree_path)
    if not conflict_file_paths:
        raise HTTPException(status_code=409, detail="No merge conflicts to resolve")

    # Resolve agent type and config from body or run defaults
    agent_type_str: str | None = body.agent_type
    agent_config_override: dict[str, Any] | None = body.agent_config

    agent_type: AgentType | None
    if agent_type_str:
        valid_agent_types = [e.value for e in AgentType]
        if agent_type_str not in valid_agent_types:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid agent_type '{agent_type_str}'. Valid options: {', '.join(valid_agent_types)}",
            )
        agent_type = AgentType(agent_type_str)
    else:
        agent_type = run.agent_type

    agent_config: dict[str, Any] = agent_config_override or run.agent_config or {}

    job_id = str(uuid.uuid4())

    # Dispatch the agent in the background
    if agent_type is not None:
        executor.spawn_for_run(run.id, agent_type, agent_config)

    await emitter.emit(
        AgentFixStarted(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="agent_fix_started",
            job_id=job_id,
            agent_type=agent_type.value if agent_type else "",
        )
    )

    return {"job_id": job_id, "status": "dispatched"}


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/conflicts/{file_path:path}/resolve
# ---------------------------------------------------------------------------


@router.post(
    "/{run_id}/review/conflicts/{file_path:path}/resolve",
    response_model=ConflictResolutionResponse,
)
async def resolve_conflict_endpoint(
    run_id: str,
    file_path: str,
    body: ConflictResolutionRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    emitter: Annotated[PersistentEventEmitter, Depends(get_event_emitter)],
) -> ConflictResolutionResponse:
    """Apply per-block resolutions for a conflict file.

    Each resolution specifies a block_index and a choice of 'ours', 'theirs',
    or 'manual' (with manual_content required for the manual choice).
    The file is written with conflict markers removed and staged with git add.
    """
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    # Validate the file actually has conflicts
    try:
        conflict_file_paths = await get_conflict_files(worktree_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if file_path not in conflict_file_paths:
        raise HTTPException(
            status_code=404,
            detail=f"File {file_path!r} is not an unresolved conflict file",
        )

    # Validate resolution choices
    for res in body.resolutions:
        if res.choice not in ("ours", "theirs", "manual"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid choice {res.choice!r} for block {res.block_index}; "
                "must be 'ours', 'theirs', or 'manual'",
            )
        if res.choice == "manual" and not res.manual_content:
            raise HTTPException(
                status_code=422,
                detail=f"manual_content is required when choice is 'manual' (block {res.block_index})",
            )

    # Apply the resolutions
    resolutions = [
        ConflictBlockResolution(
            block_index=r.block_index,
            choice=r.choice,
            manual_content=r.manual_content,
        )
        for r in body.resolutions
    ]
    try:
        await resolve_conflict(worktree_path, file_path, resolutions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Count remaining conflict files
    try:
        remaining_files = await get_conflict_files(worktree_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    remaining_conflicts = len(remaining_files)

    await emitter.emit(
        ConflictResolved(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="conflict_resolved",
            file_path=file_path,
            remaining_conflicts=remaining_conflicts,
        )
    )

    return ConflictResolutionResponse(
        path=file_path,
        status="resolved",
        remaining_conflicts=remaining_conflicts,
    )


# ---------------------------------------------------------------------------
# Merge readiness computation
# ---------------------------------------------------------------------------


async def compute_readiness(
    run: Run,
    repo_path: Path,
    test_runner: TestRunner,
    executor: AgentExecutor,
) -> MergeReadiness:
    """Evaluate all four merge readiness gates and return aggregate result.

    Gates:
    - clean_merge: merge prediction is clean (no predicted conflicts)
    - no_unresolved_conflicts: no unresolved conflict files in worktree
    - tests_pass: most recent test run passed (or no tests configured)
    - no_active_jobs: no running agent or test jobs
    """
    gates: list[Gate] = []

    # --- Gate: clean_merge ---
    if not run.source_branch:
        gates.append(
            Gate(
                name="clean_merge",
                status="pending",
                description="No source branch configured",
            )
        )
    else:
        run_branch = f"orchestrator/run-{run.id}"
        try:
            status = await asyncio.to_thread(
                get_branch_status, repo_path, run_branch, run.source_branch
            )
            if status.can_merge_cleanly:
                gates.append(
                    Gate(
                        name="clean_merge",
                        status="pass",
                        description="Merge prediction is clean",
                    )
                )
            else:
                gates.append(
                    Gate(
                        name="clean_merge",
                        status="fail",
                        description=f"Merge conflicts predicted in {status.predicted_conflict_count} file(s)",
                    )
                )
        except Exception:
            gates.append(
                Gate(
                    name="clean_merge",
                    status="pending",
                    description="Unable to compute merge prediction",
                )
            )

    # --- Gate: no_unresolved_conflicts ---
    worktree_path: Path | None = Path(run.worktree_path) if run.worktree_path else None
    if worktree_path is None or not worktree_path.exists():
        gates.append(
            Gate(
                name="no_unresolved_conflicts",
                status="pending",
                description="Worktree not available",
            )
        )
    else:
        try:
            conflict_files = await get_conflict_files(worktree_path)
            if not conflict_files:
                gates.append(
                    Gate(
                        name="no_unresolved_conflicts",
                        status="pass",
                        description="No unresolved merge conflicts",
                    )
                )
            else:
                gates.append(
                    Gate(
                        name="no_unresolved_conflicts",
                        status="fail",
                        description=f"{len(conflict_files)} file(s) have unresolved merge conflicts",
                    )
                )
        except Exception:
            gates.append(
                Gate(
                    name="no_unresolved_conflicts",
                    status="pending",
                    description="Unable to check conflict status",
                )
            )

    # --- Gate: tests_pass ---
    commands = _get_auto_verify_commands(run.routine_embedded)
    if not commands:
        gates.append(
            Gate(
                name="tests_pass",
                status="pass",
                description="No tests configured",
            )
        )
    elif test_runner.is_running(run.id):
        gates.append(
            Gate(
                name="tests_pass",
                status="pending",
                description="Test run is in progress",
            )
        )
    else:
        last_result = test_runner.get_last_result_for_run(run.id)
        if last_result is None:
            gates.append(
                Gate(
                    name="tests_pass",
                    status="pending",
                    description="No test run recorded yet",
                )
            )
        elif last_result.status == "passed":
            gates.append(
                Gate(
                    name="tests_pass",
                    status="pass",
                    description="Most recent test run passed",
                )
            )
        else:
            gates.append(
                Gate(
                    name="tests_pass",
                    status="fail",
                    description=f"Most recent test run {last_result.status}",
                )
            )

    # --- Gate: no_active_jobs ---
    agent_running = executor.is_running(run.id)
    test_running = test_runner.is_running(run.id)
    if agent_running or test_running:
        reasons: list[str] = []
        if agent_running:
            reasons.append("agent job")
        if test_running:
            reasons.append("test job")
        gates.append(
            Gate(
                name="no_active_jobs",
                status="fail",
                description=f"Active jobs: {', '.join(reasons)}",
            )
        )
    else:
        gates.append(
            Gate(
                name="no_active_jobs",
                status="pass",
                description="No active agent or test jobs",
            )
        )

    ready = all(g.status == "pass" for g in gates)
    return MergeReadiness(ready=ready, gates=gates)


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/merge-readiness
# ---------------------------------------------------------------------------


@router.get("/{run_id}/review/merge-readiness", response_model=MergeReadiness)
async def get_merge_readiness(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    config: Annotated[GlobalConfig, Depends(get_global_config)],
    test_runner: Annotated[TestRunner, Depends(get_test_runner)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> MergeReadiness:
    """Return merge readiness by evaluating all four gates.

    Gates:
    - clean_merge: merge prediction is clean (no predicted conflicts)
    - no_unresolved_conflicts: no unresolved conflict files
    - tests_pass: most recent test run passed (or no tests configured)
    - no_active_jobs: no running agent or test jobs
    """
    run = await service.get_run(run_id)
    repo_path = config.paths.get_repos_path() / run.repo_name
    return await compute_readiness(run, repo_path, test_runner, executor)


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/revert-back-merge
# ---------------------------------------------------------------------------


@router.post("/{run_id}/review/revert-back-merge")
async def revert_back_merge_endpoint(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    emitter: Annotated[PersistentEventEmitter, Depends(get_event_emitter)],
) -> dict[str, str]:
    """Revert the last back merge commit.

    The HEAD commit must be a merge commit created by a previous back-merge
    operation. Returns the SHA of the revert commit and the new HEAD.
    """
    run = await service.get_run(run_id)
    worktree_path = _require_worktree(run.worktree_path)

    merge_sha = await asyncio.to_thread(_find_merge_commit_sync, worktree_path)
    if not merge_sha:
        raise HTTPException(
            status_code=409,
            detail="No back merge commit found to revert; HEAD is not a merge commit",
        )

    try:
        result = await asyncio.to_thread(revert_back_merge, worktree_path, merge_sha)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await emitter.emit(
        BackMergeReverted(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="back_merge_reverted",
            reverted_commit=result.reverted_commit,
            new_head=result.new_head,
        )
    )

    return {"reverted_commit": result.reverted_commit, "new_head": result.new_head}
