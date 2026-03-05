"""CLI subprocess agent.

Spawns a CLI tool (e.g., claude, codex) as a subprocess, sends the prompt
to stdin, reads output from stdout, and integrates the Nudger for stuck detection.

When ``api_base_url`` is set on the ExecutionContext, the prompt is enriched
with callback instructions (REST or MCP) so the subprocess can call back to
the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.agents.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    QuotaBucket,
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
        phase: str = "building",
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
        self._phase = phase
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
        # Git workflow instructions for builder phase — added to every CLI agent prompt
        # because the CLI agent is responsible for committing work before submitting.
        git_section = ""
        if phase == "building":
            git_section = (
                "\n\n## Git Workflow\n"
                "Before submitting, commit your changes to git:\n"
                "- Stage all relevant changes: `git add <files>`\n"
                "- Commit with a descriptive message: `git commit -m 'Description'`\n"
                "- Example: `git commit -m 'Implement authentication system with login and signup'`\n"
                "- ALWAYS use `git --no-pager` for git commands that produce output\n"
                "  (e.g. `git --no-pager diff`, `git --no-pager log`, `git --no-pager show`)\n"
                "- Commit conventions: use imperative mood, e.g. 'Add feature' not 'Added feature'\n"
            )

        if context.api_base_url is None:
            return prompt + git_section

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
                    "\n\n## Authentication\n"
                    "Include the following header when connecting to the MCP server:\n"
                    "Authorization: Bearer ${ORCHESTRATOR_AUTH_TOKEN}"
                )
            else:
                api_section += (
                    "\n\n## Authentication\n"
                    "Include the following header with all API requests:\n"
                    "Authorization: Bearer ${ORCHESTRATOR_AUTH_TOKEN}"
                )

        # Add step-level tool hints
        if context.available_tools:
            tools_section = (
                "\n\n## Step Tools\nThe following additional tools are available for this step:\n"
            )
            for tool_name in context.available_tools:
                tools_section += f"- {tool_name}\n"
            api_section += tools_section

        # Add external MCP server info
        if context.mcp_servers:
            mcp_section = "\n\n## External MCP Servers\nThe following external MCP servers are available for this step:\n"
            for mcp in context.mcp_servers:
                if mcp.url:
                    mcp_section += f"- **{mcp.name}**: {mcp.url}\n"
                elif mcp.command:
                    cmd_str = f"{mcp.command} {' '.join(mcp.args or [])}"
                    mcp_section += f"- **{mcp.name}**: (stdio) {cmd_str}\n"
            api_section += mcp_section

        return prompt + git_section + api_section

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
                "\n\n## Authentication\n"
                "Include the following header with all requests:\n"
                "Authorization: Bearer ${ORCHESTRATOR_AUTH_TOKEN}"
            )

        # Add step-level tool hints
        if context.available_tools:
            tools_section = (
                "\n\n## Step Tools\nThe following additional tools are available for this step:\n"
            )
            for tool_name in context.available_tools:
                tools_section += f"- {tool_name}\n"
            api_section += tools_section

        # Add external MCP server info
        if context.mcp_servers:
            mcp_section = "\n\n## External MCP Servers\nThe following external MCP servers are available for this step:\n"
            for mcp in context.mcp_servers:
                if mcp.url:
                    mcp_section += f"- **{mcp.name}**: {mcp.url}\n"
                elif mcp.command:
                    cmd_str = f"{mcp.command} {' '.join(mcp.args or [])}"
                    mcp_section += f"- **{mcp.name}**: (stdio) {cmd_str}\n"
            api_section += mcp_section

        return prompt + api_section

    def _write_mcp_json(self, working_dir: str, mcp_servers: list[Any]) -> None:
        """Write .mcp.json to working dir for Claude Code auto-discovery.

        Args:
            working_dir: Directory path where .mcp.json will be written.
            mcp_servers: List of MCPServerConfig objects.
        """
        mcp_config: dict[str, Any] = {"mcpServers": {}}
        for mcp in mcp_servers:
            server_entry: dict[str, Any] = {}
            if mcp.url:
                server_entry["url"] = mcp.url
            elif mcp.command:
                server_entry["command"] = mcp.command
                if mcp.args:
                    server_entry["args"] = mcp.args
            if mcp.env:
                server_entry["env"] = dict(mcp.env)
            if mcp.auth_token_env:
                # Pass env var reference, not the actual token
                server_entry["env"] = server_entry.get("env", {})
                server_entry["env"][mcp.auth_token_env] = f"${{{mcp.auth_token_env}}}"
            mcp_config["mcpServers"][mcp.name] = server_entry

        mcp_json_path = Path(working_dir) / ".mcp.json"
        mcp_json_path.write_text(json.dumps(mcp_config, indent=2))

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
            self._phase,
        )

        try:
            # Build a clean environment for the child process.
            # Remove CLAUDECODE so that nested `claude` invocations don't
            # refuse to start with "cannot be launched inside another session".
            child_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            # Pass auth token via environment variable if present
            if context.auth_token:
                child_env["ORCHESTRATOR_AUTH_TOKEN"] = context.auth_token

            # Write .mcp.json for Claude Code auto-discovery if MCP servers are configured
            if context.mcp_servers:
                self._write_mcp_json(context.working_dir, context.mcp_servers)

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
        except GateBlockedError:  # re-raise for executor retry path
            raise  # Let executor handle as revision, not a crash
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
            # Ensure the subprocess is terminated so it doesn't become an orphan
            # when the asyncio task is cancelled (e.g. server shutdown/reload).
            if self._process is not None and self._process.returncode is None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._process = None

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._process is not None:
            self._process.terminate()


class ClaudeCliQuotaAgent:
    """Quota fetcher for the Claude CLI, authenticated via macOS keychain.

    Reads the OAuth access token stored by ``claude auth login`` in the
    macOS keychain (service name ``"Claude Code-credentials"``), then calls
    the internal Anthropic usage API to get per-bucket utilisation figures.

    The ``name`` must match the ``AgentOption.name`` emitted by
    ``ToolDetector._detect_cli_tools()`` for the ``claude`` binary.
    """

    name = "claude"

    def get_quota(self) -> AgentQuota | None:
        """Fetch quota from the Anthropic OAuth usage API.

        Returns ``None`` if the CLI is not installed, the keychain entry is
        missing (e.g. non-macOS platforms or not logged in), or the API call
        fails.
        """
        import json as _json
        import subprocess as _sp
        import sys as _sys

        if shutil.which("claude") is None:
            return None

        # Keychain access is macOS-only
        if _sys.platform != "darwin" or shutil.which("security") is None:
            return None

        # Retrieve the OAuth access token from the macOS keychain
        try:
            result = _sp.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    "Claude Code-credentials",
                    "-g",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            # Password appears in stderr as: password: "...json..."
            combined = result.stdout + result.stderr
            password_line = next(
                (line for line in combined.splitlines() if line.startswith("password:")),
                None,
            )
            if not password_line:
                return None

            # Strip leading 'password: "' and trailing '"'
            raw_json = password_line[len('password: "') : -1]
            creds = _json.loads(raw_json)
            token: str | None = creds.get("claudeAiOauth", {}).get("accessToken")
            if not token:
                return None
        except Exception:
            return None

        # Call the internal Anthropic OAuth usage API
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception:
            return None

        # --- Parse the response ---
        five_hour: dict[str, Any] = data.get("five_hour") or {}
        seven_day: dict[str, Any] = data.get("seven_day") or {}
        seven_day_sonnet: dict[str, Any] = data.get("seven_day_sonnet") or {}
        extra: dict[str, Any] = data.get("extra_usage") or {}

        week_used_pct = float(seven_day.get("utilization", 0))
        week_remaining_pct = 100.0 - week_used_pct
        session_used_pct = float(five_hour.get("utilization", 0))
        session_remaining_pct = 100.0 - session_used_pct

        # Determine resets date for the weekly bucket (for label only)
        week_resets_at: str | None = seven_day.get("resets_at")
        resets_label = ""
        if week_resets_at:
            try:
                dt = datetime.fromisoformat(week_resets_at.replace("Z", "+00:00"))
                resets_label = f"resets {dt.strftime('%b %d')}"
            except Exception:
                pass

        # Build compact label
        label_parts = [f"Claude Max — 7d: {week_remaining_pct:.0f}%"]
        label_parts.append(f"session: {session_remaining_pct:.0f}%")
        if seven_day_sonnet:
            sonnet_used_pct = float(seven_day_sonnet.get("utilization", 0))
            label_parts.append(f"sonnet: {100.0 - sonnet_used_pct:.0f}%")
        if resets_label:
            label_parts.append(resets_label)

        # Build structured breakdown for expanded sidebar view
        buckets: list[QuotaBucket] = [
            QuotaBucket(
                label="7-day weekly",
                remaining_pct=week_remaining_pct,
                resets_at=seven_day.get("resets_at"),
            ),
            QuotaBucket(
                label="5-hour session",
                remaining_pct=session_remaining_pct,
                resets_at=five_hour.get("resets_at"),
            ),
        ]
        if seven_day_sonnet:
            sonnet_used_pct = float(seven_day_sonnet.get("utilization", 0))
            buckets.append(
                QuotaBucket(
                    label="Sonnet weekly",
                    remaining_pct=100.0 - sonnet_used_pct,
                    resets_at=seven_day_sonnet.get("resets_at"),
                )
            )
        if extra.get("is_enabled"):
            extra_limit = float(extra.get("monthly_limit", 0)) / 100  # cents → USD
            extra_used = float(extra.get("used_credits", 0)) / 100
            extra_remaining = round(extra_limit - extra_used, 2)
            buckets.append(
                QuotaBucket(
                    label="Extra usage",
                    remaining_usd=extra_remaining,
                )
            )

        return AgentQuota(
            balance_pct=week_remaining_pct,
            label=" · ".join(label_parts),
            breakdown=buckets,
        )
