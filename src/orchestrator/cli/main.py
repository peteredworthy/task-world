"""Main CLI entry point."""

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
def serve(host: str, port: int, reload: bool) -> None:
    """Start the local FastAPI backend."""
    import uvicorn

    root = Path(__file__).resolve().parents[3]
    reload_dirs = [str(root / "src"), str(root / "scripts")] if reload else None
    uvicorn.run(
        "scripts.serve:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs,
        app_dir=str(root),
    )


cli.add_command(serve)
cli.add_command(runs)
cli.add_command(routines)
cli.add_command(agents)
cli.add_command(repos)
cli.add_command(db)


if __name__ == "__main__":
    cli()
