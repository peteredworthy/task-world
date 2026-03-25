"""Agent management commands."""

import asyncio
import json

import click

from orchestrator.runners import ToolDetector


@click.group()
def agents() -> None:
    """Manage agents."""
    pass


@agents.command("detect")
@click.pass_context
def detect_agents(ctx: click.Context) -> None:
    """Detect available agents."""

    async def _detect() -> None:
        as_json = ctx.obj["json"]

        detector = ToolDetector()
        agent_options = await detector.detect_all()

        if as_json:
            result = [
                {
                    "name": option.name,
                    "agent_type": option.agent_type,
                    "available": option.available,
                    "detail": option.detail,
                    "install_hint": option.install_hint,
                }
                for option in agent_options
            ]
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Available agents:")
            for option in agent_options:
                status = "✓" if option.available else "✗"
                click.echo(f"\n  {status} {option.name}")
                click.echo(f"    Type: {option.agent_type}")
                click.echo(f"    Status: {option.detail}")
                if not option.available and option.install_hint:
                    click.echo(f"    Install: {option.install_hint}")

    asyncio.run(_detect())


@agents.command("list")
@click.pass_context
def list_agents(ctx: click.Context) -> None:
    """List available agent types (alias for detect)."""
    ctx.invoke(detect_agents)
