"""Main CLI entry point."""

import json as json_lib
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from orchestrator.cli.agents import agents
from orchestrator.cli.db import db
from orchestrator.cli.repos import repos
from orchestrator.cli.routines import routines
from orchestrator.cli.runs import runs

# Load .env file from current directory (for OPENAI_API_KEY, etc.)
# This ensures environment variables are available when running via `orchestrator` CLI
load_dotenv()


@click.group()
@click.option("--db", default="orchestrator.db", help="Database path")
@click.option("--json", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx: click.Context, db: str, json: bool) -> None:
    """Orchestrator - LLM Agent Workflow Management."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["json"] = json


@click.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind")
@click.option("--port", default=8000, show_default=True, help="Port to bind")
@click.option("--reload/--no-reload", default=False, help="Restart when backend files change")
@click.option(
    "--log-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Supervisor log root (default: .orchestrator/logs/server)",
)
@click.option(
    "--supervisor/--no-supervisor",
    default=True,
    help="Use the durable external process supervisor",
)
@click.option("--health-path", default="/health", show_default=True)
@click.option("--health-interval", default=1.0, type=click.FloatRange(min=0.05))
@click.option("--health-timeout", default=1.0, type=click.FloatRange(min=0.05))
@click.option("--health-failures", default=5, type=click.IntRange(min=1))
@click.option("--health-startup-grace", default=30.0, type=click.FloatRange(min=0.0))
def serve(
    host: str,
    port: int,
    reload: bool,
    log_dir: Path | None,
    supervisor: bool,
    health_path: str,
    health_interval: float,
    health_timeout: float,
    health_failures: int,
    health_startup_grace: float,
) -> None:
    """Start the local FastAPI backend with durable crash evidence."""
    root = Path(__file__).resolve().parents[3]
    reload_dirs = [str(root / "src"), str(root / "scripts")] if reload else None
    if reload and supervisor:
        raise click.UsageError(
            "--reload has its own restart owner and requires --no-supervisor; "
            "the supervised production-shaped path never uses a reloader"
        )
    if not supervisor:
        import uvicorn

        os.environ.setdefault("PYTHONUNBUFFERED", "1")
        os.environ.setdefault("PYTHONFAULTHANDLER", "1")
        os.environ.setdefault("LOG_AUTO_CONFIG", "false")
        uvicorn.run(
            "scripts.serve:app",
            host=host,
            port=port,
            reload=reload,
            reload_dirs=reload_dirs,
            app_dir=str(root),
        )
        return

    from orchestrator.cli.server_supervisor import SupervisorConfig, run_server_supervisor

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "scripts.serve:app",
        "--host",
        host,
        "--port",
        str(port),
        "--app-dir",
        str(root),
    ]
    resolved_log_dir = log_dir or root / ".orchestrator" / "logs" / "server"
    health_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    normalized_health_path = health_path if health_path.startswith("/") else f"/{health_path}"
    exit_code = run_server_supervisor(
        SupervisorConfig(
            command=tuple(command),
            cwd=root,
            log_root=resolved_log_dir,
            healthcheck_url=f"http://{health_host}:{port}{normalized_health_path}",
            healthcheck_interval_seconds=health_interval,
            healthcheck_timeout_seconds=health_timeout,
            healthcheck_failure_threshold=health_failures,
            healthcheck_startup_grace_seconds=health_startup_grace,
        )
    )
    if exit_code:
        raise click.exceptions.Exit(exit_code)


@click.command("server-status")
@click.option(
    "--log-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Supervisor log root (default: .orchestrator/logs/server)",
)
@click.pass_context
def server_status(ctx: click.Context, log_dir: Path | None) -> None:
    """Read bounded supervisor state after verifying the recorded owner identity."""
    from orchestrator.cli.server_supervisor import inspect_supervisor_identity, read_state

    root = Path(__file__).resolve().parents[3]
    resolved_log_dir = log_dir or root / ".orchestrator" / "logs" / "server"
    state = read_state(resolved_log_dir / "supervisor-state.json")
    if state is None:
        raise click.ClickException(f"no valid supervisor state at {resolved_log_dir}")
    supervisor_identity = inspect_supervisor_identity(state)
    if state.status in ("running", "stopping") and not supervisor_identity.identity_verified:
        state = state.model_copy(
            update={
                "status": "abrupt_supervisor_loss",
                "stop_reason": "abrupt_supervisor_loss",
                "serving_process_health": "unknown",
                "collector_health": "unknown",
            }
        )
    readback = {
        "session_id": state.session_id[:256],
        "status": state.status,
        "supervisor_pid": state.supervisor_pid,
        "supervisor_recorded_process_group_id": (supervisor_identity.recorded_process_group_id),
        "supervisor_observed_process_group_id": (supervisor_identity.observed_process_group_id),
        "supervisor_identity_verified": supervisor_identity.identity_verified,
        "supervisor_liveness": supervisor_identity.liveness,
        "supervisor_identity_detail": supervisor_identity.detail[:512],
        "child_pid": state.child_pid,
        "child_process_group_id": state.child_process_group_id,
        "serving_process_health": state.serving_process_health,
        "collector_pid": state.collector_pid,
        "collector_process_group_id": state.collector_process_group_id,
        "collector_health": state.collector_health,
        "attempt": state.attempt,
        "consecutive_failures": state.consecutive_failures,
        "consecutive_health_failures": state.consecutive_health_failures,
        "last_health_check_at": (
            state.last_health_check_at.isoformat()
            if state.last_health_check_at is not None
            else None
        ),
        "updated_at": state.updated_at.isoformat(),
        "stop_reason": state.stop_reason[:512] if state.stop_reason is not None else None,
    }
    if bool(ctx.obj.get("json")):
        click.echo(json_lib.dumps(readback, separators=(",", ":"), sort_keys=True))
        return
    for key, value in readback.items():
        click.echo(f"{key}: {value}")


def _bounded_crash_barrier_readback(state: object) -> dict[str, object]:
    """Return operator facts without disclosing release capabilities."""
    from orchestrator.graph_runtime import CrashBarrierPlanState, CrashBarrierState

    if isinstance(state, CrashBarrierState):
        return {
            "schema_version": 1,
            "barrier_id": state.barrier_id,
            "run_id": state.run_id[:256],
            "execution_id": state.execution_id[:256],
            "point": state.point,
            "status": state.status,
            "owner_pid": state.owner_pid,
            "owner_create_time": state.owner_create_time,
            "reached_at": state.reached_at.isoformat(),
            "released_at": state.released_at.isoformat() if state.released_at else None,
        }
    if not isinstance(state, CrashBarrierPlanState):
        return {"status": "disabled"}
    return {
        "schema_version": 2,
        "barrier_id": state.barrier_id,
        "run_id": state.run_id[:256],
        "nonce": state.nonce[:128],
        "config_hash": state.config_hash,
        "target": state.target.model_dump(mode="json"),
        "slots": [
            {
                "slot": slot.slot,
                "point": slot.point,
                "status": slot.status,
                "node_id": slot.node_id[:256] if slot.node_id else None,
                "execution_id": slot.execution_id[:256] if slot.execution_id else None,
                "lease_id": slot.lease_id[:256] if slot.lease_id else None,
                "lease_generation": slot.lease_generation,
                "owner_pid": slot.owner_pid,
                "owner_create_time": slot.owner_create_time,
                "reached_at": slot.reached_at.isoformat() if slot.reached_at else None,
                "released_at": slot.released_at.isoformat() if slot.released_at else None,
            }
            for slot in state.slots
        ],
    }


@click.command("crash-barrier-status")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Crash-barrier state directory (default: .orchestrator/state/crash-barriers)",
)
@click.pass_context
def crash_barrier_status(ctx: click.Context, state_dir: Path | None) -> None:
    """Read the bounded configured crash-drill state."""
    from orchestrator.graph_runtime import crash_barrier_from_environment

    root = Path(__file__).resolve().parents[3]
    barrier = crash_barrier_from_environment(
        os.environ,
        state_dir=state_dir or root / ".orchestrator" / "state" / "crash-barriers",
    )
    readback = _bounded_crash_barrier_readback(barrier.read_status())
    if bool(ctx.obj.get("json")):
        click.echo(json_lib.dumps(readback, separators=(",", ":"), sort_keys=True))
        return
    for key, value in readback.items():
        click.echo(f"{key}: {value}")


@click.command("crash-barrier-crash")
@click.option("--slot", required=True, type=click.IntRange(min=1, max=2))
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Crash-barrier state directory (default: .orchestrator/state/crash-barriers)",
)
@click.option(
    "--log-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Supervisor log root (default: .orchestrator/logs/server)",
)
@click.pass_context
def crash_barrier_crash(
    ctx: click.Context,
    slot: int,
    state_dir: Path | None,
    log_dir: Path | None,
) -> None:
    """Crash only a reached slot owned by the verified serving child."""
    from orchestrator.cli.server_supervisor import crash_verified_serving_child, read_state
    from orchestrator.graph_runtime import (
        CrashBarrierPlanState,
        CrashBarrierState,
        crash_barrier_from_environment,
    )

    root = Path(__file__).resolve().parents[3]
    barrier = crash_barrier_from_environment(
        os.environ,
        state_dir=state_dir or root / ".orchestrator" / "state" / "crash-barriers",
    )
    barrier_state = barrier.read_status()
    if isinstance(barrier_state, CrashBarrierState):
        if slot != 1 or barrier_state.status != "reached":
            raise click.ClickException("the requested exact-execution barrier is not reached")
        owner_pid = barrier_state.owner_pid
        owner_create_time = barrier_state.owner_create_time
    elif isinstance(barrier_state, CrashBarrierPlanState):
        selected = barrier_state.slots[slot - 1]
        if (
            selected.status != "reached"
            or selected.owner_pid is None
            or selected.owner_create_time is None
        ):
            raise click.ClickException(f"crash barrier slot {slot} is not reached")
        owner_pid = selected.owner_pid
        owner_create_time = selected.owner_create_time
    else:
        raise click.ClickException("crash barrier is disabled")
    resolved_log_dir = log_dir or root / ".orchestrator" / "logs" / "server"
    supervisor_state = read_state(resolved_log_dir / "supervisor-state.json")
    if supervisor_state is None:
        raise click.ClickException("official supervisor state is missing or malformed")
    result = crash_verified_serving_child(
        supervisor_state,
        reached_owner_pid=owner_pid,
        reached_owner_create_time=owner_create_time,
    )
    if result.outcome != "signaled":
        raise click.ClickException(result.detail)
    readback = result.model_dump(mode="json")
    if bool(ctx.obj.get("json")):
        click.echo(json_lib.dumps(readback, separators=(",", ":"), sort_keys=True))
        return
    for key, value in readback.items():
        click.echo(f"{key}: {value}")


cli.add_command(serve)
cli.add_command(server_status)
cli.add_command(crash_barrier_status)
cli.add_command(crash_barrier_crash)
cli.add_command(runs)
cli.add_command(routines)
cli.add_command(agents)
cli.add_command(repos)
cli.add_command(db)


if __name__ == "__main__":
    cli()
