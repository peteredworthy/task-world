"""Run management commands."""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import httpx
import websockets

from orchestrator.config.enums import AgentRunnerType, RoutineSource, RunStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import resolve_default_journal_path
from orchestrator.db import replay_journal_to_repository
from orchestrator.db import CheckpointRepository, RunRepository
from orchestrator.config.routines.discovery import discover_routines
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow.locks import InMemoryLockManager
from orchestrator.workflow.service import WorkflowService

from orchestrator.cli.approve import approve_command


@click.group()
def runs() -> None:
    """Manage runs."""
    pass


# Register the approve command
runs.add_command(approve_command)


@runs.command("list")
@click.option("--repo", "-r", help="Filter by repository name")
@click.option("--status", "-s", help="Filter by status")
@click.pass_context
def list_runs(ctx: click.Context, repo: str | None, status: str | None) -> None:
    """List runs."""

    async def _list() -> None:
        db_path = ctx.obj["db"]
        as_json = ctx.obj["json"]

        engine = create_engine(db_path)
        await init_db(engine)
        session_factory = create_session_factory(engine)

        async with session_factory() as session:
            repository = RunRepository(session)

            # Apply filters
            if repo:
                runs_list = await repository.list_by_repo(repo)
            elif status:
                try:
                    status_enum = RunStatus(status)
                    runs_list = await repository.list_by_status(status_enum)
                except ValueError:
                    click.echo(f"Error: Invalid status '{status}'", err=True)
                    sys.exit(1)
            else:
                runs_list = await repository.list_all()

        await engine.dispose()

        if as_json:
            # Serialize to JSON
            result = [
                {
                    "id": run.id,
                    "routine_id": run.routine_id,
                    "repo_name": run.repo_name,
                    "status": run.status.value,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                }
                for run in runs_list
            ]
            click.echo(json.dumps(result, indent=2))
        else:
            # Human-readable output
            if not runs_list:
                click.echo("No runs found.")
                return

            for run in runs_list:
                status_str = run.status.value
                click.echo(
                    f"{run.id} | {run.routine_id or '<embedded>'} | {status_str} | {run.repo_name}"
                )

    asyncio.run(_list())


@runs.command("create")
@click.argument("routine_id")
@click.option("--repo", "-r", required=True, help="Repository name in repos directory")
@click.option("--branch", "-b", required=True, help="Branch to base worktree on")
@click.option("--config", "-c", multiple=True, help="Config key=value pairs")
@click.option(
    "--agent", "-a", help="Agent type (openhands_local, cli_subprocess, user_managed, etc.)"
)
@click.option("--agent-config", "-ac", multiple=True, help="Agent config key=value pairs")
@click.pass_context
def create_run(
    ctx: click.Context,
    routine_id: str,
    repo: str,
    branch: str,
    config: tuple[str, ...],
    agent: str | None,
    agent_config: tuple[str, ...],
) -> None:
    """Create a new run."""

    async def _create() -> None:
        db_path = ctx.obj["db"]
        as_json = ctx.obj["json"]

        # Parse config
        cfg: dict[str, str] = {}
        for kv in config:
            if "=" not in kv:
                click.echo(f"Error: Invalid config format '{kv}'. Expected key=value", err=True)
                sys.exit(1)
            key, value = kv.split("=", 1)
            cfg[key] = value

        # Parse agent config
        agent_cfg: dict[str, str] = {}
        for kv in agent_config:
            if "=" not in kv:
                click.echo(
                    f"Error: Invalid agent config format '{kv}'. Expected key=value", err=True
                )
                sys.exit(1)
            key, value = kv.split("=", 1)
            agent_cfg[key] = value

        engine = create_engine(db_path)
        await init_db(engine)
        session_factory = create_session_factory(engine)

        async with session_factory() as session:
            repository = RunRepository(session)

            # Discover routines
            routine_dirs = [
                (Path("routines"), RoutineSource.LOCAL),
            ]
            discovered = discover_routines(routine_dirs)

            # Find the routine
            routine_config = None
            for routine in discovered:
                if routine.config.id == routine_id:
                    routine_config = routine.config
                    break

            if routine_config is None:
                click.echo(f"Error: Routine '{routine_id}' not found", err=True)
                sys.exit(1)

            # Create run
            run = create_run_from_routine(
                routine=routine_config,
                repo_name=repo,
                source_branch=branch,
                config=cfg,
            )

            # Set agent if provided
            if agent:
                try:
                    run.agent_type = AgentRunnerType(agent)
                except ValueError:
                    click.echo(f"Error: Invalid agent type '{agent}'", err=True)
                    sys.exit(1)
                if agent_cfg:
                    run.agent_config = agent_cfg

            # Save to database
            await repository.save(run)
            await session.commit()

        await engine.dispose()

        if as_json:
            result = {
                "id": run.id,
                "routine_id": run.routine_id,
                "repo_name": run.repo_name,
                "status": run.status.value,
                "agent_type": run.agent_type.value if run.agent_type else None,
            }
            click.echo(json.dumps(result, indent=2))
        else:
            agent_str = f" with agent {run.agent_type.value}" if run.agent_type else ""
            click.echo(f"Created run {run.id}{agent_str}")

    asyncio.run(_create())


