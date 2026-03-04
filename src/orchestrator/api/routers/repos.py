"""API router for repository management."""

import asyncio
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_repos_path, get_session
from orchestrator.api.schemas.repos import (
    AddRepoRequest,
    BranchCountResponse,
    BranchesListResponse,
    BranchResponse,
    ProjectRoutineResponse,
    ProjectRoutinesListResponse,
    RepoResponse,
    ReposListResponse,
    RepoStatsResponse,
)
from orchestrator.db.models import RunModel
from orchestrator.repos import branch_count, get_repo, list_branches, list_repos
from orchestrator.routines.discovery import discover_routines_in_repo, get_routine_from_repo

router = APIRouter(prefix="/api/repos", tags=["repos"])

# Maximum branches to return before truncating
MAX_BRANCHES = 100


@router.get("", response_model=ReposListResponse)
async def list_repositories(
    repos_path: Annotated[Path, Depends(get_repos_path)],
) -> ReposListResponse:
    """List all repositories in the repos directory."""
    repos = list_repos(repos_path)
    return ReposListResponse(
        repos=[
            RepoResponse(
                name=r.name,
                path=str(r.path),
                default_branch=r.default_branch,
            )
            for r in repos
        ]
    )


@router.post("", response_model=RepoResponse, status_code=201)
async def add_repository(
    body: AddRepoRequest,
    repos_path: Annotated[Path, Depends(get_repos_path)],
) -> RepoResponse:
    """Add a repository by cloning a URL or symlinking a local path."""
    if body.url:
        # Validate URL scheme
        if not body.url.startswith(("http://", "https://", "ssh://", "git@")):
            raise HTTPException(
                status_code=422,
                detail="Repository URL must use http://, https://, ssh://, or git@ format",
            )
        # Infer name from URL: last path segment, strip .git suffix
        url = body.url.rstrip("/")
        name = url.split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]

        dest = repos_path / name
        if dest.exists():
            raise HTTPException(status_code=409, detail="Repository already exists")

        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            body.url,
            str(dest),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode(errors="replace").strip()
            raise HTTPException(status_code=422, detail=f"Failed to clone: {stderr}")

        repo = get_repo(repos_path, name)
        return RepoResponse(
            name=repo.name,
            path=str(repo.path),
            default_branch=repo.default_branch,
        )

    # body.path is set (validated by schema)
    path_obj = Path(body.path).resolve()  # type: ignore[arg-type]
    if not path_obj.exists() or not (path_obj / ".git").exists():
        raise HTTPException(status_code=422, detail="Not a valid git repository")

    name = path_obj.name

    # If already inside repos_path, just return it
    try:
        path_obj.relative_to(repos_path)
        repo = get_repo(repos_path, name)
        return RepoResponse(
            name=repo.name,
            path=str(repo.path),
            default_branch=repo.default_branch,
        )
    except ValueError:
        pass  # Not inside repos_path, continue to symlink

    dest = repos_path / name
    if dest.exists():
        raise HTTPException(status_code=409, detail="Already exists")

    dest.symlink_to(path_obj)
    repo = get_repo(repos_path, name)
    return RepoResponse(
        name=repo.name,
        path=str(repo.path),
        default_branch=repo.default_branch,
    )


@router.delete("/{name}", status_code=204)
async def remove_repository(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
) -> None:
    """Remove a repository from the repos directory."""
    entry = repos_path / name
    if not entry.exists() and not entry.is_symlink():
        raise HTTPException(status_code=404, detail="Repository not found")

    if entry.is_symlink():
        entry.unlink()
    else:
        shutil.rmtree(entry)


@router.get("/{name}", response_model=RepoResponse)
async def get_repository(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
) -> RepoResponse:
    """Get details of a specific repository."""
    repo = get_repo(repos_path, name)
    return RepoResponse(
        name=repo.name,
        path=str(repo.path),
        default_branch=repo.default_branch,
    )


