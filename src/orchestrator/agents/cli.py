"""CLI subprocess agent.

Spawns a CLI tool (e.g., claude, codex) as a subprocess, sends the prompt
to stdin, reads output from stdout, and integrates the Nudger for stuck detection.

When ``api_base_url`` is set on the ExecutionContext, the prompt is enriched
with callback instructions (REST or MCP) so the subprocess can call back to
the orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType

if TYPE_CHECKING:
    from orchestrator.agents.monitor import AgentMonitor
    from orchestrator.agents.parsers.base import StreamParser

logger = logging.getLogger(__name__)


class _DefaultTimeProvider:
    """Default time provider using UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class CLIAgent:
    """Agent that runs CLI tools as a subprocess.

    Sends the prompt to stdin and reads output from stdout.
    Integrates Nudger for stuck detection: if no output for a configured
    duration, the agent is nudged via stdin. After max nudges, it is killed.

    Configuration:
        To use global nudger settings from ~/.orchestrator/config.yaml:

            from orchestrator.config.global_config import load_global_config

            global_cfg = load_global_config()
            agent = CLIAgent(
                command="claude",
                nudger_config=global_cfg.nudger.to_agent_config(),
            )
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
        poll_interval: float = 5.0,
        parser: StreamParser | None = None,
        agent_monitor: AgentMonitor | None = None,
        run_id: str | None = None,
    ) -> None:
        self._command = command
        base_args = args or []
        if model is not None:
            base_args = ["--model", model, *base_args]
        self._args = base_args
        self._callback_channel = callback_channel
        self._stdin_mode = stdin_mode
        self._nudger_config = nudger_config or NudgerConfig()
        self._time_provider = time_provider or _DefaultTimeProvider()
        self._poll_interval = poll_interval
        self._cancelled = False
        self._process: asyncio.subprocess.Process | None = None
        self._parser = parser
        self._agent_monitor = agent_monitor
        self._run_id = run_id

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
        phase: str = "building",
    ) -> str:
        """Enrich the prompt with callback instructions when api_base_url is set.

        Args:
            prompt: The original prompt text.
            context: Execution context with run/task IDs and optional API base URL.
            callback_channel: ``"rest"`` for REST API instructions, ``"mcp"``
                for MCP SSE connection instructions.
            phase: ``"building"`` for builder instructions, ``"verifying"``
                for verifier instructions.
        """
        if context.api_base_url is None:
            return prompt

        base = context.api_base_url.rstrip("/")

        if phase == "verifying":
            return CLIAgent._build_verifier_prompt(prompt, context, base, callback_channel)

        workflow_section = (
            f"\n\n## Orchestrator Integration\n"
            f"You are connected to an orchestrator that tracks your progress.\n"
            f"Run ID: {context.run_id}, Task ID: {context.task_id}\n\n"
            f"### Required Workflow\n"
            f"1. Implement each requirement listed above.\n"
            f"2. After completing each requirement, report it as 'done' "
            f"using the requirement ID exactly as listed "
            f"(for numeric IDs, R1/R-01/1 are all accepted).\n"
            f"3. Once ALL requirements are addressed, submit your work.\n"
            f"4. All CRITICAL requirements must be 'done' before submission succeeds.\n"
            f"   Valid statuses: done, blocked, not_applicable\n"
        )

        if callback_channel == "mcp":
            api_section = (
                f"{workflow_section}\n"
                f"### MCP Server Connection\n"
                f"Connect to: {base}/mcp/sse\n\n"
                f"### Available MCP Tools\n"
                f"- **orchestrator_get_requirements**(run_id, task_id)\n"
                f"  Returns all checklist items with current status and grades.\n"
                f"- **orchestrator_update_checklist**(run_id, task_id, req_id, status, note?)\n"
                f"  Mark a requirement as done/blocked/not_applicable.\n"
                f"  Example: orchestrator_update_checklist('{context.run_id}', "
                f"'{context.task_id}', 'R1', 'done')\n"
                f"- **orchestrator_request_clarification**(run_id, task_id, questions)\n"
                f"  Request clarification from the human. Task will pause until answered.\n"
                f"  Example: orchestrator_request_clarification('{context.run_id}', "
                f'\'{context.task_id}\', [{{"id": "Q1", "question": "...", "required": true}}])\n'
                f"- **orchestrator_submit**(run_id, task_id)\n"
                f"  Submit your work for verification. "
                f"All CRITICAL items must be 'done' first."
            )
        else:
            api_section = (
                f"{workflow_section}\n"
                f"### REST API Endpoints\n"
                f"Base URL: {base}\n\n"
                f"**Get current checklist status:**\n"
                f"  GET {base}/api/runs/{context.run_id}/tasks/{context.task_id}\n\n"
                f"**Mark a requirement done:**\n"
                f"  PATCH {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"/checklist/{{req_id}}\n"
                f'  Body: {{"status": "done"}}\n'
                f'  Example: PATCH .../checklist/R1 with body {{"status": "done"}}\n'
                f"  (For numeric IDs, R1/R-01/1 are accepted.)\n\n"
                f"**Submit for verification (after all requirements addressed):**\n"
                f"  POST {base}/api/runs/{context.run_id}/tasks/{context.task_id}/submit"
            )

        if context.auth_token:
            if callback_channel == "mcp":
                api_section += (
                    f"\n\n## Authentication\n"
                    f"Include the following header when connecting to the MCP server:\n"
                    f"Authorization: Bearer {context.auth_token}"
                )
            else:
                api_section += (
                    f"\n\n## Authentication\n"
                    f"Include the following header with all API requests:\n"
                    f"Authorization: Bearer {context.auth_token}"
                )

        return prompt + api_section

    @staticmethod
    def _build_verifier_prompt(
        prompt: str,
        context: ExecutionContext,
        base: str,
        callback_channel: str,
    ) -> str:
        """Build verifier-specific callback instructions."""
        workflow_section = (
            f"\n\n## Orchestrator Integration (Verifier)\n"
            f"You are connected to an orchestrator. Your role is to VERIFY the builder's work.\n"
            f"Run ID: {context.run_id}, Task ID: {context.task_id}\n\n"
            f"### Required Workflow\n"
            f"1. Review the code changes made by the builder.\n"
            f"2. Grade EVERY requirement using the grading tool.\n"
            f"3. After grading all requirements, complete the verification.\n"
            f"4. Grades: A (excellent), B (good), C (adequate), D (poor), F (failing)\n"
        )

        if callback_channel == "mcp":
            api_section = (
                f"{workflow_section}\n"
                f"### MCP Server Connection\n"
                f"Connect to: {base}/mcp/sse\n\n"
                f"### Available MCP Tools\n"
                f"- **orchestrator_get_requirements**(run_id, task_id)\n"
                f"  Returns all checklist items with current status.\n"
                f"- **orchestrator_set_grade**(run_id, task_id, req_id, grade, grade_reason?)\n"
                f"  Set a grade on a requirement.\n"
                f"  Example: orchestrator_set_grade('{context.run_id}', "
                f"'{context.task_id}', 'R1', 'A', 'Well implemented')\n"
                f"- **orchestrator_submit**(run_id, task_id)\n"
                f"  Complete the verification after grading all requirements."
            )
        else:
            api_section = (
                f"{workflow_section}\n"
                f"### REST API Endpoints\n"
                f"Base URL: {base}\n\n"
                f"**Get current checklist status:**\n"
                f"  GET {base}/api/runs/{context.run_id}/tasks/{context.task_id}\n\n"
                f"**Set grade on a requirement:**\n"
                f"  PUT {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"/checklist/{{req_id}}/grade\n"
                f'  Body: {{"grade": "A", "grade_reason": "Well implemented"}}\n\n'
                f"**Complete verification (after grading all requirements):**\n"
                f"  POST {base}/api/runs/{context.run_id}/tasks/{context.task_id}"
                f"/complete-verification"
            )

        if context.auth_token:
            api_section += (
                f"\n\n## Authentication\n"
                f"Include the following header with all requests:\n"
                f"Authorization: Bearer {context.auth_token}"
            )

        return prompt + api_section

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
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
            # Build a clean environment for the child process.
            # Remove CLAUDECODE so that nested `claude` invocations don't
            # refuse to start with "cannot be launched inside another session".
            child_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=context.working_dir,
                env=child_env,
                limit=1024 * 1024,  # 1MB readline buffer for large JSON output
            )

            # Store PID for agent monitoring
            # This should be persisted to run.agent_config["pid"] by the caller
            # so that AgentMonitor can check process liveness
            agent_pid = self._process.pid

            # Notify caller that subprocess was created so metadata can be persisted
            if on_agent_metadata and agent_pid:
                try:
                    await on_agent_metadata({"pid": agent_pid})
                except Exception as e:
                    logger.warning(f"Failed to call on_agent_metadata callback: {e}")

            # Send prompt to stdin
            if self._process.stdin is not None:
                try:
                    self._process.stdin.write(enriched_prompt.encode())
                    self._process.stdin.write(b"\n")
                    await self._process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError, ConnectionError):
                    pass  # Process exited before we finished writing — that's fine
                if self._stdin_mode == "close":
                    self._process.stdin.close()

            # Read output with periodic nudge checks
            output_lines: list[str] = []
            batch_buffer: list[str] = []
            BATCH_SIZE = 20
            while True:
                if self._cancelled:
                    self._process.terminate()
                    raise AgentCancelledError("cli_subprocess")

                try:
                    if self._process.stdout is None:
                        break
                    line_bytes = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=self._poll_interval,
                    )
                    if not line_bytes:
                        break  # EOF

                    line = line_bytes.decode(errors="replace").rstrip()
                    output_lines.append(line)
                    batch_buffer.append(line)
                    if self._parser is not None:
                        self._parser.parse_line(line)
                    if len(batch_buffer) >= BATCH_SIZE and on_output:
                        await on_output(batch_buffer)
                        batch_buffer = []
                    nudger.record_output()

                except TimeoutError:
                    # Check nudger
                    action = nudger.check()
                    if action == NudgeAction.KILL:
                        self._process.terminate()
                        if batch_buffer and on_output:
                            await on_output(batch_buffer)
                        # Notify monitor that agent was killed due to being stuck
                        if self._agent_monitor and self._run_id:
                            try:
                                await self._agent_monitor.on_agent_died(
                                    run_id=self._run_id,
                                    agent_type=AgentType.CLI_SUBPROCESS,
                                    exit_code=None,
                                    reason=f"agent_stuck_killed_after_{nudger.nudge_count}_nudges",
                                )
                            except Exception as e:
                                logger.warning(f"Failed to notify monitor of stuck agent: {e}")
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

            if batch_buffer and on_output:
                await on_output(batch_buffer)
                batch_buffer = []

            await self._process.wait()

            success = self._process.returncode == 0

            # If process exited with non-zero code (failure), notify monitor
            if not success and self._agent_monitor and self._run_id:
                try:
                    await self._agent_monitor.on_agent_died(
                        run_id=self._run_id,
                        agent_type=AgentType.CLI_SUBPROCESS,
                        exit_code=self._process.returncode,
                        reason="agent_exit_failure",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify monitor of agent exit failure: {e}")

            # Finalize parser to get structured action log
            action_log = None
            final_output_lines = output_lines
            if self._parser is not None:
                action_log = self._parser.finalize()
                # Extract readable text from parsed entries so agent_output
                # remains useful even though stdout is NDJSON
                readable = self._parser.get_readable_text()
                if readable.strip():
                    final_output_lines = readable.split("\n")

            # If process completed successfully, submit for verification
            # This triggers the workflow to move from BUILDING to VERIFYING
            if success:
                await on_submit()

            return ExecutionResult(
                success=success,
                error=(
                    f"Process exited with code {self._process.returncode}"
                    if self._process.returncode != 0
                    else None
                ),
                metrics=ExecutionMetrics(),
                agent_metadata={"pid": agent_pid} if agent_pid else {},
                output_lines=final_output_lines,
                action_log=action_log,
            )

        except AgentCancelledError:
            raise
        except AgentExecutionError:
            raise
        except AgentNotAvailableError:
            raise
        except Exception as exc:
            # Check if process died unexpectedly and notify monitor
            if self._process and self._agent_monitor and self._run_id:
                try:
                    exit_code = self._process.returncode
                    await self._agent_monitor.on_agent_died(
                        run_id=self._run_id,
                        agent_type=AgentType.CLI_SUBPROCESS,
                        exit_code=exit_code,
                        reason="agent_execution_error",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify monitor of agent execution error: {e}")
            raise AgentExecutionError("cli_subprocess", str(exc)) from exc
        finally:
            self._process = None

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._process is not None:
            self._process.terminate()