@runs.command("start")
@click.argument("run_id")
@click.pass_context
def start_run(ctx: click.Context, run_id: str) -> None:
    """Start a run (DRAFT -> ACTIVE)."""

    async def _start() -> None:
        db_path = ctx.obj["db"]
        as_json = ctx.obj["json"]

        engine = create_engine(db_path)
        await init_db(engine)
        session_factory = create_session_factory(engine)

        async with session_factory() as session:
            lock_manager = InMemoryLockManager()

            service = WorkflowService(
                session=session,
                lock_manager=lock_manager,
            )

            try:
                # Start the run
                run = await service.start_run(run_id=run_id)
                await session.commit()

            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)

        await engine.dispose()

        if as_json:
            result = {
                "id": run.id,
                "status": run.status.value,
                "agent_type": run.agent_type.value if run.agent_type else None,
            }
            click.echo(json.dumps(result, indent=2))
        else:
            agent_str = f" with agent {run.agent_type.value}" if run.agent_type else ""
            click.echo(f"Started run {run.id}{agent_str}")

    asyncio.run(_start())


@runs.command("watch")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def watch_run(ctx: click.Context, run_id: str, url: str) -> None:
    """Watch a run in real-time."""

    async def _watch() -> None:
        # Convert http:// to ws://
        ws_url = url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url.rstrip('/')}/ws/runs/{run_id}"

        shutdown = False

        def signal_handler(sig: int, frame: object) -> None:
            nonlocal shutdown
            shutdown = True

        # Register Ctrl+C handler
        signal.signal(signal.SIGINT, signal_handler)

        click.echo(f"Watching run {run_id}... (Press Ctrl+C to stop)")

        try:
            async with websockets.connect(ws_url) as websocket:  # type: ignore[attr-defined]
                while not shutdown:
                    try:
                        # Set a short timeout so we can check shutdown flag
                        message = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                        if ctx.obj["json"]:
                            # Output raw JSON
                            click.echo(message)
                        else:
                            # Parse and format
                            try:
                                event = json.loads(message)
                                event_type = event.get("event_type", "unknown")
                                timestamp = event.get("timestamp", "")
                                click.echo(f"[{timestamp}] {event_type}")
                                # Show key fields based on event type
                                if "task_id" in event:
                                    click.echo(f"  Task: {event.get('task_id')}")
                                if "status" in event:
                                    click.echo(f"  Status: {event.get('status')}")
                                if "message" in event:
                                    click.echo(f"  Message: {event.get('message')}")
                            except json.JSONDecodeError:
                                click.echo(message)
                    except asyncio.TimeoutError:
                        continue  # Check shutdown flag and loop

        except websockets.exceptions.WebSocketException as e:  # type: ignore[attr-defined]
            click.echo(f"WebSocket error: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            if not shutdown:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)

        click.echo("\nStopped watching.")

    asyncio.run(_watch())


def _parse_iso_timestamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@runs.command("replay-journal")
@click.option(
    "--journal",
    "journal_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to JSONL journal (defaults to DB-adjacent .orchestrator/state/history.jsonl)",
)
@click.option(
    "--run-id",
    "run_ids",
    multiple=True,
    help="Replay only selected run IDs (repeatable)",
)
@click.option(
    "--since",
    default=None,
    help="Replay only entries at/after this ISO-8601 timestamp (example: 2026-03-09T10:00:00Z)",
)
@click.option(
    "--dry-run", is_flag=True, help="Parse and evaluate replay without writing DB changes"
)
@click.option(
    "--from-checkpoint", is_flag=True, default=False, help="Resume from last saved checkpoint"
)
@click.option(
    "--show-checkpoint", is_flag=True, default=False, help="Show current checkpoint info and exit"
)
@click.option("--batch-size", type=int, default=100, help="Events per transaction batch")
@click.pass_context
def replay_journal(
    ctx: click.Context,
    journal_path: Path | None,
    run_ids: tuple[str, ...],
    since: str | None,
    dry_run: bool,
    from_checkpoint: bool,
    show_checkpoint: bool,
    batch_size: int,
) -> None:
    """Replay JSONL journal entries onto a restored DB."""

    async def _replay() -> None:
        db_path = ctx.obj["db"]
        as_json = ctx.obj["json"]

        selected_journal = journal_path or resolve_default_journal_path(db_path)
        if selected_journal is None:
            click.echo(
                "Error: Could not resolve journal path. Provide --journal explicitly.",
                err=True,
            )
            sys.exit(1)
        if not selected_journal.exists():
            click.echo(f"Error: Journal file not found: {selected_journal}", err=True)
            sys.exit(1)

        # Preflight: check journal is readable
        if not os.access(selected_journal, os.R_OK):
            click.echo(f"Error: Journal file is not readable: {selected_journal}", err=True)
            sys.exit(1)

        engine = create_engine(db_path)
        await init_db(engine)
        session_factory = create_session_factory(engine)

        # Handle --show-checkpoint: display checkpoint info and exit
        if show_checkpoint:
            async with session_factory() as session:
                checkpoint_repo = CheckpointRepository(session)
                checkpoint = await checkpoint_repo.get_checkpoint(str(selected_journal))
            await engine.dispose()

            if checkpoint is None:
                if as_json:
                    click.echo(json.dumps({"checkpoint": None}))
                else:
                    click.echo(f"No checkpoint found for journal: {selected_journal}")
                return

            cp_info = {
                "journal_path": checkpoint.journal_path,
                "last_applied_sequence": checkpoint.last_applied_sequence,
                "last_applied_timestamp": checkpoint.last_applied_timestamp.isoformat()
                if checkpoint.last_applied_timestamp
                else None,
                "updated_at": checkpoint.updated_at.isoformat() if checkpoint.updated_at else None,
            }
            if as_json:
                click.echo(json.dumps({"checkpoint": cp_info}, indent=2))
            else:
                click.echo(f"Journal:  {cp_info['journal_path']}")
                click.echo(f"Sequence: {cp_info['last_applied_sequence']}")
                click.echo(f"Applied:  {cp_info['last_applied_timestamp']}")
                click.echo(f"Updated:  {cp_info['updated_at']}")
            return

        since_dt: datetime | None = None
        if since:
            try:
                since_dt = _parse_iso_timestamp(since)
            except ValueError:
                click.echo(f"Error: Invalid --since timestamp: {since}", err=True)
                sys.exit(1)

        # Preflight: validate checkpoint consistency when resuming
        if from_checkpoint:
            async with session_factory() as session:
                checkpoint_repo = CheckpointRepository(session)
                existing_cp = await checkpoint_repo.get_checkpoint(str(selected_journal))
            if existing_cp is not None:
                # Read max sequence from journal to validate consistency
                from orchestrator.db import scan_max_sequence

                max_journal_seq = scan_max_sequence(selected_journal)
                if existing_cp.last_applied_sequence > max_journal_seq:
                    click.echo(
                        f"Error: Checkpoint sequence ({existing_cp.last_applied_sequence}) "
                        f"exceeds max journal sequence ({max_journal_seq}). "
                        f"Journal may have been truncated.",
                        err=True,
                    )
                    await engine.dispose()
                    sys.exit(1)

        async with session_factory() as session:
            repository = RunRepository(session)
            checkpoint_repo = CheckpointRepository(session) if from_checkpoint else None
            summary = await replay_journal_to_repository(
                repository,
                journal_path=selected_journal,
                run_ids=set(run_ids) if run_ids else None,
                since=since_dt,
                dry_run=dry_run,
                batch_size=batch_size,
                from_checkpoint=from_checkpoint,
                checkpoint_repo=checkpoint_repo,
            )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()

        await engine.dispose()

        result: dict[str, Any] = {
            "journal_path": str(summary.journal_path),
            "parsed_entries": summary.parsed_entries,
            "replayed_events": summary.replayed_events,
            "updated_runs": summary.updated_runs,
            "missing_runs": summary.missing_runs,
            "dry_run": dry_run,
        }
        if summary.checkpoint_sequence is not None:
            result["checkpoint_sequence"] = summary.checkpoint_sequence
        if summary.resumed_from_sequence is not None:
            result["resumed_from_sequence"] = summary.resumed_from_sequence

        if as_json:
            click.echo(json.dumps(result, indent=2))
            return

        click.echo(f"Journal: {result['journal_path']}")
        click.echo(
            f"Parsed {summary.parsed_entries} entries; "
            f"replayed {summary.replayed_events} events into {summary.updated_runs} run(s)."
        )
        if summary.resumed_from_sequence is not None:
            click.echo(f"Resumed from checkpoint sequence: {summary.resumed_from_sequence}")
        if summary.checkpoint_sequence is not None:
            click.echo(f"Checkpoint sequence: {summary.checkpoint_sequence}")
        if summary.missing_runs:
            click.echo(
                f"Skipped {summary.missing_runs} run(s) absent from current DB backup.",
                err=True,
            )
        if dry_run:
            click.echo("Dry-run mode: no DB changes were written.")

    asyncio.run(_replay())


@runs.command("pause")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def pause_run(ctx: click.Context, run_id: str, url: str) -> None:
    """Pause a run (ACTIVE -> PAUSED)."""

    async def _pause() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/pause"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url)
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
            click.echo(f"Paused run {run_id}")
            click.echo(f"Status: {result.get('status')}")

    asyncio.run(_pause())


@runs.command("resume")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.option(
    "--agent",
    "-a",
    help="Agent type to switch to (openhands_local, cli_subprocess, user_managed, etc.)",
)
@click.option("--agent-config", "-ac", multiple=True, help="Agent config key=value pairs")
@click.pass_context
def resume_run(
    ctx: click.Context, run_id: str, url: str, agent: str | None, agent_config: tuple[str, ...]
) -> None:
    """Resume a run (PAUSED -> ACTIVE), optionally changing the agent."""

    async def _resume() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/resume"

        # Build request body
        request_body: dict[str, Any] = {}

        if agent:
            # Validate agent type
            try:
                AgentRunnerType(agent)  # Validate it's a valid enum value
                request_body["agent_type"] = agent
            except ValueError:
                click.echo(f"Error: Invalid agent type '{agent}'", err=True)
                sys.exit(1)

        # Parse agent config if provided
        if agent_config:
            agent_cfg: dict[str, str] = {}
            for kv in agent_config:
                if "=" not in kv:
                    click.echo(
                        f"Error: Invalid agent config format '{kv}'. Expected key=value", err=True
                    )
                    sys.exit(1)
                key, value = kv.split("=", 1)
                agent_cfg[key] = value
            request_body["agent_config"] = agent_cfg

        try:
            async with httpx.AsyncClient() as client:
                # Send request body only if we have agent settings to change
                if request_body:
                    response = await client.post(api_url, json=request_body)
                else:
                    response = await client.post(api_url)
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
            agent_str = f" with agent {result.get('agent_type')}" if agent else ""
            click.echo(f"Resumed run {run_id}{agent_str}")
            click.echo(f"Status: {result.get('status')}")

    asyncio.run(_resume())


@runs.command("cancel")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def cancel_run(ctx: click.Context, run_id: str, url: str) -> None:
    """Cancel a run (ACTIVE/PAUSED -> FAILED)."""

    async def _cancel() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/cancel"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url)
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
            click.echo(f"Cancelled run {run_id}")
            click.echo(f"Status: {result.get('status')}")

    asyncio.run(_cancel())


@runs.command("status")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def status_run(ctx: click.Context, run_id: str, url: str) -> None:
    """Show run status and details."""

    async def _status() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}"

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
            # Human-readable format
            click.echo(f"Run: {result.get('id')}")
            click.echo(f"Status: {result.get('status')}")
            click.echo(f"Repository: {result.get('repo_name')}")
            if result.get("routine_id"):
                click.echo(f"Routine: {result.get('routine_id')}")
            if result.get("agent_type"):
                click.echo(f"Agent: {result.get('agent_type')}")

            # Show step progress
            steps = result.get("steps", [])
            current_step_idx = result.get("current_step_index", 0)
            click.echo(f"\nSteps ({current_step_idx + 1}/{len(steps)}):")
            for i, step in enumerate(steps):
                status_icon = "✓" if step.get("completed") else "○"
                current_marker = "→" if i == current_step_idx else " "
                click.echo(f"  {current_marker} {status_icon} {step.get('title', 'Untitled')}")

                # Show task status
                tasks = step.get("tasks", [])
                for task in tasks:
                    task_status = task.get("status")
                    task_title = task.get("title", "Untitled")
                    click.echo(f"       - {task_title}: {task_status}")

            # Show timestamps
            click.echo(f"\nCreated: {result.get('created_at')}")
            if result.get("started_at"):
                click.echo(f"Started: {result.get('started_at')}")
            if result.get("completed_at"):
                click.echo(f"Completed: {result.get('completed_at')}")

            # Show token usage if any
            total_tokens = (
                result.get("total_tokens_read", 0)
                + result.get("total_tokens_write", 0)
                + result.get("total_tokens_cache", 0)
            )
            if total_tokens > 0:
                click.echo(f"\nTokens used: {total_tokens:,}")
                total_actions = result.get("total_num_actions", 0)
                if total_actions > 0:
                    click.echo(f"Tool calls: {total_actions:,}")
                total_duration = result.get("total_duration_ms", 0)
                if total_duration > 0:
                    click.echo(f"Duration: {total_duration / 1000:.0f}s")
                if result.get("estimated_cost_usd"):
                    click.echo(f"Estimated cost: ${result.get('estimated_cost_usd'):.4f}")

    asyncio.run(_status())


