"""CLI subprocess agent.

Spawns a CLI tool (e.g., claude, codex) as a subprocess, sends the prompt
to stdin, reads output from stdout, and integrates the Nudger for stuck detection.

When ``api_base_url`` is set on the ExecutionContext, the prompt is enriched
with callback instructions (REST or MCP) so the subprocess can call back to
the orchestrator.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
from orchestrator.agents.types import (
    AgentInfo,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType


class _DefaultTimeProvider:
    """Default time provider using UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class CLIAgent:
    """Agent that runs CLI tools as a subprocess.

    Sends the prompt to stdin and reads output from stdout.
    Integrates Nudger for stuck detection: if no output for a configured
    duration, the agent is nudged via stdin. After max nudges, it is killed.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        model: str | None = None,
        callback_channel: str = "rest",
        stdin_mode: str = "close",
        nudger_config: NudgerConfig | None = None,
        time_provider: TimeProvider | None = None,
    ) -> None:
        self._command = command
        base_args = args or []
        if model is not None:
            base_args = ["--model", model, *base_args]
        self._args = base_args
        self._model = model
        self._callback_channel = callback_channel
        self._stdin_mode = stdin_mode
        self._nudger_config = nudger_config or NudgerConfig()
        self._time_provider = time_provider or _DefaultTimeProvider()
        self._cancelled = False
        self._process: asyncio.subprocess.Process | None = None

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            agent_type=AgentType.CLI_SUBPROCESS,
            name=self._command,
        )

    @staticmethod
    def build_prompt(
        prompt: str,
        context: ExecutionContext,
        callback_channel: str = "rest",
    ) -> str:
        """Enrich the prompt with callback instructions when api_base_url is set.

        Args:
            prompt: The original prompt text.
            context: Execution context with run/task IDs and optional API base URL.
            callback_channel: ``"rest"`` for REST API instructions, ``"mcp"``
                for MCP SSE connection instructions.
        """
        if context.api_base_url is None:
            return prompt

        base = context.api_base_url.rstrip("/")

        if callback_channel == "mcp":
            api_section = (
                f"\n\n## Orchestrator MCP Server\n"
                f"Connect to the MCP server at: {base}/mcp/sse\n"
                f"Run ID: {context.run_id}, Task ID: {context.task_id}\n\n"
                f"Available MCP tools:\n"
                f"- orchestrator_get_requirements(run_id, task_id)"
                f" → Get checklist items\n"
                f"- orchestrator_update_checklist(run_id, task_id, req_id, status, note?)"
                f" → Mark requirement done/blocked\n"
                f"- orchestrator_submit(run_id, task_id)"
                f" → Submit task for verification"
            )
        else:
            api_section = (
                f"\n\n## Orchestrator REST API\n"
                f"Base URL: {base}\n"
                f"Run ID: {context.run_id}, Task ID: {context.task_id}\n\n"
                f"PATCH {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"/checklist/{{req_id}}  → Mark requirement done/blocked\n"
                f"POST  {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"/submit               → Submit task for verification\n"
                f"GET   {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"                      → Check current checklist status"
            )
        return prompt + api_section

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
    ) -> ExecutionResult:
        """Execute the CLI tool with the given context."""
        path = shutil.which(self._command)
        if path is None:
            raise AgentNotAvailableError(
                "cli_subprocess",
                f"{self._command} not found in PATH",
            )

        if self._cancelled:
            raise AgentCancelledError("cli_subprocess")

        cmd = [path, *self._args]
        nudger = Nudger(self._nudger_config, self._time_provider)
        enriched_prompt = self.build_prompt(
            context.prompt,
            context,
            self._callback_channel,
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=context.working_dir,
            )

            # Send prompt to stdin
            if self._process.stdin is not None:
                self._process.stdin.write(enriched_prompt.encode())
                self._process.stdin.write(b"\n")
                await self._process.stdin.drain()
                if self._stdin_mode == "close":
                    self._process.stdin.close()

            # Read output with periodic nudge checks
            output_lines: list[str] = []
            while True:
                if self._cancelled:
                    self._process.terminate()
                    raise AgentCancelledError("cli_subprocess")

                try:
                    if self._process.stdout is None:
                        break
                    line_bytes = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=5.0,
                    )
                    if not line_bytes:
                        break  # EOF

                    line = line_bytes.decode(errors="replace").rstrip()
                    output_lines.append(line)
                    nudger.record_output()

                except TimeoutError:
                    # Check nudger
                    action = nudger.check()
                    if action == NudgeAction.KILL:
                        self._process.terminate()
                        raise AgentExecutionError(
                            "cli_subprocess",
                            f"Agent stuck after {nudger.nudge_count} nudges, killed",
                        )
                    elif action == NudgeAction.NUDGE:
                        message = nudger.record_nudge()
                        output_lines.append(f"[nudge #{nudger.nudge_count}] {message}")
                        # Deliver nudge to stdin if still open
                        if self._stdin_mode == "open" and self._process.stdin is not None:
                            try:
                                self._process.stdin.write((message + "\n").encode())
                                await self._process.stdin.drain()
                            except (BrokenPipeError, ConnectionResetError):
                                pass  # Process already exited

            await self._process.wait()

            return ExecutionResult(
                success=self._process.returncode == 0,
                error=(
                    f"Process exited with code {self._process.returncode}"
                    if self._process.returncode != 0
                    else None
                ),
                metrics=ExecutionMetrics(),
            )

        except AgentCancelledError:
            raise
        except AgentExecutionError:
            raise
        except AgentNotAvailableError:
            raise
        except Exception as exc:
            raise AgentExecutionError("cli_subprocess", str(exc)) from exc
        finally:
            self._process = None

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._process is not None:
            self._process.terminate()
