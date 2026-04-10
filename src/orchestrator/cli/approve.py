"""CLI command for handling pending user actions."""

import asyncio
import json
import sys
from typing import Any

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


@click.command("approve")
@click.argument("run_id")
@click.option("--url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def approve_command(ctx: click.Context, run_id: str, url: str) -> None:
    """Handle pending user actions for a run.

    Interactively answers clarification questions and approves/rejects
    tasks awaiting human input.
    """

    async def _approve() -> None:
        as_json = ctx.obj["json"]
        console = Console()

        # Get pending actions
        api_url = f"{url.rstrip('/')}/api/runs/{run_id}/pending-actions"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(api_url)
                response.raise_for_status()
                pending_actions = response.json()

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

        if not pending_actions:
            if as_json:
                click.echo(json.dumps({"message": "No pending actions"}))
            else:
                console.print("[green]No pending actions for this run.[/green]")
            return

        if as_json:
            # In JSON mode, just output the actions
            click.echo(json.dumps(pending_actions, indent=2))
            return

        # Interactive mode
        console.print(
            f"\n[bold blue]Found {len(pending_actions)} pending action(s) for run {run_id}[/bold blue]\n"
        )

        for i, action in enumerate(pending_actions, 1):
            action_type = action.get("action_type")
            task_id = action.get("task_id")
            step_id = action.get("step_id")

            console.print(f"\n[bold]Action {i}/{len(pending_actions)}[/bold]")
            console.print(f"Task: {task_id}")
            console.print(f"Step: {step_id}")
            console.print(f"Type: {action_type}\n")

            if action_type == "clarification":
                await _handle_clarification(console, client, url, run_id, action)
            elif action_type == "approval":
                await _handle_approval(console, client, url, run_id, action)
            else:
                console.print(f"[yellow]Unknown action type: {action_type}[/yellow]")

        console.print("\n[green]All pending actions processed![/green]\n")

    async def _handle_clarification(
        console: Console,
        client: httpx.AsyncClient,
        url: str,
        run_id: str,
        action: dict[str, Any],
    ) -> None:
        """Handle a clarification request."""
        task_id = action.get("task_id")
        clarif_req = action.get("clarification_request")

        if not clarif_req:
            console.print("[yellow]No clarification data available[/yellow]")
            return

        request_id = clarif_req.get("id")
        questions = clarif_req.get("questions", [])

        console.print(
            Panel(f"[bold cyan]Clarification Request[/bold cyan]\n\n{len(questions)} question(s)")
        )

        # Collect answers
        answers: list[dict[str, str | None]] = []
        for j, question in enumerate(questions, 1):
            q_id = question.get("id")
            q_text = question.get("question")
            q_context = question.get("context", "")
            q_options = question.get("options", [])

            console.print(f"\n[bold]Question {j}/{len(questions)}:[/bold]")
            console.print(f"{q_text}")
            if q_context:
                console.print(f"[dim]{q_context}[/dim]")

            # Show options if available
            if q_options:
                console.print("\nOptions:")
                table = Table(show_header=False, box=None)
                for idx, opt in enumerate(q_options, 1):
                    table.add_row(f"  {idx}.", opt)
                console.print(table)

                # Get selection
                while True:
                    choice = Prompt.ask(
                        "\nSelect option number (or type custom answer)",
                        default="1",
                    )
                    # Try parsing as number
                    try:
                        choice_idx = int(choice) - 1
                        if 0 <= choice_idx < len(q_options):
                            selected_option = q_options[choice_idx]
                            answers.append(
                                {
                                    "question_id": q_id,
                                    "selected_option": selected_option,
                                    "free_text": None,
                                }
                            )
                            console.print(f"[green]Selected: {selected_option}[/green]")
                            break
                        else:
                            console.print("[red]Invalid option number[/red]")
                    except ValueError:
                        # Free text answer
                        answers.append(
                            {
                                "question_id": q_id,
                                "selected_option": None,
                                "free_text": choice,
                            }
                        )
                        console.print(f"[green]Answer: {choice}[/green]")
                        break
            else:
                # Free text only
                answer_text = Prompt.ask("\nYour answer")
                answers.append(
                    {
                        "question_id": q_id,
                        "selected_option": None,
                        "free_text": answer_text,
                    }
                )

        # Submit answers
        console.print("\n[yellow]Submitting answers...[/yellow]")
        submit_url = f"{url.rstrip('/')}/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond"

        try:
            response = await client.post(submit_url, json={"answers": answers})
            response.raise_for_status()
            result = response.json()
            console.print("[green]✓ Answers submitted successfully![/green]")
            console.print(f"Task transitioned to: {result.get('new_status', 'unknown')}")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error submitting answers: {e}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    async def _handle_approval(
        console: Console,
        client: httpx.AsyncClient,
        url: str,
        run_id: str,
        action: dict[str, Any],
    ) -> None:
        """Handle an approval request."""
        step_id = action.get("step_id")
        summary_artifact = action.get("summary_artifact", "No summary available")
        approval_prompt = action.get("approval_prompt", "")

        console.print(Panel("[bold cyan]Approval Request[/bold cyan]"))

        # Show summary
        console.print("\n[bold]Summary:[/bold]")
        console.print(Panel(summary_artifact, border_style="dim"))

        if approval_prompt:
            console.print("\n[bold]Approval Prompt:[/bold]")
            console.print(approval_prompt)

        # Ask for approval
        console.print()
        approved = Confirm.ask("Approve this step?", default=True)

        # Get user name
        approved_by = Prompt.ask("Your name", default="user")

        # Optional comment
        comment = None
        if Confirm.ask("Add a comment?", default=False):
            comment = Prompt.ask("Comment")

        # Submit approval
        console.print("\n[yellow]Submitting approval...[/yellow]")
        submit_url = f"{url.rstrip('/')}/api/runs/{run_id}/steps/{step_id}/approve"

        try:
            response = await client.post(
                submit_url,
                json={
                    "approved_by": approved_by,
                    "comment": comment,
                },
            )
            response.raise_for_status()
            result = response.json()

            if approved:
                console.print("[green]✓ Step approved successfully![/green]")
            else:
                console.print("[yellow]Step approval submitted[/yellow]")

            console.print(
                f"Approved by: {result.get('human_approval', {}).get('approved_by', 'unknown')}"
            )
            if comment:
                console.print(f"Comment: {comment}")

        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error submitting approval: {e}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    asyncio.run(_approve())