@runs.command("branch-status")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def branch_status(ctx: click.Context, run_id: str, url: str) -> None:
    """Show branch status for a run (behind/ahead, merge-ability)."""

    async def _branch_status() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/branch-status"

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
            click.echo(f"Branch: {result.get('run_branch')}")
            click.echo(f"Source: {result.get('source_branch')}")
            click.echo(f"Behind: {result.get('behind_count')} commits")
            click.echo(f"Ahead:  {result.get('ahead_count')} commits")
            if result.get("has_conflicts"):
                click.echo("Merge:  CONFLICTS detected")
            elif result.get("can_merge_cleanly"):
                click.echo("Merge:  Clean merge possible")

    asyncio.run(_branch_status())


@runs.command("back-merge")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def back_merge_cmd(ctx: click.Context, run_id: str, url: str) -> None:
    """Pull source branch updates into run branch."""

    async def _back_merge() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/back-merge"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url)
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
            click.echo(f"Back-merge complete: {result.get('message')}")
            click.echo(f"Commit: {result.get('merge_commit')}")

    asyncio.run(_back_merge())


@runs.command("merge-back")
@click.argument("run_id")
@click.option(
    "--strategy", type=click.Choice(["squash", "merge"]), default=None, help="Merge strategy"
)
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def merge_back_cmd(ctx: click.Context, run_id: str, strategy: str | None, url: str) -> None:
    """Merge run branch back into source branch."""

    async def _merge_back() -> None:
        as_json = ctx.obj["json"]
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/merge-back"

        request_body: dict[str, Any] = {}
        if strategy:
            request_body["strategy"] = strategy

        try:
            async with httpx.AsyncClient() as client:
                if request_body:
                    response = await client.post(api_url, json=request_body)
                else:
                    response = await client.post(api_url)
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
            click.echo(f"Merge-back complete: {result.get('message')}")
            click.echo(f"Strategy: {result.get('strategy')}")
            click.echo(f"Commit: {result.get('merge_commit')}")

    asyncio.run(_merge_back())
