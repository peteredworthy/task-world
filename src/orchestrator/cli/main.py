"""Main CLI entry point."""

import click
from dotenv import load_dotenv

from orchestrator.cli.agents import agents
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


cli.add_command(runs)
cli.add_command(routines)
cli.add_command(agents)
cli.add_command(repos)


if __name__ == "__main__":
    cli()
