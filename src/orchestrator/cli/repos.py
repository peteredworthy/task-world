"""Repository management commands."""

import json
from pathlib import Path

import click

from orchestrator.config.global_config import load_global_config
from orchestrator.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.repos.errors import RepoNotFoundError


@click.group()
def repos() -> None:
    """Manage repositories."""
    pass


@repos.command("list")
@click.option("--repos-dir", help="Override repos directory path")
@click.pass_context
def list_repos_cmd(ctx: click.Context, repos_dir: str | None) -> None:
    """List available repositories."""
    as_json = ctx.obj["json"]

    # Load config to get repos directory
    config = load_global_config()
    path = Path(repos_dir) if repos_dir else config.paths.get_repos_path()

    discovered = list_repos(path)

    if as_json:
        result = [
            {
                "name": repo.name,
                "path": str(repo.path),
                "default_branch": repo.default_branch,
            }
            for repo in discovered
        ]
        click.echo(json.dumps(result, indent=2))
    else:
        if not discovered:
            click.echo(f"No repositories found in {path}")
            return

        click.echo(f"Repositories in {path}:\n")
        for repo in discovered:
            click.echo(f"  {repo.name}")
            click.echo(f"    Default branch: {repo.default_branch}")
            click.echo(f"    Path: {repo.path}")
            click.echo()


@repos.command("show")
@click.argument("name")
@click.option("--repos-dir", help="Override repos directory path")
@click.pass_context
def show_repo(ctx: click.Context, name: str, repos_dir: str | None) -> None:
    """Show details of a specific repository."""
    as_json = ctx.obj["json"]

    config = load_global_config()
    path = Path(repos_dir) if repos_dir else config.paths.get_repos_path()

    try:
        repo = get_repo(path, name)
    except RepoNotFoundError:
        if as_json:
            click.echo(json.dumps({"error": f"Repository '{name}' not found"}))
        else:
            click.echo(f"Error: Repository '{name}' not found in {path}", err=True)
        raise SystemExit(1)

    # Get branch count
    branches = list_branches(repo.path)
    local_count = sum(1 for b in branches if not b.is_remote)
    remote_count = sum(1 for b in branches if b.is_remote)

    if as_json:
        result = {
            "name": repo.name,
            "path": str(repo.path),
            "default_branch": repo.default_branch,
            "local_branches": local_count,
            "remote_branches": remote_count,
        }
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Repository: {repo.name}")
        click.echo(f"Path: {repo.path}")
        click.echo(f"Default branch: {repo.default_branch}")
        click.echo(f"Local branches: {local_count}")
        click.echo(f"Remote branches: {remote_count}")


@repos.command("branches")
@click.argument("name")
@click.argument("pattern", required=False, default="")
@click.option("--local-only", is_flag=True, help="Show only local branches")
@click.option("--limit", default=100, help="Maximum number of branches to show")
@click.option("--repos-dir", help="Override repos directory path")
@click.pass_context
def list_branches_cmd(
    ctx: click.Context,
    name: str,
    pattern: str,
    local_only: bool,
    limit: int,
    repos_dir: str | None,
) -> None:
    """List branches in a repository.

    Optionally filter by glob pattern. Examples:
      feat*         - branches starting with "feat"
      */auth        - branches ending with "/auth"
      release-*     - release branches
    """
    as_json = ctx.obj["json"]

    config = load_global_config()
    path = Path(repos_dir) if repos_dir else config.paths.get_repos_path()

    try:
        repo = get_repo(path, name)
    except RepoNotFoundError:
        if as_json:
            click.echo(json.dumps({"error": f"Repository '{name}' not found"}))
        else:
            click.echo(f"Error: Repository '{name}' not found in {path}", err=True)
        raise SystemExit(1)

    branches = list_branches(repo.path, pattern=pattern, include_remote=not local_only)
    total = len(branches)
    truncated = total > limit
    branches = branches[:limit]

    if as_json:
        result = {
            "branches": [
                {
                    "name": b.name,
                    "is_remote": b.is_remote,
                    "commit": b.commit,
                }
                for b in branches
            ],
            "total": total,
            "truncated": truncated,
        }
        click.echo(json.dumps(result, indent=2))
    else:
        if not branches:
            if pattern:
                click.echo(f"No branches matching '{pattern}'")
            else:
                click.echo("No branches found")
            return

        if pattern:
            click.echo(f"Branches matching '{pattern}':")
        else:
            click.echo("Branches:")
        click.echo()

        for branch in branches:
            remote_marker = " (remote)" if branch.is_remote else ""
            click.echo(f"  {branch.name}{remote_marker}")
            click.echo(f"    Commit: {branch.commit}")

        if truncated:
            click.echo()
            click.echo(f"Showing {limit} of {total} branches. Use --limit to see more.")
