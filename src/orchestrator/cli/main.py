"""Main CLI entry point."""

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
def serve(host: str, port: int, reload: bool, log_dir: Path | None, supervisor: bool) -> None:
    """Start the local FastAPI backend with durable crash evidence."""
    root = Path(__file__).resolve().parents[3]
    reload_dirs = [str(root / "src"), str(root / "scripts")] if reload else None
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
    if reload:
        command.append("--reload")
        for reload_dir in reload_dirs or []:
            command.extend(("--reload-dir", reload_dir))

    resolved_log_dir = log_dir or root / ".orchestrator" / "logs" / "server"
    exit_code = run_server_supervisor(
        SupervisorConfig(
            command=tuple(command),
            cwd=root,
            log_root=resolved_log_dir,
        )
    )
    if exit_code:
        raise click.exceptions.Exit(exit_code)


cli.add_command(serve)
cli.add_command(runs)
cli.add_command(routines)
cli.add_command(agents)
cli.add_command(repos)
cli.add_command(db)


if __name__ == "__main__":
    cli()