@router.get("/{name}/branches", response_model=BranchesListResponse)
async def list_repository_branches(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
    pattern: Annotated[str, Query(description="Glob pattern to filter branches")] = "",
    include_remote: Annotated[bool, Query(description="Include remote branches")] = True,
) -> BranchesListResponse:
    """List branches in a repository.

    If more than 100 branches match, the result is truncated.
    Use the pattern parameter to filter branches using glob patterns like:
    - `feat*` - branches starting with "feat"
    - `*/auth` - branches ending with "/auth"
    - `release-*` - release branches
    """
    repo = get_repo(repos_path, name)
    branches = list_branches(repo.path, pattern=pattern, include_remote=include_remote)

    truncated = len(branches) > MAX_BRANCHES
    if truncated:
        branches = branches[:MAX_BRANCHES]

    return BranchesListResponse(
        branches=[
            BranchResponse(
                name=b.name,
                is_remote=b.is_remote,
                commit=b.commit,
            )
            for b in branches
        ],
        total=len(branches) if not truncated else branch_count(repo.path, pattern, include_remote),
        truncated=truncated,
    )


@router.get("/{name}/branches/count", response_model=BranchCountResponse)
async def count_repository_branches(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
    pattern: Annotated[str, Query(description="Glob pattern to filter branches")] = "",
    include_remote: Annotated[bool, Query(description="Include remote branches")] = True,
) -> BranchCountResponse:
    """Count branches matching a pattern.

    Use this endpoint to check if refining the pattern is needed before
    fetching the full branch list.
    """
    repo = get_repo(repos_path, name)
    count = branch_count(repo.path, pattern=pattern, include_remote=include_remote)
    return BranchCountResponse(count=count, pattern=pattern)


@router.get("/{name}/stats", response_model=RepoStatsResponse)
async def get_repository_stats(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepoStatsResponse:
    """Get statistics for a specific repository.

    Returns the number of runs associated with this repository.
    """
    # Validate that the repo exists
    get_repo(repos_path, name)

    result = await session.execute(
        select(func.count()).select_from(RunModel).where(RunModel.repo_name == name)
    )
    run_count = result.scalar_one()
    return RepoStatsResponse(run_count=run_count)


@router.get("/{name}/routines", response_model=ProjectRoutinesListResponse)
async def list_repository_routines(
    name: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
    branch: Annotated[str, Query(description="Branch to read routines from")] = "main",
) -> ProjectRoutinesListResponse:
    """List routines defined in a repository at a specific branch.

    Routines are discovered from the `routines/` directory within the repository.
    Supports both flat files (`routines/*.yaml`) and directory-based routines
    (`routines/*/routine.yaml`).

    Directory-based routines may include a `scaffolding/` subdirectory with
    template files that get copied to the worktree on run start.
    """
    repo = get_repo(repos_path, name)
    routines = discover_routines_in_repo(repo.path, branch)

    # Get commit for the branch
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", branch],
            cwd=repo.path,
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
    except subprocess.CalledProcessError:
        commit = ""

    return ProjectRoutinesListResponse(
        routines=[
            ProjectRoutineResponse(
                id=r.config.id,
                name=r.config.name,
                description=r.config.description,
                source="PROJECT",
                path=r.path,
                commit=r.commit,
                has_scaffolding=r.has_scaffolding,
                config=r.config.model_dump(),
            )
            for r in routines
        ],
        branch=branch,
        commit=commit,
    )


@router.get("/{name}/routines/{routine_id}", response_model=ProjectRoutineResponse)
async def get_repository_routine(
    name: str,
    routine_id: str,
    repos_path: Annotated[Path, Depends(get_repos_path)],
    branch: Annotated[str, Query(description="Branch to read routine from")] = "main",
) -> ProjectRoutineResponse:
    """Get a specific routine from a repository.

    Returns the full routine configuration including steps, tasks, and requirements.
    """
    repo = get_repo(repos_path, name)
    routine = get_routine_from_repo(repo.path, branch, routine_id)

    if routine is None:
        raise HTTPException(
            status_code=404, detail=f"Routine '{routine_id}' not found in branch '{branch}'"
        )

    return ProjectRoutineResponse(
        id=routine.config.id,
        name=routine.config.name,
        description=routine.config.description,
        source="PROJECT",
        path=routine.path,
        commit=routine.commit,
        has_scaffolding=routine.has_scaffolding,
        config=routine.config.model_dump(),
    )
