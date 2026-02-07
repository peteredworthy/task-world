"""Routine management commands."""

import asyncio
import json
import sys
from pathlib import Path

import click
import httpx

from orchestrator.config.enums import RoutineSource
from orchestrator.routines.discovery import discover_routines
from orchestrator.routines.errors import (
    RoutineNotFoundError,
    RoutineParseError,
    RoutineValidationError,
)
from orchestrator.routines.loader import load_routine_from_path


@click.group()
def routines() -> None:
    """Manage routines."""
    pass


@routines.command("list")
@click.option("--project", "-p", help="Project directory to scan")
@click.pass_context
def list_routines(ctx: click.Context, project: str | None) -> None:
    """List available routines."""
    as_json = ctx.obj["json"]

    # Build list of directories to scan
    routine_dirs = [(Path("routines"), RoutineSource.LOCAL)]
    if project:
        routine_dirs.append((Path(project) / "routines", RoutineSource.PROJECT))

    # Discover routines
    discovered = discover_routines(routine_dirs)

    if as_json:
        result = [
            {
                "id": routine.config.id,
                "name": routine.config.name,
                "description": routine.config.description,
                "source": routine.source.value,
                "path": str(routine.path),
                "steps": len(routine.config.steps),
                "inputs": len(routine.config.inputs),
            }
            for routine in discovered
        ]
        click.echo(json.dumps(result, indent=2))
    else:
        if not discovered:
            click.echo("No routines found.")
            return

        for routine in discovered:
            source_str = f"[{routine.source.value}]"
            steps_str = f"{len(routine.config.steps)} steps"
            click.echo(f"{routine.config.id} | {routine.config.name} | {steps_str} | {source_str}")


@routines.command("validate")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def validate_routine(ctx: click.Context, path: Path) -> None:
    """Validate a routine YAML file."""
    as_json = ctx.obj["json"]

    try:
        routine_config = load_routine_from_path(path)

        if as_json:
            result = {
                "valid": True,
                "id": routine_config.id,
                "name": routine_config.name,
                "steps": len(routine_config.steps),
                "inputs": len(routine_config.inputs),
            }
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"✓ Valid routine: {routine_config.id}")
            click.echo(f"  Name: {routine_config.name}")
            click.echo(f"  Steps: {len(routine_config.steps)}")
            click.echo(f"  Inputs: {len(routine_config.inputs)}")

    except RoutineNotFoundError:
        if as_json:
            click.echo(json.dumps({"valid": False, "errors": ["File not found"]}))
        else:
            click.echo(f"✗ Error: File not found: {path}", err=True)
        sys.exit(1)

    except RoutineParseError as e:
        if as_json:
            click.echo(json.dumps({"valid": False, "errors": [str(e)]}))
        else:
            click.echo(f"✗ Parse error: {e}", err=True)
        sys.exit(1)

    except RoutineValidationError as e:
        if as_json:
            errors = [str(err) for err in e.errors]
            click.echo(json.dumps({"valid": False, "errors": errors}))
        else:
            click.echo("✗ Validation errors:", err=True)
            for error in e.errors:
                click.echo(f"  - {error}", err=True)
        sys.exit(1)


@routines.command("show")
@click.argument("routine_id")
@click.option("--project", "-p", help="Project directory to scan")
@click.option("--url", help="API server URL (uses local discovery if not provided)")
@click.pass_context
def show_routine(ctx: click.Context, routine_id: str, project: str | None, url: str | None) -> None:
    """Show details of a specific routine."""
    as_json = ctx.obj["json"]

    if url:
        # Use API to fetch routine details
        async def _show_via_api() -> None:
            api_url = f"{url.rstrip('/')}/api/routines/{routine_id}"

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(api_url)
                    response.raise_for_status()
                    result = response.json()

            except httpx.HTTPStatusError as e:
                if as_json:
                    click.echo(json.dumps({"error": str(e), "status": e.response.status_code}))
                else:
                    click.echo(f"Error: {e}", err=True)
                sys.exit(1)
            except Exception as e:
                if as_json:
                    click.echo(json.dumps({"error": str(e)}))
                else:
                    click.echo(f"Error: {e}", err=True)
                sys.exit(1)

            if as_json:
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"Routine: {result.get('name')}")
                click.echo(f"ID: {result.get('id')}")
                click.echo(f"Description: {result.get('description', 'N/A')}")
                click.echo(f"Source: {result.get('source')}")

                inputs = result.get("inputs", [])
                click.echo(f"\nInputs ({len(inputs)}):")
                for inp in inputs:
                    required_str = "[required]" if inp.get("required") else "[optional]"
                    click.echo(
                        f"  - {inp.get('name')}: {inp.get('description', 'N/A')} {required_str}"
                    )

                steps = result.get("steps", [])
                click.echo(f"\nSteps ({len(steps)}):")
                for i, step in enumerate(steps, 1):
                    click.echo(
                        f"  {i}. {step.get('title', 'Untitled')} ({step.get('task_count', 0)} tasks)"
                    )

        asyncio.run(_show_via_api())
    else:
        # Use local discovery (original implementation)
        # Build list of directories to scan
        routine_dirs = [(Path("routines"), RoutineSource.LOCAL)]
        if project:
            routine_dirs.append((Path(project) / "routines", RoutineSource.PROJECT))

        # Discover routines
        discovered = discover_routines(routine_dirs)

        # Find the routine
        routine_config = None
        for routine in discovered:
            if routine.config.id == routine_id:
                routine_config = routine.config
                break

        if routine_config is None:
            if as_json:
                click.echo(json.dumps({"error": "Routine not found"}))
            else:
                click.echo(f"Error: Routine '{routine_id}' not found", err=True)
            sys.exit(1)

        if as_json:
            result = {
                "id": routine_config.id,
                "name": routine_config.name,
                "description": routine_config.description,
                "inputs": [
                    {"name": inp.name, "description": inp.description, "required": inp.required}
                    for inp in routine_config.inputs
                ],
                "steps": [
                    {
                        "id": step.id,
                        "title": step.title,
                        "tasks": [
                            {
                                "id": task.id,
                                "title": task.title,
                                "requirements": len(task.requirements),
                            }
                            for task in step.tasks
                        ],
                    }
                    for step in routine_config.steps
                ],
            }
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Routine: {routine_config.name}")
            click.echo(f"ID: {routine_config.id}")
            click.echo(f"Description: {routine_config.description}")
            click.echo(f"\nInputs ({len(routine_config.inputs)}):")
            for inp in routine_config.inputs:
                required_str = "[required]" if inp.required else "[optional]"
                click.echo(f"  - {inp.name}: {inp.description} {required_str}")

            click.echo(f"\nSteps ({len(routine_config.steps)}):")
            for i, step in enumerate(routine_config.steps, 1):
                click.echo(f"  {i}. {step.title}")
                for task in step.tasks:
                    click.echo(f"     - {task.title} ({len(task.requirements)} requirements)")
